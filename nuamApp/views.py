from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import ProtectedError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from nuamApp import almacen, permisos
from nuamApp.auditoria import diferencias, registrar
from nuamApp.extractor import extraer_de_pdf
from nuamApp.forms import CalificacionForm, CargaMasivaForm, CertificadoForm, CorredorForm
from nuamApp.models import Auditoria, Calificacion, Certificado, Corredor
from nuamApp.permisos import requiere
from nuamApp.validators import validar_pdf


# ---------------------------------------------------------------------------
# Funciones de apoyo: hacen lo mismo que empleadoRegistro, pero sirven
# para los tres modelos (así no repetimos el código tres veces).
# ---------------------------------------------------------------------------
def _instantanea(objeto, campos):
  """Copia simple de los valores de un registro (para registrar qué cambió en la auditoría)."""
  datos = {}
  for campo in campos:
    valor = objeto._meta.get_field(campo).value_from_object(objeto)
    datos[campo] = getattr(valor, 'name', valor)  # los archivos se registran solo por su nombre
  return datos


def _formulario(request, clase_form, titulo, destino, instancia=None, **extra):
  campos = [c for c in clase_form._meta.fields]
  antes = _instantanea(instancia, campos) if instancia is not None else None
  form = clase_form(instance=instancia, **extra)
  if request.method == 'POST':
    form = clase_form(request.POST, request.FILES, instance=instancia, **extra)
    if form.is_valid():
      objeto = form.save()  # INSERT (si es nuevo) o UPDATE (si se está editando)
      despues = _instantanea(objeto, campos)
      if antes is None:
        registrar(request, 'CREAR', objeto, {'campos': despues})
      else:
        registrar(request, 'MODIFICAR', objeto, {'cambios': diferencias(antes, despues, campos)})
      messages.success(request, 'Los datos se guardaron correctamente.')
      return redirect(destino)  # redirect evita reenviar el formulario al recargar
  data = {'form': form, 'titulo': titulo, 'volver': destino}
  return render(request, 'nuamApp/formulario.html', data)


def _eliminar(request, objeto, destino, titulo):
  if request.method == 'POST':
    # Se anotan los datos ANTES de borrar: después del delete() el objeto pierde su pk
    pk, descripcion, modelo = objeto.pk, str(objeto), objeto._meta.model_name
    try:
      objeto.delete()
      registrar(request, 'ELIMINAR', objeto, {'modelo': modelo}, objeto_id=pk, descripcion=descripcion)
      messages.success(request, 'El registro fue eliminado.')
    except ProtectedError:
      messages.error(request, 'No se puede eliminar: tiene registros asociados.')
    return redirect(destino)
  data = {'objeto': objeto, 'titulo': titulo, 'volver': destino}
  return render(request, 'nuamApp/confirmarEliminar.html', data)


def _denegar(request, motivo):
  """Acceso a un registro concreto que el rol no puede tocar: queda en la bitácora y responde 403."""
  registrar(request, 'ACCESO_DENEGADO', detalle={'ruta': request.path, 'motivo': motivo})
  raise PermissionDenied


def _certificados(request):
  """Certificados que el usuario tiene permitido ver (el rol Corredor solo ve los suyos y los de la Bolsa)."""
  return permisos.certificados_visibles(request.user, Certificado.objects.all())


# ---------------------------------------------------------------------------
# Inicio
# ---------------------------------------------------------------------------
@login_required
@requiere('ver')
def inicio(request):
  certificados = _certificados(request)
  data = {
    'total': certificados.count(),
    'pendientes': certificados.filter(estado='PENDIENTE').count(),
    'procesados': certificados.filter(estado='PROCESADO').count(),
    'validados': certificados.filter(estado='VALIDADO').count(),
    'rechazados': certificados.filter(estado='RECHAZADO').count(),
    'corredores': Corredor.objects.count(),
    'calificaciones': Calificacion.objects.filter(certificado__in=certificados).count(),
  }
  return render(request, 'nuamApp/inicio.html', data)


