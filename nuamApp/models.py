import hashlib
import json

from django.conf import settings
from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.utils import timezone

from nuamApp.validators import normalizar_rut, validar_pdf, validar_rut


class Corredor(models.Model):
  PAISES = [('CL', 'Chile'), ('PE', 'Perú'), ('CO', 'Colombia')]

  nombre = models.CharField(max_length=120, unique=True)
  pais = models.CharField('país', max_length=2, choices=PAISES, default='CL')
  activo = models.BooleanField(default=True)

  class Meta:
    ordering = ['nombre']
    verbose_name_plural = 'corredores'

  def __str__(self):
    return self.nombre


class Certificado(models.Model):
  TIPOS = [
    ('DIVIDENDOS', 'Dividendos'),
    ('INTERESES', 'Intereses'),
    ('GANANCIA_CAPITAL', 'Ganancia de capital'),
  ]
  ESTADOS = [
    ('PENDIENTE', 'Pendiente'),
    ('PROCESADO', 'Procesado'),
    ('VALIDADO', 'Validado'),
    ('RECHAZADO', 'Rechazado'),
  ]

  rut = models.CharField('RUT del contribuyente', max_length=12, validators=[validar_rut],
                         help_text='Ejemplo: 12.345.678-5')
  nombre_contribuyente = models.CharField('nombre del contribuyente', max_length=120)
  ejercicio = models.PositiveSmallIntegerField(
    'año tributario', validators=[MinValueValidator(2000), MaxValueValidator(2100)])
  tipo = models.CharField(max_length=20, choices=TIPOS)
  monto = models.DecimalField(max_digits=16, decimal_places=2, validators=[MinValueValidator(0)])
  corredor = models.ForeignKey(Corredor, null=True, blank=True, on_delete=models.PROTECT,
                               related_name='certificados',
                               help_text='Déjalo vacío si el certificado viene de la Bolsa.')
  estado = models.CharField(max_length=10, choices=ESTADOS, default='PENDIENTE')
  archivo = models.FileField('certificado PDF', upload_to='certificados/%Y/%m/', blank=True,
                             validators=[FileExtensionValidator(['pdf']), validar_pdf])
  datos_extraidos = models.JSONField(
    'datos extraídos del PDF', default=dict, blank=True, editable=False,
    help_text='Documento JSON (sin esquema fijo) con lo que la extracción automática leyó del PDF.')
  fecha_carga = models.DateTimeField(auto_now_add=True)

  class Meta:
    ordering = ['-fecha_carga']
    constraints = [
      models.UniqueConstraint(
        fields=['rut', 'ejercicio', 'tipo'], name='certificado_unico',
        violation_error_message='Ya existe un certificado de este contribuyente para ese año y tipo.'),
    ]

  def clean(self):
    # Guarda el RUT siempre con el mismo formato (12345678-5)
    self.rut = normalizar_rut(self.rut)

  @property
  def calificacion_vigente(self):
    """La del corredor tiene prioridad sobre la de la Bolsa; dentro de cada origen, la más reciente."""
    califs = list(self.calificaciones.all())  # ya vienen ordenadas de la más nueva a la más antigua
    for origen in ('CORREDOR', 'BOLSA'):
      for c in califs:
        if c.origen == origen:
          return c
    return None

  def __str__(self):
    return f'{self.rut} - {self.ejercicio} - {self.get_tipo_display()}'


class Calificacion(models.Model):
  ORIGENES = [('BOLSA', 'Bolsa'), ('CORREDOR', 'Corredor')]

  certificado = models.ForeignKey(Certificado, on_delete=models.PROTECT, related_name='calificaciones')
  origen = models.CharField(max_length=10, choices=ORIGENES, default='BOLSA')
  corredor = models.ForeignKey(Corredor, null=True, blank=True, on_delete=models.PROTECT,
                               related_name='calificaciones', editable=False,
                               help_text='Corredor que hizo la calificación (solo si el origen es Corredor).')
  calificacion = models.CharField('calificación', max_length=50)
  observacion = models.TextField('observación', blank=True)
  fecha = models.DateTimeField(auto_now_add=True)

  class Meta:
    ordering = ['-fecha', '-id']
    verbose_name = 'calificación'
    verbose_name_plural = 'calificaciones'

  def __str__(self):
    return f'{self.certificado.rut} - {self.calificacion} ({self.get_origen_display()})'


