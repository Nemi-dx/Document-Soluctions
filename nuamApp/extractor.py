"""
Extracción automática de datos desde certificados PDF (basada en reglas, sin IA).

Este módulo NO depende de Django: solo recibe texto y devuelve un diccionario.
Así se puede probar de forma aislada y ajustar las expresiones regulares cuando se
conozcan los dos formatos oficiales de certificado (ver PATRONES más abajo).

Resultado de extraer_campos(texto):
    {
      'campos':   {'rut': '12345678-5', 'nombre': '...', 'ejercicio': 2025, 'tipo': 'DIVIDENDOS', 'monto': '1250000'},
      'faltantes': ['monto'],      # campos que no se pudieron reconocer -> revisión humana
    }
"""
import io
import re
import unicodedata

CAMPOS_OBLIGATORIOS = ('rut', 'nombre', 'ejercicio', 'tipo', 'monto')

MAX_PAGINAS = 20  # un certificado no tiene más; evita procesar PDFs gigantes


def _normalizar(texto):
  """
  Minúsculas y sin tildes, MANTENIENDO el largo del texto (un carácter por carácter).
  Así una posición en el texto normalizado es la misma posición en el original.
  """
  salida = []
  for c in texto:
    base = unicodedata.normalize('NFD', c)[:1] or c   # 'ñ' -> 'n', 'á' -> 'a'
    salida.append(base.lower()[:1] or base)
  return ''.join(salida)


# Cada campo tiene una lista de patrones. Se prueba en orden y gana el primero que calza.
# Se aplican sobre el texto SIN tildes y en minúsculas (_normalizar), así "Año" y "ano" valen igual.
PATRONES = {
  'rut': [
    r'\brut(?:\s+(?:del\s+)?(?:contribuyente|beneficiario|inversionista))?\s*[:\-]?\s*(\d{1,2}(?:\.\d{3}){2}-[\dk]|\d{7,8}-[\dk])',
    r'\b(\d{1,2}(?:\.\d{3}){2}-[\dk])\b',
  ],
  'nombre': [
    r'(?:nombre|razon\s+social)(?:\s+del\s+(?:contribuyente|beneficiario|inversionista))?\s*[:\-]\s*([^\n\r]+)',
    r'contribuyente\s*[:\-]\s*([^\n\r]+)',
  ],
  'ejercicio': [
    r'\bano\s+tributario\s*[:\-]?\s*(20\d{2})',
    r'ejercicio(?:\s+tributario)?\s*[:\-]?\s*(20\d{2})',
    r'\bano\s+comercial\s*[:\-]?\s*(20\d{2})',
  ],
  'monto': [
    r'monto(?:\s+(?:total|bruto|certificado))?\s*[:\-]?\s*\$?\s*([\d\.\,]+)',
    r'valor\s*[:\-]?\s*\$?\s*([\d\.\,]+)',
  ],
}

# Palabras que identifican el tipo de certificado
TIPOS = [
  ('GANANCIA_CAPITAL', r'ganancias?\s+de\s+capital'),
  ('DIVIDENDOS', r'dividendos?'),
  ('INTERESES', r'intereses?'),
]


def extraer_texto_pdf(archivo):
  """Texto de un PDF (objeto tipo archivo). Lanza ValueError si el PDF no se puede leer."""
  try:
    from pypdf import PdfReader
    contenido = archivo.read() if hasattr(archivo, 'read') else archivo  # sirve para archivos subidos y para bytes
    lector = PdfReader(io.BytesIO(contenido))
    if lector.is_encrypted:
      raise ValueError('El PDF está protegido con contraseña.')
    paginas = lector.pages[:MAX_PAGINAS]
    return '\n'.join((p.extract_text() or '') for p in paginas)
  except ValueError:
    raise
  except Exception as exc:  # pypdf lanza distintos errores según qué esté dañado
    raise ValueError('No se pudo leer el PDF.') from exc


def normalizar_monto(texto):
  """'1.250.000' -> '1250000' ; '1.250.000,50' -> '1250000.50' ; '1,250,000.50' -> '1250000.50'."""
  texto = texto.strip().strip('.,')
  if not texto:
    return None
  if ',' in texto and '.' in texto:
    # el separador decimal es el que aparece último
    if texto.rfind(',') > texto.rfind('.'):
      texto = texto.replace('.', '').replace(',', '.')
    else:
      texto = texto.replace(',', '')
  elif ',' in texto:
    partes = texto.split(',')
    texto = texto.replace(',', '.') if len(partes) == 2 and len(partes[1]) != 3 else texto.replace(',', '')
  elif '.' in texto:
    partes = texto.split('.')
    if not (len(partes) == 2 and len(partes[1]) != 3):
      texto = texto.replace('.', '')
  return texto if re.fullmatch(r'\d+(\.\d+)?', texto) else None


def extraer_campos(texto):
  """Aplica las reglas al texto y devuelve los campos reconocidos y los faltantes."""
  original = texto or ''
  minus = _normalizar(original)
  campos = {}

  for campo, patrones in PATRONES.items():
    for patron in patrones:
      m = re.search(patron, minus)
      if not m:
        continue
      if campo == 'nombre':
        # el nombre se toma del texto original (con mayúsculas y tildes) en la misma posición
        valor = original[m.start(1):m.end(1)].strip()
      else:
        valor = m.group(1)
      if campo == 'rut':
        valor = valor.replace('.', '').upper()
      elif campo == 'ejercicio':
        valor = int(valor)
      elif campo == 'monto':
        valor = normalizar_monto(valor)
      if valor not in (None, ''):
        campos[campo] = valor
        break

  for tipo, patron in TIPOS:
    if re.search(patron, minus):
      campos['tipo'] = tipo
      break

  faltantes = [c for c in CAMPOS_OBLIGATORIOS if c not in campos]
  return {'campos': campos, 'faltantes': faltantes}


def extraer_de_pdf(archivo):
  """Atajo: PDF -> {'campos', 'faltantes', 'texto'}. El texto se guarda en la base no estructurada."""
  texto = extraer_texto_pdf(archivo)
  resultado = extraer_campos(texto)
  resultado['texto'] = texto
  return resultado
