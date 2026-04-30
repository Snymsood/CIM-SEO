from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

def get_weekly_date_windows():
    """Returns (current_start, current_end, previous_start, previous_end) for a 7-day WoW report ending yesterday."""
    current_end = date.today() - timedelta(days=1)
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
