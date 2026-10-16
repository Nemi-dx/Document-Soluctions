# Seguridad de NUAM

NUAM maneja información fiscal de terceros en un mercado regulado. Este documento resume las políticas de acceso, las amenazas consideradas, cómo se mitiga cada una y los estándares de codificación segura del proyecto. Cada punto indica **dónde está en el código** y **qué prueba lo comprueba**.

## 1. Autenticación (¿quién eres?)

| Política | Valor | Dónde |
|---|---|---|
| Todas las páginas exigen sesión | `@login_required` en cada vista | `views.py` · `SinSesionTests` |
| Contraseña | mínimo 10 caracteres; no similar al usuario, no común, no solo números | `settings.py` (`AUTH_PASSWORD_VALIDATORS`) |
| Almacenamiento de contraseñas | hash PBKDF2 con sal (por defecto de Django); nunca en texto plano | Django |
| Bloqueo por fuerza bruta | 5 intentos fallidos por usuario → bloqueo 15 minutos, incluso con la clave correcta; un acceso correcto reinicia el contador | `login.py`, `signals.py` · `AuditoriaTests.test_intentos_fallidos…` |
| Sesión | expira a los 30 minutos sin actividad; cookie `HttpOnly`, `SameSite=Lax`, `Secure` en producción | `settings.py` |
| Cierre de sesión | por POST con token CSRF | `base.html` |
| Registro | inicios, cierres e intentos fallidos quedan en la bitácora (sin guardar la clave probada) | `signals.py` |

**Limitación conocida:** el contador de intentos vive en la memoria del proceso. Con varios procesos o servidores hay que usar una caché compartida (Redis o `DatabaseCache`) cambiando `CACHES`. No hay segundo factor (MFA): queda como mejora.

## 2. Autorización (¿qué puedes hacer?)

Principio de **mínimo privilegio**: un usuario sin rol no puede hacer nada (recibe 403). Los roles son grupos de Django y todas las reglas están en un único archivo, `permisos.py`.

| Capacidad | Administrador | Analista | Corredor | Auditor |
|---|:-:|:-:|:-:|:-:|
| Ver certificados, calificaciones y corredores | ✔ | ✔ | solo los suyos y los de la Bolsa | ✔ |
| Cargar/editar certificados (manual y masivo) | ✔ | ✔ | ✘ | ✘ |
| Eliminar certificados | ✔ | ✘ | ✘ | ✘ |
| Gestionar corredores | ✔ | ✘ | ✘ | ✘ |
| Calificar como **Bolsa** | ✔ | ✔ | ✘ | ✘ |
| Calificar como **Corredor** | ✔ | ✘ | solo certificados de su corredor | ✘ |
| Editar/eliminar calificaciones | todas | solo las de la Bolsa | solo las suyas | ✘ |
| Descargar PDF | ✔ | ✔ | solo los de su alcance (otro: 404) | ✔ |
| Ver la bitácora de auditoría | ✔ | ✘ | ✘ | ✔ |
| Administrar usuarios y roles | ✔ (panel `/admin/`) | ✘ | ✘ | ✘ |

Reglas de negocio reflejadas en el código:
- **La calificación del corredor tiene prioridad sobre la de la Bolsa** (`Certificado.calificacion_vigente`); la de la Bolsa nunca se borra al calificar el corredor.
- **Las modificaciones del corredor son locales:** un corredor solo califica certificados de su corredor y solo toca sus calificaciones (`permisos.py`, `forms.py`).

Se aplica en tres capas: (1) decorador `@requiere(...)` en cada vista, (2) filtros de datos (`certificados_visibles`), (3) botones ocultos en la interfaz. La interfaz es solo comodidad: la protección real está en las dos primeras. Pruebas: `RolesTests` (15 casos).

## 3. Amenazas y mitigaciones

