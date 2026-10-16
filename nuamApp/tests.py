"""
Pruebas automatizadas de NUAM.   Ejecutar:  python manage.py test

Secciones:
  1. Unitarias: RUT, extractor de PDF, hash encadenado.
  2. Integrales: vistas con sesión, roles y permisos, auditoría, carga masiva, archivos.
  3. Rendimiento: volumen de datos, número de consultas y tiempos.
El plan completo (incluidas las pruebas manuales) está en docs/PRUEBAS.md.
"""
import io
import tempfile
import time
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from nuamApp import extractor, permisos
from nuamApp.auditoria import ip_de
from nuamApp.models import Auditoria, AuditoriaError, Calificacion, Certificado, Corredor, Perfil
from nuamApp.validators import calcular_dv, normalizar_rut, validar_rut

PDF_FALSO = b'%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n'
CLAVE = 'Clave-de-prueba-2026'


def rut_valido(cuerpo='12345678'):
  return f'{cuerpo}-{calcular_dv(cuerpo)}'


def datos_certificado(**cambios):
  datos = {'rut': '12.345.678-5', 'nombre_contribuyente': 'Ana Pérez', 'ejercicio': 2025,
           'tipo': 'DIVIDENDOS', 'monto': '1000000', 'estado': 'PENDIENTE'}
  datos.update(cambios)
  return datos


def crear_usuario(rol, nombre=None, corredor=None):
  """Crea un usuario con el rol (grupo) indicado y, si corresponde, su corredor."""
  usuario = get_user_model().objects.create_user(nombre or f'u_{rol.lower()}', password=CLAVE)
  if rol:
    usuario.groups.add(Group.objects.get_or_create(name=rol)[0])
  Perfil.objects.create(usuario=usuario, corredor=corredor)
  return usuario


def pdf_con_texto(lineas):
  """Construye un PDF real mínimo (una página) con las líneas de texto dadas. Solo caracteres ASCII."""
  def esc(t):
    return t.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
  contenido = 'BT /F1 12 Tf 50 750 Td 14 TL\n' + ''.join(f'({esc(linea)}) Tj T*\n' for linea in lineas) + 'ET'
  objetos = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R '
    '/Resources << /Font << /F1 5 0 R >> >> >>',
    f'<< /Length {len(contenido)} >>\nstream\n{contenido}\nendstream',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
  ]
  salida = b'%PDF-1.4\n'
  posiciones = []
  for numero, objeto in enumerate(objetos, start=1):
    posiciones.append(len(salida))
    salida += f'{numero} 0 obj\n{objeto}\nendobj\n'.encode('latin-1')
  inicio_xref = len(salida)
  salida += f'xref\n0 {len(objetos) + 1}\n0000000000 65535 f \n'.encode()
  salida += ''.join(f'{p:010d} 00000 n \n' for p in posiciones).encode()
  salida += f'trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{inicio_xref}\n%%EOF\n'.encode()
  return salida


def pdf_certificado(rut='12.345.678-5', nombre='Ana Perez', ano=2025, tipo='Dividendos', monto='1.250.000'):
  return pdf_con_texto([
    f'CERTIFICADO DE {tipo.upper()}', f'Ano Tributario: {ano}', f'RUT del contribuyente: {rut}',
    f'Nombre del contribuyente: {nombre}', f'Monto total: ${monto}'])


# ===========================================================================
# 1. UNITARIAS
# ===========================================================================
class RutTests(TestCase):
  def test_rut_valido_con_y_sin_puntos(self):
    validar_rut('12.345.678-5')
    validar_rut('12345678-5')
    validar_rut('123456785')

  def test_rut_con_dv_incorrecto(self):
    with self.assertRaises(ValidationError):
      validar_rut('12.345.678-4')

  def test_rut_con_basura(self):
    for malo in ('abc', '', '1-9', '12.345.678-X'):
      with self.assertRaises(ValidationError):
        validar_rut(malo)

  def test_normalizar(self):
    self.assertEqual(normalizar_rut('12.345.678-5'), '12345678-5')
    self.assertEqual(normalizar_rut('123456785'), '12345678-5')

  def test_digito_k(self):
    # 7 dígitos cuyo DV es K
    cuerpo = next(str(n) for n in range(10000000, 10000100) if calcular_dv(str(n)) == 'K')
    validar_rut(f'{cuerpo}-K')
    validar_rut(f'{cuerpo}-k')


