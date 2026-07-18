# Arquitectura — MedLibra

## Propósito y límites

MedLibra será el producto vertical de turnos y gestión clínica para consultorios, profesionales independientes y centros médicos.

LibraGenda aporta el motor genérico de agenda. MedLibra debe mantener el dominio clínico propio — pacientes, historia clínica, evoluciones y diagnósticos — separado del motor común.

No confundir con PACS, Farmacia ni Portal de Pacientes del Servidor Homei; son proyectos separados y no comparten infraestructura.

## Componentes previstos

- `app/`: API FastAPI y dominio clínico propio.
- Agenda: composición de LibraGenda para recursos, servicios y turnos.
- `patients`: pacientes y ficha clínica operativa.
- `clinical`: historia clínica, evoluciones y diagnósticos.
- `billing` (opcional): composición con LibraCore, todavía no decidida.

## Persistencia e integración

La aplicación configura LibraGenda mediante `LIBRAGENDA_DATABASE_URL` y usa PostgreSQL dedicado para MedLibra. Las migraciones de LibraGenda se ejecutan desde un checkout del repositorio upstream en la versión exacta pineada, antes de iniciar la API; no se usa `create_all()` en producción.

Actualmente `pyproject.toml` pinea LibraGenda `v0.3.0`. No se actualiza automáticamente: la compatibilidad debe revisarse como tarea separada.

## Entornos y deploy

- Desarrollo: entorno dev con base `medlibra` y usuario dedicado.
- Demo: producción controlada para validación.
- Producción: dominio del cliente.

La rama observada actualmente es `main`. La adopción de `develop` como rama de integración queda pendiente de una decisión operativa explícita.
