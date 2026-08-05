"""Que audita MedLibra — y, sobre todo, que NO deja escrito.

El mecanismo vive en `libraauth.auditoria` (v0.11.0). Lo que queda aca es lo
unico que el producto sabe: cuales de sus modelos vale la pena auditar y **cual
de sus datos no puede terminar copiado en el log**.

> 🔴 **Este producto guarda datos de salud, y el log lo lee cualquier admin.**
> Un log de auditoria util contesta *quien* toco *que ficha* y *cuando*; no
> tiene por que contestar *que dice* esa ficha. Copiar el texto de una nota
> clinica o la medicacion de una receta al `actividad_log` seria sacar esos
> datos de la tabla donde estan y ponerlos en otra que se mira por motivos
> completamente distintos — con menos cuidado y ante mas ojos.
>
> Por eso hay dos defensas, y hacen falta las dos:
>
> 1. `COLUMNAS_CLINICAS` sale del **diff**.
> 2. `etiqueta_segura()` sale de la **descripcion**. No alcanza con lo
>    anterior: la etiqueta se arma leyendo atributos directamente, asi que un
>    `title` oculto del diff igual terminaria escrito en el texto de la fila.
"""
from libraauth.auditoria import (  # noqa: F401 — re-export para el router y los tests
    BORRAR,
    CREAR,
    EDITAR,
    AuditoriaRepository,
)
from libraauth.auditoria import etiqueta_por_defecto

# {nombre de la clase del modelo: nombre logico}
AUDITABLES: dict[str, str] = {
    # Dominio de LibraGenda
    "ClientRow": "paciente",
    "AppointmentRow": "turno",
    "ServiceRow": "prestacion",
    "ResourceRow": "consultorio",
    "BranchRow": "sede",
    "AvailabilityRow": "disponibilidad",
    "AvailabilityExceptionRow": "excepcion",
    "TimeBlockRow": "bloqueo",
    "HolidayRow": "feriado",
    "DepositRow": "seña",
    # Dominio propio de MedLibra
    "PatientRow": "ficha",
    "ClinicalNoteRow": "nota clinica",
    "ClinicalDocumentRow": "documento clinico",
    "PrescriptionRow": "receta",
    "PrescriptionItemRow": "item de receta",
    "StudyOrderRow": "orden de estudio",
    "StudyOrderItemRow": "item de orden",
    "StudyResultRow": "resultado",
    "ConsentRow": "consentimiento",
    "BranchHoursRow": "horario",
    "BranchContactRow": "contacto",
    "BusinessSettingsRow": "configuracion",
    "ServicePriceRow": "precio",
    "ServiceIvaRateRow": "alicuota",
}

# Lo que NUNCA entra al diff. El motor ya oculta contrasenas y tokens; esto es
# lo que solo este producto sabe que es sensible.
COLUMNAS_CLINICAS = frozenset({
    # Contenido clinico propiamente dicho
    "text", "notes", "diagnosis", "medication", "dosage", "instructions",
    "result", "results", "observations", "indications", "title", "content",
    # Identificatorios del paciente
    "dni", "cuit", "birth_date", "email", "phone",
})

# Las entidades cuyo *nombre* ya es informacion clinica: de estas no se escribe
# ninguna etiqueta, solo el tipo y el id. "Nota clinica #418" dice quien la
# toco y cuando, que es para lo que existe el log.
ENTIDADES_SIN_ETIQUETA = frozenset({
    "ClinicalNoteRow", "ClinicalDocumentRow", "PrescriptionRow",
    "PrescriptionItemRow", "StudyOrderRow", "StudyOrderItemRow",
    "StudyResultRow", "ConsentRow", "PatientRow",
})


def etiqueta_segura(obj) -> str:
    """Sin etiqueta para lo clinico; la de siempre para el resto (una sede, un
    consultorio o una prestacion no dicen nada de ningun paciente)."""
    if type(obj).__name__ in ENTIDADES_SIN_ETIQUETA:
        return ""
    return etiqueta_por_defecto(obj)


# Afuera de la lista blanca:
#
# - `AppointmentTransitionRow` y `SentReminderRow` **ya son historial**: la
#   ficha del turno los muestra, y auditarlos pondria el mismo hecho dos veces.
# - `ModuleRow` la reescribe `ensure_seeded()` en cada arranque del contenedor.
