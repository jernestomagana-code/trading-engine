"""NYSE regular session presentation. Futures require their own exchange evidence.
Sources: https://www.nyse.com/markets/hours-calendars (2026–2028 early closes).
Not an order authorization or substitute for broker trading-hours metadata.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

def _observed_fixed_market_holiday(year, month, day):
    holiday = datetime(year, month, day).date()
    if holiday.weekday() == 5:  # Saturday observed Friday
        return holiday - timedelta(days=1)
    if holiday.weekday() == 6:  # Sunday observed Monday
        return holiday + timedelta(days=1)
    return holiday


def _nth_weekday_date(year, month, weekday, occurrence):
    current = datetime(year, month, 1).date()
    while current.weekday() != weekday:
        current += timedelta(days=1)
    return current + timedelta(days=7 * (occurrence - 1))


def _last_weekday_date(year, month, weekday):
    if month == 12:
        current = datetime(year, 12, 31).date()
    else:
        current = datetime(year, month + 1, 1).date() - timedelta(days=1)
    while current.weekday() != weekday:
        current -= timedelta(days=1)
    return current


def _easter_date(year):
    """Gregorian Easter date; Good Friday is two days earlier."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return datetime(year, month, day).date()


def _us_market_holiday_dates(year):
    holidays = {
        (datetime(year, 1, 2).date() if datetime(year, 1, 1).weekday() == 6 else datetime(year, 1, 1).date()),   # New Year's Day
        _nth_weekday_date(year, 1, 0, 3),             # Martin Luther King Jr. Day
        _nth_weekday_date(year, 2, 0, 3),             # Washington's Birthday
        _easter_date(year) - timedelta(days=2),       # Good Friday
        _last_weekday_date(year, 5, 0),               # Memorial Day
        _observed_fixed_market_holiday(year, 6, 19),  # Juneteenth
        _observed_fixed_market_holiday(year, 7, 4),   # Independence Day
        _nth_weekday_date(year, 9, 0, 1),             # Labor Day
        _nth_weekday_date(year, 11, 3, 4),            # Thanksgiving Day
        _observed_fixed_market_holiday(year, 12, 25), # Christmas Day
    }
    return holidays



EARLY_CLOSES = {"2026-11-27", "2026-12-24", "2027-11-26", "2028-07-03", "2028-11-24"}

def trading_day(day):
    return day.weekday() < 5 and day not in _us_market_holiday_dates(day.year)

def session(now=None):
    current = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("America/New_York"))
    day = current.date()
    close_hour = 13 if day.isoformat() in EARLY_CLOSES else 16
    opened = trading_day(day) and (9, 30) <= (current.hour, current.minute) < (close_hour, 0)
    label = "Acciones: abierto" if opened else "Acciones: cerrado"
    reason = "Festivo de bolsa" if day.weekday() < 5 and not trading_day(day) else "Cierre anticipado a las 13:00 Nueva York" if close_hour == 13 else "Sesión regular 09:30–16:00 Nueva York"
    return {"open": opened, "label": label, "reason": reason}

def next_open(now=None):
    current = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("America/New_York"))
    candidate = current.replace(hour=9, minute=30, second=0, microsecond=0)
    if candidate <= current:
        candidate += timedelta(days=1)
    while not trading_day(candidate.date()):
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc)
