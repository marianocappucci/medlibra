"""`patients` y `walkins` apuntan a `agenda_clients` (libragenda v0.14.0, ADR-043).

libragenda renombró su `clients` a `agenda_clients` porque LibraCore tiene una `clients` propia (id entero) y,
con una sola base por producto, las dos no pueden llamarse igual. En MedLibra cuelgan de esa tabla:

- **`patients`**, cuyo `id` es a la vez clave primaria y clave foránea (la ficha clínica comparte el id del
  cliente de la agenda; verificado en el esquema, no supuesto);
- **`walkins.client_id`**, la demanda espontánea.

Lo que se mide acá, sobre PostgreSQL y con la cadena real:

1. Los modelos y las revisiones dicen `agenda_clients`, y no queda ninguna referencia a `clients` en el código.
2. **Base nueva**: la cadena de libragenda deja `agenda_clients` y las revisiones de MedLibra le cuelgan las
   claves; las claves se hacen cumplir (un paciente sin cliente no entra, un cliente con ficha no se borra).
3. **Instancia viva**: una base que todavía tiene `clients` y claves apuntándole, al correr
   `libragenda-migrar upgrade`, ve moverse las dos claves **solas**. Es lo que el plan no había podido verificar
   para `patients`, con su clave primaria que es también foránea.
"""
from __future__ import annotations

import re
from pathlib import Path

import psycopg
import pytest
from alembic import command
from bases_temporales import base_temporal, consultar, correr_cadena, cruda, una

RAIZ = Path(__file__).resolve().parent.parent


def _destino_de_las_claves(url: str) -> dict[str, str]:
    """`{tabla.columna: tabla a la que apunta}` de las claves foráneas de `patients` y `walkins` hacia el cliente."""
    filas = consultar(url, """
        SELECT c.conrelid::regclass::text || '.' || a.attname, c.confrelid::regclass::text
        FROM pg_constraint c
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
        WHERE c.contype = 'f' AND c.conrelid IN ('patients'::regclass, 'walkins'::regclass)
          AND c.confrelid::regclass::text IN ('clients', 'agenda_clients')
    """)
    return dict(filas)


# ── 1. El código ────────────────────────────────────────────────────────────


def test_los_modelos_apuntan_a_agenda_clients():
    from libragenda.sqlalchemy_repository import Base

    import app.main  # noqa: F401 - registra todos los modelos en `Base.metadata`

    tablas = Base.metadata.tables
    assert "clients" not in tablas, "libragenda v0.14.0 no declara `clients`: la de LibraCore es otra"
    assert "agenda_clients" in tablas
    for tabla, columna in (("patients", "id"), ("walkins", "client_id")):
        destinos = {fk.column.table.name for fk in tablas[tabla].columns[columna].foreign_keys}
        assert destinos == {"agenda_clients"}, (tabla, columna, destinos)


def test_no_queda_ninguna_referencia_a_la_clients_de_libragenda_en_el_codigo():
    """Una guarda de fuentes: la `ForeignKey("clients.id")` que se cuele en un modelo o en una revisión nueva
    funciona contra una base de antes y muere contra una unida, que es donde menos se prueba."""
    patron = re.compile(r"""["']clients\.id["']|\b(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+clients\b""", re.IGNORECASE)
    encontrados = []
    for carpeta in ("app", "migrations", "scripts"):
        for archivo in (RAIZ / carpeta).rglob("*"):
            if archivo.suffix not in (".py", ".sh", ".sql") or "__pycache__" in archivo.parts:
                continue
            for n, linea in enumerate(archivo.read_text(encoding="utf-8").splitlines(), 1):
                if patron.search(linea) and "docker/postgres-init" not in str(archivo):
                    encontrados.append(f"{archivo.relative_to(RAIZ)}:{n}: {linea.strip()}")
    assert not encontrados, "\n".join(encontrados)


# ── 2. Base nueva ───────────────────────────────────────────────────────────


