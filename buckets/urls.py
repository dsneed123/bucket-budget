from django.urls import path
from . import views

urlpatterns = [
    path('buckets/', views.bucket_list, name='bucket_list'),
    path('buckets/add/', views.bucket_add, name='bucket_add'),
    path('buckets/templates/', views.bucket_templates, name='bucket_templates'),
    path('buckets/reorder/', views.bucket_reorder, name='bucket_reorder'),
    path('buckets/quick-allocate/', views.quick_allocate, name='quick_allocate'),
    path('buckets/<int:bucket_id>/', views.bucket_detail, name='bucket_detail'),
    path('buckets/<int:bucket_id>/edit/', views.bucket_edit, name='bucket_edit'),
    path('buckets/<int:bucket_id>/delete/', views.bucket_delete, name='bucket_delete'),
    path('buckets/<int:bucket_id>/archive/', views.bucket_archive, name='bucket_archive'),
    path('buckets/<int:bucket_id>/unarchive/', views.bucket_unarchive, name='bucket_unarchive'),
]
