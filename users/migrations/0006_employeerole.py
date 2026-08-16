# Hand-written migration 2026-07-19
# - Drops EmployeeAccessControl table (from 0005)
# - Removes choices constraint on Employee.role
# - Creates EmployeeRole table
# - Seeds built-in roles with sensible defaults
# NOTE: OWNER is NOT seeded — it is a special system role handled entirely in
#       code (RoleBasedPermission always grants full access to OWNER without
#       any DB lookup). Nobody can modify OWNER's access level.

from django.db import migrations, models
import uuid


BUILTIN_ROLES = [
    # (name,              display_name,      emp,   deal,  prod,  coll,  ord,   att,   vis,   lead)
    ("SENIOR_MANAGER", "Senior Manager",   True,  True,  True,  True,  True,  True,  True,  True),
    ("MANAGER",        "Manager",          True,  True,  True,  True,  True,  True,  True,  True),
    ("SYSADMIN",       "Sys-Admin",        True,  False, True,  True,  False, False, True,  False),
    ("ACCOUNTANT",     "Accountant",       False, False, False, True,  True,  False, False, True),
    ("SALESMAN",       "Salesman",         False, False, False, False, False, False, False, False),
    ("DRIVER",         "Driver",           False, False, False, False, False, False, False, False),
    ("WATCHMAN",       "Watchman",         False, False, False, False, False, False, False, False),
    ("EMPLOYEE",       "Employee",         False, False, False, False, False, False, False, False),
]


def seed_roles(apps, schema_editor):
    EmployeeRole = apps.get_model('users', 'EmployeeRole')
    for (name, display_name, emp, deal, prod, coll, ord_, att, vis, lead) in BUILTIN_ROLES:
        EmployeeRole.objects.get_or_create(
            name=name,
            defaults=dict(
                display_name=display_name,
                is_builtin=True,
                employee_manage=emp,
                dealers_manage=deal,
                products_manage=prod,
                collection_manage=coll,
                orders_manage=ord_,
                attendance_manage=att,
                visit_manage=vis,
                leads_manage=lead,
            )
        )


def unseed_roles(apps, schema_editor):
    EmployeeRole = apps.get_model('users', 'EmployeeRole')
    EmployeeRole.objects.filter(is_builtin=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0005_employeeaccesscontrol'),
    ]

    operations = [
        # 1. Drop old per-employee access control table
        migrations.DeleteModel(
            name='EmployeeAccessControl',
        ),

        # 2. Remove choices constraint on Employee.role, extend max_length to 50
        migrations.AlterField(
            model_name='employee',
            name='role',
            field=models.CharField(
                default='EMPLOYEE',
                help_text="Must match an EmployeeRole.name (e.g. 'MANAGER', 'SALESMAN', or a custom role name).",
                max_length=50,
                verbose_name='Role',
            ),
        ),

        # 3. Create new EmployeeRole table
        migrations.CreateModel(
            name='EmployeeRole',
            fields=[
                ('id',           models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name',         models.CharField(max_length=50, unique=True, help_text="Internal key, e.g. 'MANAGER'")),
                ('display_name', models.CharField(max_length=100, help_text="Human-readable label")),
                ('is_builtin',   models.BooleanField(default=False)),
                ('employee_manage',   models.BooleanField(default=False)),
                ('dealers_manage',    models.BooleanField(default=False)),
                ('products_manage',   models.BooleanField(default=False)),
                ('collection_manage', models.BooleanField(default=False)),
                ('orders_manage',     models.BooleanField(default=False)),
                ('attendance_manage', models.BooleanField(default=False)),
                ('visit_manage',      models.BooleanField(default=False)),
                ('leads_manage',      models.BooleanField(default=False)),
                ('created_at',   models.DateTimeField(auto_now_add=True)),
                ('updated_at',   models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Employee Role',
                'verbose_name_plural': 'Employee Roles',
                'ordering': ['name'],
            },
        ),

        # 4. Seed built-in roles
        migrations.RunPython(seed_roles, reverse_code=unseed_roles),
    ]
