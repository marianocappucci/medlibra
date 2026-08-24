"""El honorario del profesional: cuánto sale la consulta con cada uno.

Pedido del humano (2026-08-22): *"agregar cobro de honorarios por médico,
permitiendo setear valor de la consulta por profesional"*.

## Qué agrega sobre el precio por sede

`service_prices` modela **(prestación × sede)**: la misma consulta puede costar
distinto en dos consultorios. Lo que no puede decir es que la consulta con la
Dra. Vidal salga más cara que con el Dr. Molina en la **misma** sede, que es
justamente lo que distingue a un honorario de un precio de lista.

Este módulo agrega **(prestación × profesional)**, que **pisa** al de la sede
cuando existe.

## 🔴 Un solo resolvedor, y tiene que seguir siendo uno

`precio_del_turno()` es el único lugar donde se decide qué se cobra. Hoy tiene
un único consumidor —`complete_appointment`— y ahí está la trampa: es fácil que
mañana la seña, un presupuesto o el envío a facturar copien la línea
`service_prices.get(...)` en vez de llamar acá. Con dos lugares resolviendo lo
mismo, el honorario del profesional aplica en uno y no en el otro, y la
diferencia aparece como un descuadre de caja que nadie sabe de dónde sale.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from libragenda.sqlalchemy_repository import Base


class ResourceServicePriceRow(Base):
    __tablename__ = "resource_service_prices"
    __table_args__ = (UniqueConstraint("service_id", "resource_id"),)

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id"), index=True)
    resource_id: Mapped[str] = mapped_column(ForeignKey("resources.id"), index=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))


def _to_dict(row: ResourceServicePriceRow) -> dict:
    return {
        "id": row.id, "service_id": row.service_id,
        "resource_id": row.resource_id, "price": row.price,
    }


class ResourcePriceRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def set_price(
        self, id: str, service_id: str, resource_id: str, price: Decimal,
    ) -> dict:
        """Crea o actualiza el honorario de ese (prestación, profesional)."""
        with self.session_factory.begin() as session:
            row = session.scalar(
                select(ResourceServicePriceRow).where(
                    ResourceServicePriceRow.service_id == service_id,
                    ResourceServicePriceRow.resource_id == resource_id,
                )
            )
            if row is None:
                row = ResourceServicePriceRow(
                    id=id, service_id=service_id, resource_id=resource_id, price=price,
                )
                session.add(row)
            else:
                row.price = price
            session.flush()
            return _to_dict(row)

    def list_for_resource(self, resource_id: str) -> list[dict]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(ResourceServicePriceRow).where(
                    ResourceServicePriceRow.resource_id == resource_id,
                )
            ).all()
            return [_to_dict(row) for row in rows]

    def get(self, service_id: str, resource_id: str) -> dict | None:
        with self.session_factory() as session:
            row = session.scalar(
                select(ResourceServicePriceRow).where(
                    ResourceServicePriceRow.service_id == service_id,
                    ResourceServicePriceRow.resource_id == resource_id,
                )
            )
            return _to_dict(row) if row else None

    def delete(self, service_id: str, resource_id: str) -> None:
        with self.session_factory.begin() as session:
            row = session.scalar(
                select(ResourceServicePriceRow).where(
                    ResourceServicePriceRow.service_id == service_id,
                    ResourceServicePriceRow.resource_id == resource_id,
                )
            )
            if row is None:
                raise KeyError((service_id, resource_id))
            session.delete(row)


def precio_del_turno(
    resource_prices: ResourcePriceRepository,
    service_prices,
    service_id: str,
    resource_id: str,
    branch_id: str | None,
) -> dict | None:
    """Qué se cobra por un turno: **el honorario del profesional, si lo tiene**.

    El orden no es arbitrario. El precio por sede es el de lista —lo que sale
    esa prestación en ese consultorio— y el del profesional es la excepción
    explícita que alguien cargó para él; una excepción que no pisara al general
    no serviría para nada.

    Devuelve `None` si no hay ninguno de los dos, que es el caso de "se completa
    sin facturar" y no un error.
    """
    propio = resource_prices.get(service_id, resource_id)
    if propio is not None:
        return propio
    if branch_id is None:
        # Sin sede no hay precio de lista que buscar. No es lo mismo que "no
        # tiene precio": es que la pregunta no se puede hacer.
        return None
    return service_prices.get(service_id, branch_id)
