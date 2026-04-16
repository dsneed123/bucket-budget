from django import template
from accounts.currencies import format_currency

register = template.Library()


@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)


@register.filter
def currency(value, currency_code='USD'):
    """
    Format a number as a currency string.

    Usage: {{ amount|currency:user.currency }}
    Examples: $1,234.56 for USD, ¥1,235 for JPY
    """
    return format_currency(value, currency_code)
