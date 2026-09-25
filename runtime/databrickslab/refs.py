"""Dynamic value references: {{job.run_id}}, {{job.parameters.x}}, {{tasks.t.values.k}}, ...

As in Databricks, the text inside the braces is not an expression. A reference in
an unknown namespace stays literal text; a reference in a known namespace that
does not resolve is an error.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Callable

REFERENCE = re.compile(r'\{\{\s*([^{}]*?)\s*\}\}')
NAMESPACES = {'job', 'task', 'tasks', 'workspace', 'input', 'backfill'}
# Deprecated references Databricks still resolves, and their current equivalents.
DEPRECATED = {'job_id': ['job', 'id'], 'run_id': ['task', 'run_id'], 'start_date': ['job', 'start_time', 'iso_date'],
              'start_time': ['job', 'start_time', 'timestamp_ms'], 'task_retry_count': ['task', 'retry_count'],
              'parent_run_id': ['job', 'run_id'], 'task_key': ['task', 'name']}
TIME_ARGS = ('iso_weekday', 'is_weekday', 'iso_date', 'iso_datetime', 'year', 'month', 'day', 'hour', 'minute',
             'second', 'timestamp_ms')
RESULT_STATES = ('success', 'failed', 'excluded', 'canceled', 'evicted', 'timedout', 'upstream_canceled',
                 'upstream_evicted', 'upstream_failed')


class ReferenceError_(ValueError):
    pass


def split_path(text: str) -> list[str]:
    """job.parameters.`my key` -> ['job', 'parameters', 'my key']."""
    parts, current, quoted = [], '', False
    for char in text:
        if char == '`':
            quoted = not quoted
        elif char == '.' and not quoted:
            parts.append(current)
            current = ''
        else:
            current += char
    parts.append(current)
    return parts


def as_text(value: Any) -> str:
    """Values become text: strings as they are, booleans as true/false, others as JSON."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return json.dumps(value)


def time_value(moment: datetime, argument: str) -> str:
    moment = moment.astimezone(timezone.utc) if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    return {
        'iso_weekday': str(moment.isoweekday()), 'is_weekday': 'true' if moment.isoweekday() <= 5 else 'false',
        'iso_date': moment.date().isoformat(), 'iso_datetime': moment.replace(tzinfo=None).isoformat(),
        'year': str(moment.year), 'month': str(moment.month), 'day': str(moment.day), 'hour': str(moment.hour),
        'minute': str(moment.minute), 'second': str(moment.second),
        'timestamp_ms': str(int(moment.timestamp() * 1000)),
    }[argument]


def resolve(text: str, lookup: Callable[[list[str]], Any]) -> str:
    """Replace every reference of `text`; `lookup` raises ReferenceError_ for an invalid known reference."""
    def replace(match: re.Match[str]) -> str:
        path = split_path(match.group(1))
        if len(path) == 1 and path[0] in DEPRECATED:
            path = DEPRECATED[path[0]]
        if not path or path[0] not in NAMESPACES:
            return match.group(0)  # unknown namespace: literal text, as Databricks does
        return as_text(lookup(path))
    return REFERENCE.sub(replace, text)


def references(text: str) -> list[list[str]]:
    return [split_path(m.group(1)) for m in REFERENCE.finditer(text) if split_path(m.group(1))[0] in NAMESPACES]
