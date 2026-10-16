"""
Funciones para dejar rastro en la bitácora de auditoría (modelo Auditoria).
"""
import ipaddress
import logging

from django.conf import settings

from nuamApp import permisos
from nuamApp.models import Auditoria

logger = logging.getLogger(__name__)


def ip_de(request):
  """
  IP del cliente. Por defecto solo se confía en REMOTE_ADDR (cualquiera puede falsificar X-Forwarded-For).
  Detrás de nginx (AWS) REMOTE_ADDR sería siempre 127.0.0.1; ahí se activa DJANGO_PROXY_CONFIABLE=1 y se
  usa X-Real-IP, que nginx REEMPLAZA con la IP real en cada petición (el cliente no puede falsificarla).
  """
  if request is None:
    return None
  ip = request.META.get('REMOTE_ADDR')
  if getattr(settings, 'PROXY_CONFIABLE', False):
    candidata = request.META.get('HTTP_X_REAL_IP', '').strip()
    try:
      ipaddress.ip_address(candidata)  # solo se acepta si es una IP válida
      ip = candidata
    except ValueError:
      pass
  return ip


def registrar(request, accion, objeto=None, detalle=None, usuario=None, objeto_id=None, descripcion=None):
  """
  Agrega una fila a la bitácora. `objeto` es el registro afectado (opcional).
  Si falla, se anota en el log del servidor pero NO se interrumpe la operación del usuario.
  """
  try:
    usuario = usuario or getattr(request, 'user', None)
    nombre = getattr(usuario, 'username', '') or (detalle or {}).get('usuario', '') or 'anónimo'
    Auditoria.objects.create(
      usuario=nombre,
      rol=permisos.rol_de(usuario) or '',
      accion=accion,
      modelo=objeto._meta.model_name if objeto is not None else '',
      # objeto_id y descripcion se pasan aparte cuando el objeto ya fue borrado (su pk queda en None)
      objeto_id=str(objeto_id if objeto_id is not None else (objeto.pk if objeto is not None and objeto.pk is not None else '')),
      objeto=(descripcion if descripcion is not None else (str(objeto) if objeto is not None else ''))[:200],
      detalle=detalle or {},
      ip=ip_de(request),
    )
  except Exception:
    logger.exception('No se pudo escribir en la bitácora de auditoría')


def diferencias(antes, despues, campos):
  """Diccionario {campo: [valor_antes, valor_despues]} solo con los campos que cambiaron."""
  cambios = {}
  for campo in campos:
    if antes.get(campo) != despues.get(campo):
      cambios[campo] = [antes.get(campo), despues.get(campo)]
  return cambios
