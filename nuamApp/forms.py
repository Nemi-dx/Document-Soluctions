from django import forms

from nuamApp import permisos
from nuamApp.models import Calificacion, Certificado, Corredor


class BootstrapMixin:
  """Le pone a cada campo la clase de Bootstrap que corresponde (en empleadosProyecto se hacía campo por campo con widgets)."""

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    for campo in self.fields.values():
      if isinstance(campo.widget, forms.CheckboxInput):
        clase = 'form-check-input'
      elif isinstance(campo.widget, forms.Select):
        clase = 'form-select'
      else:
        clase = 'form-control'
      campo.widget.attrs['class'] = clase


class CorredorForm(BootstrapMixin, forms.ModelForm):
  class Meta:
    model = Corredor
    fields = ['nombre', 'pais', 'activo']


class CertificadoForm(BootstrapMixin, forms.ModelForm):
  class Meta:
    model = Certificado
    fields = ['rut', 'nombre_contribuyente', 'ejercicio', 'tipo', 'monto', 'corredor', 'estado', 'archivo']


class CalificacionForm(BootstrapMixin, forms.ModelForm):
  """
  Cada rol ve solo lo que le corresponde:
    * Analista: califica como Bolsa.
    * Corredor: califica como Corredor, y solo certificados de su corredor.
    * Administrador: puede elegir el origen.
  """

  class Meta:
    model = Calificacion
    fields = ['certificado', 'origen', 'calificacion', 'observacion']
    widgets = {'observacion': forms.Textarea(attrs={'rows': 3})}

  def __init__(self, *args, usuario=None, **kwargs):
    super().__init__(*args, **kwargs)
    self.usuario = usuario
    rol = permisos.rol_de(usuario)
    certificados = Certificado.objects.all()
    if rol == permisos.CORREDOR:
      corredor = permisos.corredor_de(usuario)
      certificados = certificados.filter(corredor=corredor) if corredor else certificados.none()
      self.fields['origen'].choices = [('CORREDOR', 'Corredor')]
      self.fields['origen'].initial = 'CORREDOR'
    elif rol == permisos.ANALISTA:
      self.fields['origen'].choices = [('BOLSA', 'Bolsa')]
      self.fields['origen'].initial = 'BOLSA'
    self.fields['certificado'].queryset = certificados

  def clean(self):
    datos = super().clean()
    certificado = datos.get('certificado')
    origen = datos.get('origen')
    if certificado is not None and origen == 'CORREDOR':
      if certificado.corredor_id is None:
        self.add_error('certificado', 'Este certificado viene de la Bolsa: no tiene corredor que lo califique.')
      elif permisos.rol_de(self.usuario) == permisos.CORREDOR and not permisos.puede_calificar_certificado(
          self.usuario, certificado):
        self.add_error('certificado', 'Solo puedes calificar certificados de tu corredor.')
    return datos

  def save(self, commit=True):
    calificacion = super().save(commit=False)
    # El corredor que califica es el dueño del certificado (así la modificación queda local a él)
    calificacion.corredor = calificacion.certificado.corredor if calificacion.origen == 'CORREDOR' else None
    if commit:
      calificacion.save()
    return calificacion


class MultipleFileInput(forms.ClearableFileInput):
  allow_multiple_selected = True


class MultipleFileField(forms.FileField):
  """Campo para subir varios archivos a la vez (patrón oficial de la documentación de Django)."""

  def __init__(self, *args, **kwargs):
    kwargs.setdefault('widget', MultipleFileInput())
    super().__init__(*args, **kwargs)

  def clean(self, data, initial=None):
    limpiar_uno = super().clean
    if isinstance(data, (list, tuple)):
      return [limpiar_uno(d, initial) for d in data]
    return [limpiar_uno(data, initial)]


class CargaMasivaForm(BootstrapMixin, forms.Form):
  MAX_ARCHIVOS = 50

  archivos = MultipleFileField(label='Certificados PDF', help_text='Hasta 50 PDF a la vez, máximo 10 MB cada uno.')
  corredor = forms.ModelChoiceField(
    queryset=Corredor.objects.filter(activo=True), required=False, label='Corredor',
    help_text='Déjalo vacío si los certificados vienen de la Bolsa.')

  def clean_archivos(self):
    archivos = self.cleaned_data['archivos']
    if not archivos:
      raise forms.ValidationError('Selecciona al menos un archivo.')
    if len(archivos) > self.MAX_ARCHIVOS:
      raise forms.ValidationError(f'Máximo {self.MAX_ARCHIVOS} archivos por carga.')
    return archivos
