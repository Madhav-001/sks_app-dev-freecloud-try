from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('communication', '0002_note_categories_image_title_delete'),
    ]

    operations = [
        migrations.DeleteModel(
            name='Notification',
        ),
    ]
