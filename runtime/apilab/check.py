"""The API Lab's hidden checker: real read-only SQL on the bronze layer, and the simulated API's request log.

The output has the shape of missionlab's (status, requires, criteria with their checks), so the Workbench shows it
with the shared missions panel. A failed check says what it found, never the answer.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Callable

from missionlab.model import SqlCheck

from .model import ApiLogCheck, ApiRunCheck, Mission, all_checks
from .service import TRUTH

Outcome = tuple[bool, str]


def sql_queries(mission: Mission) -> list[str]:
    queries: list[str] = []
    for check in all_checks(mission):
        if isinstance(check, SqlCheck) and check.sql not in queries:
            queries.append(check.sql)
    return queries


def _sql(check: SqlCheck, ctx: dict) -> Outcome:
    from datapass_runtime.execution import compare_rows
    result = ctx['sql'].get(check.sql)
    if result is None or result.get('error'):
        return False, f'The check query failed: {(result or {}).get("error", "not run")}'
    if result.get('truncated'):
        return False, 'The check result is truncated.'
    if compare_rows(result['rows'], check.expected):
        return True, 'As expected.'
    shown = json.dumps(result['rows'][:4], default=str)
    return False, f'Found: {shown}{" …" if len(result["rows"]) > 4 else ""}'


def _last_run(ctx: dict) -> dict | None:
    return ctx['runs'][-1] if ctx['runs'] else None


def _run(check: ApiRunCheck, ctx: dict) -> Outcome:
    run = _last_run(ctx)
    if run is None:
        return False, 'Your ingestion has not run yet.'
    if check.day is not None and run['day'] != check.day:
        return False, f'The last run was on day {run["day"]} of the API.'
    if run['status'] != 'ok':
        first = (run.get('error') or '').strip().splitlines()
        return False, f'The last run failed: {first[-1] if first else "error"}'
    return True, f'Run {run["run"]} finished.'


def _log(check: ApiLogCheck, ctx: dict) -> Outcome:
    run = _last_run(ctx)
    if run is None:
        return False, 'Your ingestion has not run yet.'
    if check.day is not None and run['day'] != check.day:
        return False, f'The last run was on day {run["day"]} of the API.'
    entries = [e for e in ctx['log'] if e.get('run') == run['run']]
    calls = [e for e in entries if e.get('path') == check.endpoint]
    if not calls:
        return False, f'The last run made no request to {check.endpoint}.'
    if check.authorized:
        refused = [e for e in entries if e.get('status') == 401]
        if refused:
            return False, f'{len(refused)} request(s) were refused with 401 (no or wrong API key).'
    for status in check.saw_status:
        if not any(e.get('status') == status for e in calls):
            return False, f'The run never met a {status} answer, so this part of the scenario was not exercised.'
    if check.retry_after_respected:
        ignored = [e for e in calls if e.get('violation') == 'retry_after_ignored']
        if ignored:
            return False, f'{len(ignored)} request(s) arrived before the Retry-After delay was over.'
    if check.retried_5xx:
        for index, entry in enumerate(calls):
            if int(entry.get('status', 0)) >= 500:
                same = [e for e in calls[index + 1:] if e.get('query') == entry.get('query') and e.get('status') == 200]
                if not same:
                    return False, f'A {entry["status"]} answer ({_describe(entry)}) was never retried successfully.'
    if check.param_required:
        missing = [e for e in calls if check.param_required not in (e.get('query') or {})]
        if missing:
            return False, f'{len(missing)} request(s) had no {check.param_required} parameter.'
    if check.complete and not any(e.get('status') == 200 and e.get('final') for e in calls):
        return False, f'The run never received the last page of {check.endpoint}.'
    records = sum(int(e.get('records') or 0) for e in calls)
    if check.max_records is not None and records > check.max_records:
        return False, f'The run fetched {records} records from {check.endpoint}.'
    return True, f'{len(calls)} request(s), {records} record(s).'


def _describe(entry: dict) -> str:
    query = entry.get('query') or {}
    return '&'.join(f'{k}={v}' for k, v in query.items()) or 'first page'


CHECKS: dict[str, Callable[[Any, dict], Outcome]] = {'sql': _sql, 'api_log': _log, 'api_run': _run}


def evaluate(mission: Mission, sql_results: dict[str, dict], log: list[dict], runs: list[dict]) -> dict:
    ctx = {'sql': sql_results, 'log': log, 'runs': runs}

    def run(check) -> dict:
        try:
            passed, detail = CHECKS[check.kind](check, ctx)
        except Exception as error:  # a broken log line is a failed check, not an outage
            passed, detail = False, f'Could not check: {error}'
        if not passed and check.fail:
            detail = f'{check.fail} {detail}'
        return {'kind': check.kind, 'passed': passed, 'detail': detail}

    unmet = [r.message for r in mission.requires if not run(r.check)['passed']]
    criteria = []
    for criterion in mission.acceptance:
        results = [run(check) for check in criterion.checks]
        criteria.append({'id': criterion.id, 'text': criterion.text, 'passed': all(r['passed'] for r in results),
                         'checks': results})
    passed = not unmet and all(c['passed'] for c in criteria)
    return {'mission_id': mission.id, 'version': mission.version, 'status': 'passed' if passed else 'not-yet',
            'requires': unmet, 'criteria': criteria,
            'checked_at': datetime.now().astimezone().isoformat(timespec='seconds'), 'truth': TRUTH}
