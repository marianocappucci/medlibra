"""Facturacion/caja para MedLibra, compuesto sobre libracore.db.

libracore.db es sqlite3 crudo, sin capa de abstraccion -- una conexion
propia, separada del engine SQLAlchemy que usa LibraGenda/MedLibra para
el resto del dominio (ver DECISIONS.md ADR-XXX de este repo). MedLibra es
de instancia unica por cliente (arquitectura silo, igual que
Contalibra/Restolibra), asi que hay una sola "empresa" ARCA -- una
constante fija, no una tabla de empresas.

Una sola factura por turno completado (decision del usuario, 2026-07-22):
la sena ya cobrada (si existe) y el saldo restante se reconcilian como dos
movimientos de caja separados -- cada uno con su propio medio de pago --
pero apuntando a la MISMA factura. La sena nunca genera su propia factura.
"""
import os
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from libracore import arca_facturacion
from libracore.db import arca_config as db_arca_config
from libracore.db import caja as db_caja
from libracore.db import core as libracore_core
from libracore.db import facturas as db_facturas
from libracore.db.schema import init_core_schema

EMPRESA = "consultorio"

TIPO_FACTURA_A = 1
TIPO_FACTURA_B = 6

# Codigos de condicion de IVA del receptor que exige ARCA/AFIP -- mismo
# mapeo que usa Contalibra en web/routers/facturas.py (IVA_CODES), no
# migrado a libracore todavia por ser un dict chico y estable, no un
# modulo con logica propia.
IVA_CODES = {
    "Responsable Inscripto": 1,
    "IVA Responsable Inscripto": 1,
    "Monotributista": 6,
    "Responsable Monotributo": 6,
    "IVA Exento": 4,
    "Consumidor Final": 5,
    "No Alcanzado": 3,
    "IVA No Responsable": 3,
}

_IVA_RATE = Decimal("0.21")


class BillingError(Exception):
    """Base error for billing use-case failures."""


class BalanceRequiresMedioPago(BillingError):
    """Raised when there's a positive balance to invoice but no medio_pago
    was given to record how it was collected."""


def configure(db_path: str) -> None:
    """Llamar una vez al arrancar la app: configura libracore.db contra su
    propio archivo SQLite (independiente del engine de LibraGenda) y
    asegura que el schema compartido y una caja por defecto existan."""
    directory = os.path.dirname(db_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    libracore_core.configure(db_path)
    conn = libracore_core.get_connection()
    try:
        init_core_schema(conn)
        conn.commit()
    finally:
        conn.close()
    if db_caja.get_default_caja_id() is None:
        caja_id = db_caja.create_caja_config(
            "Caja Consultorio", "", list(db_caja.MEDIOS_PAGO_LABELS),
        )
        db_caja.set_default_caja(caja_id)


def get_arca_config() -> dict | None:
    return db_arca_config.obtener_arca_config(EMPRESA)


def set_arca_config(
    cuit: str, punto_venta: int, clave_path: str, certificado_path: str,
    ambiente: str = "homologacion",
) -> dict:
    if get_arca_config() is None:
        db_arca_config.crear_arca_config(
            EMPRESA, cuit, punto_venta, clave_path, certificado_path, ambiente,
        )
    else:
        db_arca_config.actualizar_arca_config(
            EMPRESA, cuit=cuit, punto_venta=punto_venta,
            clave_path=clave_path, certificado_path=certificado_path, ambiente=ambiente,
        )
    return get_arca_config()


def _tipo_comprobante(condicion_iva: str | None) -> int:
    return TIPO_FACTURA_A if condicion_iva == "Responsable Inscripto" else TIPO_FACTURA_B


def _split_iva(total: Decimal) -> tuple[Decimal, Decimal]:
    """Asume `total` como monto final (IVA incluido) y separa subtotal/IVA
    al 21% -- simplificacion documentada: no contempla servicios de salud
    exentos ni otras alicuotas; a revisar con un contador antes de facturar
    contra ARCA real (ver TASKS.md)."""
    subtotal = (total / (Decimal("1") + _IVA_RATE)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    iva_amount = total - subtotal
    return subtotal, iva_amount


async def invoice_appointment(
    patient: dict, service_price: Decimal, referencia: str,
    deposit_amount: Decimal | None = None, deposit_medio_pago: str | None = None,
    balance_medio_pago: str | None = None,
) -> dict:
    """Emite una factura por el total del servicio y registra el/los
    movimiento(s) de caja correspondientes. Se llama una sola vez, al
    completar el turno -- no por cada pago.
    """
    deposit_amount = deposit_amount or Decimal("0")
    balance = service_price - deposit_amount
    if balance > 0 and not balance_medio_pago:
        raise BalanceRequiresMedioPago(balance)

    arca_cfg = get_arca_config()
    punto_venta = arca_cfg["punto_venta"] if arca_cfg else 1
    tipo = _tipo_comprobante(patient.get("condicion_iva"))
    subtotal, iva_amount = _split_iva(service_price)

    numero, ta, arca_used = await arca_facturacion.get_next_numero_with_arca(punto_venta, tipo)
    factura_id = db_facturas.create_factura(
        tipo, punto_venta, numero, date.today().isoformat(),
        patient.get("cuit") or "", patient.get("name") or "",
        IVA_CODES.get(patient.get("condicion_iva"), IVA_CODES["Consumidor Final"]),
        [], float(subtotal), float(iva_amount), float(service_price),
    )
    factura = db_facturas.get_factura(factura_id)
    factura = await arca_facturacion.solicitar_cae(factura_id, factura, ta, arca_used)

    if deposit_amount > 0:
        db_caja.create_caja_movimiento(
            date.today().isoformat(), "ingreso", f"Sena factura {numero}",
            deposit_amount, referencia=f"{referencia}-sena",
            factura_id=factura_id, medio_pago=deposit_medio_pago or "",
        )
    if balance > 0:
        db_caja.create_caja_movimiento(
            date.today().isoformat(), "ingreso", f"Saldo factura {numero}",
            balance, referencia=f"{referencia}-saldo",
            factura_id=factura_id, medio_pago=balance_medio_pago or "",
        )
    return factura
