"""WSGI config for bucket_budget project."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bucket_budget.settings')

application = get_wsgi_application()
