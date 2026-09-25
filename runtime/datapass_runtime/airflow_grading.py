"""Airflow Lab grading: parse the learner's DAG file, simulate each fixture scenario, compare outcome rows.

The DAG source is read by a whitelisted AST parser and never executed. Each
private fixture carries a scenario (scheduler clock, task behavior) and an
outcome table (runs, task instances, rendered templates, edges or tasks);
the simulated rows are graded with the shared row validator.
"""
import time
import uuid

from airflowlab.model import AirflowLabError
from airflowlab.parser import parse_dag
from airflowlab.simulate import Scenario, outcome_rows

from .exercise_validation import validate_result


def grade_airflow(engine, request, spec, private):
    start = time.perf_counter()
    try:
        dag, error = parse_dag(request['code']), None
    except AirflowLabError as exc:
        dag, error = None, f"DAG file rejected: {exc}"
    checks = []
    for fixture in private.fixtures:
        if request['mode'] != 'submit' and fixture.visibility != 'visible':
            continue
        scenario = Scenario.model_validate(fixture.scenario)
        rows, message = [], error
        if dag is not None:
            try:
                rows = outcome_rows(dag, scenario)
            except AirflowLabError as exc:
                message = f"Simulation stopped: {exc}"
        columns = scenario.columns or (list(rows[0]) if rows else [])
        result = {'rows': rows, 'columns': columns, 'truncated': False}
        passed = message is None and validate_result(result, fixture.expected, spec.validation,
                                                     request['code'], spec.language)
        check = dict(id=fixture.id, visibility=fixture.visibility, passed=passed,
                     status='passed' if passed else 'failed', execution_id=uuid.uuid4().hex,
                     execution_status='error' if message else 'success', elapsed_ms=0,
                     input_versions={},
                     message=message or ('Simulated outcome matches.' if passed else 'Simulated outcome differs.'))
        if fixture.visibility == 'visible':
            check.update(actual=rows, expected=fixture.expected)
        checks.append(check)
    return dict(status='passed' if all(c['passed'] for c in checks) else 'failed',
                checks=checks, runs=[], truth='simulated',
                runtime=dict(adapter=spec.runtime, engine='datapass-airflow-simulator',
                             engine_version='1', session_generation=engine.generation),
                elapsed_ms=round((time.perf_counter() - start) * 1000, 3))
