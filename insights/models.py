from django.conf import settings
from django.db import models


class Recommendation(models.Model):
    PRIORITY_LOW = 'low'
    PRIORITY_MEDIUM = 'medium'
    PRIORITY_HIGH = 'high'
    PRIORITY_CHOICES = [
        (PRIORITY_LOW, 'Low'),
        (PRIORITY_MEDIUM, 'Medium'),
        (PRIORITY_HIGH, 'High'),
    ]

    CATEGORY_BUDGET = 'budget'
    CATEGORY_SAVINGS = 'savings'
    CATEGORY_QUALITY = 'quality'
    CATEGORY_VENDOR = 'vendor'
    CATEGORY_CHOICES = [
        (CATEGORY_BUDGET, 'Budget'),
        (CATEGORY_SAVINGS, 'Savings'),
        (CATEGORY_QUALITY, 'Quality'),
        (CATEGORY_VENDOR, 'Vendor'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='recommendations',
    )
    message = models.TextField()
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default=PRIORITY_MEDIUM)
    is_dismissed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Recommendation({self.user_id}, {self.category}, {self.priority})'
