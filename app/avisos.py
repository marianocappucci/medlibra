"""Los avisos al paciente: qué se le dice y por dónde sale (ADR-049).

El motor (`libracore.avisos`, ADR-090) sabe **cómo sale un mensaje y que no salga dos veces**; `libragenda` sabe **cuándo toca
recordar** (`ReminderDispatcher`). Lo que es de MedLibra, y vive acá, es lo que ninguno de los dos puede saber: a qué teléfono y
a qué mail se le escribe a un paciente, y con qué texto.

🔴 **El texto de un aviso NO lleva nada clínico** (Ley 25.326 de datos personales y Ley 26.529 de derechos del paciente: los datos
de salud son sensibles). Un WhatsApp lo puede leer cualquiera que vea la pantalla del teléfono, y un mail, quien tenga la casilla.
Por eso el recordatorio dice **sólo**: la sede, la fecha, la hora, el profesional, el consultorio y la dirección si la hay.
**No lleva la prestación** (una «consulta oncológica» o una «prueba de embarazo» ya dice qué le pasa a la persona), ni el motivo
del turno, ni el nombre del paciente, ni su DNI. Nada de eso se lee acá a propósito: `redactar` no toca el servicio del turno, y
`test_avisos_de_turnos.py` lo sostiene.

El nombre del profesional y el del consultorio son los que cargó el consultorio en Configuración. Si el negocio los escribe con la
especialidad («Dra. Vidal — Oncología»), esa palabra viaja: el nombre de un recurso es del consultorio, no un campo clínico, y quien
lo carga tiene que saberlo. Está dicho en el ADR-049.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from libracore.avisos import Mensaje, Proveedor, Resumen, configuracion, reintentar_fallidos
from libracore.avisos.agenda import NotificacionPorAvisos
from libragenda import ReminderDispatcher, ReminderNotification

from .services.husos import SIN_SUCURSAL, hora_de_pared

logger = logging.getLogger("medlibra.avisos")

#: Los días en castellano, a mano: el nombre que da `strftime` depende del locale del proceso, que en un contenedor es el de C.
_DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")

ASUNTO = "Recordatorio de turno"


def texto_del_recordatorio(
    instante_local: datetime, *, sede: str = "", profesional: str = "", consultorio: str = "",
    direccion: str = "", telefono_de_la_sede: str = "", con_formato: bool = False,
) -> str:
    """El texto del recordatorio. **Función pura, y sin prestación a propósito**: ver el docstring del módulo.

    `instante_local` es la hora de pared de la sede (sin huso). `con_formato` pone el título en negrita de WhatsApp (`*...*`); el
    mail va en texto plano. Lo que viene vacío no sale (una sede sin dirección no dice «Dirección:»).
    """
    titulo = f"*{ASUNTO}*" if con_formato else ASUNTO
    dia = f"{_DIAS[instante_local.weekday()]} {instante_local:%d/%m/%Y}"
    lineas = [titulo, f"Tenés un turno el {dia} a las {instante_local:%H:%M} hs."]
    for rotulo, valor in (("Lugar", sede), ("Profesional", profesional), ("Consultorio", consultorio),
                          ("Dirección", direccion)):
        valor = (valor or "").strip()
        if valor:
            lineas.append(f"{rotulo}: {valor}")
    telefono = (telefono_de_la_sede or "").strip()
    if telefono:
        lineas.append(f"Para cambiarlo o cancelarlo, comunicate al {telefono}.")
    return "\n".join(lineas)


def armar_notificacion(*, catalog, appointments, branches, consultorios,
                       proveedores: Callable[[], Mapping[str, Proveedor]]) -> NotificacionPorAvisos:
    """El `NotificationPort` de `libragenda` que manda de verdad, por WhatsApp y por mail (reemplaza al `LoggingNotificationPort`).

    - `catalog`: el catálogo de `libragenda` (clientes, recursos). `appointments`: su repositorio de turnos (para los recursos
      secundarios, que es donde está el consultorio, ADR-042). `branches`: `BranchRepository` (dirección, teléfono y huso de la
      sede). `consultorios`: `ConsultorioRepository` (para saber cuál de los recursos del turno es una sala).
    - `proveedores`: se resuelve en **cada envío** (la configuración de avisos cambia con el proceso andando).
    - La clave del aviso es `agenda:{turno}:{política}` (la pone el motor): `24h` y `2h` de un mismo turno son dos avisos, y el
      mismo no sale dos veces.
    """

    def contacto(client_id: str) -> dict[str, str]:
        paciente = catalog.get_client(client_id)
        if paciente is None:
            return {}
        return {"telefono": paciente.phone or "", "email": paciente.email or ""}

    def redactar(notificacion: ReminderNotification, canal: str) -> Mensaje:
        recurso = catalog.get_resource(notificacion.resource_id)
        sede = branches.get(recurso.branch_id) if recurso is not None and recurso.branch_id else None
        turno = appointments.get(notificacion.appointment_id)
        consultorio = ""
        for rid in (turno.secondary_resource_ids if turno is not None else ()):
            sala = consultorios.get(rid)  # los recursos secundarios que no son una sala dan None
            if sala is not None:
                consultorio = sala["name"]
                break
        texto = texto_del_recordatorio(
            hora_de_pared(notificacion.starts_at, sede["timezone"] if sede else SIN_SUCURSAL),
            sede=sede["name"] if sede else "",
            profesional=recurso.name if recurso is not None else "",
            consultorio=consultorio,
            direccion=(sede.get("address") or "") if sede else "",
            telefono_de_la_sede=(sede.get("phone") or "") if sede else "",
            con_formato=canal == "whatsapp",
        )
        return Mensaje("", asunto=ASUNTO, cuerpo=texto)

    return NotificacionPorAvisos(proveedores, contacto=contacto, redactar=redactar)


def proveedores_de_la_instancia(smtp_config: Callable) -> Callable[[], dict[str, Proveedor]]:
    """`{canal: proveedor}` según la configuración de avisos de la instancia, resuelto en cada llamada.

    Pasa por `configuracion.proveedores` (y no por una referencia guardada) para que la pantalla de Avisos cambie el modo sin
    reiniciar y para que un test pueda cambiar el transporte de Evolution."""
    return lambda: configuracion.proveedores(smtp_config)


def reintentar_los_fallidos(proveedores: Mapping[str, Proveedor]) -> dict[str, Resumen]:
    """`reintentar_fallidos` en cada canal. **Mejor esfuerzo**: se llama después de `dispatch`, que ya dio los recordatorios por
    enviados; una excepción acá (la base, un proveedor) no puede convertir en un 500 una tanda que ya salió. Lo que no se
    reintenta ahora, se reintenta en la corrida que sigue."""
    resumenes: dict[str, Resumen] = {}
    for canal, proveedor in proveedores.items():
        try:
            resumenes[canal] = reintentar_fallidos(proveedor)
        except Exception:  # noqa: BLE001 - ver el docstring
            logger.exception("No se pudieron reintentar los avisos fallidos de %s.", canal)
            continue
        logger.info("Reintento de avisos fallidos por %s: %s", canal, resumenes[canal])
    return resumenes


def enviar_recordatorios(dispatcher: ReminderDispatcher, proveedores: Callable[[], Mapping[str, Proveedor]],
                         ahora: datetime | None = None) -> list[ReminderNotification]:
    """Una tanda: manda los recordatorios vencidos (`dispatch`) y, **después**, reintenta los avisos que fallaron.

    Es lo que corren `POST /reminders/dispatch` y `scripts/enviar_recordatorios.py`. Devuelve los recordatorios vencidos de esta
    tanda, igual que `dispatch`. Síncrono y bloqueante (`despachar` espera al proveedor): desde una ruta `def` o un script.
    """
    vencidos = dispatcher.dispatch(ahora or datetime.now(UTC))
    reintentar_los_fallidos(proveedores())
    return vencidos