class ExtractorTests(SimpleTestCase):
  def test_extrae_todos_los_campos(self):
    texto = ('CERTIFICADO DE DIVIDENDOS\nAño Tributario: 2025\nRUT del contribuyente: 12.345.678-5\n'
             'Nombre del contribuyente: María Fernanda Soto Rojas\nMonto total: $1.250.000\n')
    r = extractor.extraer_campos(texto)
    self.assertEqual(r['faltantes'], [])
    self.assertEqual(r['campos'], {'rut': '12345678-5', 'nombre': 'María Fernanda Soto Rojas', 'ejercicio': 2025,
                                   'tipo': 'DIVIDENDOS', 'monto': '1250000'})

  def test_variantes_de_etiquetas_y_decimales(self):
    r = extractor.extraer_campos('Certificado sobre intereses\nRazón Social: Los Alerces SpA\nRUT: 76123456-0\n'
                                 'Ejercicio: 2024\nMonto: 3.480.000,50')
    self.assertEqual(r['campos']['tipo'], 'INTERESES')
    self.assertEqual(r['campos']['monto'], '3480000.50')
    self.assertEqual(r['campos']['nombre'], 'Los Alerces SpA')

  def test_campos_faltantes_quedan_identificados(self):
    r = extractor.extraer_campos('Ganancia de capital\nRUT 9.876.543-K\nAño tributario 2024')
    self.assertEqual(r['campos']['tipo'], 'GANANCIA_CAPITAL')
    self.assertEqual(r['campos']['rut'], '9876543-K')
    self.assertEqual(set(r['faltantes']), {'nombre', 'monto'})

  def test_texto_vacio(self):
    self.assertEqual(extractor.extraer_campos('')['faltantes'], list(extractor.CAMPOS_OBLIGATORIOS))
    self.assertEqual(extractor.extraer_campos(None)['campos'], {})

  def test_normalizar_monto(self):
    casos = [('1.250.000', '1250000'), ('1,250,000.50', '1250000.50'), ('1250,5', '1250.5'),
             ('1.234', '1234'), ('12.5', '12.5'), ('abc', None), ('', None), ('1.250.000,50', '1250000.50')]
    for crudo, esperado in casos:
      self.assertEqual(extractor.normalizar_monto(crudo), esperado, crudo)

  def test_lee_un_pdf_real(self):
    r = extractor.extraer_de_pdf(io.BytesIO(pdf_certificado()))
    self.assertEqual(r['faltantes'], [])
    self.assertEqual(r['campos']['rut'], '12345678-5')
    self.assertEqual(r['campos']['monto'], '1250000')

  def test_pdf_danado_lanza_valueerror(self):
    with self.assertRaises(ValueError):
      extractor.extraer_de_pdf(io.BytesIO(b'%PDF-1.4 esto esta roto'))


class PermisosUnitariosTests(TestCase):
  def test_superusuario_es_administrador(self):
    root = get_user_model().objects.create_superuser('root', 'r@x.cl', CLAVE)
    self.assertEqual(permisos.rol_de(root), permisos.ADMIN)

  def test_usuario_sin_grupo_no_tiene_rol(self):
    self.assertIsNone(permisos.rol_de(crear_usuario(None, 'sinrol')))

  def test_usuario_inactivo_no_tiene_rol(self):
    usuario = crear_usuario(permisos.ADMIN, 'inactivo')
    usuario.is_active = False
    self.assertIsNone(permisos.rol_de(usuario))

  def test_con_varios_grupos_gana_el_de_mas_privilegio(self):
    usuario = crear_usuario(permisos.AUDITOR, 'doble')
    usuario.groups.add(Group.objects.get_or_create(name=permisos.ANALISTA)[0])
    self.assertEqual(permisos.rol_de(usuario), permisos.ANALISTA)

  def test_matriz_de_capacidades(self):
    esperado = {
      permisos.ADMIN: {'ver', 'escribir_certificados', 'eliminar_certificados', 'gestionar_corredores',
                       'calificar_bolsa', 'calificar_corredor', 'ver_auditoria'},
      permisos.ANALISTA: {'ver', 'escribir_certificados', 'calificar_bolsa'},
      permisos.CORREDOR: {'ver', 'calificar_corredor'},
      permisos.AUDITOR: {'ver', 'ver_auditoria'},
    }
    for rol, capacidades in esperado.items():
      reales = {c for c, roles in permisos.CAPACIDADES.items() if rol in roles}
      self.assertEqual(reales, capacidades, rol)


class IpDeAuditoriaTests(SimpleTestCase):
  """La IP de la bitácora no se puede falsificar con cabeceras, salvo que haya un proxy de confianza."""

  def _peticion(self, **cabeceras):
    return RequestFactory().get('/', REMOTE_ADDR='10.0.0.5', **cabeceras)

  def test_por_defecto_ignora_las_cabeceras(self):
    self.assertEqual(ip_de(self._peticion(HTTP_X_REAL_IP='8.8.8.8', HTTP_X_FORWARDED_FOR='9.9.9.9')), '10.0.0.5')

  @override_settings(PROXY_CONFIABLE=True)
  def test_con_proxy_de_confianza_usa_x_real_ip(self):
    self.assertEqual(ip_de(self._peticion(HTTP_X_REAL_IP='200.1.2.3')), '200.1.2.3')

  @override_settings(PROXY_CONFIABLE=True)
  def test_con_proxy_una_cabecera_invalida_se_ignora(self):
    self.assertEqual(ip_de(self._peticion(HTTP_X_REAL_IP='no-es-una-ip')), '10.0.0.5')
    self.assertEqual(ip_de(self._peticion()), '10.0.0.5')


class CadenaDeHashTests(TestCase):
  def _crear(self, n):
    return [Auditoria.objects.create(usuario='u', accion='CREAR', modelo='corredor', objeto_id=str(i),
                                     detalle={'n': i, 'monto': '10.5'}) for i in range(n)]

  def test_cadena_integra(self):
    filas = self._crear(5)
    self.assertEqual(filas[0].hash_anterior, '')
    self.assertEqual(filas[1].hash_anterior, filas[0].hash)
    self.assertIsNone(Auditoria.verificar_cadena())

  def test_no_se_puede_modificar_ni_borrar(self):
    fila = self._crear(1)[0]
    fila.usuario = 'otro'
    with self.assertRaises(AuditoriaError):
      fila.save()
    with self.assertRaises(AuditoriaError):
      fila.delete()
    with self.assertRaises(AuditoriaError):
      Auditoria.objects.all().update(usuario='otro')
    with self.assertRaises(AuditoriaError):
      Auditoria.objects.all().delete()

  def _sql(self, sentencia, parametros):
    with connection.cursor() as cursor:
      cursor.execute(sentencia, parametros)

  def test_detecta_fila_alterada_directamente_en_la_base(self):
    filas = self._crear(4)
    tabla = connection.ops.quote_name(Auditoria._meta.db_table)
    self._sql(f'UPDATE {tabla} SET usuario = %s WHERE id = %s', ['intruso', filas[1].id])
    self.assertEqual(Auditoria.verificar_cadena(), filas[1].id)

  def test_detecta_fila_borrada_directamente_en_la_base(self):
    filas = self._crear(4)
    tabla = connection.ops.quote_name(Auditoria._meta.db_table)
    self._sql(f'DELETE FROM {tabla} WHERE id = %s', [filas[1].id])
    self.assertEqual(Auditoria.verificar_cadena(), filas[2].id)  # la siguiente ya no calza con su anterior


