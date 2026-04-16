from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0008_userstreak'),
    ]

    operations = [
        migrations.AddField(
            model_name='userpreferences',
            name='no_spend_goal',
            field=models.IntegerField(default=0),
        ),
    ]
