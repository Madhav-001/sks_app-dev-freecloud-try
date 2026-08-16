from django.contrib import admin
from django.contrib import messages
from notifications.models import Notification, Device, NotificationPreference
from notifications.services import NotificationService


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "recipient",
        "sender",
        "title",
        "notification_type",
        "priority",
        "status",
        "is_read",
        "created_at",
    )
    list_filter = (
        "notification_type",
        "priority",
        "status",
        "is_read",
        "created_at",
    )
    search_fields = (
        "title",
        "body",
        "recipient__username",
        "recipient__name",
        "sender__username",
    )
    readonly_fields = ("created_at", "updated_at", "read_at")
    ordering = ("-created_at",)

    # Custom action to trigger broadcast sending from admin list view
    actions = ["mark_as_read_bulk"]

    def mark_as_read_bulk(self, request, queryset):
        rows_updated = queryset.update(is_read=True)
        if rows_updated == 1:
            message_bit = "1 notification was"
        else:
            message_bit = f"{rows_updated} notifications were"
        self.message_user(request, f"{message_bit} successfully marked as read.")

    mark_as_read_bulk.short_description = "Mark selected notifications as read"


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "platform",
        "device_name",
        "app_version",
        "active",
        "last_seen",
    )
    list_filter = ("platform", "active", "last_seen")
    search_fields = ("device_name", "device_id", "user__username", "user__name")
    ordering = ("-last_seen",)


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "orders",
        "collections",
        "payments",
        "crm",
        "attendance",
        "announcements",
        "system",
        "updated_at",
    )
    list_filter = (
        "orders",
        "collections",
        "payments",
        "crm",
        "attendance",
        "announcements",
        "system",
    )
    search_fields = ("user__username", "user__name")
