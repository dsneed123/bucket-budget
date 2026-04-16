import pytz

from django import template
from django.utils import timezone as django_timezone

register = template.Library()


@register.filter
def in_timezone(value, tz_name):
    """Convert an aware datetime to the given pytz timezone name.

    Returns a naive datetime in the target timezone so Django's |date: filter
    formats it without reconverting to the server timezone.

    Usage: {{ some_datetime|in_timezone:prefs.timezone|date:"M j, Y g:i A" }}
    """
    if not value or not tz_name:
        return value
    try:
        tz = pytz.timezone(str(tz_name))
        if django_timezone.is_aware(value):
            return value.astimezone(tz).replace(tzinfo=None)
    except (pytz.exceptions.UnknownTimeZoneError, AttributeError):
        pass
    return value