# ===========================================================================
# 2. INTEGRALES
# ===========================================================================
class SinSesionTests(TestCase):
  def test_todas_las_paginas_piden_login(self):
    for nombre in ('inicio', 'corredores', 'certificados', 'calificaciones', 'auditoria',
                   'corredor_nuevo', 'certificado_nuevo', 'certificado_carga', 'calificacion_nuevo'):
      respuesta = self.client.get(reverse(nombre))
      self.assertEqual(respuesta.status_code, 302, nombre)
      self.assertIn('/ingresar/', respuesta['Location'], nombre)


class ConSesionTests(TestCase):
  """CRUD completo con un usuario Administrador."""

  def setUp(self):
    self.usuario = crear_usuario(permisos.ADMIN, 'tester')
    self.client.force_login(self.usuario)
    self.corredor = Corredor.objects.create(nombre='Corredora Andes')

  def test_las_paginas_cargan(self):
    for nombre in ('inicio', 'corredores', 'certificados', 'calificaciones', 'auditoria',
                   'corredor_nuevo', 'certificado_nuevo', 'certificado_carga', 'calificacion_nuevo'):
      self.assertEqual(self.client.get(reverse(nombre)).status_code, 200, nombre)

  def test_crear_corredor(self):
    r = self.client.post(reverse('corredor_nuevo'), {'nombre': 'Nuevo Corredor', 'pais': 'PE', 'activo': 'on'})
    self.assertRedirects(r, reverse('corredores'))
    self.assertTrue(Corredor.objects.filter(nombre='Nuevo Corredor', pais='PE').exists())

  def test_editar_corredor(self):
    r = self.client.post(reverse('corredor_editar', args=[self.corredor.id]),
                         {'nombre': 'Andes Renombrada', 'pais': 'CL', 'activo': 'on'})
    self.assertRedirects(r, reverse('corredores'))
    self.corredor.refresh_from_db()
    self.assertEqual(self.corredor.nombre, 'Andes Renombrada')

  def test_crear_certificado_normaliza_rut(self):
    r = self.client.post(reverse('certificado_nuevo'), datos_certificado(corredor=self.corredor.id))
    self.assertRedirects(r, reverse('certificados'))
    self.assertEqual(Certificado.objects.get().rut, '12345678-5')

  def test_rut_invalido_no_se_guarda(self):
    r = self.client.post(reverse('certificado_nuevo'), datos_certificado(rut='12.345.678-0'))
    self.assertEqual(r.status_code, 200)
    self.assertContains(r, 'RUT inválido')
    self.assertEqual(Certificado.objects.count(), 0)

  def test_certificado_duplicado_se_rechaza(self):
    self.client.post(reverse('certificado_nuevo'), datos_certificado())
    r = self.client.post(reverse('certificado_nuevo'), datos_certificado(rut='12345678-5'))
    self.assertEqual(r.status_code, 200)
    self.assertContains(r, 'Ya existe un certificado')
    self.assertEqual(Certificado.objects.count(), 1)

  def test_editar_certificado(self):
    self.client.post(reverse('certificado_nuevo'), datos_certificado())
    cert = Certificado.objects.get()
    r = self.client.post(reverse('certificado_editar', args=[cert.id]), datos_certificado(estado='VALIDADO'))
    self.assertRedirects(r, reverse('certificados'))
    cert.refresh_from_db()
    self.assertEqual(cert.estado, 'VALIDADO')

  def test_estado_procesado_es_valido(self):
    r = self.client.post(reverse('certificado_nuevo'), datos_certificado(estado='PROCESADO'))
    self.assertRedirects(r, reverse('certificados'))
    self.assertEqual(Certificado.objects.get().estado, 'PROCESADO')

  def test_eliminar_pide_confirmacion_y_borra(self):
    cert = Certificado.objects.create(rut=rut_valido(), nombre_contribuyente='X', ejercicio=2025,
                                      tipo='INTERESES', monto=1)
    url = reverse('certificado_eliminar', args=[cert.id])
    self.assertEqual(self.client.get(url).status_code, 200)
    self.assertTrue(Certificado.objects.exists())  # GET no borra
    self.client.post(url)
    self.assertFalse(Certificado.objects.exists())

  def test_no_se_elimina_corredor_con_certificados(self):
    Certificado.objects.create(rut=rut_valido(), nombre_contribuyente='X', ejercicio=2025,
                               tipo='INTERESES', monto=1, corredor=self.corredor)
    self.client.post(reverse('corredor_eliminar', args=[self.corredor.id]))
    self.assertTrue(Corredor.objects.filter(pk=self.corredor.pk).exists())

  def test_no_se_elimina_certificado_con_calificaciones(self):
    cert = Certificado.objects.create(rut=rut_valido(), nombre_contribuyente='X', ejercicio=2025,
                                      tipo='INTERESES', monto=1)
    Calificacion.objects.create(certificado=cert, origen='BOLSA', calificacion='Con crédito')
    self.client.post(reverse('certificado_eliminar', args=[cert.id]))
    self.assertTrue(Certificado.objects.filter(pk=cert.pk).exists())

  def test_prioridad_corredor_sobre_bolsa(self):
    cert = Certificado.objects.create(rut=rut_valido(), nombre_contribuyente='X', ejercicio=2025,
                                      tipo='INTERESES', monto=1, corredor=self.corredor)
    self.assertIsNone(cert.calificacion_vigente)
    Calificacion.objects.create(certificado=cert, origen='BOLSA', calificacion='Con crédito')
    self.assertEqual(Certificado.objects.get().calificacion_vigente.calificacion, 'Con crédito')
    Calificacion.objects.create(certificado=cert, origen='CORREDOR', calificacion='Sin crédito')
    Calificacion.objects.create(certificado=cert, origen='BOLSA', calificacion='Bolsa más nueva')
    vigente = Certificado.objects.get().calificacion_vigente
    self.assertEqual((vigente.origen, vigente.calificacion), ('CORREDOR', 'Sin crédito'))

  def test_crear_calificacion(self):
    cert = Certificado.objects.create(rut=rut_valido(), nombre_contribuyente='X', ejercicio=2025,
                                      tipo='INTERESES', monto=1)
    r = self.client.post(reverse('calificacion_nuevo'),
                         {'certificado': cert.id, 'origen': 'BOLSA', 'calificacion': 'Con crédito'})
    self.assertRedirects(r, reverse('calificaciones'))
    self.assertEqual(Calificacion.objects.count(), 1)

  def test_calificacion_de_corredor_en_certificado_de_la_bolsa_se_rechaza(self):
    cert = Certificado.objects.create(rut=rut_valido(), nombre_contribuyente='X', ejercicio=2025,
                                      tipo='INTERESES', monto=1)  # sin corredor = viene de la Bolsa
    r = self.client.post(reverse('calificacion_nuevo'),
                         {'certificado': cert.id, 'origen': 'CORREDOR', 'calificacion': 'Con crédito'})
    self.assertEqual(r.status_code, 200)
    self.assertContains(r, 'viene de la Bolsa')
    self.assertEqual(Calificacion.objects.count(), 0)


