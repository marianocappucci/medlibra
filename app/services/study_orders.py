"""Estudios: pedidos de estudios/analisis por paciente, con resultado.

Un pedido tiene uno o mas items (analisis de sangre, radiografia, etc.),
mismo patron que recetas -- una consulta suele generar un pedido con
varios estudios a la vez. Cada item puede tener uno o mas resultados
propios (llegan por separado, en momentos distintos): el resultado es un
registro nuevo vinculado al item, nunca una edicion del pedido original --
mismo espiritu append-only que recetas/notas clinicas.
"""
from datetime import UTC, datetime, timezone
from uuid import uuid4

from libragenda.sqlalchemy_repository import Base
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship, sessionmaker

from . import historia_en_nodo


class StudyOrderRow(Base):
    __tablename__ = "study_orders"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    author: Mapped[str] = mapped_column(String(200))

    items: Mapped[list["StudyOrderItemRow"]] = relationship(
        back_populates="order", order_by="StudyOrderItemRow.position",
        cascade="all, delete-orphan",
    )


class StudyOrderItemRow(Base):
    __tablename__ = "study_order_items"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("study_orders.id"), index=True)
    # Orden de carga dentro del pedido -- el id es un UUID, no sirve para
    # ordenar (no es secuencial), así que se guarda la posición explícita.
    position: Mapped[int] = mapped_column(Integer)
    study_type: Mapped[str] = mapped_column(String(200))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    order: Mapped[StudyOrderRow] = relationship(back_populates="items")
    results: Mapped[list["StudyResultRow"]] = relationship(
        back_populates="item", order_by="StudyResultRow.created_at",
        cascade="all, delete-orphan",
    )


class StudyResultRow(Base):
    __tablename__ = "study_results"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("study_order_items.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    author: Mapped[str] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)

    item: Mapped[StudyOrderItemRow] = relationship(back_populates="results")


def _result_to_dict(result: StudyResultRow) -> dict:
    return {
        "id": result.id, "item_id": result.item_id,
        "created_at": result.created_at, "author": result.author, "text": result.text,
    }


def _order_to_dict(row: StudyOrderRow) -> dict:
    return {
        "id": row.id, "patient_id": row.patient_id,
        "created_at": row.created_at, "author": row.author,
        "items": [
            {
                "id": item.id, "study_type": item.study_type, "reason": item.reason,
                "results": [_result_to_dict(result) for result in item.results],
            }
            for item in row.items
        ],
    }


class PedidoEnviadoALibraView(Exception):
    """El pedido ya está en LibraView (ADR-051): no se borra."""


class StudyOrderRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def create(self, patient_id: str, author: str, items: list[dict]) -> dict:
        if not items:
            raise ValueError("a study order needs at least one item")
        row = StudyOrderRow(
            id=str(uuid4()), patient_id=patient_id, author=author,
            created_at=datetime.now(UTC),
            items=[
                StudyOrderItemRow(
                    id=str(uuid4()), position=position,
                    study_type=item["study_type"], reason=item.get("reason"),
                )
                for position, item in enumerate(items)
            ],
        )
        with self.session_factory.begin() as session:
            session.add(row)
            session.flush()
            session.refresh(row)
            # En un nodo de LibraEdge el pedido sube como `pedido_estudio.alta`, en esta misma transaccion (ADR-045).
            historia_en_nodo.encolar_alta(session, historia_en_nodo.PEDIDO_DE_ESTUDIO, row)
            result = _order_to_dict(row)
        return result

    def get(self, order_id: str) -> dict | None:
        with self.session_factory() as session:
            row = session.get(StudyOrderRow, order_id)
            return _order_to_dict(row) if row else None

    def list_by_patient(self, patient_id: str) -> list[dict]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(StudyOrderRow)
                .where(StudyOrderRow.patient_id == patient_id)
                .order_by(StudyOrderRow.created_at)
            ).all()
            return [_order_to_dict(row) for row in rows]

    def delete(self, order_id: str) -> None:
        """Borra el pedido. Si ya se mandó a LibraView (ADR-051) levanta `PedidoEnviadoALibraView`: del otro lado hay una orden con
        estudios que se van a hacer y a informar, y borrar acá dejaría informes que llegan a un pedido que no existe. Si el envío
        quedó en error o pendiente (LibraView no lo tiene) se borra junto con sus filas."""
        # Import perezoso: `libraview` importa este módulo (sus tablas apuntan a las del pedido).
        from .libraview import ENVIADO, EnvioALibraViewRow, EstudioEnLibraViewRow

        with self.session_factory.begin() as session:
            row = session.get(StudyOrderRow, order_id)
            if row is None:
                raise KeyError(order_id)
            envio = session.get(EnvioALibraViewRow, order_id)
            if envio is not None:
                if envio.estado == ENVIADO:
                    raise PedidoEnviadoALibraView(order_id)
                for estudio in session.scalars(
                    select(EstudioEnLibraViewRow).where(EstudioEnLibraViewRow.order_id == order_id)
                ):
                    session.delete(estudio)
                session.delete(envio)
                # Primero las hijas: las FK apuntan al pedido y a sus ítems.
                session.flush()
            session.delete(row)

    def add_result(self, item_id: str, author: str, text: str) -> dict:
        with self.session_factory.begin() as session:
            item = session.get(StudyOrderItemRow, item_id)
            if item is None:
                raise KeyError(item_id)
            result = StudyResultRow(
                id=str(uuid4()), item_id=item_id, author=author,
                created_at=datetime.now(UTC), text=text,
            )
            session.add(result)
            session.flush()
            session.refresh(result)
            out = _result_to_dict(result)
        return out

    def delete_result(self, result_id: str) -> None:
        with self.session_factory.begin() as session:
            row = session.get(StudyResultRow, result_id)
            if row is None:
                raise KeyError(result_id)
            session.delete(row)

    def get_item_order_id(self, item_id: str) -> str | None:
        with self.session_factory() as session:
            item = session.get(StudyOrderItemRow, item_id)
            return item.order_id if item else None
