from django.urls import path

from . import views

app_name = 'savings'

urlpatterns = [
    path('savings/', views.savings_list, name='savings_list'),
    path('savings/add/', views.savings_goal_add, name='savings_goal_add'),
    path('savings/<int:goal_id>/', views.savings_goal_detail, name='savings_goal_detail'),
]
