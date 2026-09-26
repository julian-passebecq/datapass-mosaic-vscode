"""Concept checks (Practice language `quiz`): questions about what does not execute locally.

Fabric capacities, Synapse DWUs, Databricks compute, Unity Catalog, table formats: nothing runs.
The learner writes an answer line in a text file; the runtime compares it with the private
answer in grading.server.json. The answer and the explanation ("why") never leave the runtime
before a submission: a Run only checks that the answer is well formed.
"""
import re
import time
import uuid
from typing import Literal

from pydantic import Field

from .exercise_contracts import Contract

ANSWER_LINE = re.compile(r'^\s*answer\s*:(.*)$', re.IGNORECASE | re.MULTILINE)
LETTER = re.compile(r'^[a-h]$')


class QuizScenario(Contract):
    """One fixture of a concept check: `format` (visible) or `answer` (hidden, submit only)."""
    check: Literal['format', 'answer']
    kind: Literal['choice', 'text']
    choices: list[str] = Field(default_factory=list)
    correct: list[str] = Field(default_factory=list)
    accepted: list[str] = Field(default_factory=list)
    why: str = ''


def check_scenario(language, raw):
    scenario = QuizScenario.model_validate(raw)
    if scenario.kind == 'choice':
        if not scenario.choices or any(not LETTER.fullmatch(c) for c in scenario.choices):
            raise ValueError('A choice question lists its letters (a-h)')
        if scenario.check == 'answer' and (not scenario.correct or not set(scenario.correct) <= set(scenario.choices)):
            raise ValueError('A choice answer names letters among the choices')
    elif scenario.check == 'answer' and not scenario.accepted:
        raise ValueError('A short-answer question lists its accepted answers')
    if scenario.check == 'answer' and not scenario.why:
        raise ValueError('An answer fixture explains why')
    return scenario


def normalize_text(value):
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s.%-]', ' ', value.lower())).strip().rstrip('.')


def parse_answer(code):
    """The last `answer:` line's value, or None when there is none or it is empty."""
    found = ANSWER_LINE.findall(code or '')
    value = found[-1].strip() if found else ''
    return value or None


def letters(value):
    parts = [p.strip().lower().rstrip(')') for p in re.split(r'[,\s]+', value) if p.strip()]
    return parts


def grade_quiz(engine, request, spec, private):
    start = time.perf_counter()
    answer = parse_answer(request['code'])
    checks = []
    for fixture in private.fixtures:
        if request['mode'] != 'submit' and fixture.visibility != 'visible':
            continue
        scenario = QuizScenario.model_validate(fixture.scenario)
        if scenario.check == 'format':
            if answer is None:
                passed, message = False, 'No answer yet: write it after "answer:" and save.'
            elif scenario.kind == 'choice':
                given = letters(answer)
                passed = bool(given) and all(g in scenario.choices for g in given)
                message = 'The answer is well formed; Submit to check it.' if passed else \
                    'Answer with the letter of a choice (' + ', '.join(scenario.choices) + '), several separated by commas.'
            else:
                passed = len(answer) <= 200
                message = 'The answer is well formed; Submit to check it.' if passed else 'Keep the answer under 200 characters.'
        else:
            if answer is None:
                passed = False
            elif scenario.kind == 'choice':
                passed = set(letters(answer)) == set(scenario.correct)
            else:
                passed = normalize_text(answer) in {normalize_text(a) for a in scenario.accepted}
            message = ('Correct. ' + scenario.why) if passed else \
                'Not the expected answer. Read the reference sheet and try again.'
        checks.append(dict(id=fixture.id, visibility=fixture.visibility, passed=passed,
                           status='passed' if passed else 'failed', execution_id=uuid.uuid4().hex,
                           execution_status='success', elapsed_ms=0, input_versions={}, message=message))
    return dict(status='passed' if all(c['passed'] for c in checks) else 'failed',
                checks=checks, runs=[], truth='concept-check',
                runtime=dict(adapter=spec.runtime, engine='datapass-concept-check', engine_version='1',
                             session_generation=engine.generation),
                elapsed_ms=round((time.perf_counter() - start) * 1000, 3))
