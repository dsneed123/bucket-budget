from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('health/', views.health, name='health'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('api/stats/', views.stats_api, name='stats_api'),
]
