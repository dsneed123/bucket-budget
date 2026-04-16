from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('buckets', '0001_initial'),
        ('transactions', '0005_transaction_receipt'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='VendorMapping',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('vendor_name', models.CharField(max_length=100)),
                ('last_used', models.DateTimeField(auto_now=True)),
                ('bucket', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='vendor_mappings', to='buckets.bucket')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='vendor_mappings', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-last_used'],
                'unique_together': {('user', 'vendor_name')},
            },
        ),
    ]
