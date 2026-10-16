"""
Validaciones propias de NUAM: RUT chileno y archivo PDF.
"""
import re

from django.core.exceptions import ValidationError

TAMANO_MAXIMO_PDF = 10 * 1024 * 1024  # 10 MB


def normalizar_rut(rut):
    """'12.345.678-5' o '123456785' -> '12345678-5' (sin puntos, con guion, K en mayúscula)."""
    rut = re.sub(r'[.\s]', '', rut or '').upper()
    if '-' not in rut and len(rut) > 1:
        rut = rut[:-1] + '-' + rut[-1]
    return rut


def calcular_dv(cuerpo):
    """Dígito verificador de un RUT (algoritmo módulo 11)."""
    suma, factor = 0, 2
    for digito in reversed(str(cuerpo)):
        suma += int(digito) * factor
        factor = 2 if factor == 7 else factor + 1
    resto = 11 - (suma % 11)
    if resto == 11:
        return '0'
    if resto == 10:
        return 'K'
    return str(resto)


def validar_rut(valor):
    rut = normalizar_rut(valor)
    partes = re.fullmatch(r'(\d{7,8})-([\dK])', rut)
    if not partes or calcular_dv(partes.group(1)) != partes.group(2):
        raise ValidationError('RUT inválido. Revisa el número y el dígito verificador.')


def validar_pdf(archivo):
    """Solo PDF reales (firma %PDF-) de hasta 10 MB."""
    if getattr(archivo, '_committed', False):
        return  # archivo ya guardado antes: no se vuelve a revisar
    if archivo.size > TAMANO_MAXIMO_PDF:
        raise ValidationError('El archivo supera el máximo de 10 MB.')
    cabecera = archivo.read(5)
    archivo.seek(0)
    if cabecera != b'%PDF-':
        raise ValidationError('El archivo no es un PDF válido.')
