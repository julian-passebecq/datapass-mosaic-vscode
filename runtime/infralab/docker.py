"""The simulated Docker engine: Dockerfile reader, BuildKit-style build with a layer cache, run, and compose.

The Dockerfile is read line by line into instructions; nothing in it is executed. `RUN` lines are text: their effect
(layer size, duration) is estimated from what they name (pip requirements, apt packages). COPY hashes the real files of
the build context after `.dockerignore`, so the layer cache behaves like BuildKit's: a step is CACHED when its parent
and its inputs did not change. Containers are records in `.infralab/world.json`; their behaviour (the port the app
listens on, the environment it needs, the health endpoint) comes from the mission's shipped app description and the
image's CMD. Nothing is built, pulled or run.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import fnmatch
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shlex
from typing import Any
from urllib.parse import urlparse

import yaml

from . import world as worldlib

BOLD, GREEN, YELLOW, RED, CYAN, DIM, RESET = '\x1b[1m', '\x1b[32m', '\x1b[33m', '\x1b[31m', '\x1b[36m', '\x1b[2m', '\x1b[0m'
FOOTER = f'{DIM}[simulated: Docker is simulated by Datapass; nothing was built, pulled or run]{RESET}'
MAX_CONTEXT_FILES = 3000
MAX_HASH_BYTES = 20_000_000

# Base images the simulated registry serves: size (MB), default user, tools in the image.
BASE_IMAGES: dict[str, dict[str, Any]] = {
    'python:3.13': {'size_mb': 1020, 'tools': ['curl', 'wget', 'bash', 'apt-get', 'pip', 'python']},
    'python:3.12': {'size_mb': 1010, 'tools': ['curl', 'wget', 'bash', 'apt-get', 'pip', 'python']},
    'python:3.12-slim': {'size_mb': 125, 'tools': ['bash', 'apt-get', 'pip', 'python']},
    'python:3.12-alpine': {'size_mb': 57, 'tools': ['sh', 'apk', 'pip', 'python']},
    'python:3.11-slim': {'size_mb': 130, 'tools': ['bash', 'apt-get', 'pip', 'python']},
    'node:20-slim': {'size_mb': 200, 'tools': ['bash', 'apt-get', 'node', 'npm']},
    'nginx:1.27-alpine': {'size_mb': 48, 'tools': ['sh', 'apk', 'curl', 'wget']},
    'postgres:16': {'size_mb': 430, 'tools': ['bash', 'pg_isready', 'psql']},
    'postgres:16-alpine': {'size_mb': 240, 'tools': ['sh', 'pg_isready', 'psql', 'wget']},
    'debian:bookworm-slim': {'size_mb': 74, 'tools': ['bash', 'apt-get']},
    'ubuntu:24.04': {'size_mb': 78, 'tools': ['bash', 'apt-get']},
    'alpine:3.20': {'size_mb': 8, 'tools': ['sh', 'apk', 'wget']},
}
LATEST = {'python': 'python:3.13', 'node': 'node:20-slim', 'nginx': 'nginx:1.27-alpine', 'postgres': 'postgres:16',
          'debian': 'debian:bookworm-slim', 'ubuntu': 'ubuntu:24.04', 'alpine': 'alpine:3.20'}
# Teaching estimates of installed package sizes (MB).
PIP_SIZES = {'pandas': 60, 'numpy': 35, 'polars': 40, 'pyarrow': 110, 'fastapi': 2, 'uvicorn': 3, 'pydantic': 8,
             'sqlalchemy': 12, 'psycopg2-binary': 10, 'psycopg': 6, 'requests': 1, 'httpx': 2, 'duckdb': 45,
             'azure-storage-blob': 9, 'azure-identity': 7, 'orjson': 1}
DOCKERFILE_INSTRUCTIONS = {'FROM', 'RUN', 'COPY', 'ADD', 'WORKDIR', 'ENV', 'ARG', 'EXPOSE', 'USER', 'CMD',
                           'ENTRYPOINT', 'HEALTHCHECK', 'LABEL', 'VOLUME', 'STOPSIGNAL', 'SHELL', 'ONBUILD'}


class DockerError(Exception):
    pass


# ---- Dockerfile ----------------------------------------------------------------------------------------------------


@dataclass
class Instruction:
    kind: str
    args: str
    flags: dict[str, str]
    line: int
    raw: str

    def exec_form(self) -> list[str] | None:
        text = self.args.strip()
        if text.startswith('['):
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                return None
            if isinstance(value, list) and all(isinstance(v, str) for v in value):
                return value
        return None


@dataclass
class Stage:
    base: str
    name: str | None
    line: int
    steps: list[Instruction] = field(default_factory=list)


def parse_dockerfile(text: str, file: str = 'Dockerfile') -> list[Stage]:
    lines = text.replace('\r\n', '\n').split('\n')
    logical: list[tuple[int, str]] = []
    buf, start = '', 0
    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        if not buf and (not stripped or stripped.startswith('#')):
            continue
        if buf and stripped.startswith('#'):
            continue
        if not buf:
            start = number
        if stripped.endswith('\\'):
            buf += stripped[:-1] + ' '
            continue
        buf += stripped
        logical.append((start, buf))
        buf = ''
    if buf:
        logical.append((start, buf))
    stages: list[Stage] = []
    for number, text_line in logical:
        parts = text_line.split(None, 1)
        kind = parts[0].upper()
        rest = parts[1] if len(parts) > 1 else ''
        if kind not in DOCKERFILE_INSTRUCTIONS:
            raise DockerError(f'{file}:{number}: unknown instruction: {parts[0]}')
        flags: dict[str, str] = {}
        while rest.startswith('--'):
            flag, _, remainder = rest.partition(' ')
            name, _, value = flag[2:].partition('=')
            flags[name] = value
            rest = remainder.strip()
        instruction = Instruction(kind, rest, flags, number, text_line)
        if kind == 'FROM':
            words = rest.split()
            if not words:
                raise DockerError(f'{file}:{number}: FROM requires an image')
            name = words[2] if len(words) == 3 and words[1].lower() == 'as' else None
            if len(words) not in (1, 3):
                raise DockerError(f'{file}:{number}: FROM takes an image and an optional AS name')
            stages.append(Stage(words[0], name, number))
            continue
        if not stages:
            if kind == 'ARG':
                continue
            raise DockerError(f'{file}:{number}: no build stage in current context: a Dockerfile starts with FROM')
        if kind in ('ONBUILD', 'SHELL'):
            raise DockerError(f'{file}:{number}: {kind} is not simulated in this lab')
        stages[-1].steps.append(instruction)
    if not stages:
        raise DockerError(f'{file}: the Dockerfile has no FROM instruction')
    return stages


def resolve_base(image: str, world: dict, stages: dict[str, 'Stage']) -> tuple[str, dict[str, Any]]:
    """The canonical base image name and its catalog entry, or a pull error."""
    catalog = {**BASE_IMAGES, **world['docker'].get('base_images', {})}
    name = image.split('@', 1)[0]
    if name in stages:
        return name, {'stage': True}
    if ':' not in name.rsplit('/', 1)[-1]:
        name += ':latest'
    repo, tag = name.rsplit(':', 1)
    if tag == 'latest' and repo in LATEST:
        return LATEST[repo], catalog[LATEST[repo]]
    if name in catalog:
        return name, catalog[name]
    for built in world['docker']['images'].values():
        if name in built.get('tags', []):
            return name, {'size_mb': built['size_mb'], 'tools': built.get('tools', []), 'local': True}
    raise DockerError(f'failed to resolve source metadata for docker.io/library/{name}: pull access denied, repository '
                      f'does not exist or may require authorization (the simulated registry serves: '
                      f'{", ".join(sorted(catalog))})')


# ---- Build context -------------------------------------------------------------------------------------------------


def dockerignore_patterns(context: Path) -> list[str]:
    path = context / '.dockerignore'
    if not path.is_file():
        return []
    patterns = []
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            patterns.append(line.rstrip('/'))
    return patterns


def ignored(relative: str, patterns: list[str]) -> bool:
    result = False
    for pattern in patterns:
        negate = pattern.startswith('!')
        body = pattern[1:] if negate else pattern
        body = body.lstrip('/')
        if body.startswith('./'):
            body = body[2:]
        if _match(relative, body):
            result = not negate
    return result


def _match(relative: str, pattern: str) -> bool:
    parts = relative.split('/')
    if '**' in pattern:
        regex = re.escape(pattern).replace(r'\*\*/', '(.*/)?').replace(r'\*\*', '.*').replace(r'\*', '[^/]*').replace(r'\?', '[^/]')
        return any(re.fullmatch(regex, '/'.join(parts[:i])) for i in range(1, len(parts) + 1))
    # A pattern matches the path or one of its parent folders (Docker excludes the folder and what it holds).
    return any(fnmatch.fnmatchcase('/'.join(parts[:i]), pattern) for i in range(1, len(parts) + 1))


def context_files(context: Path) -> dict[str, tuple[int, str]]:
    """Files sent to the builder: relative path -> (size, content hash), after .dockerignore."""
    patterns = dockerignore_patterns(context)
    out: dict[str, tuple[int, str]] = {}
    for path in sorted(context.rglob('*')):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(context).as_posix()
        if relative.startswith('.infralab/') or ignored(relative, patterns):
            continue
        size = path.stat().st_size
        digest = hashlib.sha256(path.read_bytes() if size <= MAX_HASH_BYTES else str(size).encode()).hexdigest()
        out[relative] = (size, digest)
        if len(out) > MAX_CONTEXT_FILES:
            raise DockerError(f'the build context has more than {MAX_CONTEXT_FILES} files: add a .dockerignore')
    return out


def copy_sources(step: Instruction) -> tuple[list[str], str]:
    form = step.exec_form()
    words = form if form is not None else shlex.split(step.args)
    if len(words) < 2:
        raise DockerError(f'line {step.line}: {step.kind} needs at least one source and a destination')
    return words[:-1], words[-1]


def matched_files(sources: list[str], files: dict[str, tuple[int, str]]) -> list[str]:
    out = []
    for source in sources:
        src = source[2:] if source.startswith('./') else source
        src = src.rstrip('/')
        for relative in files:
            if src in ('', '.') or relative == src or relative.startswith(src + '/') or fnmatch.fnmatchcase(relative, src):
                out.append(relative)
    return sorted(set(out))


# ---- Simulated effects of a step -----------------------------------------------------------------------------------


def requirements(context: Path, name: str) -> list[str]:
    path = (context / name).resolve()
    if not path.is_relative_to(context.resolve()) or not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        line = line.split('#', 1)[0].strip()
        if line and not line.startswith('-'):
            out.append(re.split(r'[<>=!~\[; ]', line, 1)[0].lower())
    return out


def run_effect(step: Instruction, context: Path, files: dict[str, tuple[int, str]], workdir: str) -> tuple[float, float, list[str]]:
    """(size MB, seconds, notes) of a RUN step, estimated from its text."""
    text = step.args
    size, seconds, notes = 1.0, 1.0, []
    for match in re.finditer(r'pip3? install ([^&|;]+)', text):
        words = match.group(1).split()
        packages: list[str] = []
        i = 0
        while i < len(words):
            word = words[i]
            if word in ('-r', '--requirement') and i + 1 < len(words):
                req = words[i + 1]
                req_path = str(PurePosixPath(workdir) / req)[1:] if not req.startswith('/') else req[1:]
                if req_path in files or req in files:
                    packages += requirements(context, req if req in files else req_path)
                i += 2
                continue
            if not word.startswith('-'):
                packages.append(re.split(r'[<>=!~\[]', word, 1)[0].lower())
            i += 1
        pkg_size = sum(PIP_SIZES.get(p, 5) for p in packages)
        size += pkg_size
        seconds += 3 + 2.5 * len(packages)
        if '--no-cache-dir' not in match.group(1):
            size += round(pkg_size * 0.3, 1)
            notes.append('pip keeps its download cache in the layer (add --no-cache-dir)')
    for match in re.finditer(r'apt-get install ([^&|;]+)', text):
        pkgs = [w for w in match.group(1).split() if not w.startswith('-')]
        size += 18 * len(pkgs)
        seconds += 12 + 4 * len(pkgs)
    if 'apt-get update' in text:
        seconds += 8
        if 'rm -rf /var/lib/apt/lists' not in text:
            size += 45
            notes.append('the apt package lists stay in the layer (rm -rf /var/lib/apt/lists/* in the same RUN)')
    if re.search(r'\b(useradd|adduser|addgroup|groupadd)\b', text):
        seconds += 1
    return round(size, 1), round(seconds, 1), notes


@dataclass
class BuildStep:
    number: int
    total: int
    text: str
    key: str
    cached: bool
    size_mb: float
    seconds: float
    stage: str


@dataclass
class BuildResult:
    steps: list[BuildStep]
    config: dict[str, Any]
    size_mb: float
    base: str
    context_mb: float
    context_files: int
    lint: list[tuple[str, int, str]]
    key: str
    tools: list[str]


def simulate_build(context: Path, dockerfile: Path, world: dict, build_args: dict[str, str] | None = None,
                   changed: dict[str, str] | None = None) -> BuildResult:
    """Walk the Dockerfile as BuildKit would. `changed` pretends some files have new content (for cache checks)."""
    if not dockerfile.is_file():
        raise DockerError(f'failed to read dockerfile: open {dockerfile.name}: no such file or directory')
    text = dockerfile.read_text(encoding='utf-8', errors='replace')
    stages = parse_dockerfile(text, dockerfile.name)
    files = context_files(context)
    for relative, content in (changed or {}).items():
        size = files.get(relative, (len(content), ''))[0]
        files[relative] = (size, hashlib.sha256(content.encode()).hexdigest())
    by_name = {s.name: s for s in stages if s.name}
    stage_keys: dict[str, str] = {}
    stage_sizes: dict[str, float] = {}
    total = sum(len(s.steps) + 1 for s in stages)
    number = 0
    steps: list[BuildStep] = []
    cache = set(world['docker'].get('cache', []))
    lint = lint_dockerfile(stages, context, files)
    final: dict[str, Any] = {}
    tools: list[str] = []
    size_total = 0.0
    key = ''
    base_name = ''
    for index, stage in enumerate(stages):
        base_name, entry = resolve_base(stage.base, world, stage_keys)
        if entry.get('stage'):
            key = stage_keys[base_name]
            size_total = stage_sizes[base_name]
        else:
            key = hashlib.sha256(f'FROM {base_name}'.encode()).hexdigest()
            size_total = float(entry['size_mb'])
            tools = list(entry.get('tools', []))
        number += 1
        steps.append(BuildStep(number, total, f'FROM {base_name}' + (f' AS {stage.name}' if stage.name else ''), key,
                               key in cache, 0.0, 0 if key in cache else 6.0, stage.name or str(index)))
        config: dict[str, Any] = {'user': 'root', 'workdir': '/', 'env': {}, 'exposed': [], 'cmd': None,
                                  'entrypoint': None, 'healthcheck': None}
        args: dict[str, str] = dict(build_args or {})
        for step in stage.steps:
            number += 1
            size, seconds = 0.0, 0.1
            inputs = ''
            if step.kind in ('COPY', 'ADD'):
                sources, dest = copy_sources(step)
                if 'from' in step.flags:
                    source_stage = step.flags['from']
                    if source_stage not in stage_keys:
                        raise DockerError(f'line {step.line}: COPY --from={source_stage}: no stage named '
                                          f'{source_stage} before this step')
                    inputs = stage_keys[source_stage] + json.dumps(sources)
                    size = 20.0
                else:
                    matched = matched_files(sources, files)
                    if not matched:
                        raise DockerError(f'failed to compute cache key: failed to calculate checksum of ref: '
                                          f'"/{sources[0]}": not found (is it excluded by .dockerignore?)')
                    inputs = json.dumps([(m, files[m][1]) for m in matched])
                    size = round(sum(files[m][0] for m in matched) / 1_000_000, 2)
                    seconds = 0.2 + size / 50
            elif step.kind == 'RUN':
                size, seconds, _notes = run_effect(step, context, files, config['workdir'])
            elif step.kind == 'WORKDIR':
                target = step.args.strip()
                config['workdir'] = target if target.startswith('/') else str(PurePosixPath(config['workdir']) / target)
            elif step.kind == 'ENV':
                config['env'].update(parse_env(step.args))
            elif step.kind == 'ARG':
                name, _, default = step.args.partition('=')
                args.setdefault(name.strip(), default.strip())
            elif step.kind == 'USER':
                config['user'] = step.args.strip().split(':')[0]
            elif step.kind == 'EXPOSE':
                config['exposed'] = sorted(set(config['exposed']) | {p.split('/')[0] for p in step.args.split()})
            elif step.kind in ('CMD', 'ENTRYPOINT'):
                form = step.exec_form()
                config[step.kind.lower()] = form if form is not None else ['/bin/sh', '-c', step.args]
            elif step.kind == 'HEALTHCHECK':
                config['healthcheck'] = parse_healthcheck(step)
            key = hashlib.sha256((key + step.raw + inputs).encode()).hexdigest()
            cached = key in cache
            steps.append(BuildStep(number, total, f'{step.kind} {step.args}'.strip(), key, cached,
                                   size, 0.0 if cached else seconds, stage.name or str(index)))
            size_total += size
        if stage.name:
            stage_keys[stage.name] = key
            stage_sizes[stage.name] = size_total
        final = config
    context_bytes = sum(size for size, _ in files.values())
    return BuildResult(steps, final, round(size_total, 1), base_name, round(context_bytes / 1_000_000, 2), len(files),
                       lint, key, tools)


def parse_env(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        words = shlex.split(text)
    except ValueError:
        words = text.split()
    if words and '=' not in words[0]:
        return {words[0]: ' '.join(words[1:])}
    for word in words:
        name, _, value = word.partition('=')
        out[name] = value
    return out


def parse_healthcheck(step: Instruction) -> dict[str, Any] | None:
    text = step.args.strip()
    if text.upper() == 'NONE':
        return None
    if not text.upper().startswith('CMD'):
        raise DockerError(f'line {step.line}: HEALTHCHECK needs CMD (or NONE)')
    rest = text[3:].strip()
    form = Instruction('CMD', rest, {}, step.line, rest).exec_form()
    command = ' '.join(form) if form else rest
    return {'test': command, 'interval': step.flags.get('interval', '30s'), 'retries': step.flags.get('retries', '3'),
            'start_period': step.flags.get('start-period', '0s')}


# ---- Lint ------------------------------------------------------------------------------------------------------------

SECRET_NAME = re.compile(r'(PASSWORD|PASSWD|SECRET|TOKEN|API_?KEY|ACCESS_?KEY)', re.I)


def lint_dockerfile(stages: list[Stage], context: Path, files: dict[str, tuple[int, str]]) -> list[tuple[str, int, str]]:
    """Findings as (rule, line, message). DL rule ids follow hadolint's; DP rules are the lab's own."""
    out: list[tuple[str, int, str]] = []
    final = stages[-1]
    for stage in stages:
        image = stage.base.split('@')[0]
        if not any(s.name == image for s in stages) and (':' not in image.rsplit('/', 1)[-1] or image.endswith(':latest')):
            out.append(('DL3007', stage.line, f'{image}: pin a version tag instead of latest'))
        dependency_step = None
        first_broad_copy = None
        for step in stage.steps:
            text = step.args
            if step.kind == 'RUN':
                if re.search(r'pip3? install', text) and '--no-cache-dir' not in text:
                    out.append(('DL3042', step.line, 'pip install without --no-cache-dir keeps the download cache'))
                if 'apt-get update' in text and 'rm -rf /var/lib/apt/lists' not in text:
                    out.append(('DL3009', step.line, 'delete the apt lists after installing (rm -rf /var/lib/apt/lists/*)'))
                if re.search(r'pip3? install|npm (ci|install)|apt-get install', text) and dependency_step is None:
                    dependency_step = step
            if step.kind in ('COPY', 'ADD') and 'from' not in step.flags:
                sources, _ = copy_sources(step)
                if any(s in ('.', './', '*') for s in sources) and first_broad_copy is None:
                    first_broad_copy = step
            if step.kind == 'ADD' and not re.search(r'\.(tar|tgz|tar\.gz|zip)\b', text):
                out.append(('DL3020', step.line, 'use COPY instead of ADD for files and folders'))
            if step.kind in ('CMD', 'ENTRYPOINT') and step.exec_form() is None:
                out.append(('DL3025', step.line, f'use the JSON (exec) form for {step.kind}, so signals reach the app'))
            if step.kind in ('ENV', 'ARG'):
                for name, value in (parse_env(text).items() if step.kind == 'ENV' else [tuple(text.partition('=')[::2])]):
                    if SECRET_NAME.search(name) and value:
                        out.append(('DP003', step.line, f'{name} puts a secret in the image: pass it at run time'))
        if first_broad_copy and dependency_step and first_broad_copy.line < dependency_step.line and stage is final:
            out.append(('DP001', first_broad_copy.line, 'the whole project is copied before the dependencies are '
                                                        'installed: any code change re-runs the install'))
    users = [s for s in final.steps if s.kind == 'USER']
    if not users or users[-1].args.strip().split(':')[0] in ('root', '0'):
        out.append(('DL3002', users[-1].line if users else final.line, 'the image runs as root: add a USER'))
    if not (context / '.dockerignore').is_file():
        out.append(('DP002', 0, 'no .dockerignore: everything in the folder is sent to the builder'))
    if not any(s.kind == 'HEALTHCHECK' for s in final.steps):
        out.append(('DP004', 0, 'no HEALTHCHECK: Docker cannot tell a running container from a working one'))
    return sorted(out, key=lambda item: (item[1], item[0]))


# ---- Images and containers -------------------------------------------------------------------------------------------


def normalize_tag(tag: str) -> str:
    return tag if ':' in tag.rsplit('/', 1)[-1] else tag + ':latest'


def find_image(world: dict, ref: str) -> dict | None:
    ref = normalize_tag(ref)
    for image in world['docker']['images'].values():
        if ref in image['tags']:
            return image
    for image_id, image in world['docker']['images'].items():
        if image_id.startswith(ref.replace('sha256:', '').split(':')[0]) and len(ref) >= 8:
            return image
    return None


def build(folder: Path, args: list[str], world: dict) -> tuple[str, int, dict]:
    tags, dockerfile_name, context_arg, build_args, no_cache = [], None, None, {}, False
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ('-t', '--tag') and i + 1 < len(args):
            tags.append(args[i + 1]); i += 2; continue
        if arg.startswith('--tag=') or arg.startswith('-t='):
            tags.append(arg.split('=', 1)[1]); i += 1; continue
        if arg in ('-f', '--file') and i + 1 < len(args):
            dockerfile_name = args[i + 1]; i += 2; continue
        if arg == '--build-arg' and i + 1 < len(args):
            name, _, value = args[i + 1].partition('='); build_args[name] = value; i += 2; continue
        if arg == '--no-cache':
            no_cache = True; i += 1; continue
        if arg.startswith('-'):
            raise DockerError(f'unknown flag: {arg} (the lab simulates -t, -f, --build-arg, --no-cache)')
        context_arg = arg
        i += 1
    if context_arg is None:
        raise DockerError('"docker buildx build" requires exactly 1 argument.\nUsage:  docker build [OPTIONS] PATH\n'
                          'Hint: the build context is usually "." (the current folder).')
    context = confined(folder, context_arg)
    if not context.is_dir():
        raise DockerError(f'unable to prepare context: path "{context_arg}" not found')
    dockerfile = confined(folder, dockerfile_name) if dockerfile_name else context / 'Dockerfile'
    if no_cache:
        world['docker']['cache'] = []
    for tag in tags:
        if not re.fullmatch(r'[a-z0-9][a-z0-9._/-]*(:[A-Za-z0-9_][A-Za-z0-9_.-]{0,127})?', tag):
            raise DockerError(f'invalid tag "{tag}": repository name must be lowercase')
    result = simulate_build(context, dockerfile, world, build_args)
    seconds = sum(s.seconds for s in result.steps) + 0.4
    lines = [f'{BOLD}[+] Building {seconds:.1f}s ({len(result.steps) + 2}/{len(result.steps) + 2}) FINISHED{RESET}',
             f' => {f"[internal] load build definition from {dockerfile.name}".ljust(70)} 0.0s',
             f' => {"[internal] load .dockerignore".ljust(70)} 0.0s',
             f' => {"[internal] load build context".ljust(70)} 0.1s',
             f' => => transferring context: {result.context_mb:.2f}MB ({result.context_files} files)']
    single = len({s.stage for s in result.steps}) == 1
    for step in result.steps:
        stage = '' if single and step.stage.isdigit() else (step.stage if not step.stage.isdigit() else f'stage-{step.stage}') + ' '
        label = f'[{stage}{step.number}/{step.total}] {step.text}'
        label = label if len(label) < 70 else label[:67] + '...'
        prefix = f'{CYAN}CACHED{RESET} ' if step.cached else ''
        lines.append(f' => {prefix}{label.ljust(70)} {step.seconds:.1f}s')
    image_id = result.key[:12]
    lines.append(' => exporting to image')
    lines.append(f' => => writing image sha256:{result.key[:64]}')
    for tag in tags:
        lines.append(f' => => naming to docker.io/library/{normalize_tag(tag)}')
    if result.lint:
        lines.append('')
        lines.append(f'{YELLOW}{len(result.lint)} lint finding(s) (DL ids follow hadolint; DP are the lab\'s own):{RESET}')
        for rule, line, message in result.lint:
            where = f'Dockerfile:{line} ' if line else ''
            lines.append(f'  {YELLOW}{rule}{RESET} {where}{message}')
    dockerfile_hash = hashlib.sha256(dockerfile.read_bytes()).hexdigest()
    image = {
        'id': image_id, 'tags': [normalize_tag(t) for t in tags], 'size_mb': result.size_mb, 'base': result.base,
        'created': world['clock'], 'config': result.config, 'tools': result.tools,
        'dockerfile': dockerfile.relative_to(folder.resolve()).as_posix() if dockerfile.is_relative_to(folder.resolve()) else dockerfile.name,
        'dockerfile_sha256': dockerfile_hash, 'context': context_arg,
        'layers': [{'step': s.text, 'size_mb': s.size_mb, 'cached': s.cached} for s in result.steps],
        'lint': [list(item) for item in result.lint],
    }
    for other in world['docker']['images'].values():
        other['tags'] = [t for t in other['tags'] if t not in image['tags']]
    world['docker']['images'] = {k: v for k, v in world['docker']['images'].items() if v['tags'] or k == image_id}
    world['docker']['images'][image_id] = image
    world['docker']['cache'] = sorted(set(world['docker'].get('cache', [])) | {s.key for s in result.steps})[-500:]
    worldlib.advance(world, seconds)
    summary = {'image': image_id, 'tags': image['tags'], 'cached_steps': sum(s.cached for s in result.steps),
               'steps': len(result.steps), 'size_mb': result.size_mb}
    return '\n'.join(lines) + '\n', 0, summary


def confined(folder: Path, relative: str) -> Path:
    path = (folder / relative).resolve()
    if not path.is_relative_to(folder.resolve()):
        raise DockerError(f'{relative}: the lab only reads files inside the mission folder')
    return path


# ---- App behaviour ---------------------------------------------------------------------------------------------------


def listening(config: dict, command: list[str] | None = None) -> tuple[str, int] | None:
    """The (host, port) the image's command listens on, read from uvicorn/gunicorn/http.server arguments."""
    argv = command or ((config.get('entrypoint') or []) + (config.get('cmd') or []))
    text = ' '.join(argv)
    host, port = '127.0.0.1', None
    if 'uvicorn' in text:
        port = 8000
        m = re.search(r'--host[= ](\S+)', text)
        host = m.group(1) if m else '127.0.0.1'
        m = re.search(r'--port[= ](\d+)', text)
        port = int(m.group(1)) if m else 8000
    elif 'gunicorn' in text:
        m = re.search(r'(?:-b|--bind)[= ](\S+):(\d+)', text)
        host, port = (m.group(1), int(m.group(2))) if m else ('127.0.0.1', 8000)
    elif 'http.server' in text:
        m = re.search(r'http\.server\s+(\d+)', text)
        host, port = '0.0.0.0', int(m.group(1)) if m else 8000
    elif 'postgres' in text or 'docker-entrypoint.sh' in text:
        host, port = '0.0.0.0', 5432
    if port is None:
        return None
    return host.strip('"\''), port


