"""Five-field cron expressions evaluated in UTC at minute resolution.

Follows the croniter semantics Airflow uses: presets such as @daily, names for
months and weekdays, lists, ranges and steps, 0 and 7 both meaning Sunday, and
when both day-of-month and day-of-week are restricted a day matches if either
field matches.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

PRESETS = {
    '@hourly': '0 * * * *',
    '@daily': '0 0 * * *',
    '@midnight': '0 0 * * *',
    '@weekly': '0 0 * * 0',
    '@monthly': '0 0 1 * *',
    '@yearly': '0 0 1 1 *',
    '@annually': '0 0 1 1 *',
}
MONTH_NAMES = {name: index for index, name in enumerate(
    ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'], start=1)}
DAY_NAMES = {name: index for index, name in enumerate(['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'])}
# Search horizon for the next/previous tick; a valid expression always matches within it.
MAX_DAYS = 366 * 8


class CronError(ValueError):
    pass


def _value(token: str, low: int, high: int, names: dict[str, int]) -> int:
    lowered = token.lower()
    if lowered in names:
        return names[lowered]
    if not token.isdigit():
        raise CronError(f"Invalid cron value {token!r}")
    value = int(token)
    if not low <= value <= high:
        raise CronError(f"Cron value {value} is outside {low}-{high}")
    return value


def _field(text: str, low: int, high: int, names: dict[str, int] | None = None) -> set[int]:
    names = names or {}
    values: set[int] = set()
    for item in text.split(','):
        if not item:
            raise CronError(f"Empty item in cron field {text!r}")
        base, _, step_text = item.partition('/')
        step = 1
        if step_text:
            if not step_text.isdigit() or int(step_text) < 1:
                raise CronError(f"Invalid cron step in {item!r}")
            step = int(step_text)
        if base == '*':
            start, end = low, high
        elif '-' in base:
            first, _, last = base.partition('-')
            start, end = _value(first, low, high, names), _value(last, low, high, names)
            if start > end:
                raise CronError(f"Descending cron range {base!r}")
        else:
            start = _value(base, low, high, names)
            end = high if step_text else start
        values.update(range(start, end + 1, step))
    return values


class Cron:
    def __init__(self, expression: str):
        text = PRESETS.get(expression.strip().lower(), expression.strip())
        fields = text.split()
        if len(fields) != 5:
            raise CronError(f"Cron expression {expression!r} must have 5 fields or be a preset such as @daily")
        self.expression = text
        self.minutes = sorted(_field(fields[0], 0, 59))
        self.hours = sorted(_field(fields[1], 0, 23))
        self.days = _field(fields[2], 1, 31)
        self.months = _field(fields[3], 1, 12, MONTH_NAMES)
        self.weekdays = {day % 7 for day in _field(fields[4], 0, 7, DAY_NAMES)}
        self.any_day = fields[2] == '*'
        self.any_weekday = fields[4] == '*'

    def _day_matches(self, day: datetime) -> bool:
        if day.month not in self.months:
            return False
        by_date = day.day in self.days
        by_weekday = day.isoweekday() % 7 in self.weekdays
        if self.any_day and self.any_weekday:
            return True
        if self.any_day:
            return by_weekday
        if self.any_weekday:
            return by_date
        return by_date or by_weekday

    def next_tick(self, after: datetime, inclusive: bool = False) -> datetime:
        """First tick at or after `after` (inclusive) or strictly after it."""
        candidate = after.replace(second=0, microsecond=0)
        if candidate < after or not inclusive:
            candidate += timedelta(minutes=1)
        day = candidate.replace(hour=0, minute=0)
        for _ in range(MAX_DAYS):
            if self._day_matches(day):
                for hour in self.hours:
                    for minute in self.minutes:
                        tick = day.replace(hour=hour, minute=minute)
                        if tick >= candidate:
                            return tick
            day += timedelta(days=1)
        raise CronError(f"Cron expression {self.expression!r} has no tick within {MAX_DAYS} days")

    def prev_tick(self, before: datetime, inclusive: bool = False) -> datetime:
        """Last tick at or before `before` (inclusive) or strictly before it."""
        candidate = before.replace(second=0, microsecond=0)
        if not inclusive and candidate == before:
            candidate -= timedelta(minutes=1)
        day = candidate.replace(hour=0, minute=0)
        for _ in range(MAX_DAYS):
            if self._day_matches(day):
                for hour in reversed(self.hours):
                    for minute in reversed(self.minutes):
                        tick = day.replace(hour=hour, minute=minute)
                        if tick <= candidate:
                            return tick
            day -= timedelta(days=1)
        raise CronError(f"Cron expression {self.expression!r} has no tick within {MAX_DAYS} days")


def utc(value: datetime) -> datetime:
    """Naive datetimes are UTC, as with Airflow's default timezone."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
