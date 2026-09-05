# Generated manually — changes sales_target to decimal_places=3 on both
# MonthlyTarget and SpecialTarget to represent weight in tons (e.g. 1.250 ton).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0004_alter_monthlytarget_id"),
    ]

    operations = [
        migrations.AlterField(
            model_name="monthlytarget",
            name="sales_target",
            field=models.DecimalField(
                decimal_places=3,
                default=0.0,
                help_text="Target sales weight in tons (e.g. 1.250 = 1 ton 250 kg)",
                max_digits=14,
            ),
        ),
        migrations.AlterField(
            model_name="specialtarget",
            name="sales_target",
            field=models.DecimalField(
                decimal_places=3,
                default=0.0,
                help_text="Target sales weight in tons (e.g. 1.250 = 1 ton 250 kg)",
                max_digits=14,
            ),
        ),
    ]
