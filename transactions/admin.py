from django.contrib import admin

from .models import CsvColumnMapping, IncomeSource, RecurringTransaction, Tag, Transaction, VendorMapping


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('date', 'description', 'amount', 'transaction_type', 'bucket', 'user')
    list_filter = ('transaction_type', 'is_recurring', 'regret', 'date')
    search_fields = ('description', 'vendor', 'user__email')
    ordering = ('-date', '-created_at')
    date_hierarchy = 'date'
    raw_id_fields = ('user', 'account', 'bucket')


@admin.register(RecurringTransaction)
class RecurringTransactionAdmin(admin.ModelAdmin):
    list_display = ('description', 'amount', 'transaction_type', 'frequency', 'next_due', 'is_active', 'user')
    list_filter = ('transaction_type', 'frequency', 'is_active', 'is_subscription')
    search_fields = ('description', 'vendor', 'user__email')
    ordering = ('next_due',)


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ('name', 'color', 'user')
    list_filter = ('user',)
    search_fields = ('name', 'user__email')


@admin.register(VendorMapping)
class VendorMappingAdmin(admin.ModelAdmin):
    list_display = ('vendor_name', 'bucket', 'user', 'last_used')
    list_filter = ('user',)
    search_fields = ('vendor_name', 'user__email')
    ordering = ('-last_used',)


@admin.register(IncomeSource)
class IncomeSourceAdmin(admin.ModelAdmin):
    list_display = ('name', 'color', 'is_active', 'user', 'created_at')
    list_filter = ('is_active', 'user')
    search_fields = ('name', 'user__email')


@admin.register(CsvColumnMapping)
class CsvColumnMappingAdmin(admin.ModelAdmin):
    list_display = ('user', 'source_key', 'updated_at')
    search_fields = ('user__email', 'source_key')
    ordering = ('-updated_at',)
