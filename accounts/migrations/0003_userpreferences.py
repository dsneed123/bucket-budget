from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_customuser_zero_based_budgeting'),
        ('banking', '0002_add_balance_history'),
    ]

    operations = [
        migrations.CreateModel(
            name='UserPreferences',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('email_weekly_digest', models.BooleanField(default=True)),
                ('email_budget_alerts', models.BooleanField(default=True)),
                ('email_goal_achieved', models.BooleanField(default=True)),
                ('start_of_week', models.CharField(
                    choices=[
                        ('monday', 'Monday'),
                        ('tuesday', 'Tuesday'),
                        ('wednesday', 'Wednesday'),
                        ('thursday', 'Thursday'),
                        ('friday', 'Friday'),
                        ('saturday', 'Saturday'),
                        ('sunday', 'Sunday'),
                    ],
                    default='monday',
                    max_length=10,
                )),
                ('fiscal_month_start', models.IntegerField(default=1)),
                ('user', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='preferences',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('default_account', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='+',
                    to='banking.bankaccount',
                )),
            ],
        ),
    ]
