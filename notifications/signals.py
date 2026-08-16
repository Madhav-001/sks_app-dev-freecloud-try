import logging
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.apps import apps
from django.utils import timezone
from notifications.services import NotificationService
from notifications.choices import NotificationType, NotificationPriority

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lazy Model Fetching Helpers to prevent circular imports
# ---------------------------------------------------------------------------
def get_employee_model():
    return apps.get_model('users', 'Employee')


def get_subdealer_model():
    return apps.get_model('dealers', 'SubDealer')


def get_attendance_model():
    return apps.get_model('tracking', 'Attendance')


def get_visit_model():
    return apps.get_model('tracking', 'Visit')


def get_order_model():
    return apps.get_model('sales', 'Order')


def get_collection_model():
    return apps.get_model('sales', 'Collection')


def get_lead_model():
    return apps.get_model('crm', 'Lead')


# ---------------------------------------------------------------------------
# Pre-save handlers to track state changes
# ---------------------------------------------------------------------------
@receiver(pre_save, sender='users.Employee')
def track_employee_pre_save(sender, instance, **kwargs):
    if instance.pk:
        try:
            old = sender.objects.get(pk=instance.pk)
            instance._old_is_active = old.is_active
            instance._old_is_deleted = old.is_deleted
            instance._old_password = old.password
            instance._old_phone = old.phone
            instance._old_email = old.email
            instance._old_address = old.address
        except sender.DoesNotExist:
            pass


@receiver(pre_save, sender='dealers.SubDealer')
def track_dealer_pre_save(sender, instance, **kwargs):
    if instance.pk:
        try:
            old = sender.objects.get(pk=instance.pk)
            instance._old_rank = old.rank
            instance._old_employee = old.employee
        except sender.DoesNotExist:
            pass


@receiver(pre_save, sender='tracking.Attendance')
def track_attendance_pre_save(sender, instance, **kwargs):
    if instance.pk:
        try:
            old = sender.objects.get(pk=instance.pk)
            instance._old_end_time = old.end_time
        except sender.DoesNotExist:
            pass


@receiver(pre_save, sender='sales.Order')
def track_order_pre_save(sender, instance, **kwargs):
    if instance.pk:
        try:
            old = sender.objects.get(pk=instance.pk)
            instance._old_status = old.status
        except sender.DoesNotExist:
            pass


@receiver(pre_save, sender='sales.Collection')
def track_collection_pre_save(sender, instance, **kwargs):
    if instance.pk:
        try:
            old = sender.objects.get(pk=instance.pk)
            instance._old_status = old.status
        except sender.DoesNotExist:
            pass


@receiver(pre_save, sender='crm.Lead')
def track_lead_pre_save(sender, instance, **kwargs):
    if instance.pk:
        try:
            old = sender.objects.get(pk=instance.pk)
            instance._old_employee = old.employee
            instance._old_category = old.category
        except sender.DoesNotExist:
            pass


# ---------------------------------------------------------------------------
# Post-save handlers to trigger notifications
# ---------------------------------------------------------------------------
@receiver(post_save, sender='users.Employee')
def handle_employee_saved(sender, instance, created, **kwargs):
    # 1. Auto-create preference on creation
    from notifications.models import NotificationPreference
    NotificationPreference.objects.get_or_create(user=instance)

    # 2. Employee Created
    if created:
        # Notify admins that a new employee was created
        NotificationService.broadcast(
            title="New Employee Created",
            body=f"Employee {instance.username} ({instance.role}) has been added.",
            notification_type=NotificationType.SYSTEM,
            sender=instance,
            priority=NotificationPriority.LOW,
            target_role="MANAGER"
        )
    else:
        # 3. Password Changed
        old_pwd = getattr(instance, '_old_password', None)
        if old_pwd and old_pwd != instance.password:
            NotificationService.send(
                recipient=instance,
                title="Password Changed",
                body="Your password has been changed successfully.",
                notification_type=NotificationType.SYSTEM,
                priority=NotificationPriority.HIGH
            )

        # 4. Profile Updated
        old_phone = getattr(instance, '_old_phone', None)
        old_email = getattr(instance, '_old_email', None)
        old_address = getattr(instance, '_old_address', None)
        if (old_phone and old_phone != instance.phone) or \
           (old_email and old_email != instance.email) or \
           (old_address and old_address != instance.address):
            NotificationService.send(
                recipient=instance,
                title="Profile Updated",
                body="Your profile details (phone, email, or address) were updated.",
                notification_type=NotificationType.SYSTEM,
                priority=NotificationPriority.LOW
            )

        # 5. User Activated / Deactivated
        old_active = getattr(instance, '_old_is_active', None)
        if old_active is not None and old_active != instance.is_active:
            title = "Account Activated" if instance.is_active else "Account Deactivated"
            body = "Your employee account has been activated." if instance.is_active else "Your employee account has been deactivated."
            NotificationService.send(
                recipient=instance,
                title=title,
                body=body,
                notification_type=NotificationType.SYSTEM,
                priority=NotificationPriority.HIGH
            )

        old_deleted = getattr(instance, '_old_is_deleted', None)
        if old_deleted is not None and old_deleted != instance.is_deleted and instance.is_deleted:
            # Soft deleted
            NotificationService.send(
                recipient=instance,
                title="Account Deactivated",
                body="Your employee account has been soft-deleted/deactivated.",
                notification_type=NotificationType.SYSTEM,
                priority=NotificationPriority.HIGH
            )


