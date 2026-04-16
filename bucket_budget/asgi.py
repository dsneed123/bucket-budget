"""ASGI config for bucket_budget project."""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bucket_budget.settings')

application = get_asgi_application()
