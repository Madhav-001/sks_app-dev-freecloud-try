from django.db import models


class NotificationQuerySet(models.QuerySet):

    def unread(self):
        return self.filter(is_read=False)

    def read(self):
        return self.filter(is_read=True)

    def mark_all_as_read(self):
        from django.utils import timezone
        return self.update(is_read=True, read_at=timezone.now())


class NotificationManager(models.Manager):

    def get_queryset(self):
        return NotificationQuerySet(self.model, using=self._db)

    def unread(self):
        return self.get_queryset().unread()

    def read(self):
        return self.get_queryset().read()
