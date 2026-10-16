"""
Inicio de sesión con bloqueo temporal tras varios intentos fallidos (defensa contra fuerza bruta).
"""
from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.core.cache import cache

MAX_INTENTOS = 5


def clave_intentos(usuario):
  return f'intentos_login:{(usuario or "").strip().lower()}'


class FormularioLogin(AuthenticationForm):
  def clean(self):
    usuario = self.data.get('username', '')
    if cache.get(clave_intentos(usuario), 0) >= MAX_INTENTOS:
      raise forms.ValidationError(
        'Demasiados intentos fallidos. Espera 15 minutos o pide ayuda a un administrador.',
        code='bloqueado')
    return super().clean()
