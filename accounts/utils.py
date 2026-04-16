import calendar
import datetime


def get_fiscal_month_range(year, month, fiscal_month_start):
    """Return (start_date, end_date) for the fiscal period labeled (year, month).

    fiscal_month_start=1 returns the standard calendar month.
    fiscal_month_start=15 makes April's period run Apr 15 – May 14.
    """
    if fiscal_month_start == 1:
        last_day = calendar.monthrange(year, month)[1]
        return datetime.date(year, month, 1), datetime.date(year, month, last_day)

    start = datetime.date(year, month, fiscal_month_start)
    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1
    end = datetime.date(next_year, next_month, fiscal_month_start) - datetime.timedelta(days=1)
    return start, end


def get_current_fiscal_month(today, fiscal_month_start):
    """Return (year, month) for the fiscal period containing today.

    With fiscal_month_start=15: Apr 16 → (year, 4); Apr 14 → (year, 3).
    """
    if fiscal_month_start == 1 or today.day >= fiscal_month_start:
        return today.year, today.month
    if today.month == 1:
        return today.year - 1, 12
    return today.year, today.month - 1


def get_user_fiscal_start(user):
    """Return the user's fiscal_month_start, defaulting to 1 if preferences not set."""
    try:
        return user.preferences.fiscal_month_start
    except Exception:
        return 1
