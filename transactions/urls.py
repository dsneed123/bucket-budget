from django.urls import path

from . import views

urlpatterns = [
    path('transactions/', views.transaction_list, name='transaction_list'),
    path('transactions/export/csv/', views.transaction_export_csv, name='transaction_export_csv'),
    path('transactions/import/csv/', views.transaction_import_csv, name='transaction_import_csv'),
    path('transactions/bulk/', views.transaction_bulk_action, name='transaction_bulk_action'),
    path('transactions/add/', views.transaction_add, name='transaction_add'),
    path('transactions/vendor-autocomplete/', views.vendor_autocomplete, name='vendor_autocomplete'),
    path('transactions/add/split/', views.transaction_add_split, name='transaction_add_split'),
    path('transactions/transfer/', views.transaction_transfer, name='transaction_transfer'),
    path('transactions/<int:transaction_id>/', views.transaction_detail, name='transaction_detail'),
    path('transactions/<int:transaction_id>/edit/', views.transaction_edit, name='transaction_edit'),
    path('transactions/<int:transaction_id>/delete/', views.transaction_delete, name='transaction_delete'),
    path('income-sources/', views.income_source_list, name='income_source_list'),
    path('income-sources/add/', views.income_source_add, name='income_source_add'),
    path('income-sources/<int:source_id>/edit/', views.income_source_edit, name='income_source_edit'),
    path('income-sources/<int:source_id>/delete/', views.income_source_delete, name='income_source_delete'),
    path('recurring/', views.recurring_list, name='recurring_list'),
    path('recurring/add/', views.recurring_add, name='recurring_add'),
    path('recurring/<int:recurring_id>/toggle/', views.recurring_toggle, name='recurring_toggle'),
    path('recurring/<int:recurring_id>/delete/', views.recurring_delete, name='recurring_delete'),
]