@receiver(post_save, sender='dealers.SubDealer')
def handle_dealer_saved(sender, instance, created, **kwargs):
    if created:
        # Dealer Created & Sub Dealer Created
        # Send to assigned employee
        NotificationService.send(
            recipient=instance.employee,
            title="New Dealer Assigned",
            body=f"Dealer shop '{instance.shop_name}' has been created and assigned to you.",
            notification_type=NotificationType.CRM,
            priority=NotificationPriority.MEDIUM
        )
        
        # Broadcast to managers
        NotificationService.broadcast(
            title="New Sub Dealer Created",
            body=f"New dealer '{instance.shop_name}' registered by {instance.employee.username}.",
            notification_type=NotificationType.CRM,
            target_role="MANAGER"
        )
    else:
        # Dealer Updated
        NotificationService.send(
            recipient=instance.employee,
            title="Dealer Profile Updated",
            body=f"The profile for dealer '{instance.shop_name}' has been updated.",
            notification_type=NotificationType.CRM,
            priority=NotificationPriority.LOW
        )

        # Dealer Approved (if rank changes or employee is assigned/reassigned)
        old_rank = getattr(instance, '_old_rank', None)
        if old_rank and old_rank != instance.rank:
            NotificationService.send(
                recipient=instance.employee,
                title="Dealer Approved / Rank Updated",
                body=f"Dealer '{instance.shop_name}' rank was updated from {old_rank} to {instance.rank}.",
                notification_type=NotificationType.CRM,
                priority=NotificationPriority.MEDIUM
            )


@receiver(post_save, sender='tracking.Attendance')
def handle_attendance_saved(sender, instance, created, **kwargs):
    if created:
        # Attendance Started
        NotificationService.send(
            recipient=instance.employee,
            title="Attendance Checked-In",
            body=f"Checked in successfully at {instance.start_time} (KM: {instance.start_km}).",
            notification_type=NotificationType.ATTENDANCE,
            priority=NotificationPriority.MEDIUM
        )
        # GPS Disabled check
        if instance.start_latitude is None or instance.start_longitude is None:
            NotificationService.send(
                recipient=instance.employee,
                title="GPS Disabled Alert",
                body="Your check-in was registered without GPS coordinates. Please enable location services.",
                notification_type=NotificationType.SYSTEM,
                priority=NotificationPriority.HIGH
            )
    else:
        # Attendance Closed
        old_end = getattr(instance, '_old_end_time', None)
        if old_end is None and instance.end_time is not None:
            NotificationService.send(
                recipient=instance.employee,
                title="Attendance Checked-Out",
                body=f"Checked out successfully at {instance.end_time}. Total KM: {instance.total_km}.",
                notification_type=NotificationType.ATTENDANCE,
                priority=NotificationPriority.MEDIUM
            )
            # GPS Disabled check
            if instance.end_latitude is None or instance.end_longitude is None:
                NotificationService.send(
                    recipient=instance.employee,
                    title="GPS Disabled Alert",
                    body="Your check-out was registered without GPS coordinates.",
                    notification_type=NotificationType.SYSTEM,
                    priority=NotificationPriority.HIGH
                )


@receiver(post_save, sender='tracking.Visit')
def handle_visit_saved(sender, instance, created, **kwargs):
    if created:
        # Visit Started & Visit Completed
        dealer_name = instance.dealer.shop_name if instance.dealer else "Client"
        NotificationService.send(
            recipient=instance.employee,
            title="Visit Registered",
            body=f"Visit to '{dealer_name}' successfully logged.",
            notification_type=NotificationType.ATTENDANCE,
            priority=NotificationPriority.LOW
        )

        # GPS Disabled Check
        if instance.latitude is None or instance.longitude is None:
            NotificationService.send(
                recipient=instance.employee,
                title="GPS Disabled Alert",
                body=f"Visit to '{dealer_name}' logged without GPS coordinates.",
                notification_type=NotificationType.SYSTEM,
                priority=NotificationPriority.HIGH
            )


