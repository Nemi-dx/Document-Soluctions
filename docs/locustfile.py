"""
Prueba de carga con Locust (usuarios simultáneos navegando NUAM).

Uso (con el servidor corriendo y `python manage.py cargar_demo` ejecutado):
    pip install locust
    locust -f docs/locustfile.py --host http://127.0.0.1:8000 --users 20 --spawn-rate 5 --run-time 1m --headless
O sin --headless para ver el panel en http://localhost:8089
"""
import re

from locust import HttpUser, between, task


class AnalistaTributario(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        # Entrar: se lee el token CSRF de la pantalla de ingreso y se envía junto con las credenciales
        pagina = self.client.get('/ingresar/')
        token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', pagina.text).group(1)
        self.client.post('/ingresar/', {
            'username': 'demo_analista', 'password': 'Demo-Nuam-2026!', 'csrfmiddlewaretoken': token,
        }, headers={'Referer': self.host + '/ingresar/'})

    @task(5)
    def ver_certificados(self):
        self.client.get('/certificados/')

    @task(3)
    def ver_calificaciones(self):
        self.client.get('/calificaciones/')

    @task(2)
    def ver_inicio(self):
        self.client.get('/')

    @task(1)
    def ver_corredores(self):
        self.client.get('/corredores/')
