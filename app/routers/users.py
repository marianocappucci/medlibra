"""Router de usuarios de MedLibra: shim sobre la factory única de la familia
(`libraauth.usuarios.build_users_router()`, ADR-018, libraauth v0.43.0).
Reemplaza la copia propia que tenía este archivo -- byte-idéntica a la de
Gestiolibra, ver el historial de `services/users.py` -- con dos defectos que
la factory cierra:

- El reset de contraseña ajena (`PUT /users/{id}/password`) no exigía ningún
  mínimo, sólo rechazaba la cadena vacía. La factory exige
  `MIN_PASSWORD_LENGTH` (6) también ahí -- antes sólo se exigía en el alta.
- Sin protección del único administrador activo: se podía degradar,
  desactivar o borrar al último admin sin que nada lo impidiera.

🔴 **Lo que la ADR-018 da por 500 en el `PUT` con rol inválido NO aplica a
este router tal cual estaba** -- verificado corriendo la suite contra el
router viejo antes de esta migración: `UserUpdate.role` ya estaba tipado
`Literal["admin", "staff"]`, así que pydantic lo rechazaba con 422 ANTES de
llegar al handler que tenía el `except ValueError` faltante; el `ValueError`
de `UserRepository.update()` era inalcanzable por HTTP. La migración no
"arregla" un 500 que no existía acá -- la gana igual, porque la validación
pasa a hacerse contra la tupla `roles` de la instancia en vez de un tipo fijo
del modelo (ver el docstring de `build_users_router`), que es lo que hace
falta para que Contalibra/Restolibra -con más de dos roles- puedan compartir
el mismo router.

`roles`/`admin_guard` son los que ya usaba este router: el `UserRepository`
de este producto se construye con el default `("admin", "staff")` (ver
`main.py`), y el guard es `require_admin_o_servicio` (rol admin del producto
o el token de servicio del backoffice, libraauth v0.7.0) -- antes se pasaba
como `dependencies=` de `app.include_router()`, ahora vive DENTRO del router
que arma la factory, así que ese `Depends()` en `main.py` se saca de ahí.
El prefijo `/users` no cambia -- ver el README de libraauth, sección "Router
de usuarios unificado".
"""
from libraauth.usuarios import build_users_router

from ..auth import require_admin_o_servicio
from ..dependencies import get_user_repository

router = build_users_router(
    prefix="/users",
    roles=("admin", "staff"),
    admin_guard=require_admin_o_servicio,
    get_repository=get_user_repository,
)
