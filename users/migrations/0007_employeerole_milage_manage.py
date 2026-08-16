"""
0007_employeerole_milage_manage.py
------------------------------------
- Adds `milage_manage` BooleanField to EmployeeRole.
- Sets True for SENIOR_MANAGER and MANAGER (they already manage all tracking data).
- All other built-in roles default to False (including SYSADMIN, ACCOUNTANT, etc.).
- OWNER is never stored in the DB; full access is always granted in code.
"""

from django.db import migrations, models


def set_milage_manage_defaults(apps, schema_editor):
    """
    Grant milage_manage=True to SENIOR_MANAGER and MANAGER by default.
    All other roles stay False (column default).
    """
    EmployeeRole = apps.get_model('users', 'EmployeeRole')
    EmployeeRole.objects.filter(name__in=["SENIOR_MANAGER", "MANAGER"]).update(
        milage_manage=True
    )


def revert_milage_manage(apps, schema_editor):
    pass  # Reverting just removes the column; no data restoration needed.


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0006_employeerole'),
    ]

    operations = [
        # Add the new column with default=False
        migrations.AddField(
            model_name='employeerole',
            name='milage_manage',
            field=models.BooleanField(
                default=False,
                help_text='Allow this role to view mileage details of all employees.',
            ),
        ),

        # Seed sensible defaults for existing built-in roles
        migrations.RunPython(set_milage_manage_defaults, reverse_code=revert_milage_manage),
    ]
