from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError

from nuamApp.models import Calificacion, Certificado, Corredor, Perfil
from nuamApp.permisos import ADMIN, ANALISTA, AUDITOR, CORREDOR, ROLES
from nuamApp.validators import calcular_dv


def rut(cuerpo):
  return f'{cuerpo}-{calcular_dv(cuerpo)}'


class Command(BaseCommand):
  help = 'Carga corredores, certificados y calificaciones de ejemplo (se puede ejecutar más de una vez).'

  def handle(self, *args, **opciones):
    if not settings.DEBUG:
      raise CommandError('Los datos y usuarios de ejemplo solo se cargan en desarrollo (DJANGO_DEBUG=1).')
    andes, _ = Corredor.objects.get_or_create(nombre='Corredora Andes', defaults={'pais': 'CL'})
    pacifico, _ = Corredor.objects.get_or_create(nombre='Pacífico Inversiones', defaults={'pais': 'PE'})
    Corredor.objects.get_or_create(nombre='Cafetal Bursátil', defaults={'pais': 'CO', 'activo': False})

    ejemplos = [
      # rut, nombre, año, tipo, monto, corredor, estado
      (rut('76123456'), 'Inversiones Los Alerces SpA', 2025, 'DIVIDENDOS', 12500000, andes, 'VALIDADO'),
      (rut('77654321'), 'Agrícola Santa Rosa Ltda.', 2025, 'INTERESES', 3480000, andes, 'VALIDADO'),
      (rut('96543210'), 'Forestal del Sur S.A.', 2024, 'GANANCIA_CAPITAL', 87250000, None, 'VALIDADO'),
      (rut('12345678'), 'María Fernanda Soto Rojas', 2025, 'DIVIDENDOS', 940000, pacifico, 'PENDIENTE'),
      (rut('9876543'), 'Comercial Los Boldos SpA', 2024, 'INTERESES', 150000, andes, 'RECHAZADO'),
    ]
    creados = []
    for r, nombre, anio, tipo, monto, corredor, estado in ejemplos:
      cert, nuevo = Certificado.objects.get_or_create(
        rut=r, ejercicio=anio, tipo=tipo,
        defaults={'nombre_contribuyente': nombre, 'monto': monto, 'corredor': corredor, 'estado': estado})
      creados.append(cert)

    # Calificaciones: el primer certificado tiene una de la Bolsa y otra del corredor (gana la del corredor)
    if not Calificacion.objects.exists():
      Calificacion.objects.create(certificado=creados[0], origen='BOLSA', calificacion='Con crédito',
                                  observacion='Información base entregada por la Bolsa.')
      Calificacion.objects.create(certificado=creados[0], origen='CORREDOR', corredor=andes, calificacion='Sin crédito',
                                  observacion='El corredor ajustó la calificación según su registro.')
      Calificacion.objects.create(certificado=creados[1], origen='BOLSA', calificacion='Con crédito')
      Calificacion.objects.create(certificado=creados[2], origen='BOLSA', calificacion='Sin crédito')

    self._crear_usuarios(andes)
    self.stdout.write(self.style.SUCCESS('Datos de ejemplo cargados.'))

  def _crear_usuarios(self, corredor):
    """Un usuario por rol para probar los permisos. Clave de desarrollo: NO usar en producción."""
    clave = 'Demo-Nuam-2026!'
    for rol in ROLES:
      Group.objects.get_or_create(name=rol)
    demo = [('demo_admin', ADMIN, None), ('demo_analista', ANALISTA, None),
            ('demo_corredor', CORREDOR, corredor), ('demo_auditor', AUDITOR, None)]
    Usuario = get_user_model()
    for nombre, rol, su_corredor in demo:
      usuario, nuevo = Usuario.objects.get_or_create(username=nombre)
      if nuevo:
        usuario.set_password(clave)
        usuario.save()
      usuario.groups.set([Group.objects.get(name=rol)])
      Perfil.objects.update_or_create(usuario=usuario, defaults={'corredor': su_corredor})
    self.stdout.write(f'Usuarios de ejemplo (clave {clave}): demo_admin, demo_analista, demo_corredor, demo_auditor')
