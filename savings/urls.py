from django.urls import path

from . import views

app_name = 'savings'

urlpatterns = [
    path('savings/', views.savings_list, name='savings_list'),
    path('savings/add/', views.savings_goal_add, name='savings_goal_add'),
    path('savings/shared/<uuid:share_uuid>/', views.savings_goal_shared, name='savings_goal_shared'),
    path('savings/auto-rules/', views.auto_save_rules, name='auto_save_rules'),
    path('savings/auto-rules/<int:rule_id>/toggle/', views.auto_save_rule_toggle, name='auto_save_rule_toggle'),
    path('savings/auto-rules/<int:rule_id>/delete/', views.auto_save_rule_delete, name='auto_save_rule_delete'),
    path('savings/<int:goal_id>/', views.savings_goal_detail, name='savings_goal_detail'),
    path('savings/<int:goal_id>/edit/', views.savings_goal_edit, name='savings_goal_edit'),
    path('savings/<int:goal_id>/contribute/', views.savings_goal_contribute, name='savings_goal_contribute'),
    path('savings/<int:goal_id>/withdraw/', views.savings_goal_withdraw, name='savings_goal_withdraw'),
    path('savings/<int:goal_id>/delete/', views.savings_goal_delete, name='savings_goal_delete'),
]
