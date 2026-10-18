"""Application service for the appointment booking use case.

Wraps LibraGenda's InMemoryScheduler with the one piece of app-specific
validation the engine can't do on its own (does this service exist at
all) — everything else is delegated straight to LibraGenda's own use
cases and domain exceptions, per CONVENTIONS.md ("no duplicar reglas de
LibraGenda").

🔴 **El terreno horario de la validación** (arreglado el 2026-08-22)
--------------------------------------------------------------------

El motor guarda **instantes en UTC**, pero la disponibilidad se configura
en **hora de pared**: `Availability` es `(día de la semana, 09:00, 19:00)`,
igual que `branch_hours`, y quien la carga la piensa en la hora del reloj
de la sucursal. Hasta hoy el turno se convertía a UTC *antes* de validarlo
y las dos comparaciones —`Availability.contains()` del motor y
`BranchHoursRepository.is_within_hours()` de acá— quedaban comparando la
hora UTC contra ventanas cargadas en hora local.

Con `America/Argentina/Buenos_Aires` (UTC-3) eso corría la comparación
tres horas: **una sucursal abierta de 9 a 19 rechazaba en la práctica todo
turno que empezara después de las 16**, con el mensaje "el horario elegido
está fuera del horario de atención" — que es exactamente lo que reportó el
humano. Y había un segundo síntoma del mismo defecto, peor porque no
dependía de las ventanas: `contains()` exige `starts_at.date() ==
ends_at.date()`, así que **cualquier turno de 21:00 en adelante cruzaba la
medianoche UTC y era irrechazable**, con la agenda abierta las 24 horas.

**La corrección no toca el motor**, y no por comodidad: `timezones.py` de
LibraGenda declara el contrato al revés — *"verticals are expected to
collect wall-clock times ... and convert at the boundary using this
module, rather than teaching the scheduling engine about civil time
zones"*. O sea que el borde es este archivo. Lo que se hace es correr **la
validación entera en hora local de la sucursal** (ventanas, excepciones,
bloqueos y choques con otros turnos, todo en el mismo terreno) y convertir
a UTC **en el repositorio**, que es el único lugar donde el instante se
guarda. De eso se encarga `_TurnosEnHoraLocal`.
"""

from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import date, datetime
from uuid import uuid4

from libragenda import Appointment, AppointmentConflict, InMemoryScheduler
from libragenda.availability_repository import SqlAlchemyAvailabilityRepository
from libragenda.catalog_repository import SqlAlchemyCatalogRepository
from libragenda.repositories import AppointmentRepository
from libragenda.scheduling import TimeBlock
from libragenda.timezones import to_utc

from .agenda_blocks import AgendaBlockRepository
from .branch_hours import BranchHoursRepository
from .husos import como_hora_de_pared, hora_de_pared, zona_del_recurso


class ServiceNotFound(Exception):
    """Raised when booking references a service that was never registered."""


class OutsideBusinessHours(Exception):
    """Raised when the slot falls outside the resource's branch hours,
    only for branches that actually have hours configured (see
    branch_hours.py's opt-in gating)."""


class ConsultorioOcupado(Exception):
    """El consultorio ya tiene otro turno encima a esa hora.

    🔴 **La sala es un recurso secundario del turno** (ADR-009 y ADR-016 de
    LibraGenda): el motor la compara y la traba junto con el profesional, dentro
    de la misma transacción, y levanta `AppointmentConflict`. Esto no sale del
    motor: lo levanta `AppointmentService` cuando el choque fue **sólo** de la
    sala, para decirle a quien agenda *qué* está ocupado. Hasta el 2026-10-17 la
    sala se chequeaba acá, afuera de esa transacción, y dos profesionales que
    reservaban a la vez entraban los dos al mismo consultorio.
    """


def _bloque_local(bloque: TimeBlock, zona: str) -> TimeBlock:
    """Un bloqueo (que se guarda como instante) llevado a hora de pared."""
    return replace(
        bloque,
        starts_at=hora_de_pared(bloque.starts_at, zona),
        ends_at=hora_de_pared(bloque.ends_at, zona),
    )


