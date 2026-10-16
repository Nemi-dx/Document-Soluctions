# NUAM – Calificaciones tributarias

Sistema web para **registrar certificados tributarios** (a mano o cargando PDF en forma masiva con extracción automática de datos), **calificarlos** respetando que la calificación del corredor tiene prioridad sobre la de la Bolsa, y **auditar** cada acción. Django + MySQL (+ MongoDB opcional).

| Documento | Contenido |
|---|---|
| [`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md) | modelo de datos (diagrama ER), bases estructurada y no estructurada, tecnologías y su justificación, vistas 4+1 |
| [`docs/SEGURIDAD.md`](docs/SEGURIDAD.md) | autenticación, roles y permisos, amenazas y mitigaciones, estándares de codificación segura |
| [`docs/PRUEBAS.md`](docs/PRUEBAS.md) | plan de pruebas: automatizadas, de rendimiento y manuales |
| [`docs/DESPLIEGUE_AWS.md`](docs/DESPLIEGUE_AWS.md) | despliegue en AWS (EC2 + RDS) paso a paso para AWS Academy |

## 1. Cómo ejecutarlo

Requiere Python 3.12+ y MySQL 8 (o MariaDB 10.6+).

```bash
# 1) Entorno virtual e instalación
python -m venv venv
venv\Scripts\activate              # Linux/Mac: source venv/bin/activate
pip install -r requirements.txt

# 2) Base de datos MySQL (una vez, como administrador de MySQL)
mysql -u root -p < docs/crear_base_mysql.sql
#    Usuario y clave por defecto en desarrollo: admin / mi_clave_123  (se cambian con DB_USER y DB_PASSWORD)

# 3) Tablas, roles y datos de ejemplo
python manage.py migrate              # también crea los 4 roles
python manage.py createsuperuser      # será Administrador
python manage.py cargar_demo          # opcional: datos de ejemplo + un usuario por rol

# 4) Arrancar
python manage.py runserver
```

Abre <http://127.0.0.1:8000/>. El panel de administración de usuarios y roles está en `/admin/`.

**Probar sin MySQL:** `DB_ENGINE=sqlite` (Windows: `set DB_ENGINE=sqlite`) antes de los pasos 3 y 4.

**Usuarios de ejemplo** (los crea `cargar_demo`, solo en desarrollo; clave `Demo-Nuam-2026!`): `demo_admin`, `demo_analista`, `demo_corredor`, `demo_auditor`.

## 2. Qué hace

- **Carga masiva de certificados PDF** (hasta 50 a la vez): el sistema lee cada PDF, extrae RUT, nombre, año tributario, tipo y monto, y deja el certificado en estado **Procesado** para que una persona lo revise y lo marque **Validado**. Un archivo con error no detiene a los demás y se informa el motivo. (`extractor.py`)
- **Registro manual** con validación de RUT chileno (dígito verificador), certificado único por RUT + año + tipo y PDF real de hasta 10 MB.
- **Calificaciones** con origen Bolsa o Corredor: la del corredor tiene prioridad (`Certificado.calificacion_vigente`) y las modificaciones de un corredor quedan locales a él.
- **Cuatro roles** con mínimo privilegio: Administrador, Analista, Corredor, Auditor (matriz en `docs/SEGURIDAD.md`).
- **Auditoría inmutable:** cada alta, cambio, baja, carga, descarga, acceso y denegación queda en una bitácora con **hash encadenado**; la pantalla *Auditoría* y `python manage.py verificar_auditoria` detectan cualquier alteración.
- **Seguridad:** login con bloqueo tras 5 intentos, sesión de 30 minutos, CSRF, PDF en carpeta privada, modo producción con HTTPS/HSTS y secretos por variables de entorno.
- **Base no estructurada (opcional):** el texto extraído de cada PDF se guarda además en MongoDB si defines `MONGO_URI`.
- **Tablas con DataTables:** búsqueda, orden y exportación a Excel, CSV, PDF o impresión.

## 3. Ajustar la extracción a los certificados reales

`nuamApp/extractor.py` reconoce los campos con expresiones regulares (diccionario `PATRONES`). Reconoce etiquetas como «RUT», «Nombre del contribuyente», «Razón social», «Año tributario», «Ejercicio», «Monto» y los tipos «dividendos», «intereses» y «ganancia de capital». Si los dos formatos oficiales usan otras palabras, se agregan en `PATRONES` y en `TIPOS`; no hay que tocar nada más. Los campos que no se reconocen se informan en pantalla para ingresarlos a mano.

## 4. Pruebas

```bash
python manage.py test          # 78 pruebas: unitarias, integrales y de rendimiento
```

El plan completo (incluidos los 14 casos manuales y la prueba de carga con Locust) está en [`docs/PRUEBAS.md`](docs/PRUEBAS.md).

## 5. Producción y despliegue en AWS

Guía paso a paso para **AWS Academy (Learner Lab)** con EC2 + RDS MySQL, Nginx, gunicorn y HTTPS: [`docs/DESPLIEGUE_AWS.md`](docs/DESPLIEGUE_AWS.md). Los archivos de configuración están en `deploy/` (`nuam.service`, `nginx_nuam.conf`, `nuam.env.ejemplo`).

Resumen de la configuración segura (`python manage.py check --deploy` no debe mostrar errores):

```bash
set DJANGO_DEBUG=0
set DJANGO_SECRET_KEY=<clave larga y aleatoria>
set DJANGO_ALLOWED_HOSTS=nuam.ejemplo.cl
set DB_PASSWORD=<clave de la base>
```

Con `DJANGO_DEBUG=0` el sistema **no arranca** si faltan la clave secreta o la clave de la base, y activa HTTPS obligatorio, HSTS y cookies seguras. Variables completas en `docs/SEGURIDAD.md`.

## 6. Limitaciones conocidas

Sin segundo factor de autenticación, sin cifrado en reposo propio de los PDF (se delega al disco/servidor), sin antivirus de archivos subidos y con el contador de intentos de login en memoria del proceso (con varios servidores usar Redis). Detalle en `docs/SEGURIDAD.md`, sección 3.