def app_for(world: dict, image: dict | None, image_ref: str) -> dict[str, Any]:
    apps = world['docker'].get('apps', {})
    repo = normalize_tag(image_ref).rsplit(':', 1)[0].split('/')[-1]
    if repo in apps:
        return apps[repo]
    base = (image or {}).get('base', normalize_tag(image_ref))
    if base.startswith('postgres'):
        return {'kind': 'postgres', 'requires_env': ['POSTGRES_PASSWORD'], 'health_path': None, 'ready_after_s': 6}
    return apps.get('*', {})


def health_status(container: dict, image: dict | None, healthcheck: dict | None, app: dict, listen: tuple[str, int] | None) -> tuple[str | None, str]:
    """(health, reason) of a running container, from its HEALTHCHECK and the app's behaviour."""
    if not healthcheck:
        return None, ''
    test = healthcheck['test']
    tools = (image or {}).get('tools') or BASE_IMAGES.get((image or {}).get('base', ''), {}).get('tools', [])
    if app.get('kind') == 'postgres':
        if 'pg_isready' in test:
            return 'healthy', ''
        return 'unhealthy', 'the health check does not ask postgres whether it is ready (pg_isready)'
    first = re.split(r'\s+', test.replace('CMD-SHELL', '').replace('CMD', '').strip())[0] if test.strip() else ''
    if first in ('curl', 'wget') and first not in tools:
        return 'unhealthy', f'/bin/sh: 1: {first}: not found (the image has no {first})'
    m = re.search(r'https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0)(?::(\d+))?(/[^\s"\')]*)?', test)
    if not m:
        return 'unhealthy', 'the health check does not call the app over HTTP'
    port = int(m.group(1) or 80)
    path = m.group(2) or '/'
    if listen is None or port != listen[1]:
        return 'unhealthy', f'connection refused on port {port}: the app listens on {listen[1] if listen else "no port"}'
    if app.get('health_path') and path != app['health_path']:
        return 'unhealthy', f'GET {path} returned 404: the app answers its health on {app["health_path"]}'
    return 'healthy', ''