class _TurnosEnHoraLocal:
    """El repositorio de turnos, visto en hora de pared de una sucursal.

    Es el borde del que habla el docstring del módulo: hacia el motor todo
    es hora local —la misma en la que están cargadas las ventanas, las
    excepciones y el horario de atención—, y hacia la base todo es UTC.

    **Sólo devuelve los turnos que comparten algún recurso con el que se está
    validando**: el profesional y, si el turno cae en un bloque de agenda, su
    consultorio. El motor ya descarta los demás al buscar choques, así que no se
    pierde nada. Antes eran sólo los del profesional, porque la sala se
    chequeaba aparte; ahora entran también los de **otros profesionales** que
    ocupan la misma sala.

    Traducirlos con una sola zona es correcto aunque vengan de otra sede: la
    conversión es de **instante a hora de pared de la sucursal que se valida**,
    y el instante es el mismo para todos. Lo que no se puede es comparar dos
    horas de pared de husos distintos entre sí, y acá nunca llegan dos.
    """

    def __init__(self, base: AppointmentRepository, zona: str, ocupados: tuple[str, ...]) -> None:
        self._base = base
        self._zona = zona
        self._ocupados = frozenset(ocupados)

    def _a_local(self, turno: Appointment) -> Appointment:
        return replace(turno, starts_at=hora_de_pared(turno.starts_at, self._zona))

    def _a_utc(self, turno: Appointment) -> Appointment:
        return replace(turno, starts_at=to_utc(turno.starts_at, self._zona))

    def _comparte(self, turno: Appointment) -> bool:
        return not self._ocupados.isdisjoint(turno.occupied_resource_ids)

    def _validador_utc(
        self, validator: Callable[[Iterable[Appointment]], Appointment],
    ) -> Callable[[Iterable[Appointment]], Appointment]:
        """El validador del motor, recibiendo hora local y devolviendo UTC."""

        def validador_utc(existentes_utc: Iterable[Appointment]) -> Appointment:
            existentes_local = tuple(
                self._a_local(turno) for turno in existentes_utc if self._comparte(turno)
            )
            return self._a_utc(validator(existentes_local))

        return validador_utc

    # -- el puerto que pide LibraGenda -------------------------------------

    def add(self, appointment: Appointment) -> None:
        self._base.add(self._a_utc(appointment))

    def get(self, appointment_id: str) -> Appointment | None:
        turno = self._base.get(appointment_id)
        return None if turno is None else self._a_local(turno)

    def save(self, appointment: Appointment) -> None:
        self._base.save(self._a_utc(appointment))

    def list(self) -> tuple[Appointment, ...]:
        return tuple(
            self._a_local(turno) for turno in self._base.list() if self._comparte(turno)
        )

    def reserve(
        self,
        appointment: Appointment,
        validator: Callable[[Iterable[Appointment]], Appointment],
    ) -> Appointment:
        """El `reserve` atomico que pide LibraGenda desde v0.10.0.

        El motor opera en hora de pared; el repositorio base, en UTC. Se traduce
        el turno a UTC para el base y se envuelve el validador para que reciba
        los turnos existentes **en hora local y solo los que comparten recurso**
        --la misma vista que da `list`--, y para devolver en UTC lo que el base
        va a guardar. Todo ocurre dentro de `_base.reserve`, que traba el
        profesional **y la sala** y es lo que conserva la atomicidad entre
        validar el choque y guardar --lo que evita que dos pedidos reserven el
        mismo slot a la vez--.
        """
        guardado = self._base.reserve(self._a_utc(appointment), self._validador_utc(validator))
        return self._a_local(guardado)

    def relocate(
        self,
        appointment: Appointment,
        validator: Callable[[Iterable[Appointment]], Appointment],
    ) -> Appointment:
        """El `relocate` atomico que pide LibraGenda para reagendar.

        Mismo borde y misma traduccion que `reserve` --y por las mismas
        razones--, sobre la otra operacion: mover un turno que ya existe.
        Reagendar tambien es leer, validar el choque y escribir sobre un hueco
        que los demas se estan disputando, asi que va adentro de una sola
        transaccion con el mismo lock; hacerlo con `save()` despues de validar
        dejaba entrar dos reagendados al mismo hueco.
        """
        guardado = self._base.relocate(self._a_utc(appointment), self._validador_utc(validator))
        return self._a_local(guardado)


