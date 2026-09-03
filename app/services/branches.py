"""Branch: coordinates LibraGenda's generic Branch (id, name, active,
timezone) with MedLibra's own contact extension (phone, address) -- same
pattern as Patient extending LibraGenda's Client, and the same feature
already built for Gestiolibra (see that repo's app/services/branches.py).
"""
from libragenda import Branch
from libragenda.catalog_repository import SqlAlchemyCatalogRepository
from libragenda.sqlalchemy_repository import Base
from sqlalchemy import ForeignKey, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker


class BranchContactRow(Base):
    __tablename__ = "branch_contacts"

    branch_id: Mapped[str] = mapped_column(ForeignKey("branches.id"), primary_key=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address: Mapped[str | None] = mapped_column(String(300), nullable=True)


class BranchRepository:
    def __init__(
        self, catalog: SqlAlchemyCatalogRepository, session_factory: sessionmaker[Session],
    ) -> None:
        self.catalog = catalog
        self.session_factory = session_factory

    def create(
        self, id: str, name: str, active: bool, timezone: str,
        phone: str | None, address: str | None,
    ) -> dict:
        branch = Branch(id, name, active, timezone)
        self.catalog.add_branch(branch)  # raises IntegrityError on duplicate id
        with self.session_factory.begin() as session:
            session.add(BranchContactRow(branch_id=id, phone=phone, address=address))
        return self._to_out(branch, phone, address)

    def get(self, branch_id: str) -> dict | None:
        branch = self.catalog.get_branch(branch_id)
        if branch is None:
            return None
        return self._to_out(branch, *self._extension(branch_id))

    def list(self) -> list[dict]:
        with self.session_factory() as session:
            extensions = {row.branch_id: row for row in session.scalars(select(BranchContactRow)).all()}
        return [
            self._to_out(
                branch,
                extensions[branch.id].phone if branch.id in extensions else None,
                extensions[branch.id].address if branch.id in extensions else None,
            )
            for branch in self.catalog.list_branches()
        ]

    def update(
        self, branch_id: str, name: str, active: bool, timezone: str,
        phone: str | None, address: str | None,
    ) -> dict:
        branch = Branch(branch_id, name, active, timezone)
        self.catalog.update_branch(branch_id, branch)  # raises KeyError if missing
        with self.session_factory.begin() as session:
            row = session.get(BranchContactRow, branch_id)
            if row is None:
                row = BranchContactRow(branch_id=branch_id)
                session.add(row)
            row.phone, row.address = phone, address
        return self._to_out(branch, phone, address)

    def delete(self, branch_id: str) -> None:
        # Borrar primero la extension (BranchContactRow.branch_id tiene FK
        # a branches.id): borrar el Branch antes violaria esa FK con
        # integridad referencial forzada (SQLite con PRAGMA foreign_keys=ON,
        # o Postgres) -- mismo bug ya encontrado y corregido en
        # PatientRepository de este mismo repo y en BranchRepository de
        # Gestiolibra.
        with self.session_factory.begin() as session:
            row = session.get(BranchContactRow, branch_id)
            if row is not None:
                session.delete(row)
        self.catalog.delete_branch(branch_id)  # raises KeyError if missing

    def _extension(self, branch_id: str) -> tuple[str | None, str | None]:
        with self.session_factory() as session:
            row = session.get(BranchContactRow, branch_id)
            return (row.phone, row.address) if row else (None, None)

    @staticmethod
    def _to_out(branch: Branch, phone: str | None, address: str | None) -> dict:
        return {
            "id": branch.id, "name": branch.name, "active": branch.active,
            "timezone": branch.timezone, "phone": phone, "address": address,
        }
