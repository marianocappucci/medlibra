# MedLibra

Vertical de turnos para salud: consultorios, profesionales independientes y
centros médicos.

Compone:

- LibraGenda `v0.5.0` — agenda, recursos, servicios, ciclo de vida de turnos,
  disponibilidad/bloqueos/excepciones, feriados y timezone por sucursal,
  recurrencias, recordatorios (puerto de notificaciones), señas (puerto de
  pagos) y motivo opcional de cancelación/reprogramación.
- LibraCore — administración/facturación/caja, **solo si MedLibra incorpora
  facturación** (no está decidido para el MVP).

MedLibra posee la API HTTP y el dominio clínico propio (pacientes, historia
clínica, evoluciones, diagnósticos — a definir en fases siguientes).
LibraGenda permanece como paquete reutilizable con PostgreSQL dedicado y
migraciones propias — base `medlibra` en el mismo Postgres 16 del VPS Donweb
que aloja la de LibraGenda, migrada con las migraciones del propio paquete
de LibraGenda (no se distribuyen en el wheel de pip, se aplican desde un
checkout de esa versión exacta contra `DATABASE_URL`).

No confundir con los sistemas de salud del Servidor Homei (PACS, Farmacia,
Portal de Pacientes) — son proyectos completamente separados, sin relación
ni infraestructura compartida.

## Documentación

- [ROADMAP.md](ROADMAP.md) — dirección estratégica.
- [TASKS.md](TASKS.md) — trabajo concreto vigente.
- [ARCHITECTURE.md](ARCHITECTURE.md) — arquitectura actual.
- [CONVENTIONS.md](CONVENTIONS.md) — estándares del código.
- [DECISIONS.md](DECISIONS.md) — decisiones y motivos.
- [CHANGELOG.md](CHANGELOG.md) — cambios publicados.
- [MODULES.md](MODULES.md) — inventario de módulos.

## Desarrollo

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
uvicorn app.main:app --reload
```

La base PostgreSQL y las migraciones de LibraGenda deben estar configuradas
antes de iniciar la aplicación real.