class AppointmentService:
    def __init__(
        self,
        catalog: SqlAlchemyCatalogRepository,
        appointments: AppointmentRepository,
        availability: SqlAlchemyAvailabilityRepository,
        branch_hours: BranchHoursRepository,
        blocks: AgendaBlockRepository,
    ) -> None:
        self.catalog = catalog
        self.appointments = appointments
        self.availability = availability
        self.branch_hours = branch_hours
        self.blocks = blocks

    def _zona(self, resource_id: str) -> str:
        return zona_del_recurso(self.catalog, resource_id)

    def _check_branch_hours(
        self, resource_id: str, starts_at: datetime, ends_at: datetime
    ) -> None:
        """El horario comercial de la sucursal, **en hora local**.

        `starts_at`/`ends_at` llegan como hora de pared, que es la misma
        unidad en la que `branch_hours` guarda sus ventanas. Pasarle instantes
        UTC era el defecto que se arregló el 2026-08-22.
        """
        resource = self.catalog.get_resource(resource_id)
        if resource is None or resource.branch_id is None:
            return
        if not self.branch_hours.is_within_hours(resource.branch_id, starts_at, ends_at):
            raise OutsideBusinessHours(resource.branch_id)

    @staticmethod
    def _sala_del_bloque(bloque: dict | None) -> tuple[str, ...]:
        """La sala del turno, como recurso secundario: la del bloque que lo cubre.

        Sin bloque —una jornada cargada por el camino viejo— no hay sala que
        declarar y el turno ocupa sólo al profesional.
        """
        return (bloque["consultorio_id"],) if bloque is not None else ()

    @staticmethod
    def _choque(exc: AppointmentConflict, resource_id: str, sala: tuple[str, ...]) -> Exception:
        """El error a levantar ante un choque del motor.

        El motor dice **cuáles** de los recursos del turno chocaron
        (`AppointmentConflict.resource_ids`). Si fue la sala y no el
        profesional, se dice "consultorio ocupado"; si el profesional estaba
        ocupado —solo o junto con la sala—, manda el horario del profesional, que
        es lo primero que hay que mirar.
        """
        if sala and resource_id not in exc.resource_ids and sala[0] in exc.resource_ids:
            return ConsultorioOcupado(sala[0])
        return exc

    def _agenda_local(
        self, resource_id: str, zona: str, dia: date, sala: tuple[str, ...] = (),
    ) -> InMemoryScheduler:
        """El motor cargado con la disponibilidad del recurso, toda en hora
        local: ventanas y excepciones ya lo están, los bloqueos se traducen.

        Las ventanas son **la disponibilidad semanal más los bloques de agenda
        vigentes ese día**. Se suman en vez de reemplazarse: las instancias que
        ya están andando tienen su jornada cargada por
        `/resources/{id}/availability` y tienen que seguir dando turnos igual
        (ver `agenda_blocks.py`). Y se derivan **para el día que se valida**,
        que es lo que hace valer el "se repite hasta determinada fecha" sin
        enseñarle vigencias al motor.

        🔴 **`holidays` y `resources` faltaban, y la regla de feriados del
        motor no podía dispararse** (arreglado el 2026-08-24). Hasta acá este
        constructor recibía sólo ventanas, bloqueos y excepciones, así que los
        dos parámetros quedaban en lista vacía — y `_is_branch_holiday()` de
        `libragenda/scheduling.py` necesita **los dos**: busca el recurso
        dentro de `resources` para sacarle la sucursal y recién ahí compara
        contra `holidays`. Con cualquiera de las dos vacía devuelve `False`
        siempre. La tabla `holidays` existía desde la migración
        `0003_timezone_holidays_branch` y nadie podía cargarla, así que el
        defecto no tenía síntoma que alguien pudiera reportar.

        🔑 **El feriado se evalúa en el día LOCAL, y eso sale gratis acá.**
        `_is_branch_holiday()` compara `appointment.starts_at.date()`, y todo
        lo que entra a este scheduler está en hora de pared de la sucursal (ver
        el docstring del módulo). Si el turno llegara como instante UTC, en
        UTC-3 uno de las 21:00 caería en el día siguiente y se lo compararía
        contra el feriado equivocado — el mismo defecto de terreno que se
        arregló el 2026-08-22, ahora en la fecha en vez de la hora.
        """
        windows = [item for _, item in self.availability.list_availability(resource_id)]
        windows += self.blocks.ventanas_vigentes(resource_id, dia)
        blocks = [
            _bloque_local(item, zona)
            for _, item in self.availability.list_blocks(resource_id)
        ]
        exceptions = [item for _, item in self.availability.list_exceptions(resource_id)]
        resource = self.catalog.get_resource(resource_id)
        # Un recurso sin sucursal no tiene calendario de feriados que aplicarle
        # -- el motor ya lo trata así, pero pedirle los feriados de `None`
        # sería traer los de todas las sucursales.
        #
        # 📝 Se traen TODOS los feriados de la sucursal, no los del día. Hoy
        # son los que alguien cargó a mano y no llegan a la decena; cuando
        # entre el feed nacional por API (unos 19 por año) va a convenir que
        # el motor sepa filtrar por fecha — `list_holidays()` sólo acepta
        # sucursal.
        holidays = (
            list(self.catalog.list_holidays(resource.branch_id))
            if resource is not None and resource.branch_id is not None
            else []
        )
        return InMemoryScheduler(
            windows, blocks, exceptions,
            holidays=holidays,
            resources=[resource] if resource is not None else [],
            repository=_TurnosEnHoraLocal(self.appointments, zona, (resource_id, *sala)),
        )

    def create(
        self, resource_id: str, service_id: str, client_id: str, starts_at: datetime
    ) -> Appointment:
        services = {item.id: item for item in self.catalog.list_services()}
        service = services.get(service_id)
        if service is None:
            raise ServiceNotFound(service_id)
        zona = self._zona(resource_id)
        inicio = como_hora_de_pared(starts_at, zona)
        # 🔴 **La duración la manda el bloque de agenda**, no la prestación
        # (decisión del humano, 2026-08-23). La prestación dice *qué* se hace;
        # cuánto dura un turno de esa agenda es del bloque, que es donde se
        # eligió 10/15/20/25/30. Sin bloque que cubra el horario —una jornada
        # cargada por el camino viejo— sigue mandando la prestación.
        duracion = self.blocks.duracion_de(resource_id, inicio) or service.duration
        self._check_branch_hours(resource_id, inicio, inicio + duracion)
        # 🔴 **La sala es un recurso secundario del turno, no un chequeo aparte.**
        # El motor la compara y la traba junto con el profesional dentro de la
        # transacción de `reserve()`: dos profesionales que piden la misma sala a
        # la vez hacen cola en su fila, y el segundo ve al primero. Chequearla
        # acá antes de llamar al motor (lo que se hacía hasta el 2026-10-17) dejaba
        # una ventana entre leer y escribir por la que entraban los dos.
        bloque = self.blocks.cubre(resource_id, inicio, duracion)
        sala = self._sala_del_bloque(bloque)
        appointment = Appointment(
            str(uuid4()), resource_id, service_id, client_id, inicio, duracion,
            secondary_resource_ids=sala,
        )
        try:
            self._agenda_local(resource_id, zona, inicio.date(), sala).create(appointment)
        except AppointmentConflict as exc:
            raise self._choque(exc, resource_id, sala) from exc
        # Lo que se devuelve es lo que se guardó: el turno en UTC. El router
        # publica su `ends_at`, y devolver la hora local lo dejaría diciendo
        # tres horas menos que la agenda que lo lista un segundo después.
        return replace(appointment, starts_at=to_utc(inicio, zona))

    def confirm(self, appointment_id: str) -> Appointment:
        scheduler = InMemoryScheduler(repository=self.appointments)
        return scheduler.confirm(appointment_id)

    def cancel(self, appointment_id: str, reason: str | None = None) -> Appointment:
        scheduler = InMemoryScheduler(repository=self.appointments)
        return scheduler.cancel(appointment_id, reason=reason)

    def complete(self, appointment_id: str) -> Appointment:
        scheduler = InMemoryScheduler(repository=self.appointments)
        return scheduler.complete(appointment_id)

    def reschedule(
        self, appointment_id: str, starts_at: datetime, reason: str | None = None
    ) -> Appointment:
        # El recurso sale del turno guardado (en UTC): es lo que determina de
        # qué sucursal —y por lo tanto de qué huso— se está hablando.
        current = self.appointments.get(appointment_id)
        resource_id = current.resource_id if current is not None else ""
        zona = self._zona(resource_id)
        inicio = como_hora_de_pared(starts_at, zona)
        sala: tuple[str, ...] = ()
        if current is not None:
            self._check_branch_hours(resource_id, inicio, inicio + current.duration)
            # La sala sigue al bloque que cubre el horario nuevo, igual que en el
            # alta: mover un turno puede cambiarlo de consultorio, y la sala nueva
            # se compara y se traba en la misma transacción que la hora. Sin
            # bloque que lo cubra el turno queda sin sala (como uno dado por la
            # disponibilidad semanal) y libera la que tenía.
            sala = self._sala_del_bloque(self.blocks.cubre(resource_id, inicio, current.duration))
        try:
            turno = self._agenda_local(resource_id, zona, inicio.date(), sala).reschedule(
                appointment_id, inicio, reason=reason, secondary_resource_ids=sala,
            )
        except AppointmentConflict as exc:
            raise self._choque(exc, resource_id, sala) from exc
        return replace(turno, starts_at=to_utc(inicio, zona))

    def agenda(self, resource_id: str, day_from: date, day_to: date) -> list[Appointment]:
        """Los turnos del recurso entre dos días, **contados en hora local**.

        Los turnos se devuelven en UTC (es el instante, y es lo que el
        contrato del endpoint publica), pero el *día* al que pertenecen es el
        del calendario de la sucursal. Hasta el 2026-08-22 el filtro miraba la
        fecha del instante UTC, así que en UTC-3 un turno de las 21:30 del
        lunes caía en el martes UTC y **no salía al pedir el lunes**: se veía
        como un turno que se guarda bien y después desaparece de la agenda.
        """
        zona = self._zona(resource_id)
        return sorted(
            (
                item for item in self.appointments.list()
                if item.resource_id == resource_id
                and day_from <= hora_de_pared(item.starts_at, zona).date() <= day_to
            ),
            key=lambda item: item.starts_at,
        )
