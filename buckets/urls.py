from django.urls import path
from . import views

urlpatterns = [
    path('buckets/', views.bucket_list, name='bucket_list'),
    path('buckets/add/', views.bucket_add, name='bucket_add'),
]
