"""
Almacén de documentos NO estructurados (MongoDB, opcional).

NUAM usa dos tipos de base de datos:
  * Estructurada (MySQL): corredores, certificados, calificaciones, auditoría. Datos con esquema fijo.
  * No estructurada (MongoDB): el texto completo extraído de cada PDF y los campos reconocidos.
    Cada documento puede tener formas distintas (los certificados cambian de formato por país y año),
    justo el caso donde un esquema fijo estorba.

Si no hay MONGO_URI configurada, la aplicación sigue funcionando: el mismo documento queda guardado en el
campo JSON `Certificado.datos_extraidos` y esta función simplemente devuelve False.
"""
import logging
import os

logger = logging.getLogger(__name__)

_cliente = None


def _obtener_cliente():
  """Devuelve el cliente de MongoDB o None si no está configurado. Se reemplaza en las pruebas."""
  global _cliente
  uri = os.environ.get('MONGO_URI')
  if not uri:
    return None
  if _cliente is None:
    import pymongo  # se importa aquí para que pymongo sea opcional
    _cliente = pymongo.MongoClient(uri, serverSelectionTimeoutMS=3000)
  return _cliente


def guardar_extraccion(documento):
  """Guarda un documento en la colección `extracciones`. Nunca rompe el flujo principal: devuelve True/False."""
  try:
    cliente = _obtener_cliente()
    if cliente is None:
      return False
    base = cliente[os.environ.get('MONGO_DB', 'nuam')]
    base['extracciones'].insert_one(dict(documento))
    return True
  except Exception:
    logger.exception('No se pudo guardar la extracción en MongoDB')
    return False
