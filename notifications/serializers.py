from rest_framework import serializers
from notifications.models import Notification, Device, NotificationPreference
from notifications.choices import PlatformChoices, NotificationType, NotificationPriority
from django.contrib.auth import get_user_model

User = get_user_model()


class NotificationSerializer(serializers.ModelSerializer):
    recipient_username = serializers.CharField(source='recipient.username', read_only=True)
    sender_username = serializers.CharField(source='sender.username', read_only=True, allow_null=True)

    class Meta:
        model = Notification
        fields = [
            'id', 'recipient', 'recipient_username', 'sender', 'sender_username',
            'title', 'body', 'notification_type', 'priority', 'status',
            'payload', 'is_read', 'read_at', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'recipient', 'sender', 'title', 'body', 'notification_type',
            'priority', 'status', 'payload', 'is_read', 'read_at', 'created_at', 'updated_at'
        ]


class DeviceRegisterSerializer(serializers.Serializer):
    platform = serializers.ChoiceField(choices=PlatformChoices.choices)
    device_id = serializers.CharField(max_length=255)
    device_name = serializers.CharField(max_length=255)
    app_version = serializers.CharField(max_length=50)
    push_token = serializers.CharField(max_length=512, required=False, allow_blank=True, allow_null=True)


class DeviceRemoveSerializer(serializers.Serializer):
    device_id = serializers.CharField(max_length=255)


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = [
            'orders', 'collections', 'payments', 'crm',
            'attendance', 'announcements', 'system'
        ]


class BroadcastSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    body = serializers.CharField()
    notification_type = serializers.ChoiceField(choices=NotificationType.choices, default=NotificationType.SYSTEM)
    priority = serializers.ChoiceField(choices=NotificationPriority.choices, default=NotificationPriority.MEDIUM)
    payload = serializers.JSONField(required=False, default=dict)
    
    # Broadcast targets
    target_role = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    target_dealer = serializers.UUIDField(required=False, allow_null=True)
    target_employee = serializers.UUIDField(required=False, allow_null=True)
    target_region = serializers.CharField(required=False, allow_blank=True, allow_null=True)