class RolesTests(TestCase):
  """Qué puede y qué no puede hacer cada rol."""

  def setUp(self):
    self.andes = Corredor.objects.create(nombre='Andes')
    self.cafetal = Corredor.objects.create(nombre='Cafetal', pais='CO')
    self.cert_andes = Certificado.objects.create(rut=rut_valido('11111111'), nombre_contribuyente='De Andes',
                                                 ejercicio=2025, tipo='INTERESES', monto=1, corredor=self.andes)
    self.cert_cafetal = Certificado.objects.create(rut=rut_valido('22222222'), nombre_contribuyente='De Cafetal',
                                                   ejercicio=2025, tipo='INTERESES', monto=1, corredor=self.cafetal)
    self.cert_bolsa = Certificado.objects.create(rut=rut_valido('33333333'), nombre_contribuyente='De la Bolsa',
                                                 ejercicio=2025, tipo='INTERESES', monto=1)
    self.admin = crear_usuario(permisos.ADMIN)
    self.analista = crear_usuario(permisos.ANALISTA)
    self.corredor = crear_usuario(permisos.CORREDOR, corredor=self.andes)
    self.auditor = crear_usuario(permisos.AUDITOR)
    self.sin_rol = crear_usuario(None, 'sinrol')

  def entrar(self, usuario):
    self.client.force_login(usuario)

  # --- sin rol / auditor / analista -------------------------------------
  def test_usuario_sin_rol_recibe_403_en_todo(self):
    self.entrar(self.sin_rol)
    for nombre in ('inicio', 'certificados', 'calificaciones', 'corredores', 'auditoria'):
      self.assertEqual(self.client.get(reverse(nombre)).status_code, 403, nombre)

  def test_auditor_solo_puede_leer(self):
    self.entrar(self.auditor)
    for nombre in ('inicio', 'certificados', 'calificaciones', 'corredores', 'auditoria'):
      self.assertEqual(self.client.get(reverse(nombre)).status_code, 200, nombre)
    for nombre in ('certificado_nuevo', 'certificado_carga', 'corredor_nuevo', 'calificacion_nuevo'):
      self.assertEqual(self.client.get(reverse(nombre)).status_code, 403, nombre)
    r = self.client.post(reverse('certificado_eliminar', args=[self.cert_bolsa.id]))
    self.assertEqual(r.status_code, 403)
    self.assertTrue(Certificado.objects.filter(pk=self.cert_bolsa.pk).exists())

  def test_analista_escribe_pero_no_elimina_ni_gestiona_corredores_ni_audita(self):
    self.entrar(self.analista)
    self.assertEqual(self.client.get(reverse('certificado_nuevo')).status_code, 200)
    self.assertEqual(self.client.get(reverse('certificado_carga')).status_code, 200)
    self.assertEqual(self.client.get(reverse('certificado_eliminar', args=[self.cert_bolsa.id])).status_code, 403)
    self.assertEqual(self.client.get(reverse('corredor_nuevo')).status_code, 403)
    self.assertEqual(self.client.get(reverse('auditoria')).status_code, 403)

  def test_botones_segun_rol(self):
    self.entrar(self.auditor)
    self.assertNotContains(self.client.get(reverse('certificados')), reverse('certificado_nuevo'))
    self.entrar(self.admin)
    self.assertContains(self.client.get(reverse('certificados')), reverse('certificado_nuevo'))

  # --- el corredor ve solo lo suyo ---------------------------------------
  def test_corredor_ve_solo_sus_certificados_y_los_de_la_bolsa(self):
    self.entrar(self.corredor)
    r = self.client.get(reverse('certificados'))
    self.assertContains(r, self.cert_andes.rut)
    self.assertContains(r, self.cert_bolsa.rut)
    self.assertNotContains(r, self.cert_cafetal.rut)

  @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
  def test_corredor_no_descarga_pdf_de_otro_corredor(self):
    self.cert_andes.archivo.save('a.pdf', ContentFile(PDF_FALSO))
    self.cert_cafetal.archivo.save('c.pdf', ContentFile(PDF_FALSO))
    self.entrar(self.corredor)
    self.assertEqual(self.client.get(reverse('certificado_archivo', args=[self.cert_andes.id])).status_code, 200)
    self.assertEqual(self.client.get(reverse('certificado_archivo', args=[self.cert_cafetal.id])).status_code, 404)

  def test_corredor_solo_califica_certificados_de_su_corredor(self):
    self.entrar(self.corredor)
    # certificado de otro corredor: la opción ni siquiera existe en el formulario
    r = self.client.post(reverse('calificacion_nuevo'),
                         {'certificado': self.cert_cafetal.id, 'origen': 'CORREDOR', 'calificacion': 'Sin crédito'})
    self.assertEqual(r.status_code, 200)
    self.assertEqual(Calificacion.objects.count(), 0)
    # certificado de la Bolsa: tampoco
    r = self.client.post(reverse('calificacion_nuevo'),
                         {'certificado': self.cert_bolsa.id, 'origen': 'CORREDOR', 'calificacion': 'Sin crédito'})
    self.assertEqual(Calificacion.objects.count(), 0)
    # el suyo: sí, y queda marcado con su corredor
    r = self.client.post(reverse('calificacion_nuevo'),
                         {'certificado': self.cert_andes.id, 'origen': 'CORREDOR', 'calificacion': 'Sin crédito'})
    self.assertRedirects(r, reverse('calificaciones'))
    calificacion = Calificacion.objects.get()
    self.assertEqual((calificacion.origen, calificacion.corredor), ('CORREDOR', self.andes))

  def test_corredor_no_puede_calificar_como_bolsa(self):
    self.entrar(self.corredor)
    self.client.post(reverse('calificacion_nuevo'),
                     {'certificado': self.cert_andes.id, 'origen': 'BOLSA', 'calificacion': 'Con crédito'})
    self.assertEqual(Calificacion.objects.count(), 0)

  def test_analista_solo_califica_como_bolsa(self):
    self.entrar(self.analista)
    self.client.post(reverse('calificacion_nuevo'),
                     {'certificado': self.cert_andes.id, 'origen': 'CORREDOR', 'calificacion': 'X'})
    self.assertEqual(Calificacion.objects.count(), 0)
    r = self.client.post(reverse('calificacion_nuevo'),
                         {'certificado': self.cert_andes.id, 'origen': 'BOLSA', 'calificacion': 'Con crédito'})
    self.assertRedirects(r, reverse('calificaciones'))
    self.assertIsNone(Calificacion.objects.get().corredor)

  def test_corredor_no_toca_calificaciones_de_la_bolsa(self):
    bolsa = Calificacion.objects.create(certificado=self.cert_andes, origen='BOLSA', calificacion='Con crédito')
    self.entrar(self.corredor)
    self.assertEqual(self.client.get(reverse('calificacion_editar', args=[bolsa.id])).status_code, 403)
    self.assertEqual(self.client.post(reverse('calificacion_eliminar', args=[bolsa.id])).status_code, 403)
    self.assertTrue(Calificacion.objects.filter(pk=bolsa.pk).exists())

  def test_corredor_no_toca_calificaciones_de_otro_corredor(self):
    ajena = Calificacion.objects.create(certificado=self.cert_cafetal, origen='CORREDOR',
                                        corredor=self.cafetal, calificacion='Sin crédito')
    self.entrar(self.corredor)
    self.assertEqual(self.client.get(reverse('calificacion_editar', args=[ajena.id])).status_code, 403)

  def test_corredor_edita_y_elimina_su_calificacion(self):
    propia = Calificacion.objects.create(certificado=self.cert_andes, origen='CORREDOR',
                                         corredor=self.andes, calificacion='Sin crédito')
    self.entrar(self.corredor)
    r = self.client.post(reverse('calificacion_editar', args=[propia.id]),
                         {'certificado': self.cert_andes.id, 'origen': 'CORREDOR', 'calificacion': 'Con crédito'})
    self.assertRedirects(r, reverse('calificaciones'))
    propia.refresh_from_db()
    self.assertEqual(propia.calificacion, 'Con crédito')
    self.client.post(reverse('calificacion_eliminar', args=[propia.id]))
    self.assertFalse(Calificacion.objects.filter(pk=propia.pk).exists())

  def test_analista_no_toca_calificaciones_de_corredor(self):
    de_corredor = Calificacion.objects.create(certificado=self.cert_andes, origen='CORREDOR',
                                              corredor=self.andes, calificacion='Sin crédito')
    self.entrar(self.analista)
    self.assertEqual(self.client.get(reverse('calificacion_editar', args=[de_corredor.id])).status_code, 403)

  def test_la_calificacion_de_la_bolsa_no_se_pierde_al_calificar_el_corredor(self):
    Calificacion.objects.create(certificado=self.cert_andes, origen='BOLSA', calificacion='Con crédito')
    self.entrar(self.corredor)
    self.client.post(reverse('calificacion_nuevo'),
                     {'certificado': self.cert_andes.id, 'origen': 'CORREDOR', 'calificacion': 'Sin crédito'})
    self.assertEqual(Calificacion.objects.filter(certificado=self.cert_andes).count(), 2)
    self.assertEqual(Certificado.objects.get(pk=self.cert_andes.pk).calificacion_vigente.calificacion, 'Sin crédito')

  def test_acceso_denegado_queda_en_la_bitacora(self):
    self.entrar(self.auditor)
    self.client.get(reverse('certificado_nuevo'))
    fila = Auditoria.objects.get(accion='ACCESO_DENEGADO')
    self.assertEqual((fila.usuario, fila.rol), (self.auditor.username, permisos.AUDITOR))
    self.assertEqual(fila.detalle['ruta'], reverse('certificado_nuevo'))