@receiver(post_save, sender='sales.Order')
def handle_order_saved(sender, instance, created, **kwargs):
    if created:
        # Order Created
        NotificationService.send(
            recipient=instance.employee,
            title="Order Created",
            body=f"Order {str(instance.id)[:8]} for '{instance.sub_dealer.shop_name}' created (Total: {instance.total_amount}).",
            notification_type=NotificationType.ORDERS,
            priority=NotificationPriority.MEDIUM
        )
        
        # Broadcast to managers
        NotificationService.broadcast(
            title="New Sales Order",
            body=f"Order {str(instance.id)[:8]} placed by {instance.employee.username} for {instance.sub_dealer.shop_name}.",
            notification_type=NotificationType.ORDERS,
            target_role="MANAGER"
        )
    else:
        old_status = getattr(instance, '_old_status', None)
        if old_status and old_status != instance.status:
            # Order Cancelled
            if instance.status == 'cancelled':
                NotificationService.send(
                    recipient=instance.employee,
                    title="Order Cancelled",
                    body=f"Order {str(instance.id)[:8]} has been cancelled.",
                    notification_type=NotificationType.ORDERS,
                    priority=NotificationPriority.HIGH
                )
            # Order Approved (status changed from pending to paid/partially paid)
            elif old_status == 'pending' and instance.status in ['paid', 'partially_paid']:
                NotificationService.send(
                    recipient=instance.employee,
                    title="Order Approved & Processed",
                    body=f"Order {str(instance.id)[:8]} is now active. Status: {instance.status}.",
                    notification_type=NotificationType.ORDERS,
                    priority=NotificationPriority.MEDIUM
                )
                
                # Invoice Generated (simulation)
                NotificationService.send(
                    recipient=instance.employee,
                    title="Invoice Generated",
                    body=f"Invoice for Order {str(instance.id)[:8]} has been generated.",
                    notification_type=NotificationType.PAYMENTS,
                    priority=NotificationPriority.LOW,
                    payload={'order_id': str(instance.id)}
                )


@receiver(post_save, sender='sales.Collection')
def handle_collection_saved(sender, instance, created, **kwargs):
    if created:
        # Collection Added
        NotificationService.send(
            recipient=instance.employee,
            title="Collection Registered",
            body=f"Payment collection of {instance.amount} ({instance.payment_type}) pending verification.",
            notification_type=NotificationType.COLLECTIONS,
            priority=NotificationPriority.MEDIUM
        )
    else:
        old_status = getattr(instance, '_old_status', None)
        if old_status and old_status != instance.status:
            # Payment Received (Collection status becomes success)
            if instance.status == 'success':
                NotificationService.send(
                    recipient=instance.employee,
                    title="Collection Successful",
                    body=f"Payment of {instance.amount} from '{instance.sub_dealer.shop_name}' has been verified and processed.",
                    notification_type=NotificationType.PAYMENTS,
                    priority=NotificationPriority.HIGH
                )


@receiver(post_save, sender='crm.Lead')
def handle_lead_saved(sender, instance, created, **kwargs):
    if created:
        # Lead Assigned (Initial creator/assigned user)
        NotificationService.send(
            recipient=instance.employee,
            title="New Lead Assigned",
            body=f"Lead '{instance.name}' has been assigned to you.",
            notification_type=NotificationType.CRM,
            priority=NotificationPriority.MEDIUM
        )
    else:
        # Lead Assigned (change of employee)
        old_emp = getattr(instance, '_old_employee', None)
        if old_emp and old_emp != instance.employee:
            NotificationService.send(
                recipient=instance.employee,
                title="Lead Reassigned",
                body=f"Lead '{instance.name}' has been reassigned to you.",
                notification_type=NotificationType.CRM,
                priority=NotificationPriority.MEDIUM
            )

        # Lead Status Changed
        old_cat = getattr(instance, '_old_category', None)
        if old_cat and old_cat != instance.category:
            NotificationService.send(
                recipient=instance.employee,
                title="Lead Status Changed",
                body=f"Lead '{instance.name}' category changed from {old_cat} to {instance.category}.",
                notification_type=NotificationType.CRM,
                priority=NotificationPriority.LOW
            )
            
            # Lead Converted
            if instance.category == 'converted':
                NotificationService.send(
                    recipient=instance.employee,
                    title="Lead Converted Successfully",
                    body=f"Congratulations! Lead '{instance.name}' has been converted.",
                    notification_type=NotificationType.CRM,
                    priority=NotificationPriority.HIGH
                )
