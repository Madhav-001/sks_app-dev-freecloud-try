"""
Migration 0006:
  - Widen MonthlyTarget.id from max_length=7 to max_length=20
    to accommodate 'YYYY-MM-<employeeidnum>' individual target IDs.
  - Remove the UniqueConstraint 'unique_employee_monthly_target' on
    (employee, year, month) — uniqueness is now guaranteed by the PK itself.
  - Make MonthlyTarget.employee nullable (null=True, blank=True) to allow
    common targets (employee=None).
  - Make SpecialTarget.employee nullable for the same reason.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0005_alter_sales_target_to_tons'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # 1. Widen the MonthlyTarget PK to hold 'YYYY-MM-<employeeidnum>'
        migrations.AlterField(
            model_name='monthlytarget',
            name='id',
            field=models.CharField(
                primary_key=True,
                max_length=20,
                editable=False,
                serialize=False,
                help_text=(
                    "Auto-generated. 'YYYY-MM' for common (employee=null); "
                    "'YYYY-MM-<employeeidnum>' for individual targets."
                ),
            ),
        ),

        # 2. Remove the old unique constraint on (employee, year, month)
        #    The PK already enforces uniqueness — this constraint is redundant
        #    and conflicts with null-employee common targets.
        migrations.RemoveConstraint(
            model_name='monthlytarget',
            name='unique_employee_monthly_target',
        ),

        # 3. Make MonthlyTarget.employee nullable
        migrations.AlterField(
            model_name='monthlytarget',
            name='employee',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='monthly_targets',
                to=settings.AUTH_USER_MODEL,
                help_text=(
                    "Employee this target belongs to. "
                    "Null = common target for all employees."
                ),
            ),
        ),

        # 4. Make SpecialTarget.employee nullable for the same reason
        migrations.AlterField(
            model_name='specialtarget',
            name='employee',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='special_targets',
                to=settings.AUTH_USER_MODEL,
                help_text=(
                    "Employee this target belongs to. "
                    "Null = common special target for all employees."
                ),
            ),
        ),
    ]
