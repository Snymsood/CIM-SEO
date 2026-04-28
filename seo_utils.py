from datetime import date, timedelta

def get_weekly_date_windows():
    """Returns (current_start, current_end, previous_start, previous_end) for a 7-day WoW report ending yesterday."""
    current_end = date.today() - timedelta(days=1)
    current_start = current_end - timedelta(days=6)
    
    previous_end = current_start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=6)
    
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
