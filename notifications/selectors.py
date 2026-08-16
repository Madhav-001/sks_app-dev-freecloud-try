from notifications.models import Notification, Device, NotificationPreference


class NotificationSelector:

    @staticmethod
    def get_user_notifications(user):
        return Notification.objects.filter(recipient=user).select_related('recipient', 'sender')

    @staticmethod
    def get_unread_notifications(user):
        return Notification.objects.filter(recipient=user, is_read=False).select_related('recipient', 'sender')

    @staticmethod
    def get_unread_count(user):
        return Notification.objects.filter(recipient=user, is_read=False).count()

    @staticmethod
    def list_devices_for_user(user):
        return Device.objects.filter(user=user)