def start_container(world: dict, name: str, image_ref: str, image: dict | None, ports: list[tuple[int, int]],
                    env: dict[str, str], command: list[str] | None = None, healthcheck: dict | None = None,
                    network: dict[str, dict] | None = None, service: str | None = None,
                    project: str | None = None) -> dict:
    config = (image or {}).get('config', {})
    merged_env = {**config.get('env', {}), **env}
    app = app_for(world, image, image_ref)
    listen = listening(config, command) if image else None
    if app.get('kind') == 'postgres':
        listen = ('0.0.0.0', 5432)
    elif app.get('listens'):
        listen = ('0.0.0.0', int(app['listens']))
    connects_to = None
    logs: list[str] = []
    status, exit_code = 'running', None
    missing = [v for v in app.get('requires_env', []) if not merged_env.get(v)]
    if missing:
        status, exit_code = 'exited', 1
        logs += app.get('missing_env_log', [f'KeyError: \'{missing[0]}\'', f'{missing[0]} is not set: the app cannot start.'])
    elif app.get('connects_env'):
        url = merged_env.get(app['connects_env'], '')
        parsed = urlparse(url)
        target = (network or {}).get(parsed.hostname or '')
        if parsed.hostname in ('localhost', '127.0.0.1'):
            status, exit_code = 'exited', 1
            logs += [f'Connecting to {parsed.hostname}:{parsed.port or 5432}...',
                     f'psycopg.OperationalError: connection to server at "{parsed.hostname}", port {parsed.port or 5432} '
                     'failed: Connection refused', 'Inside a container, localhost is the container itself.']
        elif target is None:
            status, exit_code = 'exited', 1
            logs += [f'psycopg.OperationalError: could not translate host name "{parsed.hostname}" to address: '
                     'Name or service not known']
        elif target.get('health') not in ('healthy', None) or not target.get('ready'):
            status, exit_code = 'exited', 1
            logs += [f'psycopg.OperationalError: connection to server at "{parsed.hostname}", port {parsed.port or 5432} '
                     'failed: the database system is starting up']
        else:
            connects_to = target['name']
    if status == 'running':
        logs += app.get('start_log', [])
        if listen:
            logs.append(f'INFO:     Uvicorn running on http://{listen[0]}:{listen[1]} (Press CTRL+C to quit)'
                        if 'uvicorn' in ' '.join((config.get('cmd') or []) + (command or [])) else
                        f'listening on {listen[0]}:{listen[1]}')
    hc = healthcheck if healthcheck is not None else config.get('healthcheck')
    health, reason = (None, '')
    if status == 'running':
        health, reason = health_status({}, image, hc, app, listen)
        if reason:
            logs.append(f'[health check] {reason}')
    container = {
        'name': name, 'image': normalize_tag(image_ref), 'image_id': (image or {}).get('id'), 'status': status,
        'exit_code': exit_code, 'health': health, 'health_reason': reason, 'ports': [list(p) for p in ports],
        'env': sorted(merged_env), 'listen': list(listen) if listen else None, 'user': config.get('user', 'root'),
        'started_at': world['clock'], 'logs': logs, 'service': service, 'project': project,
        'ready': status == 'running', 'connects_to': connects_to,
    }
    world['docker']['containers'][name] = container
    return container


