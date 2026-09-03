"""Alembic environment for MedLibra's own tables (not LibraGenda's).

`UserRow`/`PatientRow`/`ClinicalNoteRow` are registered on LibraGenda's
shared declarative Base (see app/services/users.py, patients.py,
clinical_notes.py), so target_metadata is deliberately left as None
instead of Base.metadata: pointing it there would make `alembic
revision --autogenerate` also see LibraGenda's own tables (branches,
clients, resources...) as belonging to this chain, which is wrong -- those
are managed by LibraGenda's own migrations (run via its
scripts/run_migrations.sh, see README.md). Migrations here are written by
hand, same convention LibraGenda itself uses. Same pattern as Gestiolibra's
own migrations/env.py.

`version_table` is set to a name distinct from the default "alembic_version"
because this chain runs against the same physical database as LibraGenda's
migrations -- sharing the default name would corrupt both chains' version
tracking.
"""
import os

from alembic import context
from libracore.db.url_de_instancia import url_de_instancia
from sqlalchemy import engine_from_config, pool

target_metadata = None
VERSION_TABLE = "alembic_version_medlibra"


def get_url():
    return url_de_instancia("medlibra") or context.config.get_main_option("sqlalchemy.url")


def run_migrations_offline():
    context.configure(
        url=get_url(), target_metadata=target_metadata,
        version_table=VERSION_TABLE, literal_binds=True,
    )
    with context.begin_transaction(): context.run_migrations()

def run_migrations_online():
    configuration = context.config.get_section(context.config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, version_table=VERSION_TABLE,
        )
        with context.begin_transaction(): context.run_migrations()

if context.is_offline_mode(): run_migrations_offline()
else: run_migrations_online()
