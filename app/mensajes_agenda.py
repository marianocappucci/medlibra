"""Los errores de la agenda, en castellano y dichos para quien los lee.

🔴 **Por qué existe este módulo.** El motor (libragenda) levanta excepciones
tipadas con mensajes en inglés pensados para el log —`outside business hours`,
`cannot transition confirmed to completed`—, y los routers los pasaban tal cual
al `detail` de la respuesta. La pantalla muestra ese `detail`, así que el
usuario veía el texto del motor: reportado el 2026-08-06 probando la demo,
*"me salió una advertencia en inglés sin formato"*.

**La traducción va en el borde de la API y no en la pantalla**: así vale para
cualquier cliente —la SPA de hoy, un móvil mañana— y no hay dos listas de
mensajes que se desincronicen. Y no se toca el motor: los mensajes de una
excepción son para el log y el `traceback`, y ahí el inglés está bien.

🔴 **El mapeo va por NOMBRE de clase, no importando las clases.** Importarlas
ata este módulo a la versión del motor que esté pineada: `OverbookingLimitReached`
existe en `develop` de libragenda pero **no** en `v0.9.0`, que es lo que estos
productos consumen, y el import rompía el arranque entero. Por nombre, una
excepción que la versión pineada no tiene simplemente no aparece nunca.

Cada mensaje dice **qué pasó y qué hacer**. "Fuera del horario de atención" sin
más deja al usuario probando horas hasta acertar; nombrar dónde mirar —el
horario del profesional o el de la sede— le ahorra ese juego.
"""

#: Qué contestar ante cada excepción del motor, por nombre de clase:
#: (código HTTP, mensaje).
#:
#: El código importa tanto como el texto: un 404 y un 409 significan cosas
#: distintas —"no existe" contra "existe y no se puede"— y la pantalla los
#: puede tratar distinto.
POR_NOMBRE = {
    "AppointmentNotFound": (404, "No se encontró el turno."),
    "ServiceNotFound": (404, "No se encontró la prestación."),
    "AppointmentConflict": (
        409,
        "Ese horario ya está ocupado. Elegí otro o revisá la agenda del profesional.",
    ),
    "AppointmentUnavailable": (
        409,
        "El profesional no atiende en ese horario. Revisá su disponibilidad en Recursos.",
    ),
    "OutsideBusinessHours": (
        409,
        "El horario elegido está fuera del horario de atención. Revisá los "
        "horarios de la sede y del profesional.",
    ),
    "OverbookingLimitReached": (
        409,
        "Se llegó al tope de sobreturnos del día para ese profesional.",
    ),
    "ResourceBranchMismatch": (
        409,
        "El profesional no atiende en esa sede.",
    ),
    # No sale del motor: LibraGenda asocia un turno a un solo recurso y no sabe
    # de salas. Lo levanta `AppointmentService` (ver ese archivo).
    "ConsultorioOcupado": (
        409,
        "El consultorio ya está ocupado a esa hora por otro profesional. "
        "Elegí otro horario o revisá los bloques de agenda.",
    ),
}

#: Nombres internos de estado del motor → cómo se dicen en la pantalla.
ESTADOS = {
    "pending": "pendiente",
    "confirmed": "confirmado",
    "in_progress": "en atención",
    "completed": "completado",
    "cancelled": "cancelado",
    "no_show": "ausente",
}

FUERA_DE_HORARIO = POR_NOMBRE["OutsideBusinessHours"][1]
SERVICIO_NO_ENCONTRADO = POR_NOMBRE["ServiceNotFound"][1]
RANGO_INVERTIDO = "La fecha final no puede ser anterior a la inicial."


def describir(exc: Exception) -> tuple[int, str]:
    """(código HTTP, mensaje en castellano) para una excepción del motor.

    Ante una excepción que esta tabla no conoce devuelve un mensaje genérico y
    **no** el texto original: filtrar el mensaje interno es deliberado. Si
    mañana el motor suma un caso, el usuario ve algo legible y el detalle queda
    donde tiene que estar, que es el log.
    """
    nombre = type(exc).__name__
    if nombre == "InvalidTransition":
        return 409, _transicion(str(exc))
    if nombre in POR_NOMBRE:
        return POR_NOMBRE[nombre]
    return 409, "No se pudo completar la operación sobre el turno."


def _transicion(texto: str) -> str:
    """Traduce los dos mensajes de transición del motor.

    Son dos formas: `cannot transition <estado> to <estado>` y
    `cannot reschedule <estado> appointment`. Se traduce **el estado** y no la
    frase entera, así que una combinación nueva del motor sigue saliendo
    legible sin tocar esta tabla.
    """
    partes = texto.split()
    if texto.startswith("cannot transition") and len(partes) >= 5:
        desde = ESTADOS.get(partes[2], partes[2])
        hasta = ESTADOS.get(partes[4], partes[4])
        return f"Un turno {desde} no puede pasar a {hasta}."
    if texto.startswith("cannot reschedule") and len(partes) >= 3:
        estado = ESTADOS.get(partes[2], partes[2])
        return f"Un turno {estado} no se puede reprogramar."
    return "Ese cambio de estado no está permitido para el turno."
