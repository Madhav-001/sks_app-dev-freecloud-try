from django.db import models


class PlatformChoices(models.TextChoices):
    ANDROID = 'ANDROID', 'Android'
    WEB = 'WEB', 'Web'


class NotificationPriority(models.TextChoices):
    LOW = 'LOW', 'Low'
    MEDIUM = 'MEDIUM', 'Medium'
    HIGH = 'HIGH', 'High'


class NotificationStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    SENT = 'SENT', 'Sent'
    FAILED = 'FAILED', 'Failed'


class NotificationType(models.TextChoices):
    ORDERS = 'orders', 'Orders'
    COLLECTIONS = 'collections', 'Collections'
    PAYMENTS = 'payments', 'Payments'
    CRM = 'crm', 'CRM'
    ATTENDANCE = 'attendance', 'Attendance'
    ANNOUNCEMENTS = 'announcements', 'Announcements'
    SYSTEM = 'system', 'System'
