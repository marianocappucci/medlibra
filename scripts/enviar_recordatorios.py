#!/usr/bin/env python
"""Manda los recordatorios de turno vencidos (WhatsApp y mail) y reintenta los avisos que fallaron. Lo corre el cron.

Antes de este script **nada versionado en el repo corria `dispatch`**: `POST /reminders/dispatch` pide la sesion de un admin y no
habia ningun cron ni script (si el servidor tiene alguno por fuera, no esta en git). Es el mismo lazo que usa
`libraclub/scripts/enviar_avisos.py` (ADR-049 de este repo, ADR-090 de libracore).

    */10 * * * * docker exec medlibra-dev python /app/scripts/enviar_recordatorios.py >> /var/log/medlibra_recordatorios.log 2>&1

🔴 **Este script ES el interruptor de los recordatorios**, junto con el modo de WhatsApp de Configuracion > Avisos. Sin el cron no sale
nada; con el cron puesto y los avisos en `apagado` (o el SMTP sin cargar) tampoco: cada canal sin destino o sin configurar no escribe
nada. El recordatorio se da por visto igual (`libragenda` lo marca enviado apenas `send` vuelve): prender un canal despues no
reenvia lo viejo. Ver el ADR-049.

Respeta lo que respeta la ruta:
  - el modulo `recordatorios` del plan (la ruta da 403 sin el): una instancia Basica no manda nada;
  - un nodo de LibraEdge no manda (los manda el central).

Corre cada 10 minutos: el recordatorio de 2 horas se mide en horas, y diez minutos de demora no cambian lo que dice.
"""
from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

# `plans.py` vive en la raiz del repo (`/app` en la imagen), fuera del paquete instalado: el servidor la ve porque arranca
# con `/app` como directorio de trabajo, pero `python /app/scripts/...` pone en `sys.path` la carpeta `scripts/`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    # El import construye la app como lo hace el servidor (`create_app`): conecta la base, enchufa el almacen de secretos (sin el,
    # Evolution no tiene la apikey) y configura `libracore.db.core`. Es lo que pide la guia del motor para un script de cron.
    from app import offline
    from app.asgi import app
    from app.avisos import enviar_recordatorios

    def marca() -> str:
        return f"[{datetime.now():%d-%m-%Y %H:%M:%S}]"

    if offline.en_un_nodo():
        print(f"{marca()} recordatorios · este proceso es un nodo: los manda el central")
        return 0
    if not app.state.modules.is_enabled("recordatorios"):
        print(f"{marca()} recordatorios · el plan de esta instancia no incluye el modulo: no se manda nada")
        return 0

    vencidos = enviar_recordatorios(app.state.reminder_dispatcher, app.state.proveedores_de_avisos, datetime.now(UTC))
    # Una linea por corrida, con fecha: un script silencioso es indistinguible de uno que no esta en el crontab. Sin ids de
    # pacientes ni de turnos: el log no lleva datos de salud (el detalle de cada aviso esta en el registro de Configuracion).
    print(f"{marca()} recordatorios · vencidos: {len(vencidos)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
