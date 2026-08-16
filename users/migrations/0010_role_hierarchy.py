# Hand-written migration 2026-08-02
# - Adds `hierarchy_level` IntegerField to EmployeeRole
# - Seeds the OWNER built-in role row (previously code-only, no DB row)
# - Backfills hierarchy_level for every existing built-in role

from django.db import migrations, models


# (name, hierarchy_level)  — OWNER gets level 1; same-tier roles share a level
ROLE_LEVELS = {
    "OWNER":           1,
    "SENIOR_MANAGER":  2,
    "MANAGER":         3,
    "SYSADMIN":        4,
    "ACCOUNTANT":      5,
    "SALESMAN":        6,
    "EMPLOYEE":        6,
    "WATCHMAN":        6,
    "DRIVER":          6,
}


def add_hierarchy_level_and_owner(apps, schema_editor):
    EmployeeRole = apps.get_model("users", "EmployeeRole")

    # 1. Backfill hierarchy_level for all existing built-in roles
    for role in EmployeeRole.objects.filter(is_builtin=True):
        role.hierarchy_level = ROLE_LEVELS.get(role.name, 99)
        role.save(update_fields=["hierarchy_level"])

    # 2. Upsert the OWNER built-in role row
    #    All permission booleans are True for OWNER.
    EmployeeRole.objects.update_or_create(
        name="OWNER",
        defaults=dict(
            display_name="Owner",
            is_builtin=True,
            hierarchy_level=1,
            employee_manage=True,
            dealers_manage=True,
            products_manage=True,
            collection_manage=True,
            orders_manage=True,
            attendance_manage=True,
            visit_manage=True,
            leads_manage=True,
            milage_manage=True,
        ),
    )


def reverse_add_hierarchy(apps, schema_editor):
    EmployeeRole = apps.get_model("users", "EmployeeRole")
    # Remove the OWNER row that we added
    EmployeeRole.objects.filter(name="OWNER", is_builtin=True).delete()
    # Reset hierarchy_level to 99 for everyone (field still exists after reverse)
    EmployeeRole.objects.update(hierarchy_level=99)


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0009_remove_owner_role"),
    ]

    operations = [
        # 1. Add the new field (default=99 means "unknown / lowest priority")
        migrations.AddField(
            model_name="employeerole",
            name="hierarchy_level",
            field=models.PositiveSmallIntegerField(
                default=99,
                help_text=(
                    "Hierarchy rank. 1 = Owner (highest authority). "
                    "Higher number = lower authority. "
                    "Used to enforce that managers can only manage roles below them."
                ),
            ),
        ),
        # 2. Seed OWNER row + backfill levels for existing built-in roles
        migrations.RunPython(
            add_hierarchy_level_and_owner,
            reverse_code=reverse_add_hierarchy,
        ),
    ]
