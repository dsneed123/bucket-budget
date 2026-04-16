"""URL configuration for bucket_budget project."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls')),
    path('', include('accounts.urls')),
    path('', include('banking.urls')),
    path('', include('buckets.urls')),
    path('', include('transactions.urls')),
    path('', include('rankings.urls')),
    path('', include('savings.urls')),
    path('', include('budget.urls')),
    path('', include('insights.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