# ---------------------------------------------------------------------------
# Corredores
# ---------------------------------------------------------------------------
@login_required
@requiere('ver')
def corredorData(request):
  corredores = Corredor.objects.all()  # SELECT * FROM nuamApp_corredor;
  return render(request, 'nuamApp/corredores.html', {'corredores': corredores})


@login_required
@requiere('gestionar_corredores')
def corredorRegistro(request):
  return _formulario(request, CorredorForm, 'Registro de Corredor', 'corredores')


@login_required
@requiere('gestionar_corredores')
def corredorEditar(request, id):
  corredor = get_object_or_404(Corredor, pk=id)
  return _formulario(request, CorredorForm, 'Editar Corredor', 'corredores', corredor)


@login_required
@requiere('gestionar_corredores')
def corredorEliminar(request, id):
  corredor = get_object_or_404(Corredor, pk=id)
  return _eliminar(request, corredor, 'corredores', 'Eliminar Corredor')


# ---------------------------------------------------------------------------
# Certificados
# ---------------------------------------------------------------------------
@login_required
@requiere('ver')
def certificadoData(request):
  certificados = _certificados(request).select_related('corredor').prefetch_related('calificaciones')
  return render(request, 'nuamApp/certificados.html', {'certificados': certificados})


@login_required
@requiere('escribir_certificados')
def certificadoRegistro(request):
  return _formulario(request, CertificadoForm, 'Registro de Certificado', 'certificados')


@login_required
@requiere('escribir_certificados')
def certificadoEditar(request, id):
  certificado = get_object_or_404(Certificado, pk=id)
  return _formulario(request, CertificadoForm, 'Editar Certificado', 'certificados', certificado)


@login_required
@requiere('eliminar_certificados')
def certificadoEliminar(request, id):
  certificado = get_object_or_404(Certificado, pk=id)
  return _eliminar(request, certificado, 'certificados', 'Eliminar Certificado')


@login_required
@requiere('ver')
def certificadoArchivo(request, id):
  """Entrega el PDF solo a usuarios con sesión y con permiso sobre ese certificado (media no es pública)."""
  certificado = get_object_or_404(_certificados(request), pk=id)  # un corredor ajeno recibe 404, no ve que existe
  if not certificado.archivo:
    raise Http404
  registrar(request, 'DESCARGA', certificado)
  respuesta = FileResponse(certificado.archivo.open('rb'), content_type='application/pdf')
  respuesta['Content-Disposition'] = f'inline; filename="certificado-{certificado.pk}.pdf"'
  return respuesta


# ---------------------------------------------------------------------------
# Carga masiva con extracción automática
# ---------------------------------------------------------------------------
def _procesar_pdf(request, archivo, corredor):
  """Valida un PDF, extrae sus datos y crea el certificado. Devuelve {'archivo', 'ok', 'motivo'}."""
  resultado = {'archivo': archivo.name, 'ok': False, 'motivo': ''}
  try:
    validar_pdf(archivo)  # tamaño y firma %PDF-
    extraccion = extraer_de_pdf(archivo)
    archivo.seek(0)
  except ValidationError as error:
    resultado['motivo'] = ' '.join(error.messages)
    return resultado
  except ValueError as error:
    resultado['motivo'] = str(error)
    return resultado

  if extraccion['faltantes']:
    resultado['motivo'] = 'No se reconocieron los campos: ' + ', '.join(extraccion['faltantes']) + '. Ingrésalo manualmente.'
    return resultado

  campos = extraccion['campos']
  try:
    certificado = Certificado(
      rut=campos['rut'], nombre_contribuyente=campos['nombre'][:120], ejercicio=campos['ejercicio'],
      tipo=campos['tipo'], monto=Decimal(campos['monto']), corredor=corredor, estado='PROCESADO',
      archivo=archivo,
      datos_extraidos={'archivo_original': archivo.name, 'campos': campos,
                       'texto': extraccion['texto'].replace('\x00', '')[:20000]})
    certificado.full_clean()  # mismas validaciones que el formulario manual (RUT, rango, duplicado, PDF)
    certificado.save()
  except (ValidationError, InvalidOperation) as error:
    resultado['motivo'] = ' '.join(error.messages) if isinstance(error, ValidationError) else 'Monto inválido.'
    return resultado

  registrar(request, 'CARGA', certificado, {'archivo': archivo.name, 'campos': campos})
  almacen.guardar_extraccion({
    'certificado_id': certificado.pk, 'archivo': archivo.name, 'campos': campos,
    'texto': certificado.datos_extraidos['texto'], 'fecha': timezone.now()})
  resultado['ok'] = True
  resultado['motivo'] = 'Procesado: revísalo y valídalo.'
  return resultado


