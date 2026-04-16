from django.urls import path

from . import views

urlpatterns = [
    path('insights/', views.insights, name='insights'),
    path('insights/recommendations/<int:rec_id>/dismiss/', views.dismiss_recommendation, name='dismiss_recommendation'),
]
