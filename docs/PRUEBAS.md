# Plan de pruebas de NUAM

## 1. Estrategia

| Tipo | Qué comprueba | Cómo | Cantidad |
|---|---|---|---|
| **Unitarias** | funciones aisladas: RUT, extractor de PDF, roles, hash encadenado, IP de la bitácora | automatizadas (`tests.py`) | 24 |
| **Integrales** | vistas completas con sesión, base de datos, permisos por rol, auditoría, carga de archivos, MongoDB simulado | automatizadas (Django test client) | 49 |
| **Rendimiento** | consultas por página sin crecer con los datos (sin N+1), tiempos con 300 certificados, 200 registros de auditoría, 20 PDF reales | automatizadas (`RendimientoTests`) + carga concurrente con Locust | 5 + Locust |
| **Manuales** | lo que un humano debe ver: pantallas, mensajes, flujo completo por rol | casos de la sección 4 | 14 |

Total automatizado: **78 pruebas** (`nuamApp/tests.py`).

## 2. Herramientas

| Herramienta | Tipo | Uso |
|---|---|---|
| `python manage.py test` | automatizada | ejecuta las 78 pruebas con una base temporal (`test_nuam`, que el script `crear_base_mysql.sql` ya autoriza) |
| `DB_ENGINE=sqlite python manage.py test` | automatizada | versión rápida sin MySQL (Windows: `set DB_ENGINE=sqlite` antes) |
| `ruff check .` | automatizada | errores de código y nombres sin definir |
| `python manage.py check --deploy` | automatizada | revisa la configuración de seguridad |
| **Locust** (`docs/locustfile.py`) | automatizada | usuarios simultáneos navegando el sistema |
| Navegador + lista de casos | manual | sección 4 |

## 3. Cómo ejecutar

```bash
# Pruebas automatizadas (todas)
python manage.py test

# Una clase o una prueba
python manage.py test nuamApp.tests.RolesTests
python manage.py test nuamApp.tests.RendimientoTests

# Con más detalle
python manage.py test -v 2

# Prueba de carga con 20 usuarios durante 1 minuto (instalar locust antes: pip install locust)
python manage.py cargar_demo
locust -f docs/locustfile.py --host http://127.0.0.1:8000 --users 20 --spawn-rate 5 --run-time 1m --headless
```

### Qué cubre cada clase de pruebas

| Clase | Casos | Cubre |
|---|---:|---|
| `RutTests` | 5 | validación y normalización del RUT, dígito K |
| `ExtractorTests` | 7 | lectura de los campos, variantes de etiquetas, montos, campos faltantes, PDF real y PDF dañado |
| `IpDeAuditoriaTests` | 3 | la IP de la bitácora no se falsifica con cabeceras (solo con proxy de confianza) |
| `PermisosUnitariosTests` | 5 | resolución del rol y matriz de capacidades |
| `CadenaDeHashTests` | 4 | cadena íntegra; detecta fila alterada o borrada; bitácora inmodificable |
| `SinSesionTests` | 1 | todas las páginas exigen login |
| `ConSesionTests` | 14 | CRUD completo, RUT inválido, duplicados, borrado protegido, prioridad corredor/Bolsa |
| `RolesTests` | 15 | qué puede y qué no puede cada rol, alcance por corredor, PDF ajeno, calificaciones locales |
| `AuditoriaTests` | 7 | altas/cambios/bajas registrados, login/logout, bloqueo por intentos |
| `ArchivoTests` | 4 | subida de PDF, rechazo de archivos falsos, descarga con sesión |
| `CargaMasivaTests` | 8 | extracción desde PDF real, un error no detiene a los demás, límite de 50, MongoDB simulado y su caída |
| `RendimientoTests` | 5 | sin consultas extra por fila, tiempos con volumen |

## 4. Pruebas manuales

