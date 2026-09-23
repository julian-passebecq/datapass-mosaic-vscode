from __future__ import annotations
import json
from pathlib import Path
import os
import re


def content_root() -> Path:
    configured = os.getenv('DATAPASS_CONTENT_ROOT')
    if configured:
        resolved = Path(configured).expanduser().resolve()
        if resolved.is_dir():
            return resolved
        raise RuntimeError(f'DATAPASS_CONTENT_ROOT does not exist or is not a directory: {resolved}')
    candidates = []
    source_root = Path(__file__).resolve().parents[2]
    candidates.extend([
        source_root / 'content',
        Path.cwd() / 'content',
        Path.cwd().parent / 'content',
    ])
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_dir():
            return resolved
    searched = ', '.join(str(candidate) for candidate in candidates)
    raise RuntimeError(f'Datapass content directory was not found. Checked: {searched}')


CONTENT = content_root()


def cases():
    return [json.loads(p.read_text()) for p in sorted((CONTENT / 'cases').glob('*.json'))]


def get_case(case_id: str):
    if not re.fullmatch(r'[a-z0-9-]{1,64}', case_id):
        raise ValueError('Invalid case ID.')
    path = CONTENT / 'cases' / f'{case_id}.json'
    if not path.exists():
        raise KeyError('Unknown case study.')
    return json.loads(path.read_text())


def compile_dbt(code: str, case: dict) -> str:
    models = {s['id']: s['output_asset'] for s in case['steps'] if s.get('output_asset')}
    def ref(match):
        name = match.group(1)
        if name not in models:
            raise ValueError(f'Unknown dbt ref: {name}')
        return models[name]
    def source(match):
        namespace, name = match.groups()
        if namespace != 'retail' or name not in {'orders', 'dim_customer_segment'}:
            raise ValueError('Only registered retail sources are available in this case.')
        return f'source.{name}'
    output = re.sub(r"{{\s*ref\(\s*['\"]([A-Za-z0-9_]+)['\"]\s*\)\s*}}", ref, code)
    output = re.sub(r"{{\s*source\(\s*['\"]([A-Za-z0-9_]+)['\"]\s*,\s*['\"]([A-Za-z0-9_]+)['\"]\s*\)\s*}}", source, output)
    if '{{' in output or '{%' in output or '{#' in output:
        raise ValueError('Unsupported Jinja. The root adapter supports literal ref() and source() only.')
    return output


def topological_steps(steps: list[dict]) -> list[dict]:
    by_id = {s['id']: s for s in steps}
    if len(by_id) != len(steps):
        raise ValueError('Duplicate step IDs.')
    result, visiting, done = [], set(), set()
    def visit(id):
        if id in visiting:
            raise ValueError('Task dependencies contain a cycle.')
        if id in done:
            return
        if id not in by_id:
            raise ValueError(f'Unknown dependency: {id}')
        visiting.add(id)
        for parent in by_id[id]['depends_on']:
            visit(parent)
        visiting.remove(id)
        done.add(id)
        result.append(by_id[id])
    for step in steps:
        visit(step['id'])
    return result
