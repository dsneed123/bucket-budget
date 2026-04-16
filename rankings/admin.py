from django.contrib import admin

from .models import NecessitySnapshot


@admin.register(NecessitySnapshot)
class NecessitySnapshotAdmin(admin.ModelAdmin):
    list_display = ('user', 'period_start', 'period_end', 'avg_score', 'total_spend', 'transaction_count', 'created_at')
    list_filter = ('user',)
    ordering = ('-period_start',)