Preparación: `python manage.py migrate`, `python manage.py cargar_demo` (crea los usuarios `demo_admin`, `demo_analista`, `demo_corredor`, `demo_auditor`, clave `Demo-Nuam-2026!`) y `python manage.py runserver`. Marcar el resultado obtenido con ✔ o ✘ y anotar la fecha y quién probó.

| ID | Rol | Pasos | Resultado esperado | Obtenido |
|---|---|---|---|:-:|
| M-01 | — | Abrir `/` sin iniciar sesión | Redirige a la pantalla de ingreso | ☐ |
| M-02 | — | Ingresar con clave incorrecta 5 veces y luego con la correcta | Al sexto intento aparece «Demasiados intentos fallidos» aunque la clave sea correcta | ☐ |
| M-03 | Analista | Ingresar y abrir *Carga masiva*; subir 3 PDF de certificado (uno repetido y un `.txt` renombrado a `.pdf`) | Resultado por archivo: los válidos «Procesado», el repetido «Ya existe…», el falso «no es un PDF válido»; ninguno detiene a los otros | ☐ |
| M-04 | Analista | Abrir *Certificados* y revisar un certificado procesado | Aparece con estado Procesado, datos correctos y botón para ver el PDF | ☐ |
| M-05 | Analista | Editar el certificado y cambiar su estado a Validado | Se guarda y el estado cambia en la tabla | ☐ |
| M-06 | Analista | Intentar entrar a `/certificados/<id>/eliminar/` escribiendo la dirección | Pantalla «No tienes permiso para esto» | ☐ |
| M-07 | Corredor | Ingresar y abrir *Certificados* | Solo ve certificados de su corredor y de la Bolsa | ☐ |
| M-08 | Corredor | Crear una calificación sobre un certificado de su corredor | Se guarda con origen Corredor y su nombre de corredor | ☐ |
| M-09 | Corredor | Intentar editar una calificación de la Bolsa | No aparece el botón Editar; por dirección directa, 403 | ☐ |
| M-10 | Auditor | Ingresar y recorrer todas las pantallas | Solo lectura: no hay botones de agregar, editar ni eliminar | ☐ |
| M-11 | Auditor | Abrir *Auditoría* y pulsar «Verificar integridad» | «Cadena íntegra…» en verde | ☐ |
| M-12 | Administrador | Crear, editar y eliminar un corredor sin certificados | Las tres acciones aparecen en *Auditoría* con usuario y hora | ☐ |
| M-13 | Administrador | Intentar eliminar un corredor que tiene certificados | Mensaje «No se puede eliminar: tiene registros asociados» | ☐ |
| M-14 | Todos | Abrir el sistema desde un celular o reducir la ventana | El menú se contrae y las tablas siguen usables (diseño adaptable) | ☐ |

**Prueba de manipulación de la bitácora (opcional, demostración):** en la base de datos ejecutar `UPDATE nuamApp_auditoria SET usuario='otro' WHERE id=1;` y luego `python manage.py verificar_auditoria`. Debe responder «¡Cadena rota! Primer registro dañado: #1».

## 5. Registro de resultados (completar al ejecutar)

| Fecha | Quién | Comando | Resultado | Observaciones |
|---|---|---|---|---|
| ____ | ____ | `python manage.py test` | ___ pruebas, ___ errores | |
| ____ | ____ | Locust 20 usuarios / 1 min | ___ peticiones, ___ fallos, mediana ___ ms | |
| ____ | ____ | Casos manuales M-01 a M-14 | ___ ✔ / ___ ✘ | |

## 6. Criterios de aceptación de rendimiento

- Con 300 certificados, el listado responde en menos de 3 segundos y el número de consultas a la base **no depende** de la cantidad de filas.
- Verificar 200 registros de auditoría toma menos de 5 segundos.
- Procesar 20 PDF reales en una carga masiva toma menos de 20 segundos.
- Locust: 0 % de errores 5xx con 20 usuarios simultáneos.
