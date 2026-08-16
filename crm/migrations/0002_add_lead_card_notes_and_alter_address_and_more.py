import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crm', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='lead',
            name='card',
            field=models.ImageField(blank=True, null=True, upload_to='lead_cards/'),
        ),
        migrations.AddField(
            model_name='lead',
            name='notes',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='leads',
                to='communication.note',
            ),
        ),
        migrations.AlterField(
            model_name='lead',
            name='address',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AlterField(
            model_name='lead',
            name='company_name',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AlterField(
            model_name='lead',
            name='email',
            field=models.EmailField(blank=True, default='', max_length=254),
        ),
        migrations.AlterField(
            model_name='lead',
            name='rank',
            field=models.CharField(blank=True, choices=[('a', 'A'), ('b', 'B'), ('c', 'C')], default='', max_length=5),
        ),
    ]
