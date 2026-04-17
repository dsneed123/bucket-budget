from django.contrib import admin

from .models import Bucket


@admin.register(Bucket)
class BucketAdmin(admin.ModelAdmin):
    list_display = ('name', 'monthly_allocation', 'is_active', 'is_uncategorized', 'rollover', 'user')
    list_filter = ('is_active', 'is_uncategorized', 'rollover')
    search_fields = ('name', 'user__email')
    ordering = ('sort_order', 'name')
