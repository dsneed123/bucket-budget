import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Creates a superuser if none exists, using DJANGO_SUPERUSER_EMAIL and DJANGO_SUPERUSER_PASSWORD env vars.'

    def handle(self, *args, **options):
        User = get_user_model()

        if User.objects.filter(is_superuser=True).exists():
            self.stdout.write('Superuser already exists, skipping.')
            return

        email = os.environ.get('DJANGO_SUPERUSER_EMAIL')
        password = os.environ.get('DJANGO_SUPERUSER_PASSWORD')

        if not email or not password:
            self.stderr.write('DJANGO_SUPERUSER_EMAIL and DJANGO_SUPERUSER_PASSWORD must be set.')
            return

        User.objects.create_superuser(email=email, password=password)
        self.stdout.write(self.style.SUCCESS(f'Superuser created: {email}'))
