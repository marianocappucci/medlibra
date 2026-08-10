#!/usr/bin/env bash
# Reset diario de la demo publica de Medlibra.
#
# Deja las bases de cero, el arranque reconstruye el esquema y despues se
# siembra. **El estado limpio es codigo, no un backup guardado a mano**: eso es
# lo que hace que sea reproducible, y que agregar un dato de ejemplo sea un
# commit y no una operacion manual sobre el servidor.
#
# Corre por cron, despues de los backups -- no se pisan.
#
# 🔴 **Solo toca la instancia demo.** El contenedor esta escrito aca, no viene
# por argumento: un reset apuntado al contenedor equivocado le borra la base a
# un cliente, y no hay confirmacion que valga a las cuatro de la manana.
#
# 🔴 **Este archivo es el unico lugar donde vive la logica.** Hasta el
# 2026-08-10 habia una copia suelta en `/root/scripts-demo/reset_medlibra.sh`
# que el cron llamaba, y esa copia tenia DOS defensas que este archivo no tenia
# (la guarda por `DEMO_MODE` y el orden "seed antes de borrar", las dos
# agregadas despues de sendos incidentes). Ahora el cron llama a este.
set -euo pipefail

CONTENEDOR="medlibra-demo"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# --- La guarda ------------------------------------------------------------
# Si el nombre no es el de una demo, no se sigue. Es barato, y es lo unico que
# separa "resetear la demo" de "borrarle la base a un cliente".
case "$CONTENEDOR" in
  *-demo|*-publica) ;;
  *) log "ABORTA: '$CONTENEDOR' no parece una instancia demo."; exit 2 ;;
esac

# 🔴 La guarda del nombre no alcanza, y esto no es teorico: hasta el 2026-08-07
# el contenedor llamado `restolibra-demo` era el que servia
# sistema.restolibra.com.ar. El nombre decia demo y no lo era. Por eso se
# verifica una propiedad real de la instancia -DEMO_MODE, lo unico que enciende
# el auto-login publico- y no como se llama.
if ! docker exec "$CONTENEDOR" printenv DEMO_MODE 2>/dev/null | grep -qx 1; then
  log "ABORTA: $CONTENEDOR no tiene DEMO_MODE=1. El nombre no alcanza."
  exit 4
fi

if ! docker ps --format '{{.Names}}' | grep -qx "$CONTENEDOR"; then
  log "ABORTA: el contenedor $CONTENEDOR no esta corriendo."
  exit 3
fi

log "=== reset de $CONTENEDOR ==="

# --- 0. El seed, ANTES de tocar la base -----------------------------------
# 🔴 El 2026-08-06 este script borro la base y recien despues descubrio que no
# podia sembrar: `scripts/seed_demo.py` vive en `develop` y el checkout del VPS
# esta en `main`. Cinco demos quedaron vacias, y el cron lo habria repetido
# todas las noches. El orden correcto es conseguir el seed primero: si no esta,
# no se borra nada.
SEED_LOCAL=/tmp/seed-medlibra.py
git -C /root/medlibra fetch -q origin || { log "ABORTA: no se pudo hacer fetch de medlibra."; exit 5; }
git -C /root/medlibra show origin/develop:scripts/seed_demo.py > "$SEED_LOCAL" || { log "ABORTA: no esta scripts/seed_demo.py en origin/develop."; exit 6; }
[ -s "$SEED_LOCAL" ] || { log "ABORTA: el seed salio vacio."; exit 7; }
log "seed listo desde origin/develop ($(wc -l < "$SEED_LOCAL") lineas)"

# --- 1. Bases de cero -----------------------------------------------------
# 🔴 Que sea "borrar los .db" depende del motor, y desde el corte a PostgreSQL
# ya no da igual: con la base en PostgreSQL, un `rm /app/data/*.db` borra
# archivos que no usa nadie, el contenedor reinicia contra los datos de ayer y
# el seed se apila encima. El reset seguiria diciendo "listo" todas las noches
# sin resetear nada. Por eso el motor se DETECTA, y si no se puede detectar se
# aborta en vez de suponer SQLite.
#
# 🔴 Y son DOS bases: el dominio y LibraCore no pueden compartir schema en este
# producto -- los dos declaran una tabla `clients` con `id` de tipos
# incompatibles. Resetear una sola deja la demo a medias.
URL_DOMINIO=$(docker exec "$CONTENEDOR" printenv DATABASE_URL 2>/dev/null || true)
URL_CORE=$(docker exec "$CONTENEDOR" printenv MEDLIBRA_LIBRACORE_DB_PATH 2>/dev/null || true)

es_postgres() {
  case "$1" in postgres://*|postgresql://*|postgresql+*://*) return 0 ;; *) return 1 ;; esac
}

