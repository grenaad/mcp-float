"""Utility functions for workday and holiday calculation."""

import calendar
from datetime import date

import holidays as _holidays


def _za_holidays(year: int) -> _holidays.HolidayBase:
    """Return South African public holidays for the given year."""
    return _holidays.ZA(years=year)


def get_workdays_for_month(year: int, month: int) -> list[str]:
    """Calculate working days (Mon-Fri, excluding SA public holidays).

    Args:
        year: The year (e.g. 2025).
        month: The month number (1-12).

    Returns:
        List of date strings in YYYY-MM-DD format.
    """
    if month < 1 or month > 12:
        raise ValueError(f"Month must be between 1 and 12, got: {month}")

    za = _za_holidays(year)
    workdays: list[str] = []
    _, days_in_month = calendar.monthrange(year, month)

    for day in range(1, days_in_month + 1):
        d = date(year, month, day)
        if d.weekday() < 5 and d not in za:
            workdays.append(d.isoformat())

    return workdays


def get_holidays_for_month(year: int, month: int) -> dict[str, str]:
    """Return SA public holidays that fall in a given month.

    Args:
        year: The year (e.g. 2025).
        month: The month number (1-12).

    Returns:
        Dict mapping date string (YYYY-MM-DD) to holiday name.
    """
    if month < 1 or month > 12:
        raise ValueError(f"Month must be between 1 and 12, got: {month}")

    za = _za_holidays(year)
    result: dict[str, str] = {}

    for d, name in sorted(za.items()):
        if d.month == month:
            result[d.isoformat()] = name

    return result


def get_holiday_name(year: int, month: int, day: int) -> str:
    """Return the holiday name for a specific date, or empty string.

    Args:
        year: The year.
        month: The month.
        day: The day.

    Returns:
        Holiday name if the date is an SA public holiday, else "".
    """
    za = _za_holidays(year)
    d = date(year, month, day)
    return za.get(d, "")
