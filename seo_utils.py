from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

def get_weekly_date_windows(as_of: date | None = None):
    """Return the last completed Monday–Sunday week and the week before it.

    A later rerun of a Monday report keeps the same reporting period.
    """
    today = as_of or date.today()
    days_since_sunday = (today.weekday() + 1) % 7 or 7
    current_end = today - timedelta(days=days_since_sunday)
    current_start = current_end - timedelta(days=6)
    
    previous_end = current_start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=6)
    
    return current_start, current_end, previous_start, previous_end


def get_monthly_date_windows():
    """
    Returns (current_start, current_end, previous_start, previous_end) for monthly MoM report.
    
    On May 1st: Returns April 1-30 (current) vs March 1-31 (previous)
    On any day: Returns last complete month vs month before that
    
    Returns:
        tuple: (current_start, current_end, previous_start, previous_end)
    """
    today = date.today()
    
    # Current month: first day of last month to last day of last month
    current_start = (today.replace(day=1) - relativedelta(months=1))
    current_end = today.replace(day=1) - timedelta(days=1)
    
    # Previous month: one month before current
    previous_start = (current_start - relativedelta(months=1))
    previous_end = current_start - timedelta(days=1)
    
    return current_start, current_end, previous_start, previous_end

def short_url(url, max_len=58):
    """Shortens a URL for display in tables or charts."""
    text = str(url)
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."

def safe_pct_change(current, previous):
    """Safely calculates percentage change between two values."""
    if previous == 0:
        return None
    return (current - previous) / previous
