from django.core.exceptions import ValidationError
from notifications.choices import PlatformChoices


def validate_platform(value):
    if value not in PlatformChoices.values:
        raise ValidationError(f"'{value}' is not a valid platform choice. Allowed: {PlatformChoices.values}")
