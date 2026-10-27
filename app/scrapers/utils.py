from datetime import date, timedelta


DEFAULT_MAX_AGE_DAYS = 14


def is_recent(
    posted_date: date | None, max_age_days: int = DEFAULT_MAX_AGE_DAYS
) -> bool:
    """Return True if the job was posted within the last max_age_days."""
    if posted_date is None:
        return False
    today = date.today()
    cutoff = today - timedelta(days=max_age_days)
    return cutoff <= posted_date <= today