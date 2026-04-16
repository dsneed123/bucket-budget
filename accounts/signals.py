from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import CustomUser

DEFAULT_BUCKETS = [
    {'name': 'Essentials',      'icon': '🏠', 'color': '#00d4aa', 'monthly_allocation': 0},
    {'name': 'Transportation',  'icon': '🚗', 'color': '#0984e3', 'monthly_allocation': 0},
    {'name': 'Food & Dining',   'icon': '🍽️', 'color': '#f9ca24', 'monthly_allocation': 0},
    {'name': 'Entertainment',   'icon': '🎬', 'color': '#e056fd', 'monthly_allocation': 0},
    {'name': 'Health',          'icon': '💪', 'color': '#ff4757', 'monthly_allocation': 0},
    {'name': 'Shopping',        'icon': '🛍️', 'color': '#fd79a8', 'monthly_allocation': 0},
    {'name': 'Subscriptions',   'icon': '📱', 'color': '#a29bfe', 'monthly_allocation': 0},
    {'name': 'Personal',        'icon': '👤', 'color': '#6c5ce7', 'monthly_allocation': 0},
    {'name': 'Uncategorized',   'icon': '❓', 'color': '#636e72', 'monthly_allocation': 0, 'is_uncategorized': True},
]


@receiver(post_save, sender=CustomUser)
def create_default_buckets(sender, instance, created, **kwargs):
    if not created:
        return

    from buckets.models import Bucket

    buckets = [
        Bucket(
            user=instance,
            name=data['name'],
            icon=data['icon'],
            color=data['color'],
            monthly_allocation=data['monthly_allocation'],
            is_uncategorized=data.get('is_uncategorized', False),
            sort_order=data.get('sort_order', i),
        )
        for i, data in enumerate(DEFAULT_BUCKETS)
    ]
    Bucket.objects.bulk_create(buckets)