def test_una_base_nueva_cuelga_patients_y_walkins_de_agenda_clients_y_las_hace_cumplir():
    with base_temporal("fk") as url:
        # Sólo lo que las revisiones de MedLibra necesitan debajo: la cadena de libragenda y la propia.
        correr_cadena(url, solo=("libragenda-migrar", "alembic"))

        assert _destino_de_las_claves(url) == {"patients.id": "agenda_clients", "walkins.client_id": "agenda_clients"}

        # Se hacen cumplir: un paciente sin cliente de la agenda no entra...
        with psycopg.connect(cruda(url), autocommit=True) as c:
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                c.execute("INSERT INTO patients (id) VALUES ('no-existe')")
            c.execute("INSERT INTO agenda_clients (id, name, active) VALUES ('c1', 'Paciente Ficticio', true)")
            c.execute("INSERT INTO patients (id, dni) VALUES ('c1', '11111111')")
            # ...y el cliente con ficha no se borra mientras la ficha exista.
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                c.execute("DELETE FROM agenda_clients WHERE id = 'c1'")

            # La demanda espontánea, igual.
            c.execute("INSERT INTO branches (id, name, active, timezone) VALUES ('b1', 'Sede', true, 'UTC')")
            c.execute("INSERT INTO services (id, name, duration_seconds, active) VALUES ('s1', 'Consulta', 1800, true)")
            c.execute("INSERT INTO resources (id, name, branch_id, active) VALUES ('r1', 'Dr. Ficticio', 'b1', true)")
            c.execute("INSERT INTO consultorios (id, name, branch_id, active) VALUES ('k1', 'Consultorio 1', 'b1', true)")
            c.execute("INSERT INTO agenda_blocks (id, resource_id, consultorio_id, weekday, starts_at, ends_at, "
                      "valid_from, slot_minutes, modality) "
                      "VALUES ('bl1', 'r1', 'k1', 0, '09:00', '12:00', '2026-01-01', 30, 'espontanea')")
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                c.execute("INSERT INTO walkins (id, block_id, day, client_id, service_id, arrival_order, status, created_at) "
                          "VALUES ('w0', 'bl1', '2026-10-26', 'no-existe', 's1', 1, 'waiting', now())")
            c.execute("INSERT INTO walkins (id, block_id, day, client_id, service_id, arrival_order, status, created_at) "
                      "VALUES ('w1', 'bl1', '2026-10-26', 'c1', 's1', 1, 'waiting', now())")


# ── 3. Instancia viva ───────────────────────────────────────────────────────


def test_en_una_instancia_viva_las_dos_claves_siguen_solas_el_renombre_de_libragenda(monkeypatch):
    """El estado de `dev` y `demo` hoy: `clients` con `patients` y `walkins` colgando. `libragenda-migrar upgrade`
    la renombra y PostgreSQL mueve las claves; `patients.id` es primaria y foránea a la vez y tiene que
    seguir siendo las dos cosas."""
    from libragenda.migrar import configuracion, upgrade

    with base_temporal("viva") as url:
        correr_cadena(url, solo=("libragenda-migrar", "alembic"))
        # Se vuelve al estado de antes: se baja la revisión de libragenda que renombra (`0010_agenda_clients`).
        monkeypatch.setenv("DATABASE_URL", url)
        command.downgrade(configuracion(url), "-1")
        # El control: de verdad quedó como la instancia de antes, con las claves apuntando a `clients`.
        assert _destino_de_las_claves(url) == {"patients.id": "clients", "walkins.client_id": "clients"}
        consultar(url, "INSERT INTO clients (id, name, active) VALUES ('c1', 'Paciente Ficticio', true)")
        consultar(url, "INSERT INTO patients (id, dni) VALUES ('c1', '11111111')")

        upgrade(url)

        assert _destino_de_las_claves(url) == {"patients.id": "agenda_clients", "walkins.client_id": "agenda_clients"}
        # Los datos están, y `patients.id` sigue siendo clave primaria además de foránea.
        assert una(url, "SELECT count(*) FROM patients p JOIN agenda_clients c ON c.id = p.id") == 1
        assert una(url, "SELECT count(*) FROM pg_constraint WHERE conrelid = 'patients'::regclass AND contype = 'p'") == 1
        # Y la del motor no existe en este dominio: ya no hay una `clients` con la que confundirse.
        assert una(url, "SELECT count(*) FROM pg_tables WHERE tablename = 'clients'") == 0
