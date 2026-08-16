# Generated manually on 2026-07-18

from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0004_alter_employee_email'),
    ]

    operations = [
        migrations.CreateModel(
            name='EmployeeAccessControl',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('employee_create', models.BooleanField(default=False)),
                ('employee_update', models.BooleanField(default=False)),
                ('employee_delete', models.BooleanField(default=False)),
                ('dealers_create', models.BooleanField(default=False)),
                ('dealers_update', models.BooleanField(default=False)),
                ('dealers_delete', models.BooleanField(default=False)),
                ('products_create', models.BooleanField(default=False)),
                ('products_update', models.BooleanField(default=False)),
                ('products_enable_disable', models.BooleanField(default=False)),
                ('collection_edit', models.BooleanField(default=False)),
                ('collection_update', models.BooleanField(default=False)),
                ('collection_approve_reject', models.BooleanField(default=False)),
                ('orders_edit', models.BooleanField(default=False)),
                ('orders_update', models.BooleanField(default=False)),
                ('orders_approve_reject', models.BooleanField(default=False)),
                ('attendance_edit', models.BooleanField(default=False)),
                ('attendance_update', models.BooleanField(default=False)),
                ('attendance_approve_reject', models.BooleanField(default=False)),
                ('visit_edit', models.BooleanField(default=False)),
                ('visit_update', models.BooleanField(default=False)),
                ('visit_approve_reject', models.BooleanField(default=False)),
                ('leads_delete', models.BooleanField(default=False)),
                ('leads_convert', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('employee', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='access_control', to='users.employee')),
            ],
        ),
    ]