def parse_ports(specs: list[str]) -> list[tuple[int, int]]:
    out = []
    for spec in specs:
        parts = str(spec).split(':')
        if len(parts) == 3:
            parts = parts[1:]
        if len(parts) == 1:
            out.append((int(parts[0].split('/')[0]), int(parts[0].split('/')[0])))
        else:
            out.append((int(parts[0]), int(parts[1].split('/')[0])))
    return out


def port_in_use(world: dict, host_port: int, except_name: str | None = None) -> str | None:
    for container in world['docker']['containers'].values():
        if container['name'] != except_name and container['status'] == 'running' and any(p[0] == host_port for p in container['ports']):
            return container['name']
    return None


def run(folder: Path, args: list[str], world: dict) -> tuple[str, int, dict]:
    name, ports, env, detach, image_ref, command = None, [], {}, False, None, []
    i = 0
    while i < len(args):
        arg = args[i]
        if image_ref is not None:
            command.append(arg); i += 1; continue
        if arg in ('-d', '--detach', '--rm', '-it', '-i', '-t'):
            detach = detach or arg in ('-d', '--detach'); i += 1; continue
        if arg == '--name' and i + 1 < len(args):
            name = args[i + 1]; i += 2; continue
        if arg in ('-p', '--publish') and i + 1 < len(args):
            ports.append(args[i + 1]); i += 2; continue
        if arg in ('-e', '--env') and i + 1 < len(args):
            k, _, v = args[i + 1].partition('='); env[k] = v; i += 2; continue
        if arg.startswith('-'):
            raise DockerError(f'unknown flag: {arg} (the lab simulates -d, --name, -p, -e, --rm)')
        image_ref = arg
        i += 1
    if image_ref is None:
        raise DockerError('"docker run" requires at least 1 argument: the image')
    image = find_image(world, image_ref)
    if image is None:
        raise DockerError(f"Unable to find image '{normalize_tag(image_ref)}' locally\ndocker: Error response from "
                          f"daemon: pull access denied for {image_ref.split(':')[0]}, repository does not exist or may "
                          'require \'docker login\'. Build it first: docker build -t <name:tag> .')
    parsed = parse_ports(ports)
    name = name or f'{image_ref.split(":")[0].split("/")[-1]}_{len(world["docker"]["containers"]) + 1}'
    if name in world['docker']['containers']:
        raise DockerError(f'docker: Error response from daemon: Conflict. The container name "/{name}" is already in '
                          f'use. Remove it first (docker rm -f {name}).')
    for host, _ in parsed:
        other = port_in_use(world, host)
        if other:
            raise DockerError(f'docker: Error response from daemon: Bind for 0.0.0.0:{host} failed: port is already '
                              f'allocated (by {other}).')
    container = start_container(world, name, image_ref, image, parsed, env, command or None)
    worldlib.advance(world, 2)
    out = (container['image_id'] or '') + hashlib.sha256(name.encode()).hexdigest()[:52] if detach else '\n'.join(container['logs'])
    if container['status'] == 'exited' and detach:
        out += f'\n{DIM}(the container exited with code {container["exit_code"]}: docker logs {name}){RESET}'
    return out + '\n', 0, {'container': name, 'status': container['status']}


