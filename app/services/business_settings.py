"""Datos del negocio como un todo (no de un consultorio puntual): nombre
comercial y moneda. Singleton -- una sola fila. Mismo feature ya construido
para Gestiolibra, ported verbatim.
"""
from sqlalchemy import String
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from libragenda.sqlalchemy_repository import Base

SETTINGS_ID = "default"


class BusinessSettingsRow(Base):
    __tablename__ = "business_settings"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    business_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="ARS")


class BusinessSettingsRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def get(self) -> dict:
        with self.session_factory() as session:
            row = session.get(BusinessSettingsRow, SETTINGS_ID)
            if row is None:
                return {"business_name": None, "currency": "ARS"}
            return {"business_name": row.business_name, "currency": row.currency}

    def update(self, business_name: str | None, currency: str) -> dict:
        with self.session_factory.begin() as session:
            row = session.get(BusinessSettingsRow, SETTINGS_ID)
            if row is None:
                row = BusinessSettingsRow(id=SETTINGS_ID)
                session.add(row)
            row.business_name, row.currency = business_name, currency
        return {"business_name": business_name, "currency": currency}
