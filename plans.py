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


# Superset de todos los módulos gateables = los del plan más alto (Premium).
TODOS_LOS_MODULOS = set(PLAN_MODULOS["premium"])


def aplicar_plan_en_db(db_path: str, plan: str) -> None:
    """Aplica un plan escribiendo el estado de módulos directo en la DB
    SQLite de un cliente (`clientes/<slug>/data/medlibra.db`). Lo usa el
    provisioning para asignar el plan de una instancia sin depender del
    contenedor.

    Idempotente: crea las filas de módulos que falten (INSERT OR IGNORE +
    UPDATE), funciona igual sobre una DB recién migrada o una existente.
    Requiere que la tabla `modulos` ya exista (la crea la migración propia
    de MedLibra, `0011_modulos`)."""
    import sqlite3
    if plan not in PLAN_MODULOS:
        raise ValueError(f"Plan desconocido: {plan!r}")
    activos = modulos_de_plan(plan)
    con = sqlite3.connect(db_path)
    try:
        for m in sorted(TODOS_LOS_MODULOS):
            on = 1 if m in activos else 0
            con.execute(
                "INSERT OR IGNORE INTO modulos (modulo, habilitado, plan) VALUES (?,?,?)",
                (m, on, plan),
            )
            con.execute(
                "UPDATE modulos SET habilitado=?, plan=? WHERE modulo=?",
                (on, plan, m),
            )
        con.commit()
    finally:
        con.close()
