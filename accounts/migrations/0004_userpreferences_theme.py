from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_userpreferences'),
    ]

    operations = [
        migrations.AddField(
            model_name='userpreferences',
            name='theme',
            field=models.CharField(
                choices=[('dark', 'Dark'), ('midnight', 'Midnight'), ('ocean', 'Ocean')],
                default='dark',
                max_length=10,
            ),
        ),
    ]
