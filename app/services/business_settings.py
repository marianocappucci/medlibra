"""Datos del negocio como un todo (no de un consultorio puntual): nombre
comercial, moneda y alicuota de IVA por defecto. Singleton -- una sola
fila. Portado de Gestiolibra, con `default_iva_rate` propio de MedLibra
(ver `iva_rates.py`).
"""
from decimal import Decimal

from sqlalchemy import Numeric, String
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from libragenda.sqlalchemy_repository import Base

from .iva_rates import DEFAULT_RATE, validate_rate

SETTINGS_ID = "default"


class BusinessSettingsRow(Base):
    __tablename__ = "business_settings"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    business_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="ARS")
    # Alicuota que se aplica a los servicios que no tienen una propia.
    # Arranca en 21% para no cambiarle el comportamiento a ninguna
    # instalacion existente -- un consultorio con prestaciones exentas la
    # baja a 0 una sola vez, en vez de servicio por servicio.
    default_iva_rate: Mapped[Decimal] = mapped_column(
        Numeric(6, 4), default=DEFAULT_RATE, server_default=str(DEFAULT_RATE)
    )


class BusinessSettingsRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def get(self) -> dict:
        with self.session_factory() as session:
            row = session.get(BusinessSettingsRow, SETTINGS_ID)
            if row is None:
                return {
                    "business_name": None, "currency": "ARS",
                    "default_iva_rate": DEFAULT_RATE,
                }
            return {
                "business_name": row.business_name, "currency": row.currency,
                "default_iva_rate": Decimal(row.default_iva_rate),
            }

    def update(
        self, business_name: str | None, currency: str,
        default_iva_rate: Decimal | None = None,
    ) -> dict:
        """`default_iva_rate=None` deja la que estaba -- no la pisa con el
        default del modulo, para que un PUT que sólo cambia el nombre no
        le mueva la alicuota al consultorio."""
        with self.session_factory.begin() as session:
            row = session.get(BusinessSettingsRow, SETTINGS_ID)
            if row is None:
                row = BusinessSettingsRow(id=SETTINGS_ID, default_iva_rate=DEFAULT_RATE)
                session.add(row)
            row.business_name, row.currency = business_name, currency
            if default_iva_rate is not None:
                row.default_iva_rate = validate_rate(default_iva_rate)
            session.flush()
            resolved = Decimal(row.default_iva_rate)
        return {
            "business_name": business_name, "currency": currency,
            "default_iva_rate": resolved,
        }
