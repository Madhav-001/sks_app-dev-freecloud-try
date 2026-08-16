# Generated for Attendance targets and VisitPlan model
import uuid
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("tracking", "0003_visit_mileage_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="attendance",
            name="daily_sales_target",
            field=models.DecimalField(
                blank=True, decimal_places=2, default=0.0, max_digits=12, null=True
            ),
        ),
        migrations.AddField(
            model_name="attendance",
            name="daily_collection_target",
            field=models.DecimalField(
                blank=True, decimal_places=2, default=0.0, max_digits=12, null=True
            ),
        ),
        migrations.AddField(
            model_name="attendance",
            name="daily_visit_target",
            field=models.PositiveIntegerField(blank=True, default=0, null=True),
        ),
        migrations.AddField(
            model_name="attendance",
            name="today_visit_plan",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="VisitPlan",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("plan_date", models.DateField()),
                ("area", models.CharField(max_length=255)),
                ("visit_target", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "employee",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="visit_plans",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-plan_date"],
                "indexes": [
                    models.Index(
                        fields=["employee", "plan_date"],
                        name="tracking_vi_employe_b2c4e1_idx",
                    )
                ],
                "unique_together": {("employee", "plan_date")},
            },
        ),
    ]
