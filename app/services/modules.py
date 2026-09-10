"""Módulos habilitados por plan comercial (ver `plans.py` en la raíz del
repo -- fuente de verdad del mapeo plan→módulos, compartida con
`libracore.provisioning`).

Solo recordatorios, señas, facturación y dashboard son gateables; todo el
dominio clínico (pacientes, historia clínica, recetas, estudios, documentos,
consentimientos) y turnos/catálogo son siempre libres. Por defecto
(instancia recién migrada, sin plan asignado todavía) **todo queda
habilitado** -- mismo criterio que Gestiolibra/Contalibra: el seed inicial
no bloquea nada, y recién `aplicar_plan_en_db()` (llamado por el
provisioning al dar de alta un cliente real con un plan elegido) achica el
acceso según corresponda.

🔴 **Los add-ons (`plans.ADDONS`) son la excepción a "todo habilitado".** Un
add-on no pertenece a ningún plan: nace apagado en todas las instancias y se
prende una por una desde el backoffice (`app.database.set_addon`). Ver
`is_enabled`.
"""
from libragenda.sqlalchemy_repository import Base
from sqlalchemy import select
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from plans import ADDONS, TODOS_LOS_MODULOS


class ModuleRow(Base):
    __tablename__ = "modulos"

    modulo: Mapped[str] = mapped_column(primary_key=True)
    habilitado: Mapped[bool] = mapped_column(default=True)
    plan: Mapped[str] = mapped_column(default="premium")


class ModuleRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def ensure_seeded(self) -> None:
        """Inserta los módulos que falten con `habilitado=True` -- no pisa
        el estado de los que ya existen (idempotente ante reinicios).

        🔴 **Los add-ons NO se siembran**, y no es un olvido: sembrarlos con
        `habilitado=True` los prendería solos en todas las instancias en el
        próximo arranque. Como `ADDONS` está afuera de `TODOS_LOS_MODULOS`, el
        set de abajo ya no los incluye; la fila de un add-on la crea sólo
        `set_addon` (backoffice) o `set_enabled`."""
        with self.session_factory.begin() as session:
            existentes = {row.modulo for row in session.scalars(select(ModuleRow)).all()}
            for modulo in sorted(TODOS_LOS_MODULOS - existentes):
                session.add(ModuleRow(modulo=modulo, habilitado=True, plan="premium"))

    def is_enabled(self, modulo: str) -> bool:
        """Si el módulo está habilitado en esta instancia. Tres casos:

        - **Add-on** (`plans.ADDONS`, ej. `resguardo_externo`): habilitado
          **sólo si existe la fila y dice `habilitado` verdadero**. Sin fila,
          apagado.
        - **Módulo de plan** (`TODOS_LOS_MODULOS`): lo que diga su fila; sin
          fila, habilitado (el criterio de "el seed no bloquea nada").
        - **Cualquier otro** (pacientes/historia clínica/turnos): siempre
          habilitado, incluso si nunca se sembró una fila -- no tiene sentido
          gatear el core clínico.

        🔴 **La rama de los add-ons va PRIMERO y no es redundante.** Sin ella un
        add-on cae en la tercera regla —no está en `TODOS_LOS_MODULOS`, a
        propósito— y queda habilitado en todas las instancias:
        `require_module("resguardo_externo")` nunca daría 403 y la copia a la
        nube del cliente se le ofrecería a quien no la contrató. No falla de
        ninguna forma visible: la pantalla simplemente aparece."""
        if modulo in ADDONS:
            with self.session_factory() as session:
                row = session.get(ModuleRow, modulo)
                return row is not None and bool(row.habilitado)
        if modulo not in TODOS_LOS_MODULOS:
            return True
        with self.session_factory() as session:
            row = session.get(ModuleRow, modulo)
            return bool(row.habilitado) if row is not None else True

    def get_all(self) -> dict[str, bool]:
        with self.session_factory() as session:
            rows = session.scalars(select(ModuleRow)).all()
            return {row.modulo: bool(row.habilitado) for row in rows}

    def set_enabled(self, modulo: str, habilitado: bool) -> None:
        """Prende/apaga un módulo puntual, sin pasar por un plan completo
        -- usado por tests y por un futuro ajuste manual desde el
        backoffice. `aplicar_plan_en_db()` (`plans.py`) es la vía real
        para asignar un plan completo al dar de alta un cliente."""
        with self.session_factory.begin() as session:
            row = session.get(ModuleRow, modulo)
            if row is None:
                session.add(ModuleRow(modulo=modulo, habilitado=habilitado, plan="custom"))
            else:
                row.habilitado = habilitado