def ps(world: dict, show_all: bool) -> str:
    rows = [('CONTAINER ID', 'IMAGE', 'STATUS', 'PORTS', 'NAMES')]
    for container in world['docker']['containers'].values():
        if container['status'] != 'running' and not show_all:
            continue
        status = ('Up' + (f' ({container["health"]})' if container['health'] else '') if container['status'] == 'running'
                  else f'Exited ({container["exit_code"]})')
        ports = ', '.join(f'0.0.0.0:{h}->{c}/tcp' for h, c in container['ports'])
        cid = hashlib.sha256(container['name'].encode()).hexdigest()[:12]
        rows.append((cid, container['image'], status, ports, container['name']))
    return table(rows)


def table(rows: list[tuple]) -> str:
    widths = [max(len(str(r[i])) for r in rows) for i in range(len(rows[0]))]
    return '\n'.join('   '.join(str(v).ljust(w) for v, w in zip(row, widths)).rstrip() for row in rows) + '\n'


def images(world: dict) -> str:
    rows = [('REPOSITORY', 'TAG', 'IMAGE ID', 'CREATED', 'SIZE')]
    for image in world['docker']['images'].values():
        for tag in image['tags'] or ['<none>:<none>']:
            repo, _, t = tag.rpartition(':')
            rows.append((repo, t, image['id'], image['created'], f'{image["size_mb"]:.0f}MB'))
    return table(rows)


def history(world: dict, ref: str) -> str:
    image = find_image(world, ref)
    if image is None:
        raise DockerError(f'Error response from daemon: No such image: {ref}')
    rows = [('SIZE', 'CREATED BY')]
    for layer in reversed(image['layers']):
        rows.append((f'{layer["size_mb"]:.1f}MB', layer['step'][:90]))
    return table(rows)


