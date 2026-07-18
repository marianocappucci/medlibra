# Módulos de MedLibra

## MVP

- `app`: factory FastAPI, health y routers.
- `agenda`: composición de LibraGenda para recursos, servicios y turnos.
- `patients`: pacientes y ficha clínica operativa (a definir).
- `clinical`: historia clínica, evoluciones, diagnósticos (fases siguientes).
- `billing` (opcional, no decidido): composición de LibraCore para facturación/caja.

## Después del MVP

- Recetas, estudios, documentos clínicos, consentimientos.
- Recordatorios y preferencias de comunicación (vía LibraGenda).
- Dashboard y reportes operativos.

## Fuera de alcance

Turnos genéricos no clínicos (Gestiolibra), mesas, comandas, cocina y food
cost (Restolibra), sistemas del Servidor Homei (PACS, Farmacia, Portal de
Pacientes — proyectos separados sin relación con MedLibra).
