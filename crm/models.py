import uuid
from django.db import models


class Lead(models.Model):
    CATEGORY_CHOICES = (
        ("customer", "Customer"),
        ("supplier", "Supplier"),
        ("dealer", "Dealer"),
        ("lead", "Lead"),
        ("new", "New"),
        ("contacted", "Contacted"),
        ("interested", "Interested"),
        ("qualified", "Qualified"),
        ("converted", "Converted"),
        ("lost", "Lost"),
    )
    RANK_CHOICES = (
        ("a", "A"),
        ("b", "B"),
        ("c", "C"),
    )
    SOURCE_CHOICES = (
        ("website", "Website"),
        ("referral", "Referral"),
        ("ads", "Ads"),
        ("cold_call", "Cold Call"),
        ("social_media", "Social Media"),
        ("other", "Other"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=15)
    company_name = models.CharField(max_length=255, blank=True, default='')
    email = models.EmailField(blank=True, default='')
    address = models.TextField(blank=True, default='')
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES)
    card = models.ImageField(upload_to='lead_cards/', blank=True, null=True)
    notes = models.ForeignKey(
        "communication.Note", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="leads"
    )
    employee = models.ForeignKey("users.Employee", on_delete=models.CASCADE, related_name="lead_employee")
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    rank = models.CharField(max_length=5, choices=RANK_CHOICES, blank=True, default='')

    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        "users.Employee", on_delete=models.SET_NULL, null=True, related_name="lead_deleted_by"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Customer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=15)
    email = models.EmailField()
    address = models.TextField()
    lead = models.ForeignKey(Lead, on_delete=models.SET_NULL, null=True)

    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        "users.Employee", on_delete=models.SET_NULL, null=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
