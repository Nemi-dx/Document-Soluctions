"""
Roles y permisos de NUAM.

Los roles son grupos de Django (Administrador, Analista, Corredor, Auditor).
Este archivo concentra TODAS las reglas de autorización en un solo lugar para que sean
fáciles de leer, de probar y de explicar (matriz de roles en docs/SEGURIDAD.md).

Principio: mínimo privilegio. Un usuario sin rol no puede hacer nada.
"""
from functools import wraps

from django.core.exceptions import PermissionDenied

ADMIN = 'Administrador'
ANALISTA = 'Analista'
CORREDOR = 'Corredor'
AUDITOR = 'Auditor'
ROLES = (ADMIN, ANALISTA, CORREDOR, AUDITOR)

# Capacidades del sistema -> roles que las tienen
CAPACIDADES = {
  'ver': {ADMIN, ANALISTA, CORREDOR, AUDITOR},
  'escribir_certificados': {ADMIN, ANALISTA},
  'eliminar_certificados': {ADMIN},
  'gestionar_corredores': {ADMIN},
  'calificar_bolsa': {ADMIN, ANALISTA},
  'calificar_corredor': {ADMIN, CORREDOR},
  'ver_auditoria': {ADMIN, AUDITOR},
}


def rol_de(usuario):
  """Rol efectivo del usuario, o None si no tiene ninguno. El superusuario cuenta como Administrador."""
  if not getattr(usuario, 'is_authenticated', False) or not usuario.is_active:
    return None
  if usuario.is_superuser:
    return ADMIN
  nombres = set(usuario.groups.values_list('name', flat=True))
  for rol in ROLES:  # si tuviera varios, gana el de más privilegio (el orden de ROLES)
    if rol in nombres:
      return rol
  return None


def tiene(usuario, capacidad):
  return rol_de(usuario) in CAPACIDADES[capacidad]


def corredor_de(usuario):
  """El corredor al que pertenece un usuario con rol Corredor (o None)."""
  perfil = getattr(usuario, 'perfil', None)
  return perfil.corredor if perfil else None


def requiere(*capacidades):
  """
  Decorador para vistas: responde 403 si el usuario no tiene AL MENOS UNA de las capacidades
  (va DESPUÉS de @login_required). Cada acceso denegado queda en la bitácora.
  """
  def decorador(vista):
    @wraps(vista)
    def envoltura(request, *args, **kwargs):
      if not any(tiene(request.user, c) for c in capacidades):
        from nuamApp.auditoria import registrar  # import tardío: auditoria importa este módulo
        registrar(request, 'ACCESO_DENEGADO', detalle={'ruta': request.path, 'metodo': request.method})
        raise PermissionDenied
      return vista(request, *args, **kwargs)
    return envoltura
  return decorador


# ---------------------------------------------------------------------------
# Reglas a nivel de objeto (qué registros puede ver o tocar cada rol)
# ---------------------------------------------------------------------------
def certificados_visibles(usuario, queryset):
  """Corredor: solo los de su corredor y los de la Bolsa. Los demás roles ven todo."""
  if rol_de(usuario) == CORREDOR:
    from django.db.models import Q
    corredor = corredor_de(usuario)
    if corredor is None:
      return queryset.filter(corredor__isnull=True)
    return queryset.filter(Q(corredor=corredor) | Q(corredor__isnull=True))
  return queryset


def puede_calificar_certificado(usuario, certificado):
  """El corredor solo califica certificados de SU corredor (modificaciones locales)."""
  rol = rol_de(usuario)
  if rol == CORREDOR:
    corredor = corredor_de(usuario)
    return corredor is not None and certificado.corredor_id == corredor.id
  return rol in (ADMIN, ANALISTA)


def puede_modificar_calificacion(usuario, calificacion):
  """Editar o borrar una calificación existente."""
  rol = rol_de(usuario)
  if rol == ADMIN:
    return True
  if rol == ANALISTA:
    return calificacion.origen == 'BOLSA'
  if rol == CORREDOR:
    corredor = corredor_de(usuario)
    return (calificacion.origen == 'CORREDOR' and corredor is not None
            and calificacion.corredor_id == corredor.id)
  return False
