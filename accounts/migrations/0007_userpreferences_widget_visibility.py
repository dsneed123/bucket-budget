from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0006_userpreferences_timezone'),
    ]

    operations = [
        migrations.AddField(
            model_name='userpreferences',
            name='widget_visibility',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
