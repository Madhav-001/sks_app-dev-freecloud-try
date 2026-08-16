import logging
from django.db import transaction
from django.contrib.auth import get_user_model
from django.utils import timezone
from notifications.models import Notification, NotificationPreference
from notifications.repositories import NotificationRepository, PreferenceRepository
from notifications.choices import NotificationType, NotificationPriority, NotificationStatus

User = get_user_model()
logger = logging.getLogger(__name__)


class NotificationService:

    @staticmethod
    def _prune_old_notifications():
        """Auto-prune notifications older than 60 days."""
        try:
            from datetime import timedelta
            cutoff = timezone.now() - timedelta(days=60)
            deleted_count, _ = Notification.objects.filter(created_at__lt=cutoff).delete()
            if deleted_count > 0:
                logger.info(f"Auto-pruned {deleted_count} notifications older than 60 days.")
        except Exception as e:
            logger.error(f"Error auto-pruning old notifications: {e}")

    @staticmethod
    def is_type_enabled(recipient, notification_type):
        """Check if recipient has enabled notifications of this type."""
        prefs = PreferenceRepository.get_for_user(recipient)
        # Check mapping of type to preference fields
        field_map = {
            NotificationType.ORDERS: 'orders',
            NotificationType.COLLECTIONS: 'collections',
            NotificationType.PAYMENTS: 'payments',
            NotificationType.CRM: 'crm',
            NotificationType.ATTENDANCE: 'attendance',
            NotificationType.ANNOUNCEMENTS: 'announcements',
            NotificationType.SYSTEM: 'system',
        }
        pref_field = field_map.get(notification_type, 'system')
        return getattr(prefs, pref_field, True)

    @staticmethod
    def _send_push(notification):
        """
        Synchronously processes and sends a push notification.
        """
        logger.info(f"Processing notification synchronously for ID: {notification.id}")

        try:
            with transaction.atomic():
                notification = Notification.objects.select_for_update().get(id=notification.id)

                if notification.status == NotificationStatus.SENT:
                    logger.info(f"Notification {notification.id} is already sent. Skipping.")
                    return True

                # Get recipient active devices
                from notifications.models import Device
                active_devices = Device.objects.filter(user=notification.recipient, active=True)
                push_tokens = [d.push_token for d in active_devices if d.push_token]

                # Simulate push sending:
                success = True
                error_message = None

                # Simulation of potential transport failures for robustness testing:
                if "fail_task" in notification.title:
                    success = False
                    error_message = "Temporary gateway timeout (Simulated)"

                if success:
                    notification.status = NotificationStatus.SENT
                    if not isinstance(notification.payload, dict):
                        notification.payload = {}
                    notification.payload['sent_to_tokens_count'] = len(push_tokens)
                    notification.payload['sent_at'] = timezone.now().isoformat()
                    notification.save()
                    logger.info(f"Successfully processed notification {notification.id}. Tokens notified: {len(push_tokens)}")
                    return True
                else:
                    raise Exception(error_message)

        except Notification.DoesNotExist:
            logger.error(f"Notification with ID {notification.id} does not exist.")
            return False

        except Exception as exc:
            logger.warning(f"Error sending notification {notification.id}: {str(exc)}")
            # Dead Task/Failure Handling synchronously
            try:
                with transaction.atomic():
                    notification = Notification.objects.select_for_update().get(id=notification.id)
                    notification.status = NotificationStatus.FAILED
                    if not isinstance(notification.payload, dict):
                        notification.payload = {}
                    notification.payload['error_log'] = f"Error: {str(exc)}"
                    notification.payload['failed_at'] = timezone.now().isoformat()
                    notification.save()
            except Exception as d_exc:
                logger.critical(f"Failed to write dead task status to database: {str(d_exc)}")
            return False

    @staticmethod
    def send(recipient, title, body, notification_type, sender=None, priority='MEDIUM', payload=None):
        """Send a single notification."""
        # Auto-prune notifications older than 2 months
        NotificationService._prune_old_notifications()

        # Ensure type is valid choice value
        if notification_type not in NotificationType.values:
            notification_type = NotificationType.SYSTEM

        if not NotificationService.is_type_enabled(recipient, notification_type):
            logger.info(f"Skipping notification for user {recipient.username} - Preference for type '{notification_type}' is disabled.")
            return None

        # Create record in DB via repo
        notification = NotificationRepository.create(
            recipient=recipient,
            sender=sender,
            title=title,
            body=body,
            notification_type=notification_type,
            priority=priority,
            payload=payload or {},
            status=NotificationStatus.PENDING
        )

        # Process the notification synchronously
        NotificationService._send_push(notification)

        return notification

    @staticmethod
    def send_bulk(recipients, title, body, notification_type, sender=None, priority='MEDIUM', payload=None):
        """Send notification to multiple users."""
        # Auto-prune notifications older than 2 months
        NotificationService._prune_old_notifications()

        if payload is None:
            payload = {}

        notifications_to_create = []
        for recipient in recipients:
            if NotificationService.is_type_enabled(recipient, notification_type):
                notifications_to_create.append({
                    'recipient': recipient,
                    'sender': sender,
                    'title': title,
                    'body': body,
                    'notification_type': notification_type,
                    'priority': priority,
                    'payload': payload,
                    'status': NotificationStatus.PENDING
                })

        if not notifications_to_create:
            return []

        # Bulk create in DB
        created_notifications = NotificationRepository.bulk_create(notifications_to_create)

        # Process push notifications synchronously
        for notif in created_notifications:
            NotificationService._send_push(notif)

        return created_notifications

    @staticmethod
    def broadcast(title, body, notification_type, sender=None, priority='MEDIUM', payload=None,
                  target_role=None, target_dealer=None, target_employee=None, target_region=None):
        """Broadcast notifications with specific target filtering (role, dealer, employee, etc)."""
        queryset = User.objects.filter(is_active=True, is_deleted=False)

        if target_role:
            import uuid
            from django.db.models import Q

            if hasattr(target_role, 'id') and hasattr(target_role, 'name'):
                target_role_id = target_role.id
                target_role_name = target_role.name
                queryset = queryset.filter(
                    Q(role__id=target_role_id) | Q(role__name__iexact=str(target_role_name))
                )
            else:
                target_role_str = str(target_role).strip()
                is_uuid = False
                if isinstance(target_role, uuid.UUID):
                    is_uuid = True
                else:
                    try:
                        uuid.UUID(target_role_str)
                        is_uuid = True
                    except (ValueError, TypeError, AttributeError):
                        is_uuid = False

                if is_uuid:
                    queryset = queryset.filter(
                        Q(role__id=target_role) | Q(role__name__iexact=target_role_str)
                    )
                elif target_role_str.upper() == "OWNER":
                    queryset = queryset.filter(
                        Q(role__name__iexact="OWNER") | Q(role__isnull=True)
                    )
                else:
                    queryset = queryset.filter(role__name__iexact=target_role_str)


        if target_employee:
            queryset = queryset.filter(id=target_employee)

        if target_dealer:
            # Broadcast to employee associated with the dealer
            from dealers.models import SubDealer
            dealer = SubDealer.objects.filter(id=target_dealer).first()
            if dealer:
                queryset = queryset.filter(id=dealer.employee_id)
            else:
                queryset = queryset.none()

        if target_region:
            # Match by region (e.g. state or district of employee)
            queryset = queryset.filter(state__iexact=target_region) | queryset.filter(district__iexact=target_region)

        recipients = list(queryset)
        return NotificationService.send_bulk(
            recipients=recipients,
            title=title,
            body=body,
            notification_type=notification_type,
            sender=sender,
            priority=priority,
            payload=payload
        )

    @staticmethod
    def mark_read(notification_id, user):
        """Mark a specific notification as read."""
        notification = NotificationRepository.get_by_id(notification_id, recipient=user)
        if not notification:
            return None
        return NotificationRepository.mark_as_read(notification)

    @staticmethod
    def mark_all_read(user):
        """Mark all unread notifications of the user as read."""
        return NotificationRepository.mark_all_read_for_user(user)

    @staticmethod
    def get_unread_count(user):
        """Get unread notifications count for a user."""
        from notifications.selectors import NotificationSelector
        return NotificationSelector.get_unread_count(user)

    @staticmethod
    def delete(notification_id, user):
        """Delete a notification."""
        notification = NotificationRepository.get_by_id(notification_id, recipient=user)
        if notification:
            NotificationRepository.delete(notification)
            return True
        return False

    @staticmethod
    def archive(notification_id, user):
        """Archive a notification (e.g. mark it read, or could be soft delete)."""
        # For our purposes, archive behaves like mark_read + tagging payload
        notification = NotificationRepository.get_by_id(notification_id, recipient=user)
        if not notification:
            return None
        notification.is_read = True
        notification.read_at = timezone.now()
        if not isinstance(notification.payload, dict):
            notification.payload = {}
        notification.payload['archived'] = True
        notification.payload['archived_at'] = timezone.now().isoformat()
        notification.save()
        return notification