def curl(world: dict, url: str) -> tuple[str, int]:
    parsed = urlparse(url if '://' in url else 'http://' + url)
    if parsed.hostname not in ('localhost', '127.0.0.1'):
        return f'curl: (6) Could not resolve host: {parsed.hostname} (the simulated shell only reaches localhost)\n', 6
    port = parsed.port or 80
    for container in world['docker']['containers'].values():
        mapping = next((p for p in container['ports'] if p[0] == port), None)
        if mapping is None or container['status'] != 'running':
            continue
        if container.get('networks') and all(n in internal_networks(world) for n in container['networks']):
            return (f'curl: (7) Failed to connect to localhost port {port}: Connection refused\n{DIM}('
                    f'{container["name"]} is only on internal networks: Docker publishes no port for it){RESET}\n'), 7
        listen = container.get('listen')
        if not listen or listen[1] != mapping[1]:
            return f'curl: (56) Recv failure: Connection reset by peer\n{DIM}(nothing listens on port {mapping[1]} in {container["name"]}){RESET}\n', 56
        if listen[0] in ('127.0.0.1', 'localhost'):
            return (f'curl: (56) Recv failure: Connection reset by peer\n{DIM}(the app in {container["name"]} listens on '
                    f'{listen[0]}, which is the container\'s own loopback: bind 0.0.0.0){RESET}\n'), 56
        app = app_for(world, None, container['image'])
        path = parsed.path or '/'
        if app.get('health_path') and path == app['health_path']:
            return '{"status":"ok"}\n', 0
        routes = app.get('routes', {})
        if path in routes:
            return routes[path] + '\n', 0
        if path in (app.get('writes') or {}) or path in (app.get('reads') or []):
            db = world['docker']['containers'].get(container.get('connects_to') or '')
            if db is None or db['status'] != 'running':
                return ('{"detail":"database unavailable"}\n' + f'{DIM}(HTTP 503: the app lost its database){RESET}\n'), 22
            store = data_store(world, db)
            if path in (app.get('writes') or {}):
                added = int(app['writes'][path])
                store['rows'] = int(store.get('rows', 0)) + added
                return json.dumps({'ingested': added, 'total_rows': store['rows']}) + '\n', 0
            return json.dumps({'rows': int(store.get('rows', 0)), 'database': db['service'] or db['name']}) + '\n', 0
        return '{"detail":"Not Found"}\n', 0
    return f'curl: (7) Failed to connect to localhost port {port}: Connection refused\n', 7


# ---- Compose ---------------------------------------------------------------------------------------------------------

COMPOSE_FILES = ('compose.yaml', 'compose.yml', 'docker-compose.yml', 'docker-compose.yaml')


def load_compose(folder: Path) -> tuple[str, dict]:
    for name in COMPOSE_FILES:
        path = folder / name
        if path.is_file():
            try:
                data = yaml.safe_load(path.read_text(encoding='utf-8'))
            except yaml.YAMLError as error:
                raise DockerError(f'{name}: {error}') from None
            if not isinstance(data, dict) or not isinstance(data.get('services'), dict):
                raise DockerError(f'{name}: a compose file needs a services: mapping')
            return name, data
    raise DockerError('no configuration file provided: not found (compose.yaml, docker-compose.yml)')


def compose_env(service: dict) -> dict[str, str]:
    env = service.get('environment') or {}
    if isinstance(env, list):
        out = {}
        for item in env:
            k, _, v = str(item).partition('=')
            out[k] = v
        return out
    return {str(k): '' if v is None else str(v) for k, v in env.items()}


def compose_depends(service: dict) -> dict[str, str]:
    deps = service.get('depends_on') or {}
    if isinstance(deps, list):
        return {str(d): 'service_started' for d in deps}
    return {str(k): str((v or {}).get('condition', 'service_started')) for k, v in deps.items()}


def compose_healthcheck(service: dict) -> dict | None:
    hc = service.get('healthcheck')
    if not isinstance(hc, dict) or hc.get('disable'):
        return None
    test = hc.get('test')
    if isinstance(test, list):
        test = ' '.join(str(t) for t in test)
    return {'test': str(test or ''), 'interval': str(hc.get('interval', '30s')), 'retries': str(hc.get('retries', 3)),
            'start_period': str(hc.get('start_period', '0s'))}


def compose_resources(data: dict, project: str) -> tuple[dict[str, dict], dict[str, dict]]:
    """The project's networks and named volumes, by their Docker name (<project>_<name>)."""
    networks: dict[str, dict] = {f'{project}_default': {'project': project, 'name': 'default', 'internal': False}}
    for name, spec in (data.get('networks') or {}).items():
        spec = spec or {}
        if not isinstance(spec, dict):
            raise DockerError(f'networks.{name} must be a mapping')
        unknown = set(spec) - {'driver', 'internal', 'name', 'labels', 'attachable'}
        if unknown:
            raise DockerError(f'networks.{name} Additional property {sorted(unknown)[0]} is not allowed '
                              '(the lab simulates driver, internal, name, labels)')
        if spec.get('driver', 'bridge') != 'bridge':
            raise DockerError(f'networks.{name}: the lab simulates bridge networks only')
        networks[f'{project}_{name}'] = {'project': project, 'name': str(name), 'internal': bool(spec.get('internal'))}
    volumes: dict[str, dict] = {}
    for name, spec in (data.get('volumes') or {}).items():
        spec = spec or {}
        if not isinstance(spec, dict):
            raise DockerError(f'volumes.{name} must be a mapping')
        if spec.get('external'):
            raise DockerError(f'volumes.{name}: external volumes are not simulated: declare it in this file')
        volumes[f'{project}_{name}'] = {'project': project, 'name': str(name), 'driver': spec.get('driver', 'local')}
    return networks, volumes


def service_plan(name: str, service: dict, networks: dict, volumes: dict, project: str, folder: Path) -> dict:
    """A service's networks and mounts, checked against the top-level declarations as compose does."""
    wanted = service.get('networks')
    if wanted is None:
        attached = ['default']
    elif isinstance(wanted, list):
        attached = [str(n) for n in wanted]
    elif isinstance(wanted, dict):
        attached = [str(n) for n in wanted]
    else:
        raise DockerError(f'services.{name}.networks must be a list or a mapping')
    for net in attached:
        if f'{project}_{net}' not in networks:
            raise DockerError(f'service "{name}" refers to undefined network {net}: invalid compose project')
    mounts = []
    for entry in service.get('volumes') or []:
        if isinstance(entry, dict):
            kind = entry.get('type', 'volume')
            source, target, read_only = entry.get('source'), entry.get('target'), bool(entry.get('read_only'))
        else:
            parts = str(entry).split(':')
            if len(parts) == 1:
                kind, source, target, read_only = 'volume', None, parts[0], False
            else:
                source, target = parts[0], parts[1]
                read_only = len(parts) > 2 and 'ro' in parts[2].split(',')
                kind = 'bind' if source.startswith(('.', '/', '~')) or re.match(r'^[A-Za-z]:\\', source) else 'volume'
        if not target or not str(target).startswith('/'):
            raise DockerError(f'services.{name}.volumes: the target of {entry!r} must be an absolute path in the '
                              'container')
        if kind == 'volume' and source:
            if f'{project}_{source}' not in volumes:
                raise DockerError(f'service "{name}" refers to undefined volume {source}: invalid compose project')
            mounts.append({'type': 'volume', 'source': f'{project}_{source}', 'target': str(target).rstrip('/'),
                           'read_only': read_only})
        elif kind == 'bind':
            confined(folder, str(source).lstrip('~'))
            mounts.append({'type': 'bind', 'source': str(source), 'target': str(target).rstrip('/'),
                           'read_only': read_only})
        else:
            mounts.append({'type': 'volume', 'source': None, 'target': str(target).rstrip('/'), 'read_only': False})
    return {'networks': [f'{project}_{n}' for n in attached], 'mounts': mounts}


