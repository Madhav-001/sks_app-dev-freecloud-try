import uuid
from django.core.exceptions import ValidationError
from django.db import models


def default_categories():
    return ["note"]


def validate_note_categories(value):
    if not isinstance(value, list):
        raise ValidationError("Categories must be a list.")
    valid_keys = {
        "payment",
        "followup",
        "urgent",
        "payment-reminder",
        "complaint",
        "order",
        "invoice",
        "note",
    }
    for item in value:
        if item not in valid_keys:
            raise ValidationError(f"'{item}' is not a valid category. Valid choices: {', '.join(sorted(valid_keys))}")


class Note(models.Model):
    CATEGORIES = [
        ("payment", "Payment"),
        ("followup", "Followup"),
        ("urgent", "Urgent"),
        ("payment-reminder", "Payment Reminder"),
        ("complaint", "Complaint"),
        ("order", "Order"),
        ("invoice", "Invoice"),
        ("note", "Note"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee = models.ForeignKey(
        "users.Employee", on_delete=models.CASCADE, related_name="owned_notes"
    )
    title = models.CharField(max_length=255, blank=True, null=True)
    content = models.TextField()
    image = models.ImageField(upload_to='notes/', blank=True, null=True)
    categories = models.JSONField(
        default=default_categories, 
        blank=True,
        validators=[validate_note_categories]
    )
    shared_to = models.ManyToManyField(
        "users.Employee", blank=True, related_name="shared_notes"
    )
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    archive = models.BooleanField(default=False)
    pinned = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Message(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sender = models.ForeignKey(
        "users.Employee", related_name="sent_messages", on_delete=models.CASCADE
    )
    receiver = models.ForeignKey(
        "users.Employee", related_name="received_messages", on_delete=models.CASCADE
    )
    message = models.TextField()

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


