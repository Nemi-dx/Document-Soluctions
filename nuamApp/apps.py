from django.apps import AppConfig
from django.db.models.signals import post_migrate


def crear_roles(sender, **kwargs):
  """Después de cada migrate, se asegura de que existan los 4 grupos (roles) del sistema."""
  from django.contrib.auth.models import Group

  from nuamApp.permisos import ROLES
  for nombre in ROLES:
    Group.objects.get_or_create(name=nombre)


class NuamappConfig(AppConfig):
  name = 'nuamApp'
  verbose_name = 'NUAM'

  def ready(self):
    from nuamApp import signals  # noqa: F401  (registra las señales de auditoría)
    post_migrate.connect(crear_roles, sender=self)
