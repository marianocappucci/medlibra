"""Horario comercial: default weekly hours at the branch (consultorio)
level, on top of LibraGenda's own per-resource Availability. Same feature
already built for Gestiolibra (see that repo's app/services/branch_hours.py)
-- ported verbatim, no product-specific logic in here.

Deliberately opt-in: a branch with no hours configured gates nothing here
(same as today) -- only once hours exist for a branch do bookings for its
resources also have to fall inside them.
"""
from datetime import time

from sqlalchemy import ForeignKey, Integer, Time, select
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from libragenda.sqlalchemy_repository import Base


class BranchHoursRow(Base):
    __tablename__ = "branch_hours"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    branch_id: Mapped[str] = mapped_column(ForeignKey("branches.id"), index=True)
    weekday: Mapped[int] = mapped_column(Integer)
    starts_at: Mapped[time] = mapped_column(Time)
    ends_at: Mapped[time] = mapped_column(Time)


def _to_dict(row: BranchHoursRow) -> dict:
    return {
        "id": row.id, "branch_id": row.branch_id,
        "weekday": row.weekday, "starts_at": row.starts_at, "ends_at": row.ends_at,
    }


class BranchHoursRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def create(self, branch_id: str, weekday: int, starts_at: time, ends_at: time) -> dict:
        if not 0 <= weekday <= 6:
            raise ValueError("weekday must be between 0 (Monday) and 6 (Sunday)")
        if starts_at >= ends_at:
            raise ValueError("hours must end after they start")
        row = BranchHoursRow(branch_id=branch_id, weekday=weekday, starts_at=starts_at, ends_at=ends_at)
        with self.session_factory.begin() as session:
            session.add(row)
            session.flush()
            created = _to_dict(row)
        return created

    def update(self, hours_id: int, weekday: int, starts_at: time, ends_at: time) -> dict:
        if not 0 <= weekday <= 6:
            raise ValueError("weekday must be between 0 (Monday) and 6 (Sunday)")
        if starts_at >= ends_at:
            raise ValueError("hours must end after they start")
        with self.session_factory.begin() as session:
            row = session.get(BranchHoursRow, hours_id)
            if row is None:
                raise KeyError(hours_id)
            row.weekday, row.starts_at, row.ends_at = weekday, starts_at, ends_at
            updated = _to_dict(row)
        return updated

    def list_for_branch(self, branch_id: str) -> list[dict]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(BranchHoursRow).where(BranchHoursRow.branch_id == branch_id)
            ).all()
            return [_to_dict(row) for row in rows]

    def delete(self, hours_id: int) -> None:
        with self.session_factory.begin() as session:
            row = session.get(BranchHoursRow, hours_id)
            if row is None:
                raise KeyError(hours_id)
            session.delete(row)

    def is_within_hours(self, branch_id: str, starts_at, ends_at) -> bool:
        """True if [starts_at, ends_at) falls inside a configured window for
        that weekday, or if the branch has no hours configured at all
        (opt-in gating, see module docstring)."""
        windows = self.list_for_branch(branch_id)
        if not windows:
            return True
        return any(
            starts_at.weekday() == window["weekday"]
            and starts_at.time() >= window["starts_at"]
            and ends_at.time() <= window["ends_at"]
            and starts_at.date() == ends_at.date()
            for window in windows
        )