sidecar_de() {
  local sin_usuario=${1#*@}
  local host=${sin_usuario%%:*}
  echo "${host%%/*}"
}

base_de() {
  local sin_query=${1%%\?*}
  echo "${sin_query##*/}"
}

# Cuantas filas hay en tres tablas del dominio. Es la unica forma de que este
# script pueda DECIR que reseteo: se mide antes y despues, y si despues no dio
# cero, se aborta sin sembrar.
filas_del_dominio() {
  if es_postgres "$URL_DOMINIO"; then
    docker exec "$(sidecar_de "$URL_DOMINIO")" sh -c '
      psql -tA -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
        SELECT COALESCE((SELECT COUNT(*) FROM appointments), 0)
             + COALESCE((SELECT COUNT(*) FROM clients), 0)
             + COALESCE((SELECT COUNT(*) FROM services), 0)"
    ' 2>/dev/null || echo "?"
  else
    docker exec "$CONTENEDOR" python3 -c "
import sqlite3
try:
    c = sqlite3.connect('/app/data/medlibra.db')
    print(sum(c.execute('SELECT COUNT(*) FROM ' + t).fetchone()[0]
              for t in ('appointments', 'clients', 'services')))
except Exception:
    print('?')
" 2>/dev/null || echo "?"
  fi
}

if [ -z "$URL_DOMINIO" ]; then
  log "ABORTA: no pude leer DATABASE_URL del contenedor."
  exit 8
fi

ANTES=$(filas_del_dominio)
log "filas del dominio antes del reset: $ANTES"

if es_postgres "$URL_DOMINIO"; then
  SIDECAR=$(sidecar_de "$URL_DOMINIO")
  if ! docker ps --format '{{.Names}}' | grep -qx "$SIDECAR"; then
    log "ABORTA: el sidecar '$SIDECAR' no esta corriendo."
    exit 9
  fi
  log "motor: PostgreSQL (sidecar $SIDECAR)"

  # Se para la app ANTES de tocar los schemas. Con el contenedor arriba, sus
  # conexiones abiertas dejan el `DROP SCHEMA` esperando un lock: no falla, se
  # cuelga -- ya paso, veinte minutos en silencio.
  docker stop "$CONTENEDOR" >/dev/null
  log "app parada para soltar las conexiones"

  for base in "$(base_de "$URL_DOMINIO")" "$(base_de "$URL_CORE")"; do
    [ -z "$base" ] && continue
    # `psql` corre DENTRO del sidecar y con las variables de su propio entorno:
    # asi la contrasena no pasa por la linea de comandos del host, donde
    # quedaria en el `ps` y en el log del cron.
    docker exec -e BASE="$base" "$SIDECAR" sh -c '
      psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$BASE" \
        -c "DROP SCHEMA IF EXISTS public CASCADE" \
        -c "CREATE SCHEMA public" \
        -c "GRANT ALL ON SCHEMA public TO \"$POSTGRES_USER\""
    ' >/dev/null || { log "ABORTA: no se pudo recrear el schema de $base."; docker start "$CONTENEDOR" >/dev/null; exit 10; }
    log "schema de $base recreado, vacio"
  done

  docker start "$CONTENEDOR" >/dev/null
else
  log "motor: SQLite"
  # Se borran tambien los `-wal` y `-shm`: sin eso SQLite puede reconstruir
  # parte de lo borrado desde el journal, y el reset queda a medias.
  docker exec "$CONTENEDOR" sh -c 'rm -f /app/data/*.db /app/data/*.db-wal /app/data/*.db-shm'
  log "bases borradas"
  docker restart "$CONTENEDOR" >/dev/null
fi

for _ in $(seq 1 40); do
  estado=$(docker inspect -f '{{.State.Health.Status}}' "$CONTENEDOR" 2>/dev/null || echo starting)
  [ "$estado" = "healthy" ] && break
  sleep 3
done
estado=$(docker inspect -f '{{.State.Health.Status}}' "$CONTENEDOR" 2>/dev/null || echo desconocido)
log "contenedor: $estado"
if [ "$estado" != "healthy" ]; then
  log "ABORTA: no levanto sano; no se siembra sobre una instancia rota."
  exit 4
fi

# --- 1b. Que de verdad haya reseteado -------------------------------------
# La post-condicion. Sin esto el script dice "listo" igual cuando no borro nada,
# que es exactamente como se rompe un reset al cambiar de motor.
DESPUES=$(filas_del_dominio)
log "filas del dominio despues del reset: $DESPUES"
if [ "$DESPUES" = "?" ]; then
  log "ABORTA: no pude contar las filas -- puede que una tabla haya cambiado de"
  log "        nombre. Sin poder medir, no se siembra."
  exit 11
fi
if [ "$DESPUES" != "0" ]; then
  log "ABORTA: la base no quedo vacia (antes $ANTES, despues $DESPUES)."
  log "        No se siembra encima: quedaria la demo de ayer mas la de hoy."
  exit 11
fi
if [ "$ANTES" = "0" ]; then
  log "OJO: antes tambien habia 0 filas -- el chequeo no probo nada esta vez."
fi

# --- 2. Sembrar -----------------------------------------------------------
# Por la API y desde adentro del contenedor: la contrasena sale de su propio
# entorno y nunca pasa por la linea de comandos del host.
docker cp "$SEED_LOCAL" "$CONTENEDOR:/tmp/seed.py"
docker exec -i "$CONTENEDOR" sh -c '
  python3 /tmp/seed.py \
    --url https://demo.medlibra.com.ar \
    --usuario "${MEDLIBRA_ADMIN_USERNAME:-admin}" \
    --password "$MEDLIBRA_ADMIN_PASSWORD"
'
docker exec "$CONTENEDOR" rm -f /tmp/seed.py

log "=== listo ==="
