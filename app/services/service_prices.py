"""Precio por servicio y sucursal: LibraGenda's Service has no price field
by design. One service (ej. "Consulta") can cost differently at different
consultorios, so this is a service x branch -> price table, not a single
price on Service. Same feature already built for Gestiolibra, ported
verbatim.
"""
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from libragenda.sqlalchemy_repository import Base


class ServicePriceRow(Base):
    __tablename__ = "service_prices"
    __table_args__ = (UniqueConstraint("service_id", "branch_id"),)

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id"), index=True)
    branch_id: Mapped[str] = mapped_column(ForeignKey("branches.id"), index=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))


def _to_dict(row: ServicePriceRow) -> dict:
    return {
        "id": row.id, "service_id": row.service_id,
        "branch_id": row.branch_id, "price": row.price,
    }


class ServicePriceRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def set_price(self, id: str, service_id: str, branch_id: str, price: Decimal) -> dict:
        """Create or update the price for this (service, branch) pair."""
        with self.session_factory.begin() as session:
            row = session.scalar(
                select(ServicePriceRow).where(
                    ServicePriceRow.service_id == service_id,
                    ServicePriceRow.branch_id == branch_id,
                )
            )
            if row is None:
                row = ServicePriceRow(id=id, service_id=service_id, branch_id=branch_id, price=price)
                session.add(row)
            else:
                row.price = price
            session.flush()
            result = _to_dict(row)
        return result

    def list_for_service(self, service_id: str) -> list[dict]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(ServicePriceRow).where(ServicePriceRow.service_id == service_id)
            ).all()
            return [_to_dict(row) for row in rows]

    def get(self, service_id: str, branch_id: str) -> dict | None:
        with self.session_factory() as session:
            row = session.scalar(
                select(ServicePriceRow).where(
                    ServicePriceRow.service_id == service_id,
                    ServicePriceRow.branch_id == branch_id,
                )
            )
            return _to_dict(row) if row else None

    def delete(self, service_id: str, branch_id: str) -> None:
        with self.session_factory.begin() as session:
            row = session.scalar(
                select(ServicePriceRow).where(
                    ServicePriceRow.service_id == service_id,
                    ServicePriceRow.branch_id == branch_id,
                )
            )
            if row is None:
                raise KeyError((service_id, branch_id))
            session.delete(row)
