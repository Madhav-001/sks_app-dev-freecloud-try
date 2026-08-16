import uuid
from django.db import models
from users.models import Employee


class Attendance(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE)
    date = models.DateField()

    start_km = models.FloatField()
    start_image = models.ImageField(upload_to="attendance/start/")
    start_location = models.CharField(max_length=255, null=True, blank=True)
    start_latitude = models.FloatField(null=True, blank=True)
    start_longitude = models.FloatField(null=True, blank=True)
    start_time = models.TimeField(null=True, blank=True)

    work_now = models.BooleanField(default=True)

    end_km = models.FloatField(null=True, blank=True)
    end_image = models.ImageField(upload_to="attendance/end/", null=True, blank=True)
    end_location = models.CharField(max_length=255, null=True, blank=True)
    end_latitude = models.FloatField(null=True, blank=True)
    end_longitude = models.FloatField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)

    total_km = models.FloatField(null=True, blank=True)
    total_time = models.DurationField(null=True, blank=True)
    auto_checkout = models.BooleanField(default=False)

    # Daily targets entered during check-in
    daily_sales_target = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, default=0.00)
    daily_collection_target = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, default=0.00)
    daily_visit_target = models.PositiveIntegerField(null=True, blank=True, default=0)
    today_visit_plan = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["employee", "created_at"])]



class Visit(models.Model):
    TYPE_CHOICES = [("Dealer", "Dealer"), ("Client", "Client")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    dealer = models.ForeignKey(
        "dealers.SubDealer",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="dealer_visits",
    )
    client = models.ForeignKey(
        "dealers.SubDealer",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="client_visits",
    )
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default="Dealer")
    gps_image = models.ImageField(upload_to="visits/images/")
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    time = models.TimeField(null=True, blank=True)
    collection = models.ForeignKey(
        "sales.Collection",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="visit_collection",
    )
    order = models.ForeignKey(
        "sales.Order",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="visit_order",
    )
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE)
    attendance_id = models.ForeignKey(
        Attendance,
        on_delete=models.CASCADE,
        related_name="visits",
        null=True,
        blank=True,
    )
    # Auto-calculated via distance_service — never supplied by the user.
    travelled_km = models.FloatField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["dealer", "employee", "created_at"])]


class Milage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="milage_records")
    attendance_id = models.ForeignKey(
        Attendance,
        on_delete=models.CASCADE,
        related_name="milage",
        null=True,
        blank=True,
    )
    date = models.DateField()
    return_to_home = models.FloatField(null=False, blank=False, default=0.0)
    total_distance_travelled = models.FloatField(default=0.0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # One record per employee per working day.
        unique_together = [("employee", "date")]
        indexes = [models.Index(fields=["employee", "date"])]


class VisitPlan(models.Model):
    """
    Tomorrow's / planned visit plan for an employee.
    Unique per employee + plan_date.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="visit_plans"
    )
    plan_date = models.DateField()
    area = models.CharField(max_length=255)
    visit_target = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("employee", "plan_date")]
        indexes = [models.Index(fields=["employee", "plan_date"])]
        ordering = ["-plan_date"]

    def __str__(self):
        return f"VisitPlan {self.employee.username} on {self.plan_date} ({self.area})"