@login_required
@requiere('escribir_certificados')
def certificadoCarga(request):
  form = CargaMasivaForm()
  resultados = None
  if request.method == 'POST':
    form = CargaMasivaForm(request.POST, request.FILES)
    if form.is_valid():
      corredor = form.cleaned_data['corredor']
      # Un archivo con error no detiene a los demás (HU 2)
      resultados = [_procesar_pdf(request, a, corredor) for a in form.cleaned_data['archivos']]
      correctos = sum(1 for r in resultados if r['ok'])
      if correctos:
        messages.success(request, f'{correctos} certificado(s) procesado(s).')
      if correctos < len(resultados):
        messages.warning(request, f'{len(resultados) - correctos} archivo(s) con problemas: revisa el detalle.')
      form = CargaMasivaForm()
  return render(request, 'nuamApp/carga.html', {'form': form, 'resultados': resultados})


# ---------------------------------------------------------------------------
# Calificaciones
# ---------------------------------------------------------------------------
@login_required
@requiere('ver')
def calificacionData(request):
  calificaciones = list(Calificacion.objects.filter(certificado__in=_certificados(request))
                        .select_related('certificado', 'corredor'))
  for c in calificaciones:  # el botón Editar/Eliminar solo aparece si el rol puede tocar esa fila
    c.modificable = permisos.puede_modificar_calificacion(request.user, c)
  return render(request, 'nuamApp/calificaciones.html', {'calificaciones': calificaciones})


@login_required
@requiere('calificar_bolsa', 'calificar_corredor')
def calificacionRegistro(request):
  return _formulario(request, CalificacionForm, 'Registro de Calificación', 'calificaciones',
                     usuario=request.user)


@login_required
@requiere('calificar_bolsa', 'calificar_corredor')
def calificacionEditar(request, id):
  calificacion = get_object_or_404(Calificacion, pk=id)
  if not permisos.puede_modificar_calificacion(request.user, calificacion):
    _denegar(request, 'calificación de otro origen o corredor')
  return _formulario(request, CalificacionForm, 'Editar Calificación', 'calificaciones', calificacion,
                     usuario=request.user)


@login_required
@requiere('calificar_bolsa', 'calificar_corredor')
def calificacionEliminar(request, id):
  calificacion = get_object_or_404(Calificacion, pk=id)
  if not permisos.puede_modificar_calificacion(request.user, calificacion):
    _denegar(request, 'calificación de otro origen o corredor')
  return _eliminar(request, calificacion, 'calificaciones', 'Eliminar Calificación')


# ---------------------------------------------------------------------------
# Auditoría
# ---------------------------------------------------------------------------
@login_required
@requiere('ver_auditoria')
def auditoriaData(request):
  registros = Auditoria.objects.all()[:500]  # los 500 más recientes
  estado = None
  if request.GET.get('verificar'):
    danado = Auditoria.verificar_cadena()  # recorre toda la bitácora
    estado = {'integra': danado is None, 'primer_danado': danado}
  return render(request, 'nuamApp/auditoria.html', {'registros': registros, 'estado': estado})