| # | Amenaza | OWASP 2021 | Mitigación | Dónde / prueba |
|---|---|---|---|---|
| 1 | Un usuario accede a datos o acciones que no le corresponden | A01 | Roles, filtro por corredor, 403/404 en objetos ajenos; los intentos quedan en bitácora | `permisos.py` · `RolesTests` |
| 2 | Adivinar contraseñas por fuerza bruta | A07 | Bloqueo tras 5 intentos, clave larga, sesión corta | `login.py` · `AuditoriaTests` |
| 3 | Inyección SQL | A03 | Solo ORM de Django (consultas parametrizadas); no hay SQL escrito a mano en la aplicación | todo el código |
| 4 | XSS (código malicioso en un campo) | A03 | Plantillas con autoescape; no se usa `\|safe` | `templates/` |
| 5 | CSRF (otro sitio envía acciones con tu sesión) | A01 | `CsrfViewMiddleware`, token en cada formulario, borrar y salir solo por POST, `SameSite=Lax` | `settings.py`, `confirmarEliminar.html` |
| 6 | Subir un archivo malicioso | A04/A08 | Extensión `.pdf` + firma `%PDF-` real + máximo 10 MB + máximo 50 por carga; se guarda fuera de la carpeta pública y se entrega por una vista con permisos y `Content-Type` fijo; se leen como máximo 20 páginas | `validators.py`, `views.py` · `ArchivoTests`, `CargaMasivaTests` |
| 7 | Alterar o borrar la bitácora para ocultar acciones | A09 | Solo se agrega: `save`/`delete`/`update` bloqueados, panel admin de solo lectura y **hash encadenado** (cada fila incluye el hash de la anterior; `verificar_auditoria` detecta cambios o borrados) | `models.py` · `CadenaDeHashTests` |
| 8 | Filtración de datos tributarios | A02 | HTTPS obligatorio + HSTS + cookies seguras en producción; PDF en carpeta privada; contraseñas y claves por variables de entorno | `settings.py` |
| 9 | Mala configuración (modo debug en producción, claves en el código) | A05 | `DJANGO_DEBUG=0` exige `DJANGO_SECRET_KEY` y `DB_PASSWORD` o el sistema no arranca; `ALLOWED_HOSTS` explícito | `settings.py` |
| 10 | Incrustar el sistema en otra página (clickjacking) | A05 | `X_FRAME_OPTIONS = 'DENY'` | `settings.py` |
| 11 | Saturar el servidor con subidas gigantes | A05 | Límites de tamaño y de cantidad de archivos | `settings.py`, `forms.py` |
| 12 | Falsificar la IP en la bitácora | A09 | Se usa `REMOTE_ADDR`; solo detrás de nginx (`DJANGO_PROXY_CONFIABLE=1`) se usa `X-Real-IP`, que nginx reemplaza en cada petición y se valida como IP; nunca `X-Forwarded-For` | `auditoria.py` · `IpDeAuditoriaTests` |
| 13 | Librerías con vulnerabilidades | A06 | Versiones acotadas en `requirements.txt`; revisar con `pip-audit` antes de cada entrega | `requirements.txt` |

**Pendientes (no implementados, por honestidad):** cifrado en reposo de los PDF y de la base (se delega al disco/servidor de base de datos), antivirus sobre archivos subidos, segundo factor de autenticación, política de seguridad de contenido (CSP) y hashes de integridad (SRI) para los scripts de CDN. Quien borre las **últimas** filas de la bitácora no sería detectado por el encadenado solo: habría que copiar periódicamente el último hash a un lugar externo.

## 4. Estándares de codificación segura

1. **Nunca confiar en la entrada del usuario:** todo dato pasa por un formulario/validador de Django (RUT, año, monto, archivo) antes de guardarse.
2. **Consultas solo por ORM**, sin concatenar texto en SQL.
3. **Autorización en el servidor, siempre:** cada vista lleva `@login_required` + `@requiere(...)`; los permisos de objeto se revisan antes de actuar.
4. **Lo que no se puede ver, no se revela:** un certificado ajeno responde 404 (no 403), para no confirmar que existe.
5. **Secretos fuera del código:** claves y contraseñas por variables de entorno; el modo producción se niega a arrancar sin ellas.
6. **Acciones que cambian datos solo por POST** y con token CSRF.
7. **Salida escapada:** no desactivar el autoescape de las plantillas.
8. **Archivos subidos:** validar tipo real, tamaño y cantidad; nunca usar el nombre original como ruta (Django lo sanea); servirlos por una vista con permisos.
9. **Errores sin detalles internos:** `DEBUG=False` en producción; los errores técnicos van al log del servidor, no al usuario.
10. **Registro de lo importante** (altas, cambios, bajas, accesos, denegaciones) sin guardar contraseñas ni contenido sensible innecesario.
11. **Mínimo privilegio** también en la base de datos: el usuario MySQL de la aplicación solo tiene permisos sobre la base `nuam`.
12. **Un fallo en una función auxiliar no rompe la operación principal** (bitácora y MongoDB capturan sus errores y los registran en el log).
13. **Cada regla de seguridad tiene una prueba automática** que falla si alguien la rompe (`python manage.py test`).
14. **Revisión antes de entregar:** `ruff check .`, `python manage.py check --deploy` y `pip-audit`.

## 5. Variables de entorno (producción)

| Variable | Para qué |
|---|---|
| `DJANGO_DEBUG=0` | activa el modo seguro (HTTPS, cookies seguras, HSTS) |
| `DJANGO_SECRET_KEY` | clave secreta larga y aleatoria |
| `DJANGO_ALLOWED_HOSTS` | dominios permitidos, separados por coma |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | conexión a MySQL |
| `DB_SSL_CA` | ruta del certificado de AWS para conectar a RDS con TLS (cifrado en tránsito hacia la base) |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | direcciones desde las que se aceptan formularios (`https://dominio`) |
| `DJANGO_HTTPS` | `1` (por defecto) exige HTTPS; `0` solo para una demostración sin certificado |
| `DJANGO_PROXY_CONFIABLE` | `1` cuando hay nginx delante (la IP real llega en `X-Real-IP`) |
| `MONGO_URI`, `MONGO_DB` | MongoDB opcional |

Despliegue completo en AWS: [`DESPLIEGUE_AWS.md`](DESPLIEGUE_AWS.md).
