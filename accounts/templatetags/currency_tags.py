from django import template

register = template.Library()

CURRENCY_SYMBOLS = {
    'USD': '$',
    'EUR': '€',
    'GBP': '£',
    'CAD': 'CA$',
    'AUD': 'A$',
    'JPY': '¥',
}


@register.filter
def currency(value, currency_code='USD'):
    """
    Format a number as a currency string.

    Usage: {{ amount|currency:user.currency }}
    Examples: $1,234.56 for USD, €1,234.56 for EUR
    """
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return value

    symbol = CURRENCY_SYMBOLS.get(str(currency_code).upper(), str(currency_code) + ' ')
    return f'{symbol}{amount:,.2f}'