POSTGRES_DATA = '/var/lib/postgresql/data'


def data_store(world: dict, container: dict) -> dict:
    """Where a database container keeps its data: a named volume or a bind mount on its data directory, else the
    image's anonymous volume, which lives and dies with the container."""
    for mount in container.get('mounts') or []:
        if mount['target'] in (POSTGRES_DATA, '/var/lib/postgresql') and mount['source']:
            if mount['type'] == 'volume':
                return world['docker'].setdefault('volumes', {}).setdefault(mount['source'], {'data': {}})['data']
            return world['docker'].setdefault('binds', {}).setdefault(mount['source'], {})
    return container.setdefault('data', {})


def describe_store(container: dict) -> str:
    for mount in container.get('mounts') or []:
        if mount['target'] in (POSTGRES_DATA, '/var/lib/postgresql') and mount['source']:
            return f'volume {mount["source"]}' if mount['type'] == 'volume' else f'bind mount {mount["source"]}'
    return 'an anonymous volume: it goes away with the container'


def internal_networks(world: dict) -> set[str]:
    return {n for n, spec in world['docker'].get('networks', {}).items() if spec.get('internal')}


def volume_command(args: list[str], world: dict) -> tuple[str, int, dict]:
    volumes = world['docker'].setdefault('volumes', {})
    if args[:1] == ['ls']:
        rows = [('DRIVER', 'VOLUME NAME')] + [(v.get('driver', 'local'), n) for n, v in sorted(volumes.items())]
        return table(rows), 0, {}
    if args[:1] == ['rm'] and args[1:]:
        for name in args[1:]:
            if name not in volumes:
                raise DockerError(f'Error response from daemon: get {name}: no such volume')
            users = [c['name'] for c in world['docker']['containers'].values()
                     if any(m['source'] == name for m in c.get('mounts') or [])]
            if users:
                raise DockerError(f'Error response from daemon: remove {name}: volume is in use - [{users[0]}]')
            del volumes[name]
        return '\n'.join(args[1:]) + '\n', 0, {}
    if args[:1] == ['inspect'] and args[1:]:
        name = args[1]
        if name not in volumes:
            raise DockerError(f'Error: No such volume: {name}')
        v = volumes[name]
        return json.dumps([{'Name': name, 'Driver': v.get('driver', 'local'), 'Mountpoint':
                            f'/var/lib/docker/volumes/{name}/_data', 'Labels': {'com.docker.compose.project':
                            v.get('project'), 'com.docker.compose.volume': v.get('name')}, 'CreatedAt':
                            v.get('created_at')}], indent=4) + '\n', 0, {}
    raise DockerError('Usage: docker volume ls | rm NAME | inspect NAME')


def network_command(args: list[str], world: dict) -> tuple[str, int, dict]:
    networks = world['docker'].setdefault('networks', {})
    if args[:1] == ['ls']:
        rows = [('NETWORK ID', 'NAME', 'DRIVER', 'SCOPE'), ('3f1c0b6e2a9d', 'bridge', 'bridge', 'local')]
        rows += [(hashlib.sha256(n.encode()).hexdigest()[:12], n, 'bridge', 'local') for n in sorted(networks)]
        return table(rows), 0, {}
    if args[:1] == ['inspect'] and args[1:]:
        name = args[1]
        if name not in networks:
            raise DockerError(f'Error response from daemon: network {name} not found')
        members = {c['name']: {'Name': c['name']} for c in world['docker']['containers'].values()
                   if name in (c.get('networks') or [])}
        return json.dumps([{'Name': name, 'Driver': 'bridge', 'Internal': bool(networks[name].get('internal')),
                            'Containers': members}], indent=4) + '\n', 0, {}
    raise DockerError('Usage: docker network ls | inspect NAME')


