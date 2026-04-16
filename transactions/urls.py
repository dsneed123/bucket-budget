from django.urls import path

from . import views

urlpatterns = [
    path('transactions/', views.transaction_list, name='transaction_list'),
    path('transactions/bulk/', views.transaction_bulk_action, name='transaction_bulk_action'),
    path('transactions/add/', views.transaction_add, name='transaction_add'),
    path('transactions/vendor-autocomplete/', views.vendor_autocomplete, name='vendor_autocomplete'),
    path('transactions/add/split/', views.transaction_add_split, name='transaction_add_split'),
    path('transactions/transfer/', views.transaction_transfer, name='transaction_transfer'),
    path('transactions/<int:transaction_id>/', views.transaction_detail, name='transaction_detail'),
    path('transactions/<int:transaction_id>/edit/', views.transaction_edit, name='transaction_edit'),
    path('transactions/<int:transaction_id>/delete/', views.transaction_delete, name='transaction_delete'),
]
