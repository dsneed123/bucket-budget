from django.urls import path
from . import views

urlpatterns = [
    path('accounts/', views.account_list, name='account_list'),
    path('accounts/add/', views.account_add, name='account_add'),
    path('accounts/<int:account_id>/edit/', views.account_edit, name='account_edit'),
    path('accounts/<int:account_id>/update-balance/', views.account_update_balance, name='account_update_balance'),
]
