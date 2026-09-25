"""Run journal: what the labs really ran in this workspace, recorded by the runtime as it answers.

Projects read it to verify steps such as "a Cloud Lab pipeline run succeeded" or "the exercise passed on
Submit". The API process is the only writer (the runtime runs one Uvicorn worker), after a lab route has
returned; nothing in this module runs anything. An entry keeps a few facts of the run, never its data.

The journal lives next to the catalog (`.datapass/data/run_journal.json`), keyed by lab and subject (a
pipeline, a job, an exercise...), with the latest runs of each subject first.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import threading
from typing import Any
import uuid

from .atomic import replace_file

JOURNAL_FILE = 'run_journal.json'
PER_SUBJECT = 8
MAX_SUBJECTS = 400
_LOCK = threading.Lock()

# What a lab's recorded outcome is: real local execution, a simulation, an emulation of a product, a
# simulated orchestration whose activities ran locally, or a static analysis (SQL lineage) that runs nothing.
TRUTHS = ('real', 'simulated', 'emulation', 'hybrid', 'static')


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class RunJournal:
    def __init__(self, directory: Path):
        self.path = directory / JOURNAL_FILE

    def _read(self) -> dict[str, list[dict[str, Any]]]:
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}
        subjects = data.get('subjects') if isinstance(data, dict) else None
        return {k: v for k, v in subjects.items() if isinstance(v, list)} if isinstance(subjects, dict) else {}

    def record(self, entry: dict[str, Any]) -> dict[str, Any]:
        entry = {'id': uuid.uuid4().hex[:12], 'at': _now(), **entry}
        key = f"{entry['lab']}|{entry['subject']}"
        with _LOCK:
            subjects = self._read()
            subjects[key] = [entry, *subjects.get(key, [])][:PER_SUBJECT]
            if len(subjects) > MAX_SUBJECTS:
                # Forget the subjects whose latest run is the oldest.
                for stale in sorted(subjects, key=lambda k: subjects[k][0].get('at', ''))[:len(subjects) - MAX_SUBJECTS]:
                    subjects.pop(stale)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix('.tmp')
            tmp.write_text(json.dumps({'schema_version': 1, 'subjects': subjects}, indent=1), encoding='utf-8')
            replace_file(tmp, self.path)
        return entry

    def entries(self, lab: str, subject: str | None = None) -> list[dict[str, Any]]:
        """Recorded runs of a lab (one subject, or all), newest first."""
        with _LOCK:
            subjects = self._read()
        found = [e for key, runs in subjects.items() for e in runs
                 if key.split('|', 1)[0] == lab and (subject is None or key.split('|', 1)[1] == subject)]
        return sorted(found, key=lambda e: e.get('at', ''), reverse=True)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _names(items: Any) -> list[str]:
    return sorted({str(_dict(item).get('name')) for item in _list(items) if _dict(item).get('name')})


def summarize(lab: str, request: dict[str, Any], response: Any) -> dict[str, Any] | None:
    """The journal entry of one lab run, or None when there is nothing to record (a rejected request)."""
    summarizer = SUMMARIZERS.get(lab)
    return summarizer(request, _dict(response)) if summarizer else None


def _exercise(request, response):
    if response.get('status') not in ('passed', 'failed'):
        return None
    truth = {'real': 'real', 'semantic-emulation': 'emulation'}.get(str(response.get('truth')), 'simulated')
    return {'lab': 'exercise', 'subject': request['exercise_id'], 'ok': response['status'] == 'passed',
            'status': response['status'], 'truth': truth,
            'facts': {'mode': request['mode'], 'language': request['language'], 'version': request['exercise_version']}}


def _csv_import(request, response):
    if not response.get('asset'):
        return None
    return {'lab': 'csv_import', 'subject': response['asset'], 'ok': True, 'status': 'imported', 'truth': 'real',
            'facts': {'rows': response.get('rows_imported')}}


def _file_import(request, response):
    if not response.get('asset'):
        return None
    return {'lab': 'file_import', 'subject': response['asset'], 'ok': True, 'status': 'imported', 'truth': 'real',
            'facts': {'rows': response.get('rows_imported'), 'format': response.get('format')}}


def _execute(request, response):
    language = request['language']
    ok = response.get('status') == 'success'
    result = _dict(response.get('result'))
    facts: dict[str, Any] = {'columns': [str(c) for c in _list(result.get('columns'))],
                             'rows': result.get('total_rows')}
    truth = 'real'
    if language == 'sparklab':
        truth = 'emulation'
        plan = _dict(_dict(_dict(response.get('simulation')).get('metrics')).get('plan_facts'))
        facts.update(profile=request.get('profile'), aqe=request.get('aqe'), exchanges=plan.get('exchanges'),
                     broadcast_joins=plan.get('broadcast_joins'))
    return {'lab': 'execute', 'subject': language, 'ok': ok, 'status': response.get('status', 'error'),
            'truth': truth, 'facts': facts}


def _factory(request, response):
    run = _dict(response.get('run'))
    activities = [_dict(a) for a in _list(run.get('activity_runs'))]
    local = response.get('data_plane') == 'local'
    return {'lab': 'factory', 'subject': f"{request['flavor']}/{request['name']}",
            'ok': response.get('status') == 'simulated' and run.get('status') == 'Succeeded',
            'status': run.get('status') or response.get('status', 'error'), 'truth': 'hybrid' if local else 'simulated',
            'facts': {'flavor': request['flavor'], 'data_plane': response.get('data_plane'),
                      'activities': sorted({str(a.get('name')) for a in activities if a.get('name')}),
                      'succeeded': sorted({str(a.get('name')) for a in activities if a.get('status') == 'Succeeded'}),
                      'max_attempts': max((int(a.get('attempts') or 0) for a in activities), default=0),
                      'tables_changed': _names(response.get('tables_changed'))}}


def _sqlpool(request, response):
    if not str(request.get('script') or '').strip():
        return None  # describing the pool's tables is not a run
    statements = [_dict(s) for s in _list(response.get('statements'))]
    return {'lab': 'sqlpool', 'subject': f"{request['flavor']}:{request.get('source') or 'inline'}",
            'ok': response.get('status') == 'ok' and bool(statements), 'status': response.get('status', 'error'),
            'truth': 'hybrid',
            'facts': {'flavor': request['flavor'], 'source': request.get('source') or '', 'statements': len(statements),
                      'kinds': sorted({str(s.get('kind')) for s in statements if s.get('kind')}),
                      'tables': _names(response.get('tables'))}}


def _databricks(request, response):
    run = _dict(response.get('run'))
    tasks = [_dict(t) for t in _list(run.get('tasks'))]
    local = response.get('data_plane') == 'local'
    return {'lab': 'databricks', 'subject': request['name'],
            'ok': response.get('status') == 'simulated' and run.get('result_state') == 'SUCCESS',
            'status': run.get('status_label') or response.get('status', 'error'), 'truth': 'hybrid' if local else 'simulated',
            'facts': {'data_plane': response.get('data_plane'), 'result_state': run.get('result_state'),
                      'principal': run.get('principal'),
                      'succeeded': sorted({str(t.get('key')) for t in tasks if t.get('state') == 'success'}),
                      'max_attempts': max((len(_list(t.get('attempts'))) for t in tasks), default=0),
                      'tables_changed': _names(response.get('tables_changed'))}}


def _bi(request, response):
    statements = [_dict(s) for s in _list(response.get('statements'))]
    model = _dict(response.get('model'))
    checks = [_dict(c) for c in _list(model.get('checks'))]
    tables = [_dict(t) for t in _list(model.get('tables'))]
    columns = [_dict(c) for c in _list(_dict(response.get('lineage')).get('columns'))]
    # Column lineage as "table.column<-source.table.column" edges to the columns it originates from.
    edges = sorted({f"{c.get('table')}.{c.get('column')}<-{o}" for c in columns for o in _list(c.get('origins'))})
    return {'lab': 'bi', 'subject': 'warehouse', 'ok': response.get('status') == 'ok',
            'status': response.get('status', 'error'), 'truth': 'real',
            'facts': {'ran': bool(response.get('ran')), 'statements': len(statements),
                      'model_checks': len(checks), 'model_failed': sum(1 for c in checks if c.get('status') != 'pass'),
                      'model_error': bool(model.get('error')),
                      'facts': sorted({str(t.get('name')) for t in tables if t.get('role') == 'fact'}),
                      'lineage_columns': len(columns), 'lineage_origins': edges[:4000]}}


def _dbt(request, response):
    run = _dict(response.get('run'))
    if not run:
        return None  # parse only, or an invalid project
    results = [_dict(r) for r in _list(run.get('results'))]
    select = ' '.join(request.get('select') or []) or '*'
    return {'lab': 'dbt', 'subject': f"{request['command']} {select}", 'ok': run.get('status') == 'success',
            'status': run.get('status', 'error'), 'truth': 'emulation',
            'facts': {'command': request['command'], 'select': select, 'full_refresh': bool(request.get('full_refresh')),
                      'counts': _dict(run.get('counts')),
                      'succeeded': sorted({str(r.get('name')) for r in results if r.get('status') in ('success', 'pass')}),
                      'failed': sorted({str(r.get('name')) for r in results if r.get('status') in ('error', 'fail')})}}


def _airflow(request, response):
    dag = _dict(response.get('dag'))
    if not dag.get('dag_id'):
        return None
    runs = [_dict(r) for r in _list(response.get('runs'))]
    tries = [int(_dict(i).get('try_number') or 0) for r in runs for i in _list(r.get('instances'))]
    # The label is the schedule as written: '0 6 * * *', '@daily' or CronTriggerTimetable('0 6 * * *', ...).
    label = str(_dict(dag.get('schedule')).get('label') or 'None')
    quoted = re.search(r"'([^']*)'", label)
    return {'lab': 'airflow', 'subject': str(dag['dag_id']),
            'ok': response.get('status') == 'simulated' and bool(runs) and all(r.get('state') == 'success' for r in runs),
            'status': response.get('status', 'invalid'), 'truth': 'simulated',
            'facts': {'schedule': quoted.group(1) if quoted else label, 'catchup': dag.get('catchup'),
                      'total_runs': response.get('total_runs'), 'simulated_runs': len(runs),
                      'failed_runs': sum(1 for r in runs if r.get('state') != 'success'),
                      'max_try_number': max(tries, default=0),
                      'tasks': sorted({str(_dict(t).get('task_id')) for t in _list(dag.get('tasks'))})}}


def _pipeline(request, response):
    tasks = [_dict(t) for t in _list(response.get('tasks'))]
    return {'lab': 'pipeline', 'subject': str(response.get('pipeline_id') or 'pipeline'),
            'ok': response.get('status') == 'success', 'status': response.get('status', 'failed'), 'truth': 'real',
            'facts': {'tasks': sorted({str(t.get('id')) for t in tasks}),
                      'quality_tasks': sum(1 for t in tasks if t.get('kind') == 'quality' and t.get('status') == 'success'),
                      'max_attempts': max((int(t.get('attempts') or 0) for t in tasks), default=0)}}


def _retail_demo(request, response):
    return {'lab': 'lakehouse', 'subject': 'retail-demo', 'ok': True, 'status': 'success', 'truth': 'real',
            'facts': {'tables': sorted({str(_dict(s).get('label')) for s in _list(response.get('stages'))
                                        if '.' in str(_dict(s).get('label') or '')})}}


SUMMARIZERS = {
    'exercise': _exercise, 'csv_import': _csv_import, 'file_import': _file_import, 'execute': _execute, 'factory': _factory,
    'sqlpool': _sqlpool, 'databricks': _databricks, 'bi': _bi, 'dbt': _dbt, 'airflow': _airflow,
    'pipeline': _pipeline, 'lakehouse': _retail_demo,
}
