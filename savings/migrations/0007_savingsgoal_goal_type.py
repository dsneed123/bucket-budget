from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('savings', '0006_savingsgoal_is_private_share_uuid'),
    ]

    operations = [
        migrations.AddField(
            model_name='savingsgoal',
            name='goal_type',
            field=models.CharField(
                choices=[
                    ('general', 'General'),
                    ('emergency_fund', 'Emergency Fund'),
                    ('vacation', 'Vacation'),
                    ('purchase', 'Purchase'),
                    ('debt_payoff', 'Debt Payoff'),
                    ('investment', 'Investment'),
                    ('education', 'Education'),
                    ('other', 'Other'),
                ],
                default='general',
                max_length=20,
            ),
        ),
    ]
