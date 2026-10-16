from nuamApp import permisos


def roles(request):
  """Pone `rol` y `puede` en todas las plantillas (para mostrar u ocultar botones según el rol)."""
  usuario = getattr(request, 'user', None)
  if usuario is None or not usuario.is_authenticated:
    return {}
  rol = permisos.rol_de(usuario)
  return {
    'rol': rol,
    'puede': {capacidad: rol in roles_ for capacidad, roles_ in permisos.CAPACIDADES.items()},
  }
