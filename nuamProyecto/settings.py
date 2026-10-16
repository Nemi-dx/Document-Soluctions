"""
Configuración del proyecto NUAM (versión simple, basada en empleadosProyecto).
"""

import os
from pathlib import Path

from django.contrib.messages import constants as mensajes
from django.core.exceptions import ImproperlyConfigured

# Rutas base: BASE_DIR / 'subcarpeta'
BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / 'templates'

def _bool(nombre, defecto):
    return os.environ.get(nombre, defecto).strip().lower() in ('1', 'true', 'si', 'sí', 'yes')


# DEBUG: por defecto ACTIVO para desarrollo. En producción: DJANGO_DEBUG=0 (activa además
# cookies seguras, HTTPS obligatorio y HSTS, más abajo) y exige clave secreta y credenciales por entorno.
DEBUG = _bool('DJANGO_DEBUG', '1')

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured('En producción define la variable de entorno DJANGO_SECRET_KEY.')
    SECRET_KEY = 'django-insecure-nuam-solo-para-desarrollo'

# Hosts permitidos (separados por coma). En producción: DJANGO_ALLOWED_HOSTS=nuam.ejemplo.cl
ALLOWED_HOSTS = [h.strip() for h in os.environ.get(
    'DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1' if DEBUG else '').split(',') if h.strip()]


# Aplicaciones
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'nuamApp',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# WhiteNoise sirve los archivos estáticos en producción (está en requirements.txt;
# si no está instalado, el proyecto sigue funcionando en desarrollo).
try:
    import whitenoise  # noqa: F401
    MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')
    _estaticos = 'whitenoise.storage.CompressedStaticFilesStorage'
except ImportError:
    _estaticos = 'django.contrib.staticfiles.storage.StaticFilesStorage'

ROOT_URLCONF = 'nuamProyecto.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [TEMPLATES_DIR],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'nuamApp.contexto.roles',
            ],
        },
    },
]

WSGI_APPLICATION = 'nuamProyecto.wsgi.application'


# Base de datos
# Por defecto MySQL (igual que empleadosProyecto). Para probar rápido sin MySQL:
#   set DB_ENGINE=sqlite      (Windows)   |   export DB_ENGINE=sqlite   (Linux/Mac)
if os.environ.get('DB_ENGINE', 'mysql').lower() == 'sqlite':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
else:
    import pymysql
    pymysql.install_as_MySQLdb()

    # La clave de la base de datos NO va escrita en el código. Solo en desarrollo se acepta la de clase.
    _clave_bd = os.environ.get('DB_PASSWORD')
    if _clave_bd is None:
        if not DEBUG:
            raise ImproperlyConfigured('En producción define la variable de entorno DB_PASSWORD.')
        _clave_bd = '1234'

    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': os.environ.get('DB_NAME', 'nuam'),
            'USER': os.environ.get('DB_USER', 'admin'),
            'PASSWORD': _clave_bd,
            'HOST': os.environ.get('DB_HOST', '127.0.0.1'),
            'PORT': os.environ.get('DB_PORT', '3306'),
            'OPTIONS': {'charset': 'utf8mb4'},
        }
    }
    # Conexión cifrada a RDS: descarga el certificado de AWS (global-bundle.pem) y apunta a él con DB_SSL_CA
    if os.environ.get('DB_SSL_CA'):
        DATABASES['default']['OPTIONS']['ssl'] = {'ca': os.environ['DB_SSL_CA']}


# Validación de contraseñas
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
     'OPTIONS': {'min_length': 10}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Login: a dónde mandar al usuario
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'inicio'
LOGOUT_REDIRECT_URL = 'login'

# Mensajes: Bootstrap usa "danger" en vez de "error"
MESSAGE_TAGS = {mensajes.ERROR: 'danger'}


# Internacionalización
LANGUAGE_CODE = 'es-cl'
TIME_ZONE = 'America/Santiago'
USE_I18N = True
USE_TZ = True


# Archivos estáticos
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'   # destino de `python manage.py collectstatic`

STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': _estaticos},
}

# Certificados PDF subidos. Es una carpeta PRIVADA: no se sirve por URL,
# se descarga solo con sesión iniciada (vista certificadoArchivo).
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ---------------------------------------------------------------------------
# Seguridad (ver docs/SEGURIDAD.md)
# ---------------------------------------------------------------------------
# Sesión: expira a los 30 minutos sin actividad; la cookie no es legible desde JavaScript.
SESSION_COOKIE_AGE = 30 * 60
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'

# Cabeceras
X_FRAME_OPTIONS = 'DENY'                 # nadie puede incrustar el sistema en un iframe (clickjacking)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'

# Límites de subida: un PDF de hasta 10 MB; la petición completa admite hasta 50 archivos
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FILES = 60

# Solo en producción (DEBUG = False): todo por HTTPS.
# DJANGO_HTTPS=0 existe SOLO para una demostración sin certificado (por ejemplo, entrar por http://IP
# en AWS Academy). Con HTTPS desactivado las cookies viajan sin cifrar: no usar con datos reales.
USAR_HTTPS = _bool('DJANGO_HTTPS', '1')
if not DEBUG and USAR_HTTPS:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')  # nginx envía esta cabecera

# Orígenes permitidos para formularios (Django 4+ lo exige detrás de un proxy/HTTPS).
# Ejemplo: DJANGO_CSRF_TRUSTED_ORIGINS=https://nuam.ejemplo.cl,http://54.12.34.56
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get('DJANGO_CSRF_TRUSTED_ORIGINS', '').split(',') if o.strip()]

# Detrás de nginx, la IP real llega en X-Real-IP (ver auditoria.ip_de). Solo activar con nginx delante.
PROXY_CONFIABLE = _bool('DJANGO_PROXY_CONFIABLE', '0')

# Registro de eventos del servidor (los errores de auditoría también quedan aquí)
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'consola': {'class': 'logging.StreamHandler'}},
    'loggers': {'nuamApp': {'handlers': ['consola'], 'level': 'INFO'}},
}
