"""
Señales de Django: registran en la bitácora los inicios de sesión, cierres e intentos fallidos.
"""
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.core.cache import cache
from django.dispatch import receiver

from nuamApp.auditoria import registrar
from nuamApp.login import clave_intentos

# Tiempo (segundos) durante el que se cuentan los intentos fallidos de un usuario
VENTANA_INTENTOS = 15 * 60


@receiver(user_logged_in)
def al_iniciar_sesion(sender, request, user, **kwargs):
  cache.delete(clave_intentos(user.get_username()))  # un acceso correcto reinicia el contador
  registrar(request, 'LOGIN', usuario=user)


@receiver(user_logged_out)
def al_cerrar_sesion(sender, request, user, **kwargs):
  if user is not None:
    registrar(request, 'LOGOUT', usuario=user)


@receiver(user_login_failed)
def al_fallar_acceso(sender, credentials, request=None, **kwargs):
  usuario = (credentials or {}).get('username', '')
  if usuario:
    clave = clave_intentos(usuario)
    cache.add(clave, 0, VENTANA_INTENTOS)
    try:
      cache.incr(clave)
    except ValueError:  # la clave expiró justo ahora
      cache.set(clave, 1, VENTANA_INTENTOS)
  # No se guarda la contraseña intentada; solo el nombre de usuario que se probó.
  registrar(request, 'LOGIN_FALLIDO', detalle={'usuario': usuario})
