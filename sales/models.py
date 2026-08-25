import uuid
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Sum
from users.models import Employee
from dealers.models import SubDealer


class SoftDeleteQuerySet(models.QuerySet):
    def delete(self):
        return super().update(is_deleted=True)

    def alive(self):
        return self.filter(is_deleted=False)


class SoftDeleteManager(models.Manager):
    def get_queryset(self):
        return SoftDeleteQuerySet(self.model).filter(is_deleted=False)

    def all_with_deleted(self):
        return SoftDeleteQuerySet(self.model)


class SoftDeleteModelMixin(models.Model):
    """
    Abstract mixin that adds soft-delete behaviour to any model.

    Fields
    ------
    is_deleted : BooleanField
        Flag set to True when the record is soft-deleted.

    Methods
    -------
    delete(using=None, keep_parents=False)
        Marks the record as deleted in-place instead of issuing a SQL DELETE.
        Returns (1, {"soft_deleted": 1}) to mirror Django's hard-delete return
        value so existing call-sites don't need to change.

    Usage
    -----
    class MyModel(SoftDeleteModelMixin, models.Model):
        objects = SoftDeleteManager()
        ...
    """

    is_deleted = models.BooleanField(default=False)

    class Meta:
        abstract = True

    def delete(self, using=None, keep_parents=False):
        self.is_deleted = True
        self.save(update_fields=["is_deleted"])
        return (1, {"soft_deleted": 1})


class Product(SoftDeleteModelMixin, models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)

    objects = SoftDeleteManager()

    unit = models.CharField(max_length=50)
    image = models.ImageField(upload_to="products/", null=True, blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["name"])]

    def __str__(self):
        return self.name


class Order(SoftDeleteModelMixin, models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approve", "Approve"),
        ("in_transit", "In-transit"),
        ("delivered", "Delivered"),
        ("rejected", "Rejected"),
    ]

    objects = SoftDeleteManager()

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sub_dealer = models.ForeignKey(
        SubDealer, on_delete=models.CASCADE, related_name="orders"
    )
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="orders"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["sub_dealer", "employee", "status"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"Order {self.id} - {self.sub_dealer.shop_name}"

    @property
    def collected_amount(self):
        from decimal import Decimal
        return (
            self.collections.filter(status="success").aggregate(total=Sum("amount"))[
                "total"
            ]
            or Decimal('0.00')
        )

    @property
    def total_quantity(self):
        """Total count of all products across order items (e.g. 10 steels + 20 fire steels = 30)."""
        return self.items.aggregate(total=Sum("quantity"))["total"] or 0

    @property
    def due_amount(self):
        return self.total_amount - self.collected_amount

    def update_status(self):
        collected = self.collected_amount
        if collected == 0:
            self.status = "pending"
        elif collected < self.total_amount:
            self.status = "partially_paid"
        else:
            self.status = "paid"
        self.save(update_fields=["status"])


class OrderItem(SoftDeleteModelMixin, models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items", null=True, blank=True)

    objects = SoftDeleteManager()

    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.IntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["order"]),
            models.Index(fields=["product"]),
        ]


class Collection(SoftDeleteModelMixin, models.Model):
    PAYMENT_TYPE_CHOICES = [
        ("cash", "Cash"),
        ("bank", "Bank"),
        ("upi", "UPI"),
    ]
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("success", "Success"),
        ("failed", "Failed"),
    ]
    AMOUNT_TYPE_CHOICES = [
        ("C", "Crore"),
        ("L", "Lakh"),
        ("T", "Thousand"),
    ]

    objects = SoftDeleteManager()

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sub_dealer = models.ForeignKey(
        SubDealer, on_delete=models.CASCADE, related_name="collections"
    )
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="collections"
    )
    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name="collections", null=True, blank=True
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_type = models.CharField(max_length=20, choices=PAYMENT_TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    reference_id = models.CharField(
        max_length=100, choices=AMOUNT_TYPE_CHOICES, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["order"]),
            models.Index(fields=["status"]),
            models.Index(fields=["created_at"]),
        ]


class MonthlyTarget(models.Model):
    """
    Standard monthly KPI target for a sales employee.
    Enforces exactly one target per employee per month/year.
    """
    id = models.CharField(
        primary_key=True,
        max_length=7,
        editable=False,
        help_text="Target ID in 'YYYY-MM' format (e.g. '2026-08')"
    )
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="monthly_targets",
        help_text="The sales employee this target is assigned to"
    )
    year = models.PositiveIntegerField(
        validators=[MinValueValidator(2020), MaxValueValidator(2100)],
        help_text="Target year (e.g. 2026)"
    )
    month = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(12)],
        help_text="Target month (1 to 12)"
    )

    sales_target = models.DecimalField(
        max_digits=14, decimal_places=2, default=0.00,
        help_text="Target sales amount in currency"
    )
    collection_target = models.DecimalField(
        max_digits=14, decimal_places=2, default=0.00,
        help_text="Target collection amount in currency"
    )
    visits_target = models.PositiveIntegerField(
        default=0,
        help_text="Target dealer/subdealer visits count"
    )

    target_setby = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="set_monthly_targets",
        help_text="Admin who set or last updated this target"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "year", "month"],
                name="unique_employee_monthly_target"
            )
        ]
        indexes = [
            models.Index(fields=["employee", "year", "month"]),
            models.Index(fields=["year", "month"]),
        ]
        ordering = ["-year", "-month"]

    def save(self, *args, **kwargs):
        if not self.id and self.year and self.month:
            self.id = f"{int(self.year):04d}-{int(self.month):02d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.employee.username} - {self.month}/{self.year} Target"


class SpecialTarget(models.Model):
    """
    Ad-hoc / Campaign / Festive / Sprint target for specific date ranges.
    Can overlap with regular monthly targets.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="special_targets",
        help_text="The sales employee this target is assigned to"
    )
    title = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Campaign name e.g., 'Diwali Sprint 2026'"
    )
    from_date = models.DateField(help_text="Target duration start date")
    to_date = models.DateField(help_text="Target duration end date")

    sales_target = models.DecimalField(
        max_digits=14, decimal_places=2, default=0.00,
        help_text="Target sales amount in currency"
    )
    collection_target = models.DecimalField(
        max_digits=14, decimal_places=2, default=0.00,
        help_text="Target collection amount in currency"
    )
    visits_target = models.PositiveIntegerField(
        default=0,
        help_text="Target dealer/subdealer visits count"
    )

    target_setby = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="set_special_targets",
        help_text="Admin who set or last updated this target"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["employee", "from_date", "to_date"]),
            models.Index(fields=["from_date", "to_date"]),
        ]
        ordering = ["-from_date"]

    def __str__(self):
        return f"{self.employee.username} - Special Target ({self.from_date} to {self.to_date})"

