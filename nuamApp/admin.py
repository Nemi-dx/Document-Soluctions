from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin

from nuamApp.models import Auditoria, Calificacion, Certificado, Corredor, Perfil

admin.site.site_header = 'Administración – NUAM'
admin.site.site_title = 'NUAM'
admin.site.index_title = 'Corredores, certificados y calificaciones'


class CorredorAdmin(admin.ModelAdmin):
  list_display = ['nombre', 'pais', 'activo']
  list_filter = ['pais', 'activo']
  search_fields = ['nombre']


class CertificadoAdmin(admin.ModelAdmin):
  list_display = ['rut', 'nombre_contribuyente', 'ejercicio', 'tipo', 'monto', 'corredor', 'estado']
  list_filter = ['estado', 'tipo', 'ejercicio', 'corredor']
  search_fields = ['rut', 'nombre_contribuyente']


class CalificacionAdmin(admin.ModelAdmin):
  list_display = ['certificado', 'origen', 'corredor', 'calificacion', 'fecha']
  list_filter = ['origen']


class PerfilInline(admin.StackedInline):
  """Permite asignar el corredor al crear o editar un usuario (obligatorio para el rol Corredor)."""
  model = Perfil
  can_delete = False


class UsuarioAdmin(UserAdmin):
  inlines = [PerfilInline]


class AuditoriaAdmin(admin.ModelAdmin):
  """La bitácora es de solo lectura incluso aquí: nadie puede agregar, editar ni borrar filas."""
  list_display = ['fecha', 'usuario', 'rol', 'accion', 'modelo', 'objeto']
  list_filter = ['accion', 'rol']
  search_fields = ['usuario', 'objeto']

  def has_add_permission(self, request):
    return False

  def has_change_permission(self, request, obj=None):
    return False

  def has_delete_permission(self, request, obj=None):
    return False


# Registrar los modelos en el admin
admin.site.register(Corredor, CorredorAdmin)
admin.site.register(Certificado, CertificadoAdmin)
admin.site.register(Calificacion, CalificacionAdmin)
admin.site.register(Auditoria, AuditoriaAdmin)

Usuario = get_user_model()
admin.site.unregister(Usuario)
admin.site.register(Usuario, UsuarioAdmin)
