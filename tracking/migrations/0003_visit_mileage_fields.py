"""
0003_visit_mileage_fields.py
-----------------------------
- Adds `attendance_id` (FK → Attendance) and `travelled_km` to the Visit table.
- Creates the Milage table with all fields (including new `date` field and
  unique_together constraint on employee + date).
"""

import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tracking", "0002_attendance_auto_checkout"),
    ]

    operations = [
        # ------------------------------------------------------------------
        # Visit — add attendance_id FK
        # ------------------------------------------------------------------
        migrations.AddField(
            model_name="visit",
            name="attendance_id",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="visits",
                to="tracking.attendance",
            ),
        ),
        # ------------------------------------------------------------------
        # Visit — add travelled_km (auto-calculated, nullable)
        # ------------------------------------------------------------------
        migrations.AddField(
            model_name="visit",
            name="travelled_km",
            field=models.FloatField(blank=True, null=True),
        ),
        # ------------------------------------------------------------------
        # Create Milage table
        # ------------------------------------------------------------------
        migrations.CreateModel(
            name="Milage",
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
                ("date", models.DateField()),
                (
                    "return_to_home",
                    models.FloatField(
                        blank=True,
                        null=True,
                        default=0.0,
                        help_text="Distance from last visited place to check-out location.",
                    ),
                ),
                (
                    "total_distance_travelled",
                    models.FloatField(
                        default=0.0,
                        help_text="Cumulative distance for the day, updated in real-time.",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "employee",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="milage_records",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "attendance_id",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="milage",
                        to="tracking.attendance",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(fields=["employee", "date"], name="tracking_milage_emp_date_idx"),
                ],
            },
        ),
        # ------------------------------------------------------------------
        # Milage — unique_together (one record per employee per day)
        # ------------------------------------------------------------------
        migrations.AlterUniqueTogether(
            name="milage",
            unique_together={("employee", "date")},
        ),
    ]
