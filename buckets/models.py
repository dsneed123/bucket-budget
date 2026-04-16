from django.conf import settings
from django.db import models


class Bucket(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='buckets')
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    monthly_allocation = models.DecimalField(max_digits=10, decimal_places=2)
    color = models.CharField(max_length=7, default='#0984e3')
    icon = models.CharField(max_length=10, default='💰')
    sort_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
