from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0009_userpreferences_no_spend_goal'),
    ]

    operations = [
        migrations.AddField(
            model_name='userpreferences',
            name='onboarding_complete',
            field=models.BooleanField(default=False),
        ),
    ]
