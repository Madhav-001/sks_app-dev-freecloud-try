from django.db import transaction
from django.utils import timezone
from notifications.models import Notification, Device, NotificationPreference
from notifications.choices import NotificationStatus, NotificationPriority


class NotificationRepository:

    @staticmethod
    def get_by_id(notification_id, recipient=None):
        queryset = Notification.objects.all()
        if recipient:
            queryset = queryset.filter(recipient=recipient)
        return queryset.filter(id=notification_id).first()

    @staticmethod
    def create(recipient, title, body, notification_type, sender=None, priority='MEDIUM', payload=None, status='PENDING'):
        if payload is None:
            payload = {}
        return Notification.objects.create(
            recipient=recipient,
            sender=sender,
            title=title,
            body=body,
            notification_type=notification_type,
            priority=priority,
            status=status,
            payload=payload
        )

    @staticmethod
    def bulk_create(notifications_data):
        objs = [Notification(**data) for data in notifications_data]
        return Notification.objects.bulk_create(objs)

    @staticmethod
    def mark_as_read(notification):
        notification.is_read = True
        notification.read_at = timezone.now()
        notification.save(update_fields=['is_read', 'read_at'])
        return notification

    @staticmethod
    def mark_all_read_for_user(user):
        return Notification.objects.filter(recipient=user, is_read=False).update(
            is_read=True,
            read_at=timezone.now()
        )

    @staticmethod
    def delete(notification):
        notification.delete()


import time
from django.db.utils import OperationalError


class DeviceRepository:

    @staticmethod
    def get_by_user_and_device(user, device_id):
        return Device.objects.filter(user=user, device_id=device_id).first()

    @staticmethod
    def register_device(user, platform, device_id, device_name, app_version, push_token=None):
        max_retries = 3
        for attempt in range(max_retries):
            try:
                device, created = Device.objects.update_or_create(
                    user=user,
                    device_id=device_id,
                    defaults={
                        'platform': platform,
                        'device_name': device_name,
                        'app_version': app_version,
                        'push_token': push_token,
                        'active': True,
                        'last_seen': timezone.now()
                    }
                )
                return device
            except OperationalError as exc:
                if "locked" in str(exc).lower() and attempt < max_retries - 1:
                    time.sleep(0.2 * (attempt + 1))
                    continue
                raise

    @staticmethod
    def deactivate_device(user, device_id):
        return Device.objects.filter(user=user, device_id=device_id).update(active=False)

    @staticmethod
    def get_active_tokens_for_user(user):
        return list(
            Device.objects.filter(user=user, active=True, push_token__isnull=False)
            .exclude(push_token="")
            .values_list('push_token', flat=True)
        )


class PreferenceRepository:

    @staticmethod
    def get_for_user(user):
        # Auto-create preferences if not exists
        prefs, created = NotificationPreference.objects.get_or_create(user=user)
        return prefs

    @staticmethod
    def update_preferences(user, **preferences):
        prefs = PreferenceRepository.get_for_user(user)
        for key, value in preferences.items():
            if hasattr(prefs, key):
                setattr(prefs, key, value)
        prefs.save()
        return prefs
