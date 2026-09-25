"""Terminal Lab missions: the fixture builder and the checks on the learner's files and Git repository.

Datapass never runs the learner's commands. The learner types them in a real VS Code terminal (bash or PowerShell);
this module only builds the mission folder from the shipped pack (files, then a Git history made of fixed git
commands with fixed dates and author, so the fixture's hashes are reproducible) and, when the learner asks, reads the
resulting state: files as text, CSV, scripts as text (never executed), and the repository through read-only git
commands with fsmonitor and hooks turned off.
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta
import fnmatch
import io
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from typing import Any, Callable

from .model import (AnyOfCheck, CsvCheck, FixtureFile, GitBranchCheck, GitFileCheck, GitFixture, GitIgnoreCheck,
                    GitLogCheck, GitRepoCheck, GitStashCheck, GitTagCheck, ListingCheck, Mission, PathCheck,
                    ScriptCheck, TextCheck)

MAX_TEXT_BYTES = 2_000_000
GIT_TIMEOUT = 30
TRUTH = ('Checked for real: the files and the Git repository in your mission folder, read after your own commands. '
         'Datapass ran none of them; scripts are read as text, never executed.')


class FixtureError(RuntimeError):
    pass


# ---- Git ---------------------------------------------------------------------------------------------------------


def git_executable() -> str:
    found = shutil.which('git')
    if not found:
        raise FixtureError('Git is not installed or not on PATH. The Terminal Lab needs Git (Git for Windows on Windows).')
    return found


def _base_env(folder: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update({
        # Never walk up into a repository around the workspace (the learner's own project may be one).
        'GIT_CEILING_DIRECTORIES': str(folder.parent),
        'GIT_TERMINAL_PROMPT': '0', 'GIT_OPTIONAL_LOCKS': '0', 'GIT_PAGER': 'cat', 'PAGER': 'cat',
        'LC_ALL': 'C', 'LANG': 'C',
    })
    return env


# Read-only commands must not start anything the repository's config could name.
SAFE = ['-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=.git/datapass-no-hooks', '-c', 'core.pager=cat',
        '-c', 'color.ui=false', '-c', 'log.showSignature=false']


class Repo:
    """Read-only access to one repository of the mission folder, confined to it."""

    def __init__(self, folder: Path):
        self.folder = folder
        self._root: bool | None = None

    def run(self, *args: str, binary: bool = False) -> subprocess.CompletedProcess:
        return subprocess.run([git_executable(), '--no-pager', *SAFE, *args], cwd=self.folder,
                              env=_base_env(self.folder), capture_output=True, timeout=GIT_TIMEOUT,
                              text=not binary, **({} if binary else {'encoding': 'utf-8', 'errors': 'replace'}))

    def out(self, *args: str) -> str | None:
        done = self.run(*args)
        return done.stdout if done.returncode == 0 else None

    def is_root(self) -> bool:
        """The folder is the top of its own repository (not a folder inside another one)."""
        if self._root is None:
            top = self.out('rev-parse', '--show-toplevel') if self.folder.is_dir() else None
            try:
                self._root = bool(top) and Path(top.strip()).resolve() == self.folder.resolve()
            except OSError:
                self._root = False
        return self._root

    def commit(self, rev: str) -> str | None:
        found = self.out('rev-parse', '--verify', '--quiet', '--end-of-options', f'{rev}^{{commit}}')
        return found.strip() if found else None

    def git_path(self, name: str) -> Path:
        found = self.out('rev-parse', '--git-path', name)
        return (self.folder / found.strip()) if found else self.folder / '.git' / name

    def log(self, rev: str, limit: int = 500) -> list[dict[str, Any]]:
        text = self.out('log', f'--max-count={limit}', '--format=%H%x1f%P%x1f%s%x1f%b%x1e', '--end-of-options', rev, '--')
        commits = []
        for record in (text or '').split('\x1e'):
            fields = record.strip('\n').split('\x1f')
            if len(fields) == 4:
                commits.append({'sha': fields[0], 'parents': fields[1].split(), 'subject': fields[2].strip(), 'body': fields[3]})
        return commits


def _author(fixture: GitFixture) -> tuple[str, str]:
    name, email = re.fullmatch(r'(.+) <(.+)>', fixture.author).groups()
    return name, email


def _write(folder: Path, relative: str, spec: Any) -> None:
    path = folder / relative
    if spec is None:
        if path.is_file():
            path.unlink()
        return
    text, eol = (spec.text, spec.eol) if isinstance(spec, FixtureFile) else (spec, 'lf')
    data = text.replace('\r\n', '\n')
    if eol == 'crlf':
        data = data.replace('\n', '\r\n')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode('utf-8'))
    if isinstance(spec, FixtureFile) and spec.executable:
        path.chmod(path.stat().st_mode | 0o111)


def _build_git(folder: Path, fixture: GitFixture) -> int:
    repo = folder if fixture.path == '.' else folder / fixture.path
    repo.mkdir(parents=True, exist_ok=True)
    name, email = _author(fixture)
    when = datetime.fromisoformat(fixture.start)
    env = _base_env(folder)
    # The learner's own settings (commit signing, autocrlf, hooks, templates) must not change the fixture.
    env.update({'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': str(repo / '.git' / 'datapass-none'),
                'GIT_AUTHOR_NAME': name, 'GIT_AUTHOR_EMAIL': email, 'GIT_COMMITTER_NAME': name,
                'GIT_COMMITTER_EMAIL': email, 'GIT_MERGE_AUTOEDIT': 'no', 'GIT_EDITOR': 'true'})
    fixed = ['-c', 'core.autocrlf=false', '-c', 'core.safecrlf=false', '-c', 'commit.gpgsign=false',
             '-c', 'tag.gpgsign=false', '-c', 'init.templateDir=', '-c', 'core.hooksPath=.git/datapass-no-hooks']

    def git(*args: str) -> None:
        stamp = when.isoformat()
        done = subprocess.run([git_executable(), *fixed, *args], cwd=repo, capture_output=True, text=True,
                              encoding='utf-8', errors='replace', timeout=GIT_TIMEOUT,
                              env={**env, 'GIT_AUTHOR_DATE': stamp, 'GIT_COMMITTER_DATE': stamp})
        if done.returncode != 0:
            raise FixtureError(f'git {args[0]} failed while building the fixture: {(done.stderr or done.stdout).strip()[:300]}')

    def write_all(files: dict) -> None:
        for relative, spec in files.items():
            _write(repo, relative, spec)

    git('init', '-q', '-b', fixture.branch)
    commits = 0
    for step in fixture.steps:
        if step.commit:
            write_all(step.commit.files)
            git('add', '-A')
            for relative, spec in step.commit.files.items():
                if isinstance(spec, FixtureFile) and spec.executable:
                    git('update-index', '--chmod=+x', '--', relative)
            git('commit', '-q', '-m', step.commit.message)
            commits += 1
            when += timedelta(hours=1)
        elif step.branch:
            git('branch', step.branch)
        elif step.switch:
            git('switch', '-q', step.switch)
        elif step.merge:
            git('merge', '-q', '--no-ff', '--no-edit', step.merge)
            commits += 1
            when += timedelta(hours=1)
        elif step.tag:
            git(*(['tag', '-a', step.tag.name, '-m', step.tag.message] if step.tag.message else ['tag', step.tag.name]))
        elif step.delete_branch:
            git('branch', '-q', '-D', step.delete_branch)
        elif step.reset_hard:
            git('reset', '-q', '--hard', step.reset_hard)
        elif step.stash:
            write_all(step.stash.files)
            git('stash', 'push', '-q', '--include-untracked', '-m', step.stash.message)
            when += timedelta(minutes=10)
    return commits


def build_fixture(mission: Mission, pack_dir: Path, workspace: Path) -> dict[str, Any]:
    """(Re)create `missions/<id>/` from the pack. An existing folder is moved to .datapass/missions/attic/, never
    deleted. The new one is built outside the workspace (so VS Code's Git extension, which opens every new .git it
    sees there, never holds a half-built repository) and then moved into place."""
    if mission.fixture is None:
        raise ValueError(f'Mission {mission.id} has no terminal fixture.')
    target = workspace / mission.folder
    staging = Path(tempfile.mkdtemp(prefix='datapass-fixture-'))
    building = staging / mission.id
    building.mkdir()
    try:
        overlay = pack_dir / mission.id / 'project'
        files = 0
        if overlay.is_dir():
            for path in sorted(overlay.rglob('*')):
                if path.is_file() and not path.is_symlink():
                    destination = building / path.relative_to(overlay)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, destination)
                    files += 1
                elif path.is_dir():
                    (building / path.relative_to(overlay)).mkdir(parents=True, exist_ok=True)
        for relative, spec in mission.fixture.files.items():
            _write(building, relative, spec)
            files += 1
        commits = _build_git(building, mission.fixture.git) if mission.fixture.git else 0
        previous = None
        if target.exists():
            attic = workspace / '.datapass' / 'missions' / 'attic'
            attic.mkdir(parents=True, exist_ok=True)
            previous = attic / f'{mission.id}-{datetime.now().strftime("%Y%m%d-%H%M%S")}'
            try:
                _rename(target, previous)
            except OSError as error:
                raise FixtureError(
                    f'{mission.folder} could not be moved aside ({error.strerror or error}): a program still has '
                    'it open (a terminal, an editor, or Source Control). Close it, then start over again.') from None
        target.parent.mkdir(parents=True, exist_ok=True)
        _move(building, target)
    finally:
        shutil.rmtree(staging, onerror=_force_remove)
    return {'folder': mission.folder, 'files': files, 'commits': commits,
            'previous': previous.relative_to(workspace).as_posix() if previous else None}


def _rename(source: Path, target: Path) -> None:
    """Windows refuses a rename while a scanner (antivirus, indexer) still holds a file just written: retry briefly."""
    for attempt in range(20):
        try:
            source.rename(target)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.25)


def _move(source: Path, target: Path) -> None:
    """A rename when both are on the same volume; otherwise a copy (Git's read-only objects included)."""
    try:
        _rename(source, target)
    except OSError:
        shutil.copytree(source, target, symlinks=True)


def _force_remove(function: Callable, path: str, _info: Any) -> None:
    # Git writes its objects read-only; Windows refuses to delete them until they are writable.
    os.chmod(path, 0o700)
    function(path)


# ---- Files -------------------------------------------------------------------------------------------------------

Outcome = tuple[bool, str]


def decode(data: bytes) -> str:
    """UTF-8 (with or without BOM), or UTF-16 with a BOM (Windows PowerShell 5.1's `>` and Out-File)."""
    if data.startswith(b'\xff\xfe') or data.startswith(b'\xfe\xff'):
        return data.decode('utf-16', errors='replace')
    return data.decode('utf-8-sig', errors='replace')


def _raw(files, relative: str) -> bytes | None:
    path = files.path(relative)
    if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_TEXT_BYTES:
        return None
    return path.read_bytes()


def normalized_lines(text: str) -> list[str]:
    lines = [line.rstrip() for line in text.replace('\r\n', '\n').replace('\r', '\n').split('\n')]
    while lines and not lines[-1]:
        lines.pop()
    return lines


def line_endings(text: str) -> str:
    crlf = text.count('\r\n')
    lf = text.count('\n') - crlf
    return 'none' if crlf + lf == 0 else 'crlf' if lf == 0 else 'lf' if crlf == 0 else 'mixed'


def _content_checks(where: str, text: str, contains: list[str], not_contains: list[str]) -> Outcome | None:
    missing = [c for c in contains if c not in text]
    if missing:
        return False, f'{where} does not contain {missing[0]!r}.'
    present = [c for c in not_contains if c in text]
    if present:
        return False, f'{where} still contains {present[0]!r}.'
    return None


def _path(check: PathCheck, files, _ctx: dict) -> Outcome:
    path = files.path(check.path)
    if check.type == 'absent':
        return (not path.exists() and not path.is_symlink(), f'{check.path} is gone.' if not path.exists() else f'{check.path} is still there.')
    if check.type == 'dir':
        return (path.is_dir(), f'{check.path}/ exists.' if path.is_dir() else f'There is no folder {check.path}/.')
    if not path.is_file():
        return False, f'There is no file {check.path}.'
    if path.stat().st_size < check.min_bytes:
        return False, f'{check.path} is empty.' if path.stat().st_size == 0 else f'{check.path} is too small.'
    return True, f'{check.path} exists.'


def _text(check: TextCheck, files, _ctx: dict) -> Outcome:
    data = _raw(files, check.path)
    if data is None:
        return False, f'There is no file {check.path}.'
    text = decode(data)
    if check.line_endings and line_endings(text) not in (check.line_endings, 'none'):
        return False, f'{check.path} has {line_endings(text).upper()} line endings.'
    if check.equals is not None:
        lines = normalized_lines(text)
        expected = [line.rstrip() for line in check.equals]
        if lines != expected:
            if len(lines) != len(expected):
                return False, f'{check.path} has {len(lines)} line(s); that is not the expected content.'
            first = next(i for i, (a, b) in enumerate(zip(lines, expected)) if a != b)
            return False, f'{check.path}: line {first + 1} is not the expected one: {lines[first][:160]!r}.'
    content = _content_checks(check.path, text, check.contains, check.not_contains)
    if content:
        return content
    for pattern in check.regex:
        if not re.search(pattern, text, re.MULTILINE):
            return False, f'{check.path} does not have the expected content yet.'
    return True, f'{check.path} is as expected.'


def _entries(folder: Path, recursive: bool) -> list[tuple[str, bool]]:
    out = []
    walker = os.walk(folder) if recursive else [(str(folder), *next(os.walk(folder))[1:])]
    for root, dirs, names in walker:
        dirs[:] = [d for d in dirs if d != '.git']
        base = Path(root).relative_to(folder)
        out += [((base / d).as_posix(), True) for d in dirs]
        out += [((base / n).as_posix(), False) for n in names]
    return sorted(out)


def _listing(check: ListingCheck, files, _ctx: dict) -> Outcome:
    folder = files.folder if check.dir == '.' else files.path(check.dir)
    label = 'the mission folder' if check.dir == '.' else f'{check.dir}/'
    if not folder.is_dir():
        return False, f'There is no folder {check.dir}/.'
    found = [name for name, is_dir in _entries(folder, check.recursive)
             if fnmatch.fnmatchcase(name.rsplit('/', 1)[-1], check.pattern)
             and (check.type == 'any' or (check.type == 'dir') == is_dir)]
    if check.equals is not None and sorted(found) != sorted(check.equals):
        extra = sorted(set(found) - set(check.equals))
        missing = sorted(set(check.equals) - set(found))
        if extra:
            return False, f'{label} has {", ".join(extra[:5])}{" …" if len(extra) > 5 else ""}, which should not be there.'
        return False, f'{label} is missing {len(missing)} expected entr{"y" if len(missing) == 1 else "ies"}.'
    missing = [name for name in check.includes if name not in found]
    if missing:
        return False, f'{label} has no {missing[0]}.'
    extra = [name for name in check.excludes if name in found]
    if extra:
        return False, f'{label} still has {extra[0]}.'
    if check.count is not None and len(found) != check.count:
        shown = ', '.join(found[:5]) + (' …' if len(found) > 5 else '')
        return False, f'{label} has {len(found)} matching entr{"y" if len(found) == 1 else "ies"}' + (f': {shown}.' if found else '.')
    return True, f'{label}: {len(found)} matching entr{"y" if len(found) == 1 else "ies"}.'


def _csv(check: CsvCheck, files, _ctx: dict) -> Outcome:
    data = _raw(files, check.path)
    if data is None:
        return False, f'There is no file {check.path}.'
    text = decode(data)
    if text.lstrip().startswith('#TYPE'):
        return False, f'{check.path} starts with a #TYPE line: export it without type information.'
    rows = [[value.strip() for value in row] for row in csv.reader(io.StringIO(text.replace('\r\n', '\n')))]
    while rows and not any(rows[-1]):
        rows.pop()
    if not rows:
        return False, f'{check.path} is empty.'
    if rows[0] != check.header:
        return False, f'{check.path} has the header {",".join(rows[0])}.'
    body = rows[1:]
    expected = [[value.strip() for value in row] for row in check.rows]
    if len(body) != len(expected):
        return False, f'{check.path} has {len(body)} row(s); that is not the expected content.'
    if (body if check.ordered else sorted(body)) != (expected if check.ordered else sorted(expected)):
        if check.ordered and sorted(body) == sorted(expected):
            return False, f'{check.path} has the right rows in the wrong order.'
        return False, f'{check.path} does not have the expected rows.'
    return True, f'{check.path}: {len(body)} row(s) as expected.'


def strip_comments(source: str, shell: str) -> str:
    """The script without its comments (and without the shebang line), so a command in a comment does not count."""
    if shell == 'powershell':
        source = re.sub(r'<#.*?#>', '', source, flags=re.DOTALL)
    lines = source.replace('\r\n', '\n').split('\n')
    if lines and lines[0].startswith('#!'):
        lines = lines[1:]
    out = []
    for line in lines:
        quote = None
        cut = len(line)
        for index, char in enumerate(line):
            if quote:
                if char == quote:
                    quote = None
            elif char in '"\'':
                quote = char
            elif char == '#' and (index == 0 or line[index - 1] in ' \t;|&(') and not (shell == 'bash' and line[index - 1:index] == '$'):
                cut = index
                break
        out.append(line[:cut])
    return '\n'.join(out)


def _script(check: ScriptCheck, files, _ctx: dict) -> Outcome:
    data = _raw(files, check.path)
    if data is None:
        return False, f'There is no script {check.path}.'
    source = decode(data)
    first = source.replace('\r\n', '\n').split('\n', 1)[0]
    if check.shebang and not re.search(check.shebang, first):
        return False, f'{check.path} does not start with the expected shebang line (found {first[:80]!r}).'
    if check.shell == 'bash' and '\r\n' in source:
        return False, f'{check.path} has CRLF line endings: bash would fail on the carriage returns.'
    code = strip_comments(source, check.shell)
    flags = re.MULTILINE | (re.IGNORECASE if check.shell == 'powershell' else 0)
    for pattern in check.uses:
        if not re.search(pattern, code, flags):
            return False, f'{check.path} does not do everything asked yet.'
    for pattern in check.not_uses:
        if re.search(pattern, code, flags):
            return False, f'{check.path} does something the ticket asks to avoid.'
    return True, f'{check.path} reads as asked (not run).'


# ---- Git checks --------------------------------------------------------------------------------------------------


def _repo(files, ctx: dict, relative: str) -> tuple[Repo | None, str]:
    cache = ctx.setdefault('repos', {})
    if relative not in cache:
        folder = files.folder if relative == '.' else files.path(relative)
        cache[relative] = Repo(folder)
    repo = cache[relative]
    where = 'the mission folder' if relative == '.' else f'{relative}/'
    if not repo.is_root():
        return None, f'{where} is not a Git repository of its own yet.'
    return repo, where


def _git_repo(check: GitRepoCheck, files, ctx: dict) -> Outcome:
    repo, where = _repo(files, ctx, check.repo)
    if repo is None:
        return False, where
    if check.branch:
        current = (repo.out('symbolic-ref', '--short', '-q', 'HEAD') or '').strip()
        if current != check.branch:
            return False, f'The current branch is {current or "none (detached HEAD)"}.'
    if check.in_progress is not None:
        busy = [label for name, label in (('MERGE_HEAD', 'a merge'), ('rebase-merge', 'a rebase'), ('rebase-apply', 'a rebase'),
                                          ('CHERRY_PICK_HEAD', 'a cherry-pick'), ('REVERT_HEAD', 'a revert'))
                if repo.git_path(name).exists()]
        if bool(busy) != check.in_progress:
            return False, f'{busy[0].capitalize()} is still in progress.' if busy else 'Nothing is in progress.'
    if check.clean is not None:
        status = repo.out('status', '--porcelain=v1', '--untracked-files=all')
        if status is None:
            return False, 'git status failed.'
        changed = [line[3:] for line in status.splitlines() if line.strip()]
        if bool(changed) == check.clean:
            shown = ', '.join(changed[:4]) + (' …' if len(changed) > 4 else '')
            return False, f'The working tree is not clean: {shown}.' if changed else 'The working tree is clean.'
    return True, f'{where}: a repository' + (f' on {check.branch}' if check.branch else '') + '.'


def _git_branch(check: GitBranchCheck, files, ctx: dict) -> Outcome:
    repo, where = _repo(files, ctx, check.repo)
    if repo is None:
        return False, where
    exists = repo.run('show-ref', '--verify', '--quiet', f'refs/heads/{check.name}').returncode == 0
    if exists != check.exists:
        return False, f'There is no branch {check.name}.' if check.exists else f'The branch {check.name} still exists.'
    return True, f'{check.name} exists.' if exists else f'{check.name} is gone.'


def _git_log(check: GitLogCheck, files, ctx: dict) -> Outcome:
    repo, where = _repo(files, ctx, check.repo)
    if repo is None:
        return False, where
    if not repo.commit(check.ref):
        return False, f'There is no {check.ref} in the repository.' if check.ref != 'HEAD' else 'The repository has no commit yet.'
    if check.since and not repo.commit(check.since):
        return False, f'There is no {check.since} in the repository.'
    commits = repo.log(f'{check.since}..{check.ref}' if check.since else check.ref)
    subjects = [c['subject'] for c in commits]
    label = f'{check.since}..{check.ref}' if check.since else check.ref
    if check.subjects is not None and subjects != check.subjects:
        if sorted(subjects) == sorted(check.subjects):
            return False, f'The commits of {label} are the right ones in the wrong order.'
        shown = '; '.join(subjects[:6]) + (' …' if len(subjects) > 6 else '')
        return False, f'{label} has {len(subjects)} commit(s): {shown or "none"}.'
    missing = [s for s in check.includes_subjects if s not in subjects]
    if missing:
        return False, f'{label} has no commit "{missing[0]}".'
    extra = [s for s in check.excludes_subjects if s in subjects]
    if extra:
        return False, f'{label} still has the commit "{extra[0]}".'
    if check.min_count is not None and len(commits) < check.min_count:
        return False, f'{label} has {len(commits)} commit(s).'
    if check.max_count is not None and len(commits) > check.max_count:
        return False, f'{label} has {len(commits)} commits: {"; ".join(subjects[:6])}{" …" if len(subjects) > 6 else ""}.'
    merges = [c for c in commits if len(c['parents']) > 1]
    if check.linear and merges:
        return False, f'{label} has a merge commit: "{merges[0]["subject"]}".'
    if check.min_merges is not None and len(merges) < check.min_merges:
        return False, f'{label} has no merge commit.' if not merges else f'{label} has {len(merges)} merge commit(s).'
    for ancestor in check.ancestors:
        if repo.run('merge-base', '--is-ancestor', '--end-of-options', ancestor, check.ref).returncode != 0:
            return False, f'{check.ref} does not contain {ancestor}: it is not based on it.'
    for other in check.not_ancestors:
        if repo.commit(other) and repo.run('merge-base', '--is-ancestor', '--end-of-options', other, check.ref).returncode == 0:
            return False, f'{check.ref} contains {other}.'
    if check.subject_regex:
        bad = [s for s in subjects if not re.search(check.subject_regex, s)]
        if bad:
            return False, f'The commit message "{bad[0]}" does not follow the expected format.'
    for subject, texts in check.bodies.items():
        commit = next((c for c in commits if c['subject'] == subject), None)
        if commit is None:
            return False, f'{label} has no commit "{subject}".'
        absent = [t for t in texts if t not in commit['body']]
        if absent:
            return False, f'The message of "{subject}" does not record {absent[0]!r}.'
    return True, f'{label}: {len(commits)} commit(s) as expected.'


def _git_file(check: GitFileCheck, files, ctx: dict) -> Outcome:
    repo, where = _repo(files, ctx, check.repo)
    if repo is None:
        return False, where
    if not repo.commit(check.ref):
        return False, f'There is no {check.ref} in the repository.' if check.ref != 'HEAD' else 'The repository has no commit yet.'
    listed = repo.out('ls-tree', '--end-of-options', check.ref, '--', check.path) or ''
    entry = next((line for line in listed.splitlines() if line.endswith(f'\t{check.path}')), None)
    if (entry is not None) != check.exists:
        return False, f'{check.path} is not committed on {check.ref}.' if check.exists else f'{check.path} is still committed on {check.ref}.'
    if entry is None:
        return True, f'{check.path} is not on {check.ref}.'
    mode, kind = entry.split()[:2]
    if kind != 'blob':
        return False, f'{check.path} is not a file on {check.ref}.'
    if check.mode and mode != check.mode:
        return False, f'{check.path} is committed with mode {mode}' + (' (not executable).' if check.mode == '100755' else '.')
    blob = repo.run('cat-file', 'blob', f'{check.ref}:{check.path}', binary=True)
    if blob.returncode != 0:
        return False, f'{check.path} could not be read on {check.ref}.'
    text = decode(blob.stdout)
    if check.line_endings and line_endings(text) not in (check.line_endings, 'none'):
        return False, f'{check.path} is committed with {line_endings(text).upper()} line endings.'
    if check.no_conflict_markers and re.search(r'^(<{7}|={7}|>{7})( |$)', text, re.MULTILINE):
        return False, f'{check.path} is committed with conflict markers in it.'
    content = _content_checks(f'{check.path} on {check.ref}', text, check.contains, check.not_contains)
    if content:
        return content
    return True, f'{check.path} on {check.ref} is as expected.'


def _git_tag(check: GitTagCheck, files, ctx: dict) -> Outcome:
    repo, where = _repo(files, ctx, check.repo)
    if repo is None:
        return False, where
    kind = (repo.out('cat-file', '-t', f'refs/tags/{check.name}') or '').strip()
    if not kind:
        return False, f'There is no tag {check.name}.'
    if check.annotated is not None and (kind == 'tag') != check.annotated:
        return False, f'{check.name} is a lightweight tag.' if check.annotated else f'{check.name} is an annotated tag.'
    if check.target:
        tagged, target = repo.commit(f'refs/tags/{check.name}'), repo.commit(check.target)
        if tagged != target:
            subject = (repo.out('log', '-1', '--format=%s', f'refs/tags/{check.name}') or '').strip()
            return False, f'{check.name} points at "{subject}", not at {check.target}.'
    if check.message_contains:
        message = repo.out('tag', '-l', '--format=%(contents)', check.name) or ''
        absent = [t for t in check.message_contains if t.lower() not in message.lower()]
        if absent:
            return False, f'The message of {check.name} does not mention {absent[0]!r}.'
    return True, f'{check.name} is in place.'


def _git_ignore(check: GitIgnoreCheck, files, ctx: dict) -> Outcome:
    repo, where = _repo(files, ctx, check.repo)
    if repo is None:
        return False, where
    # The repository's own rules only: a global excludes file on this machine would not travel with the repository.
    local = ['-c', 'core.excludesFile=.git/datapass-no-global-excludes']
    for path in check.ignored + check.not_ignored:
        ignored = repo.run(*local, 'check-ignore', '-q', '--no-index', '--', path).returncode == 0
        if ignored != (path in check.ignored):
            return False, f'{path} is not ignored by the repository.' if path in check.ignored else f'{path} is ignored.'
    for path in check.tracked + check.untracked:
        tracked = repo.run('ls-files', '--error-unmatch', '--', path).returncode == 0
        if tracked != (path in check.tracked):
            return False, f'{path} is not tracked.' if path in check.tracked else f'{path} is tracked by Git (it is in the index).'
    return True, 'The ignore rules and the tracked files are as expected.'


def _git_stash(check: GitStashCheck, files, ctx: dict) -> Outcome:
    repo, where = _repo(files, ctx, check.repo)
    if repo is None:
        return False, where
    entries = [line for line in (repo.out('stash', 'list', '--format=%gs') or '').splitlines() if line.strip()]
    if check.count is not None and len(entries) != check.count:
        return False, f'The stash has {len(entries)} entr{"y" if len(entries) == 1 else "ies"}.'
    if check.message_contains and not any(check.message_contains in entry for entry in entries):
        return False, 'No stash entry has the expected message.'
    return True, f'The stash has {len(entries)} entr{"y" if len(entries) == 1 else "ies"}.'


def _any_of(check: AnyOfCheck, files, ctx: dict) -> Outcome:
    details = []
    for inner in check.checks:
        passed, detail = ctx['run'](inner)
        if passed:
            return True, detail
        details.append(detail)
    return False, ' / '.join(details)


CHECKS: dict[str, Callable[[Any, Any, dict], Outcome]] = {
    'path': _path, 'text': _text, 'listing': _listing, 'csv': _csv, 'script': _script, 'git_repo': _git_repo,
    'git_branch': _git_branch, 'git_log': _git_log, 'git_file': _git_file, 'git_tag': _git_tag,
    'git_ignore': _git_ignore, 'git_stash': _git_stash, 'any_of': _any_of,
}
