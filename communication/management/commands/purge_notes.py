from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from communication.models import Note

class Command(BaseCommand):
    help = 'Permanently delete soft-deleted notes older than 30 days.'

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=30)
        deleted_count, _ = Note.objects.filter(is_deleted=True, deleted_at__lt=cutoff).delete()
        self.stdout.write(self.style.SUCCESS(f'Successfully purged {deleted_count} expired notes.'))