class AuditoriaTests(TestCase):
  def setUp(self):
    cache.clear()
    self.admin = crear_usuario(permisos.ADMIN, 'adm')
    self.client.force_login(self.admin)

  def test_crear_modificar_y_eliminar_quedan_registrados(self):
    self.client.post(reverse('corredor_nuevo'), {'nombre': 'Alfa', 'pais': 'CL', 'activo': 'on'})
    corredor = Corredor.objects.get(nombre='Alfa')
    self.client.post(reverse('corredor_editar', args=[corredor.id]), {'nombre': 'Alfa 2', 'pais': 'CL', 'activo': 'on'})
    self.client.post(reverse('corredor_eliminar', args=[corredor.id]))

    crear = Auditoria.objects.get(accion='CREAR')
    self.assertEqual((crear.usuario, crear.rol, crear.modelo, crear.objeto_id),
                     ('adm', permisos.ADMIN, 'corredor', str(corredor.id)))
    modificar = Auditoria.objects.get(accion='MODIFICAR')
    self.assertEqual(modificar.detalle['cambios']['nombre'], ['Alfa', 'Alfa 2'])
    eliminar = Auditoria.objects.get(accion='ELIMINAR')
    self.assertEqual((eliminar.objeto_id, eliminar.objeto), (str(corredor.id), 'Alfa 2'))
    self.assertIsNone(Auditoria.verificar_cadena())

  def test_un_borrado_rechazado_no_se_registra_como_eliminado(self):
    corredor = Corredor.objects.create(nombre='Con datos')
    Certificado.objects.create(rut=rut_valido(), nombre_contribuyente='X', ejercicio=2025,
                               tipo='INTERESES', monto=1, corredor=corredor)
    self.client.post(reverse('corredor_eliminar', args=[corredor.id]))
    self.assertFalse(Auditoria.objects.filter(accion='ELIMINAR').exists())

  @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
  def test_descarga_de_pdf_queda_registrada(self):
    cert = Certificado.objects.create(rut=rut_valido(), nombre_contribuyente='X', ejercicio=2025,
                                      tipo='INTERESES', monto=1)
    cert.archivo.save('a.pdf', ContentFile(PDF_FALSO))
    self.client.get(reverse('certificado_archivo', args=[cert.id]))
    self.assertTrue(Auditoria.objects.filter(accion='DESCARGA', objeto_id=str(cert.id)).exists())

  def test_pantalla_de_auditoria_verifica_la_cadena(self):
    r = self.client.get(reverse('auditoria') + '?verificar=1')
    self.assertContains(r, 'Cadena íntegra')

  def test_login_y_logout_quedan_registrados(self):
    cliente = self.client_class()
    usuario = crear_usuario(permisos.ANALISTA, 'ana')
    r = cliente.post(reverse('login'), {'username': 'ana', 'password': CLAVE})
    self.assertEqual(r.status_code, 302)
    self.assertTrue(Auditoria.objects.filter(accion='LOGIN', usuario='ana').exists())
    cliente.post(reverse('logout'))
    self.assertTrue(Auditoria.objects.filter(accion='LOGOUT', usuario='ana').exists())
    self.assertEqual(usuario.username, 'ana')

  def test_intentos_fallidos_se_registran_y_bloquean_la_cuenta(self):
    crear_usuario(permisos.ANALISTA, 'victima')
    cliente = self.client_class()
    for _ in range(5):
      cliente.post(reverse('login'), {'username': 'victima', 'password': 'mala-clave'})
    self.assertEqual(Auditoria.objects.filter(accion='LOGIN_FALLIDO', usuario='victima').count(), 5)
    # sexto intento con la clave CORRECTA: sigue bloqueado
    r = cliente.post(reverse('login'), {'username': 'victima', 'password': CLAVE})
    self.assertEqual(r.status_code, 200)
    self.assertContains(r, 'Demasiados intentos')
    self.assertNotIn('_auth_user_id', cliente.session)

  def test_un_acceso_correcto_reinicia_el_contador(self):
    crear_usuario(permisos.ANALISTA, 'olvidadizo')
    cliente = self.client_class()
    for _ in range(3):
      cliente.post(reverse('login'), {'username': 'olvidadizo', 'password': 'mala'})
    self.assertEqual(cliente.post(reverse('login'), {'username': 'olvidadizo', 'password': CLAVE}).status_code, 302)
    cliente.post(reverse('logout'))
    for _ in range(3):
      cliente.post(reverse('login'), {'username': 'olvidadizo', 'password': 'mala'})
    self.assertEqual(cliente.post(reverse('login'), {'username': 'olvidadizo', 'password': CLAVE}).status_code, 302)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ArchivoTests(TestCase):
  def setUp(self):
    self.usuario = crear_usuario(permisos.ADMIN, 'tester')
    self.client.force_login(self.usuario)

  def _subir(self, contenido, nombre='cert.pdf'):
    datos = datos_certificado(archivo=SimpleUploadedFile(nombre, contenido, content_type='application/pdf'))
    return self.client.post(reverse('certificado_nuevo'), datos)

  def test_pdf_real_se_acepta_y_se_descarga(self):
    self.assertRedirects(self._subir(PDF_FALSO), reverse('certificados'))
    cert = Certificado.objects.get()
    r = self.client.get(reverse('certificado_archivo', args=[cert.id]))
    self.assertEqual(r.status_code, 200)
    self.assertEqual(r['Content-Type'], 'application/pdf')
    self.assertEqual(b''.join(r.streaming_content), PDF_FALSO)

  def test_archivo_que_no_es_pdf_se_rechaza(self):
    r = self._subir(b'esto es solo texto', 'cert.pdf')
    self.assertContains(r, 'no es un PDF válido')
    self._subir(PDF_FALSO, 'cert.exe')
    self.assertEqual(Certificado.objects.count(), 0)

  def test_descarga_requiere_sesion(self):
    self._subir(PDF_FALSO)
    cert = Certificado.objects.get()
    self.client.logout()
    r = self.client.get(reverse('certificado_archivo', args=[cert.id]))
    self.assertEqual(r.status_code, 302)

  def test_editar_sin_cambiar_el_archivo_lo_conserva(self):
    self._subir(PDF_FALSO)
    cert = Certificado.objects.get()
    self.client.post(reverse('certificado_editar', args=[cert.id]), datos_certificado(estado='VALIDADO'))
    cert.refresh_from_db()
    self.assertEqual(cert.estado, 'VALIDADO')
    self.assertTrue(cert.archivo)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class CargaMasivaTests(TestCase):
  def setUp(self):
    self.analista = crear_usuario(permisos.ANALISTA)
    self.client.force_login(self.analista)
    self.url = reverse('certificado_carga')

  def _pdf(self, nombre, contenido):
    return SimpleUploadedFile(nombre, contenido, content_type='application/pdf')

  def test_un_pdf_se_lee_y_queda_procesado(self):
    r = self.client.post(self.url, {'archivos': [self._pdf('a.pdf', pdf_certificado())]})
    self.assertEqual(r.status_code, 200)
    self.assertTrue(r.context['resultados'][0]['ok'])
    cert = Certificado.objects.get()
    self.assertEqual((cert.rut, cert.ejercicio, cert.tipo, str(cert.monto), cert.estado),
                     ('12345678-5', 2025, 'DIVIDENDOS', '1250000.00', 'PROCESADO'))
    self.assertEqual(cert.nombre_contribuyente, 'Ana Perez')
    self.assertEqual(cert.datos_extraidos['campos']['rut'], '12345678-5')
    self.assertIn('CERTIFICADO DE DIVIDENDOS', cert.datos_extraidos['texto'])
    self.assertTrue(cert.archivo)
    self.assertTrue(Auditoria.objects.filter(accion='CARGA', objeto_id=str(cert.id)).exists())

  def test_un_archivo_con_error_no_detiene_a_los_demas(self):
    buenos = pdf_certificado()
    r = self.client.post(self.url, {'archivos': [
      self._pdf('bueno.pdf', buenos),
      self._pdf('texto.pdf', b'esto no es un pdf'),
      self._pdf('vacio.pdf', pdf_con_texto(['Documento sin datos tributarios'])),
      self._pdf('repetido.pdf', buenos),
      self._pdf('otro.pdf', pdf_certificado(rut='9.876.543-3', nombre='Luis Soto', tipo='Intereses', monto='500.000')),
    ]})
    resultados = r.context['resultados']
    self.assertEqual([x['ok'] for x in resultados], [True, False, False, False, True])
    self.assertEqual([x['archivo'] for x in resultados], ['bueno.pdf', 'texto.pdf', 'vacio.pdf', 'repetido.pdf', 'otro.pdf'])
    self.assertIn('no es un PDF', resultados[1]['motivo'])
    self.assertIn('No se reconocieron', resultados[2]['motivo'])
    self.assertIn('Ya existe', resultados[3]['motivo'])
    self.assertEqual(Certificado.objects.count(), 2)

  def test_el_certificado_queda_asignado_al_corredor_elegido(self):
    corredor = Corredor.objects.create(nombre='Andes')
    self.client.post(self.url, {'archivos': [self._pdf('a.pdf', pdf_certificado())], 'corredor': corredor.id})
    self.assertEqual(Certificado.objects.get().corredor, corredor)

  def test_maximo_de_archivos_por_carga(self):
    archivos = [self._pdf(f'{i}.pdf', PDF_FALSO) for i in range(51)]
    r = self.client.post(self.url, {'archivos': archivos})
    self.assertContains(r, 'Máximo 50 archivos')
    self.assertEqual(Certificado.objects.count(), 0)

  def test_sin_archivos_muestra_error(self):
    r = self.client.post(self.url, {})
    self.assertEqual(r.status_code, 200)
    self.assertContains(r, 'Selecciona al menos un archivo')
    self.assertEqual(Certificado.objects.count(), 0)

  def test_el_rol_corredor_no_puede_cargar(self):
    self.client.force_login(crear_usuario(permisos.CORREDOR, 'corr'))
    r = self.client.post(self.url, {'archivos': [self._pdf('a.pdf', pdf_certificado())]})
    self.assertEqual(r.status_code, 403)
    self.assertEqual(Certificado.objects.count(), 0)

  def test_se_guarda_en_la_base_no_estructurada_si_esta_disponible(self):
    cliente = MagicMock()
    with patch('nuamApp.almacen._obtener_cliente', return_value=cliente):
      self.client.post(self.url, {'archivos': [self._pdf('a.pdf', pdf_certificado())]})
    coleccion = cliente.__getitem__.return_value.__getitem__.return_value
    coleccion.insert_one.assert_called_once()
    documento = coleccion.insert_one.call_args[0][0]
    self.assertEqual(documento['campos']['rut'], '12345678-5')
    self.assertIn('texto', documento)

  def test_si_mongodb_falla_la_carga_igual_funciona(self):
    with patch('nuamApp.almacen._obtener_cliente', side_effect=Exception('sin conexión')):
      r = self.client.post(self.url, {'archivos': [self._pdf('a.pdf', pdf_certificado())]})
    self.assertTrue(r.context['resultados'][0]['ok'])
    self.assertEqual(Certificado.objects.count(), 1)


