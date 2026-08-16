# Generated for MonthlyTarget model
import uuid
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("sales", "0002_remove_order_additional_field"),
    ]

    operations = [
        migrations.CreateModel(
            name="MonthlyTarget",
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
                ("year", models.PositiveIntegerField()),
                (
                    "month",
                    models.PositiveSmallIntegerField(help_text="Month number (1-12)"),
                ),
                (
                    "sales_target",
                    models.DecimalField(decimal_places=2, default=0.0, max_digits=12),
                ),
                (
                    "collection_target",
                    models.DecimalField(decimal_places=2, default=0.0, max_digits=12),
                ),
                ("visit_target", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "employee",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="monthly_targets",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-year", "-month"],
                "indexes": [
                    models.Index(
                        fields=["employee", "year", "month"],
                        name="sales_month_employe_9cb475_idx",
                    )
                ],
                "unique_together": {("employee", "year", "month")},
            },
        ),
    ]
