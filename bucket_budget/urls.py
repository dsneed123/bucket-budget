"""URL configuration for bucket_budget project."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import path, include
from django.views.generic import TemplateView

from core.sitemaps import StaticViewSitemap

handler403 = 'django.views.defaults.permission_denied'
handler404 = 'django.views.defaults.page_not_found'
handler500 = 'django.views.defaults.server_error'

sitemaps = {
    'static': StaticViewSitemap,
}

urlpatterns = [
    path('admin/', admin.site.urls),
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='django.contrib.sitemaps.views.sitemap'),
    path('robots.txt', TemplateView.as_view(template_name='robots.txt', content_type='text/plain')),
    path('', include('core.urls')),
    path('', include('accounts.urls', namespace='accounts')),
    path('', include('banking.urls')),
    path('', include('buckets.urls')),
    path('', include('transactions.urls')),
    path('', include('rankings.urls')),
    path('', include('savings.urls')),
    path('', include('budget.urls')),
    path('', include('insights.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
