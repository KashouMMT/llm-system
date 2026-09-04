from datetime import date, datetime, timedelta, timezone

# Japan has observed no daylight saving since 1951, so a fixed +09:00 is
# exact rather than an approximation. Preferred over ZoneInfo("Asia/Tokyo")
# because zoneinfo has no tz database on Windows and would need the tzdata
# package installed just to avoid a runtime error in development.
JST = timezone(timedelta(hours=9), name="JST")


def today_in_japan() -> date:
    """
    The current date in Japan.

    These documents are dated for a Japanese reader, so UTC would print the
    wrong day for nine hours out of every twenty-four — a difference nobody
    would notice until a submission deadline.
    """
    return datetime.now(tz=JST).date()
