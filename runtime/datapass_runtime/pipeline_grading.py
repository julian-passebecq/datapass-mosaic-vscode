"""Arena DAG design grading: compile only, never execute submitted task bodies.

Task IDs, kinds, retry policy, dbt bindings and directed edges are semantic.
Python variable names, declaration order, source formatting and layout are not.
This adapter grades orchestration design, not the correctness of task SQL/code.
"""
import time
import uuid

from .pipeline_compiler import compile_pipeline, CompileError
from .exercise_validation import validate_result


def design_rows(ir):
    rows = [dict(element='task', id=t['id'], target='', kind=t['kind'],
                 retries=t['retries'], retry_delay=t['retry_delay'],
                 resource=t['resource_id'] or '', action=t['action'] or '')
            for t in ir['tasks']]
    rows += [dict(element='edge', id=e['source'], target=e['target'], kind='',
                  retries=0, retry_delay=0, resource='', action='') for e in ir['edges']]
    return sorted(rows, key=lambda r: (r['element'], r['id'], r['target']))


def grade_design(engine, request, spec, private):
    start = time.perf_counter()
    error = None
    try:
        rows = design_rows(compile_pipeline(request['code']))
    except CompileError as exc:
        rows = []
        error = str(exc)
    checks = []
    for fixture in private.fixtures:
        if request['mode'] != 'submit' and fixture.visibility != 'visible':
            continue
        # Each private fixture selects a structural projection. Empty input means
        # the entire graph; otherwise input rows select task/edge elements.
        selected = {r['element'] for r in fixture.input_rows}
        actual = [r for r in rows if not selected or r['element'] in selected]
        result = {'rows': actual, 'columns': list(rows[0]) if rows else [], 'truncated': False}
        passed = error is None and validate_result(result, fixture.expected, spec.validation,
                                                    request['code'], spec.language)
        check = dict(id=fixture.id, visibility=fixture.visibility, passed=passed,
                     status='passed' if passed else 'failed', execution_id=uuid.uuid4().hex,
                     execution_status='error' if error else 'success', elapsed_ms=0,
                     input_versions={}, message=error or ('DAG design matches.' if passed else 'DAG design differs.'))
        if fixture.visibility == 'visible':
            check.update(actual=actual, expected=fixture.expected)
        checks.append(check)
    return dict(status='passed' if all(c['passed'] for c in checks) else 'failed',
                checks=checks, runs=[], truth='design-only',
                runtime=dict(adapter=spec.runtime, engine='datapass-dag-compiler',
                             engine_version='1', session_generation=engine.generation),
                elapsed_ms=round((time.perf_counter()-start)*1000, 3))
