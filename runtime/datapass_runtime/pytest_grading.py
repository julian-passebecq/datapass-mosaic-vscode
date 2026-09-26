"""Production Python graded by pytest (Practice language `pytest`).

The learner writes a module with a function AND its tests. Grading runs real pytest on this
computer, as trusted local Python only: refused while trusted Python is off, never a fallback.

- `own-tests` fixture (visible): the learner's own tests run and pass, and there are at least
  `min_tests` of them.
- `hidden` fixtures (submit only): pytest files from grading.server.json import the learner's
  module as `solution` and must pass. Their source and test names never leave the runtime.

Each run is a child `python -m pytest` of the worker, in a fresh temporary folder, with a
timeout, plugin autoloading off, no cache, and an environment without Datapass variables or
anything named like a secret. Like the Python worker, this is not a security sandbox.
"""
import os
import subprocess
import sys
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Literal

from pydantic import Field

from .exercise_contracts import Contract

TIMEOUT_S = 60
MESSAGE_LIMIT = 1500


class PytestScenario(Contract):
    check: Literal['own-tests', 'hidden']
    min_tests: int = Field(default=1, ge=1, le=50)
    tests: str = ''


def check_scenario(language, raw):
    scenario = PytestScenario.model_validate(raw)
    if scenario.check == 'hidden' and 'def test_' not in scenario.tests:
        raise ValueError('A hidden pytest fixture ships its test file')
    if scenario.check == 'own-tests' and scenario.tests:
        raise ValueError('The own-tests fixture runs the learner\'s tests only')
    return scenario


def _env():
    blocked = ('TOKEN', 'SECRET', 'PASSWORD', 'API_KEY', 'CREDENTIAL')
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith('DATAPASS_') and not any(word in k.upper() for word in blocked)}
    env.update(PYTHONDONTWRITEBYTECODE='1', PYTEST_DISABLE_PLUGIN_AUTOLOAD='1', PYTHONIOENCODING='utf-8')
    return env


def run_pytest(code, test_file=None):
    """Run pytest on the learner's module (or on a hidden test file beside it). Returns a summary dict."""
    with tempfile.TemporaryDirectory(prefix='datapass-pytest-') as temp:
        folder = Path(temp)
        (folder / 'solution.py').write_text(code, encoding='utf-8')
        target = 'solution.py'
        if test_file is not None:
            (folder / 'test_hidden.py').write_text(test_file, encoding='utf-8')
            target = 'test_hidden.py'
        report = folder / 'report.xml'
        command = [sys.executable, '-m', 'pytest', target, '-q', '-p', 'no:cacheprovider', '--rootdir', str(folder),
                   '--junitxml', str(report), '-o', 'junit_family=xunit2', '--tb=short', '--no-header']
        try:
            done = subprocess.run(command, cwd=folder, env=_env(), capture_output=True, text=True,
                                  encoding='utf-8', errors='replace', timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return dict(ran=False, code=None, tests=0, failed=0, message=f'pytest did not finish within {TIMEOUT_S} s.')
        tests = failed = 0
        first = ''
        if report.exists():
            try:
                root = ET.parse(report).getroot()
                for case in root.iter('testcase'):
                    tests += 1
                    problem = case.find('failure')
                    if problem is None:
                        problem = case.find('error')
                    if problem is not None:
                        failed += 1
                        if not first:
                            first = f"{case.get('name')}: {problem.get('message') or ''}\n{problem.text or ''}"
            except ET.ParseError:
                pass
        output = (done.stdout or '') + (done.stderr or '')
        # 0 all passed, 1 some failed, 5 no tests collected: pytest ran. 2-4: interrupted or usage/collection error.
        ran = done.returncode in (0, 1, 5)
        return dict(ran=ran, code=done.returncode, tests=tests, failed=failed,
                    message=(first or output).strip()[-MESSAGE_LIMIT:])


def _pytest_version():
    try:
        return version('pytest')
    except PackageNotFoundError:
        return 'unavailable'


def grade_pytest(engine, request, spec, private):
    start = time.perf_counter()
    engine_version = _pytest_version()
    refusal = None
    if not engine.trusted_python:
        refusal = 'Trusted local Python is off: pytest exercises run real local Python. Enable it for this workspace (Mosaic → Python / Polars).'
    elif engine_version == 'unavailable':
        refusal = 'pytest is not installed in the Datapass runtime. Run "Datapass: Setup runtime" again.'
    checks = []
    for fixture in private.fixtures:
        if request['mode'] != 'submit' and fixture.visibility != 'visible':
            continue
        scenario = PytestScenario.model_validate(fixture.scenario)
        if refusal:
            passed, status, message = False, 'error', refusal
        elif scenario.check == 'own-tests':
            run = run_pytest(request['code'])
            status = 'success' if run['ran'] else 'error'
            passed = run['code'] == 0 and run['tests'] >= scenario.min_tests
            if passed:
                message = f"Your {run['tests']} tests pass."
            elif run['ran'] and run['failed']:
                message = f"{run['failed']} of your {run['tests']} tests fail:\n{run['message']}"
            elif run['ran']:
                message = f"Write at least {scenario.min_tests} tests (functions named test_...); found {run['tests']}."
            else:
                message = 'pytest could not run your file:\n' + run['message']
        else:
            run = run_pytest(request['code'], scenario.tests)
            status = 'success' if run['ran'] else 'error'
            passed = run['code'] == 0 and run['tests'] > 0
            message = 'Hidden tests pass.' if passed else \
                f"{run['failed']} of {run['tests']} hidden tests fail." if run['ran'] and run['tests'] else \
                'The hidden tests could not import or run your module (is it valid Python, with the requested function names?).'
        checks.append(dict(id=fixture.id, visibility=fixture.visibility, passed=passed,
                           status='passed' if passed else 'failed', execution_id=uuid.uuid4().hex,
                           execution_status=status, elapsed_ms=round((time.perf_counter() - start) * 1000, 3),
                           input_versions={}, message=message))
    return dict(status='error' if refusal else 'passed' if all(c['passed'] for c in checks) else 'failed',
                checks=checks, runs=[], truth='unsupported' if refusal else 'real',
                runtime=dict(adapter=spec.runtime, engine='pytest', engine_version=engine_version,
                             session_generation=engine.generation),
                elapsed_ms=round((time.perf_counter() - start) * 1000, 3))
