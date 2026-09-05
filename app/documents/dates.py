from datetime import date, datetime, timedelta, timezone

# Japan has observed no daylight saving since 1951, so a fixed +09:00 is
# exact rather than an approximation. Preferred over ZoneInfo("Asia/Tokyo")
# because zoneinfo has no tz database on Windows and would need the tzdata
# package installed just to avoid a runtime error in development.
JST = timezone(timedelta(hours=9), name="JST")

# Newest first: era lookups walk this list checking "on or after start".
_ERAS = [
    ("令和", date(2019, 5, 1)),
    ("平成", date(1989, 1, 8)),
    ("大正", date(1912, 7, 30)),
    ("明治", date(1868, 1, 25)),
]


def today_in_japan() -> date:
    """
    The current date in Japan.

    These documents are dated for a Japanese reader, so UTC would print the
    wrong day for nine hours out of every twenty-four — a difference nobody
    would notice until a submission deadline.
    """
    return datetime.now(tz=JST).date()


def to_japanese_era(value: date) -> str:
    """
    和暦: the Gregorian date's era name and era year, e.g. 令和8.

    No 年 suffix and no 元年 special case for an era's first year — this
    matches the reference 履歴書 template exactly, which prints "令和1"
    rather than "令和元年" throughout its history table.
    """
    for name, start in _ERAS:
        if value >= start:
            return f"{name}{value.year - start.year + 1}"

    raise ValueError(f"{value} predates the earliest supported era (明治).")


def to_japanese_era_year(year: int, month: int) -> str:
    """
    和暦 for a (year, month) pair with no day — every 学歴・職歴・資格 row
    is a YearMonth, never a full date.

    Resolved using the 1st of the month, which misattributes only an entry
    dated in the exact transition month of an era change (1926-12, 1989-01,
    2019-05), on a day before the new era actually began. Exact precision
    would need a day of month nothing in this project collects for history
    rows.
    """
    return to_japanese_era(date(year, month, 1))


def age_on(birth_date: date, reference: date) -> int:
    """
    満年齢: age using the ordinary "full years" convention, as of
    `reference` — the document's own date, not today when it is read.
    """
    years = reference.year - birth_date.year

    if (reference.month, reference.day) < (birth_date.month, birth_date.day):
        years -= 1

    return years
