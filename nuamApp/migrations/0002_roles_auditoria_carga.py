import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('nuamApp', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='calificacion',
            name='corredor',
            field=models.ForeignKey(blank=True, editable=False, help_text='Corredor que hizo la calificación (solo si el origen es Corredor).', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='calificaciones', to='nuamApp.corredor'),
        ),
        migrations.AddField(
            model_name='certificado',
            name='datos_extraidos',
            field=models.JSONField(blank=True, default=dict, editable=False, help_text='Documento JSON (sin esquema fijo) con lo que la extracción automática leyó del PDF.', verbose_name='datos extraídos del PDF'),
        ),
        migrations.AlterField(
            model_name='certificado',
            name='estado',
            field=models.CharField(choices=[('PENDIENTE', 'Pendiente'), ('PROCESADO', 'Procesado'), ('VALIDADO', 'Validado'), ('RECHAZADO', 'Rechazado')], default='PENDIENTE', max_length=10),
        ),
        migrations.CreateModel(
            name='Perfil',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('corredor', models.ForeignKey(blank=True, help_text='Obligatorio para usuarios con el rol Corredor.', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='usuarios', to='nuamApp.corredor')),
                ('usuario', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='perfil', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='Auditoria',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fecha', models.DateTimeField()),
                ('usuario', models.CharField(help_text='Nombre de usuario (se conserva aunque el usuario se elimine).', max_length=150)),
                ('rol', models.CharField(blank=True, max_length=20)),
                ('accion', models.CharField(choices=[('LOGIN', 'Inicio de sesión'), ('LOGIN_FALLIDO', 'Intento de acceso fallido'), ('LOGOUT', 'Cierre de sesión'), ('CREAR', 'Creación'), ('MODIFICAR', 'Modificación'), ('ELIMINAR', 'Eliminación'), ('CARGA', 'Carga de certificado'), ('DESCARGA', 'Descarga de PDF'), ('ACCESO_DENEGADO', 'Acceso denegado')], max_length=20)),
                ('modelo', models.CharField(blank=True, max_length=40)),
                ('objeto_id', models.CharField(blank=True, max_length=40)),
                ('objeto', models.CharField(blank=True, max_length=200)),
                ('detalle', models.JSONField(blank=True, default=dict)),
                ('ip', models.GenericIPAddressField(blank=True, null=True)),
                ('hash_anterior', models.CharField(blank=True, max_length=64)),
                ('hash', models.CharField(editable=False, max_length=64)),
            ],
            options={
                'verbose_name': 'registro de auditoría',
                'verbose_name_plural': 'registros de auditoría',
                'ordering': ['-id'],
            },
        ),
    ]
