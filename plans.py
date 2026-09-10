"""
Definición única de los planes comerciales de MedLibra y qué módulos
habilita cada uno. Fuente de verdad compartida entre:

- `app.services.modules.ModuleRepository` (aplica el plan dentro de la
  instancia de un cliente).
- `libracore.provisioning.nuevo_cliente` (asigna el plan al dar de alta).

Mismo patrón exacto que `plans.py` de Gestiolibra (import diferido desde
`libracore.db.modulos.apply_plan`/`libracore.provisioning`, que agregan la
raíz del repo a `sys.path`), adaptado al catálogo de MedLibra: a diferencia
de Gestiolibra, acá el dominio clínico completo (turnos, pacientes, historia
clínica, recetas, estudios, documentos clínicos, consentimientos) es
siempre gratis -- necesidad profesional básica de un consultorio, mismo
criterio que "turnos nunca se gatea" en Gestiolibra, extendido a todo lo
clínico. Lo que se vende por nivel es recordatorios/señas y
facturación/dashboard (decisión del usuario, 2026-07-25 -- ver
`DECISIONS.md` ADR-018).
"""

PLANES = ["basico", "estandar", "premium"]

PLAN_LABELS = {
    "basico":   "Básico",
    "estandar": "Estándar",
    "premium":  "Premium",
}

# Precio mensual de referencia (informativo, para mostrar en el backoffice).
# Más alto que Gestiolibra ($15k/$25k/$40k): MedLibra apunta a consultorios
# y profesionales de salud, no a negocios de servicios chicos.
PLAN_PRECIOS = {
    "basico":   25000,
    "estandar": 40000,
    "premium":  60000,
}

# Básico: catálogo, disponibilidad, turnos, pacientes, historia clínica,
# recetas, estudios, documentos clínicos y consentimientos -- el dominio
# clínico completo, siempre disponible, no es un módulo gateable (mismo
# criterio que "turnos" en Gestiolibra, extendido a todo lo clínico).
_BASICO: set[str] = set()

# Estándar = Básico + recordatorios y señas.
_ESTANDAR = _BASICO | {"recordatorios", "senas"}

# Premium = Estándar + facturación/caja con LibraCore y dashboard.
_PREMIUM = _ESTANDAR | {"facturacion", "dashboard"}

PLAN_MODULOS = {
    "basico":   set(_BASICO),
    "estandar": set(_ESTANDAR),
    "premium":  set(_PREMIUM),
}


def modulos_de_plan(plan: str) -> set[str]:
    """Devuelve el set de módulos habilitados para un plan (vacío si el
    plan es desconocido)."""
    return set(PLAN_MODULOS.get(plan, set()))


# Add-ons opcionales: módulos que se habilitan **por instancia** y NO
# pertenecen a ningún plan. No entran en `PLAN_MODULOS` ni en
# `TODOS_LOS_MODULOS`, así que ni `apply_plan` (motor) ni `aplicar_plan_en_db`
# (acá) los tocan: un add-on prendido **sobrevive a subir o bajar de plan**.
# `libracore.db.modulos.apply_plan` lee este set con
# `getattr(plans, "ADDONS", set())`. Mismo patrón que `mayorista` en Contalibra
# y `modo_simple` en LibraDesk. El backoffice los prende y apaga por
# `docker exec` con `app.database.set_addon`, y valida el nombre contra este set.
#
# 🔑 **Nace APAGADO, y eso no sale solo.** `ensure_seeded()` inserta toda
# entrada nueva de `TODOS_LOS_MODULOS` con `habilitado=True` en todas las
# instancias en el próximo arranque, y `ModuleRepository.is_enabled` daba por
# habilitado cualquier módulo sin fila. Por eso un add-on queda afuera de los
# dos y tiene su propia regla en `is_enabled`: habilitado sólo con una fila en
# `modulos` que diga `habilitado` verdadero. Ver `app/services/modules.py`.
#
#   - resguardo_externo: la copia externa del backup en la nube del cliente
#     (Google Drive / Dropbox), enlazada desde Configuración -> Datos / Backup
#     (`libracore.resguardo_enlace`, LibraCore v1.93.0).
ADDONS = {"resguardo_externo"}

# Superset de todos los módulos gateables = los del plan más alto (Premium).
#
# ⚠️ Los add-ons quedan afuera **a propósito** (ver `ADDONS`). Sumarlos acá los
# prendería solos en todas las instancias en el próximo arranque.
TODOS_LOS_MODULOS = set(PLAN_MODULOS["premium"])


def aplicar_plan_en_db(db_path: str, plan: str) -> None:
    """Aplica un plan escribiendo el estado de módulos directo en la DB
    SQLite de un cliente (`clientes/<slug>/data/medlibra.db`). Lo usa el
    provisioning para asignar el plan de una instancia sin depender del
    contenedor.

    Shim sobre libracore.provisioning.apply_plan_modules (extraído
    2026-07-26: el cuerpo era idéntico en Gestiolibra/MedLibra/VentaLibra
    salvo el nombre de la variable, ver
    wiki/analyses/auditoria-duplicacion-familia-libra.md). Requiere que la
    tabla `modulos` ya exista (la crea la migración propia de MedLibra,
    `0011_modulos`)."""
    if plan not in PLAN_MODULOS:
        raise ValueError(f"Plan desconocido: {plan!r}")
    from libracore.provisioning import apply_plan_modules
    apply_plan_modules(
        db_path, active_modules=modulos_de_plan(plan),
        # `- ADDONS`: aplicar un plan nunca toca un add-on. Hoy es equivalente
        # (ya estan afuera de `TODOS_LOS_MODULOS`), pero deja la invariante
        # escrita — mismo criterio que Contalibra y LibraDesk.
        all_modules=TODOS_LOS_MODULOS - ADDONS, plan=plan,
    )