def compose(folder: Path, args: list[str], world: dict) -> tuple[str, int, dict]:
    if not args:
        raise DockerError('Usage: docker compose up [-d] [--build] | ps | down [-v] | logs [SERVICE]')
    sub, rest = args[0], args[1:]
    project = re.sub(r'[^a-z0-9_-]', '', folder.name.lower()) or 'app'
    containers = world['docker']['containers']
    if sub == 'ps':
        rows = [('NAME', 'SERVICE', 'STATUS', 'PORTS')]
        for c in containers.values():
            if c.get('project') == project:
                status = ('Up' + (f' ({c["health"]})' if c['health'] else '')) if c['status'] == 'running' else f'Exited ({c["exit_code"]})'
                rows.append((c['name'], c['service'], status, ', '.join(f'0.0.0.0:{h}->{p}/tcp' for h, p in c['ports'])))
        return table(rows), 0, {}
    if sub == 'down':
        names = [n for n, c in containers.items() if c.get('project') == project]
        lines = []
        for n in names:
            lines.append(f' ✔ Container {n}  Removed')
            del containers[n]
        networks = world['docker'].setdefault('networks', {})
        for net in sorted(n for n, v in networks.items() if v.get('project') == project):
            lines.append(f' ✔ Network {net}  Removed')
            del networks[net]
        if not names and not lines:
            lines.append(f' ✔ Network {project}_default  Removed')
        volumes = world['docker'].setdefault('volumes', {})
        removed_volumes = 0
        if '-v' in rest or '--volumes' in rest:
            for vol in sorted(v for v, spec in volumes.items() if spec.get('project') == project):
                lines.append(f' ✔ Volume {vol}  Removed')
                del volumes[vol]
                removed_volumes += 1
        worldlib.advance(world, 2)
        return '\n'.join(lines) + '\n', 0, {'removed': len(names), 'volumes_removed': removed_volumes}
    if sub == 'logs':
        out = []
        for c in containers.values():
            if c.get('project') == project and (not rest or c['service'] in rest):
                out += [f'{c["service"]}  | {line}' for line in c['logs']]
        return '\n'.join(out) + '\n', 0, {}
    if sub != 'up':
        raise DockerError(f'docker compose {sub} is not simulated (up, ps, down, logs)')
    rebuild = '--build' in rest
    file_name, data = load_compose(folder)
    services: dict[str, dict] = data['services']
    declared_networks, declared_volumes = compose_resources(data, project)
    plans = {name: service_plan(name, services[name] or {}, declared_networks, declared_volumes, project, folder)
             for name in services}
    order: list[str] = []
    seen: dict[str, int] = {}

    def visit(name: str) -> None:
        if seen.get(name) == 2:
            return
        if seen.get(name) == 1:
            raise DockerError(f'dependency cycle detected at service {name}')
        if name not in services:
            raise DockerError(f'service "{name}" depends on undefined service')
        seen[name] = 1
        for dep in compose_depends(services[name] or {}):
            visit(dep)
        seen[name] = 2
        order.append(name)

    for name in services:
        visit(name)
    lines: list[str] = []
    networks = world['docker'].setdefault('networks', {})
    used = {n for plan in plans.values() for n in plan['networks']}
    for net, spec in declared_networks.items():
        if net not in used:
            continue
        if net not in networks:
            networks[net] = spec
            lines.append(f' ✔ Network {net}  Created')
        else:
            networks[net] = spec
    volumes = world['docker'].setdefault('volumes', {})
    for vol, spec in declared_volumes.items():
        if vol not in volumes:
            volumes[vol] = {**spec, 'data': {}, 'created_at': world['clock']}
            lines.append(f' ✔ Volume "{vol}"  Created')
    # Containers are recreated; what the image's anonymous volume held is carried over, as compose does on recreate.
    carried = {c['service']: c.get('data') for c in containers.values() if c.get('project') == project}
    for name in list(containers):
        if containers[name].get('project') == project:
            del containers[name]
    network: dict[str, dict] = {}
    built = 0
    for name in order:
        service = services[name] or {}
        ref = service.get('image')
        image = None
        if 'build' in service:
            spec = service['build']
            ctx = spec if isinstance(spec, str) else (spec or {}).get('context', '.')
            dockerfile = None if isinstance(spec, str) else (spec or {}).get('dockerfile')
            ref = ref or f'{project}-{name}'
            image = find_image(world, ref)
            if image is None or rebuild:
                build_args = ['-t', ref] + (['-f', str(PurePosixPath(ctx) / dockerfile)] if dockerfile else []) + [ctx]
                text, _, _ = build(folder, build_args, world)
                lines.append(text.rstrip())
                built += 1
                image = find_image(world, ref)
        elif ref:
            image = find_image(world, ref)
            if image is None:
                base, entry = resolve_base(ref, world, {})
                image = {'id': hashlib.sha256(base.encode()).hexdigest()[:12], 'tags': [base], 'size_mb': entry['size_mb'],
                         'base': base, 'tools': entry.get('tools', []), 'config': {'user': 'root', 'env': {}, 'cmd': None,
                         'entrypoint': ['docker-entrypoint.sh'], 'healthcheck': None, 'exposed': []}, 'layers': []}
                lines.append(f' ✔ {name} Pulled (simulated)')
        else:
            raise DockerError(f'service "{name}" has neither an image nor a build section')
        for dep, condition in compose_depends(service).items():
            target = network.get(dep)
            if target is None:
                continue
            if condition == 'service_healthy':
                if target['health'] is None:
                    raise DockerError(f'dependency failed to start: container {target["name"]} has no healthcheck '
                                      'configured')
                if target['health'] != 'healthy':
                    raise DockerError(f'dependency failed to start: container {target["name"]} is unhealthy')
                lines.append(f' ✔ Container {target["name"]}  Healthy')
        # A dependency with only service_started may not be ready yet when this service starts. Names resolve only
        # between services that share a network.
        view = {}
        for dep_name, target in network.items():
            if not set(plans[dep_name]['networks']) & set(plans[name]['networks']):
                continue
            ready = target['status'] == 'running'
            if compose_depends(service).get(dep_name) == 'service_started' and target.get('slow_start'):
                ready = False
            view[dep_name] = {**target, 'ready': ready}
        ports = parse_ports([str(p) for p in service.get('ports') or []])
        cname = f'{project}-{name}-1'
        for host, _ in ports:
            other = port_in_use(world, host, cname)
            if other:
                raise DockerError(f'Error response from daemon: Bind for 0.0.0.0:{host} failed: port is already '
                                  f'allocated (by {other})')
        command = service.get('command')
        if isinstance(command, str):
            command = shlex.split(command)
        container = start_container(world, cname, ref, image, ports, compose_env(service), command,
                                    compose_healthcheck(service) if 'healthcheck' in service else None, view, name,
                                    project)
        container['networks'] = plans[name]['networks']
        container['mounts'] = plans[name]['mounts']
        if carried.get(name) is not None:
            container['data'] = carried[name]
        app = app_for(world, image, ref)
        if app.get('kind') == 'postgres' and container['status'] == 'running':
            store = data_store(world, container)
            where = describe_store(container)
            if store.get('initialized'):
                container['logs'] = ['PostgreSQL Database directory appears to contain a database; Skipping '
                                     f'initialization ({where})'] + container['logs']
            else:
                store['initialized'] = True
                store.setdefault('rows', 0)
                container['logs'] = [f'initdb: creating database "{compose_env(service).get("POSTGRES_DB", "postgres")}" '
                                     f'in /var/lib/postgresql/data ({where})'] + container['logs']
        container['slow_start'] = bool(app.get('ready_after_s'))
        network[name] = container
        state = 'Started' if container['status'] == 'running' else f'Exited ({container["exit_code"]})'
        lines.append(f' ✔ Container {cname}  {state}')
    worldlib.advance(world, 5 + 3 * len(order))
    failed = [c for c in network.values() if c['status'] != 'running']
    if failed:
        lines.append(f'{YELLOW}{len(failed)} container(s) exited: docker compose logs {failed[0]["service"]}{RESET}')
    return '\n'.join(lines) + '\n', 0, {'services': len(order), 'built': built, 'exited': len(failed)}


# ---- Command entry -----------------------------------------------------------------------------------------------------


def command(folder: Path, args: list[str], world: dict) -> tuple[str, int, dict]:
    if not args or args[0] in ('help', '--help', '-h'):
        return HELP, 0, {}
    sub, rest = args[0], args[1:]
    containers = world['docker']['containers']
    if sub == 'build' or (sub == 'buildx' and rest[:1] == ['build']):
        return build(folder, rest if sub == 'build' else rest[1:], world)
    if sub == 'run':
        return run(folder, rest, world)
    if sub == 'compose':
        return compose(folder, rest, world)
    if sub == 'volume':
        return volume_command(rest, world)
    if sub == 'network':
        return network_command(rest, world)
    if sub == 'ps':
        return ps(world, '-a' in rest or '--all' in rest), 0, {}
    if sub in ('images', 'image') and (sub == 'images' or rest[:1] == ['ls']):
        return images(world), 0, {}
    if sub == 'history' and rest:
        return history(world, rest[-1]), 0, {}
    if sub == 'logs' and rest:
        container = containers.get(rest[-1])
        if container is None:
            raise DockerError(f'Error response from daemon: No such container: {rest[-1]}')
        return '\n'.join(container['logs']) + '\n', 0, {}
    if sub == 'stop' and rest:
        for name in rest:
            if name not in containers:
                raise DockerError(f'Error response from daemon: No such container: {name}')
            containers[name]['status'], containers[name]['exit_code'], containers[name]['health'] = 'exited', 0, None
        worldlib.advance(world, 1)
        return '\n'.join(rest) + '\n', 0, {}
    if sub == 'rm' and rest:
        force = '-f' in rest or '--force' in rest
        names = [r for r in rest if not r.startswith('-')]
        for name in names:
            if name not in containers:
                raise DockerError(f'Error response from daemon: No such container: {name}')
            if containers[name]['status'] == 'running' and not force:
                raise DockerError(f'Error response from daemon: cannot remove container "/{name}": container is '
                                  'running: stop the container before removing or force remove')
            del containers[name]
        return '\n'.join(names) + '\n', 0, {}
    if sub == 'rmi' and rest:
        image = find_image(world, rest[-1])
        if image is None:
            raise DockerError(f'Error response from daemon: No such image: {rest[-1]}')
        del world['docker']['images'][image['id']]
        return f'Untagged: {", ".join(image["tags"])}\nDeleted: sha256:{image["id"]}\n', 0, {}
    if sub in ('version', '--version', '-v'):
        return 'Docker version 27.3.1 (simulated by Datapass)\n', 0, {}
    raise DockerError(f"docker: '{sub}' is not a docker command the lab simulates.\nSee 'docker help'.")


HELP = f"""Usage:  docker COMMAND   {DIM}(simulated by Datapass: nothing is built, pulled or run){RESET}

  build -t NAME:TAG [-f FILE] PATH   Build an image from a Dockerfile (simulated BuildKit, layer cache)
  images                             List images
  history IMAGE                      Show the layers of an image
  run [-d] [--name N] [-p H:C] [-e K=V] IMAGE   Run a container
  ps [-a]                            List containers
  logs NAME                          Show a container's logs
  volume ls | rm | inspect           Named volumes (compose volumes: survive docker compose down, not down -v)
  network ls | inspect               Networks (compose networks: services resolve each other by name on them)
  stop NAME / rm [-f] NAME / rmi IMAGE
  compose up [-d] [--build] | ps | logs [SERVICE] | down [-v]
"""
