import calendar
import datetime


def advance_next_due(current_date, frequency):
    """Return the next due date after current_date based on frequency."""
    if frequency == 'daily':
        return current_date + datetime.timedelta(days=1)
    elif frequency == 'weekly':
        return current_date + datetime.timedelta(days=7)
    elif frequency == 'biweekly':
        return current_date + datetime.timedelta(days=14)
    elif frequency == 'yearly':
        year = current_date.year + 1
        day = min(current_date.day, calendar.monthrange(year, current_date.month)[1])
        return current_date.replace(year=year, day=day)
    else:  # monthly
        month = current_date.month + 1
        year = current_date.year
        if month > 12:
            month = 1
            year += 1
        day = min(current_date.day, calendar.monthrange(year, month)[1])
        return current_date.replace(year=year, month=month, day=day)
