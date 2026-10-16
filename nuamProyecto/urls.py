"""
URLs del proyecto NUAM.

Igual que en empleadosProyecto: cada ruta apunta a una función de views.py.
La diferencia es que ahora todas tienen un name="..." para poder enlazarlas
desde las plantillas con {% url 'nombre' %}.
"""
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from nuamApp import views as nuam
from nuamApp.login import FormularioLogin

urlpatterns = [
    path('admin/', admin.site.urls),

    # Sesión
    path('ingresar/', auth_views.LoginView.as_view(authentication_form=FormularioLogin), name='login'),
    path('salir/', auth_views.LogoutView.as_view(), name='logout'),

    # Inicio
    path('', nuam.inicio, name='inicio'),

    # Corredores
    path('corredores/', nuam.corredorData, name='corredores'),
    path('corredores/nuevo/', nuam.corredorRegistro, name='corredor_nuevo'),
    path('corredores/<int:id>/editar/', nuam.corredorEditar, name='corredor_editar'),
    path('corredores/<int:id>/eliminar/', nuam.corredorEliminar, name='corredor_eliminar'),

    # Certificados
    path('certificados/', nuam.certificadoData, name='certificados'),
    path('certificados/nuevo/', nuam.certificadoRegistro, name='certificado_nuevo'),
    path('certificados/carga/', nuam.certificadoCarga, name='certificado_carga'),
    path('certificados/<int:id>/editar/', nuam.certificadoEditar, name='certificado_editar'),
    path('certificados/<int:id>/eliminar/', nuam.certificadoEliminar, name='certificado_eliminar'),
    path('certificados/<int:id>/archivo/', nuam.certificadoArchivo, name='certificado_archivo'),

    # Calificaciones
    path('calificaciones/', nuam.calificacionData, name='calificaciones'),
    path('calificaciones/nuevo/', nuam.calificacionRegistro, name='calificacion_nuevo'),
    path('calificaciones/<int:id>/editar/', nuam.calificacionEditar, name='calificacion_editar'),
    path('calificaciones/<int:id>/eliminar/', nuam.calificacionEliminar, name='calificacion_eliminar'),

    # Auditoría
    path('auditoria/', nuam.auditoriaData, name='auditoria'),
]
