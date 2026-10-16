from django.core.management.base import BaseCommand, CommandError

from nuamApp.models import Auditoria


class Command(BaseCommand):
  help = 'Recorre la bitácora de auditoría y comprueba que la cadena de hashes no fue alterada.'

  def handle(self, *args, **opciones):
    dañado = Auditoria.verificar_cadena()
    if dañado is not None:
      raise CommandError(f'¡Cadena rota! Primer registro dañado: #{dañado}')
    self.stdout.write(self.style.SUCCESS(f'Bitácora íntegra ({Auditoria.objects.count()} registros).'))
