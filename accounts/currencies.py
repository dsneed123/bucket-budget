CURRENCIES = {
    'USD': {'symbol': '$', 'name': 'US Dollar', 'decimals': 2, 'symbol_position': 'before'},
    'EUR': {'symbol': '€', 'name': 'Euro', 'decimals': 2, 'symbol_position': 'before'},
    'GBP': {'symbol': '£', 'name': 'British Pound', 'decimals': 2, 'symbol_position': 'before'},
    'CAD': {'symbol': 'CA$', 'name': 'Canadian Dollar', 'decimals': 2, 'symbol_position': 'before'},
    'AUD': {'symbol': 'A$', 'name': 'Australian Dollar', 'decimals': 2, 'symbol_position': 'before'},
    'JPY': {'symbol': '¥', 'name': 'Japanese Yen', 'decimals': 0, 'symbol_position': 'before'},
    'INR': {'symbol': '₹', 'name': 'Indian Rupee', 'decimals': 2, 'symbol_position': 'before'},
    'BRL': {'symbol': 'R$', 'name': 'Brazilian Real', 'decimals': 2, 'symbol_position': 'before'},
}

CURRENCY_CHOICES = [(code, f'{code} — {info["name"]}') for code, info in CURRENCIES.items()]


def format_currency(value, currency_code='USD'):
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return value

    code = str(currency_code).upper()
    info = CURRENCIES.get(code)
    if info is None:
        if amount < 0:
            return f'({code} {abs(amount):,.2f})'
        return f'{code} {amount:,.2f}'

    decimals = info['decimals']
    symbol = info['symbol']
    if amount < 0:
        formatted = f'{abs(amount):,.{decimals}f}'
        return f'({symbol}{formatted})'
    formatted = f'{amount:,.{decimals}f}'
    return f'{symbol}{formatted}'