class Perfil(models.Model):
  """Datos extra del usuario: a qué corredor pertenece (solo importa para el rol Corredor)."""
  usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='perfil')
  corredor = models.ForeignKey(Corredor, null=True, blank=True, on_delete=models.PROTECT,
                               related_name='usuarios',
                               help_text='Obligatorio para usuarios con el rol Corredor.')

  def __str__(self):
    return f'Perfil de {self.usuario}'


# ---------------------------------------------------------------------------
# Auditoría inmutable con hash encadenado
# ---------------------------------------------------------------------------
class AuditoriaError(Exception):
  """Se intentó modificar o borrar un registro de auditoría."""


class AuditoriaQuerySet(models.QuerySet):
  """Bloquea las modificaciones masivas: la bitácora solo se puede agregar."""

  def update(self, **kwargs):
    raise AuditoriaError('La bitácora de auditoría no se puede modificar.')

  def delete(self):
    raise AuditoriaError('La bitácora de auditoría no se puede eliminar.')

  def bulk_update(self, *args, **kwargs):
    raise AuditoriaError('La bitácora de auditoría no se puede modificar.')


def _formato_fecha(fecha):
  return fecha.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


class Auditoria(models.Model):
  """
  Una fila por cada acción relevante (quién, cuándo, qué). Cada fila guarda el hash de la anterior:
  si alguien altera o borra una fila en la base de datos, la cadena se rompe y verificar_cadena() lo detecta.
  """
  ACCIONES = [
    ('LOGIN', 'Inicio de sesión'), ('LOGIN_FALLIDO', 'Intento de acceso fallido'), ('LOGOUT', 'Cierre de sesión'),
    ('CREAR', 'Creación'), ('MODIFICAR', 'Modificación'), ('ELIMINAR', 'Eliminación'),
    ('CARGA', 'Carga de certificado'), ('DESCARGA', 'Descarga de PDF'), ('ACCESO_DENEGADO', 'Acceso denegado'),
  ]

  fecha = models.DateTimeField()
  usuario = models.CharField(max_length=150, help_text='Nombre de usuario (se conserva aunque el usuario se elimine).')
  rol = models.CharField(max_length=20, blank=True)
  accion = models.CharField(max_length=20, choices=ACCIONES)
  modelo = models.CharField(max_length=40, blank=True)
  objeto_id = models.CharField(max_length=40, blank=True)
  objeto = models.CharField(max_length=200, blank=True)
  detalle = models.JSONField(default=dict, blank=True)
  ip = models.GenericIPAddressField(null=True, blank=True)
  hash_anterior = models.CharField(max_length=64, blank=True)
  hash = models.CharField(max_length=64, editable=False)

  objects = AuditoriaQuerySet.as_manager()

  class Meta:
    ordering = ['-id']
    verbose_name = 'registro de auditoría'
    verbose_name_plural = 'registros de auditoría'

  def __str__(self):
    return f'{self.fecha:%Y-%m-%d %H:%M} {self.usuario} {self.accion} {self.modelo} {self.objeto_id}'

  def calcular_hash(self):
    contenido = json.dumps({
      'fecha': _formato_fecha(self.fecha), 'usuario': self.usuario, 'rol': self.rol, 'accion': self.accion,
      'modelo': self.modelo, 'objeto_id': self.objeto_id, 'objeto': self.objeto, 'detalle': self.detalle,
      'ip': self.ip or '', 'hash_anterior': self.hash_anterior,
    }, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(contenido.encode('utf-8')).hexdigest()

  def save(self, *args, **kwargs):
    if self.pk is not None:
      raise AuditoriaError('Un registro de auditoría no se puede modificar.')
    with transaction.atomic():
      ultimo = Auditoria.objects.select_for_update().order_by('-id').first()
      self.hash_anterior = ultimo.hash if ultimo else ''
      self.fecha = self.fecha or timezone.now()
      # el detalle se pasa por JSON para que el hash sea el mismo antes y después de guardarlo
      self.detalle = json.loads(json.dumps(self.detalle or {}, default=str, ensure_ascii=False))
      self.hash = self.calcular_hash()
      super().save(*args, **kwargs)

  def delete(self, *args, **kwargs):
    raise AuditoriaError('Un registro de auditoría no se puede eliminar.')

  @classmethod
  def verificar_cadena(cls):
    """Recorre la bitácora en orden. Devuelve None si está íntegra, o el id del primer registro dañado."""
    anterior = ''
    for registro in cls.objects.order_by('id').iterator():
      if registro.hash_anterior != anterior or registro.calcular_hash() != registro.hash:
        return registro.id
      anterior = registro.hash
    return None
