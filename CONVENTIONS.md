# Convenciones de MedLibra

- `app/` contiene la API y el dominio clínico propio; no duplicar reglas de LibraGenda.
- LibraGenda se configura al arranque mediante `LIBRAGENDA_DATABASE_URL`.
- Migraciones de LibraGenda se ejecutan antes de iniciar la API; el `create_all()` del demo no se usa en producción.
- Routers HTTP traducen errores de dominio a códigos 404/409/422; no exponen tracebacks.
- Turnos genéricos no clínicos (barberías, lavaderos, estética) pertenecen a Gestiolibra, no a MedLibra.
- Gastronomía y mesas/comandas pertenecen a Restolibra.
- Tests unitarios para dominio clínico propio y smoke tests HTTP para cada flujo principal.
- Secretos en `.env` fuera de Git; dependencias internas pineadas a tags exactos.