# ===========================================================================
# 3. RENDIMIENTO
# ===========================================================================
class RendimientoTests(TestCase):
  """
  Con volumen: la cantidad de consultas no debe crecer con los datos (sin N+1) y los tiempos
  deben mantenerse bajos. Los límites son holgados para no fallar en computadores lentos.
  """

  def setUp(self):
    self.admin = crear_usuario(permisos.ADMIN, 'adm')
    self.client.force_login(self.admin)
    self.corredor = Corredor.objects.create(nombre='Andes')

  def _crear_certificados(self, desde, cantidad):
    ruts = [rut_valido(str(10000000 + i)) for i in range(desde, desde + cantidad)]
    Certificado.objects.bulk_create([
      Certificado(rut=rut, nombre_contribuyente=f'Contribuyente {rut}', ejercicio=2025,
                  tipo='DIVIDENDOS', monto=1000, corredor=self.corredor)
      for rut in ruts])
    # MySQL no devuelve los id en bulk_create: se vuelven a leer
    certificados = list(Certificado.objects.filter(rut__in=ruts))
    Calificacion.objects.bulk_create([
      Calificacion(certificado=c, origen='BOLSA', calificacion='Con crédito') for c in certificados])

  def _consultas(self, nombre):
    with CaptureQueriesContext(connection) as contexto:
      self.assertEqual(self.client.get(reverse(nombre)).status_code, 200)
    return len(contexto)

  def test_listados_no_hacen_consultas_extra_por_fila(self):
    self._crear_certificados(0, 5)
    for nombre in ('certificados', 'calificaciones'):
      self._consultas(nombre)  # calentamiento
    pocas = {n: self._consultas(n) for n in ('certificados', 'calificaciones')}
    self._crear_certificados(5, 295)
    muchas = {n: self._consultas(n) for n in ('certificados', 'calificaciones')}
    self.assertEqual(pocas, muchas)

  def test_listado_de_300_certificados_responde_rapido(self):
    self._crear_certificados(0, 300)
    inicio = time.perf_counter()
    r = self.client.get(reverse('certificados'))
    duracion = time.perf_counter() - inicio
    self.assertEqual(r.status_code, 200)
    self.assertLess(duracion, 3.0, f'El listado tardó {duracion:.2f} s')

  def test_verificar_200_registros_de_auditoria_es_rapido(self):
    for i in range(200):
      Auditoria.objects.create(usuario='u', accion='CREAR', modelo='certificado', objeto_id=str(i), detalle={'i': i})
    inicio = time.perf_counter()
    self.assertIsNone(Auditoria.verificar_cadena())
    self.assertLess(time.perf_counter() - inicio, 5.0)

  def test_extraer_100_textos_es_rapido(self):
    texto = ('CERTIFICADO DE DIVIDENDOS\nAño Tributario: 2025\nRUT del contribuyente: 12.345.678-5\n'
             'Nombre del contribuyente: Ana Pérez\nMonto total: $1.250.000\n') * 5
    inicio = time.perf_counter()
    for _ in range(100):
      extractor.extraer_campos(texto)
    self.assertLess(time.perf_counter() - inicio, 2.0)

  def test_carga_masiva_de_20_pdf_reales(self):
    archivos = [SimpleUploadedFile(f'c{i}.pdf', pdf_certificado(rut=rut_valido(str(20000000 + i)),
                                                                nombre=f'Persona {i}'),
                                   content_type='application/pdf')
                for i in range(20)]
    with override_settings(MEDIA_ROOT=tempfile.mkdtemp()):
      inicio = time.perf_counter()
      r = self.client.post(reverse('certificado_carga'), {'archivos': archivos})
      duracion = time.perf_counter() - inicio
    self.assertEqual(sum(1 for x in r.context['resultados'] if x['ok']), 20, r.context['resultados'])
    self.assertLess(duracion, 20.0, f'La carga tardó {duracion:.2f} s')
