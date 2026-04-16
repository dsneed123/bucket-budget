from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('budget', '0002_monthlybudgetallocation'),
    ]

    operations = [
        migrations.AddField(
            model_name='budgetsummary',
            name='notes',
            field=models.TextField(blank=True, default=''),
        ),
    ]
