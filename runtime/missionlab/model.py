"""The mission contract: `content/missions/<pack>/<mission>/mission.json`.

A mission is a ticket, not an exercise: context and a request from someone on the team, acceptance criteria, hints
the learner asks for one at a time, and a hidden checker. The learner works in a real project folder
(`missions/<id>/`, copied from the pack's base project plus the mission's `project/` overlay) with real tools; the
checker then looks at what really happened: read-only SQL on the catalog, the tools' own artifacts, files.

The lab field says which lab runs the mission: `dbt` (SQL fixture batches, dbt artifacts), `terminal` (a fixture of
files and Git history built from the pack, checked on the resulting files and repository) or `infra` (files and a
simulated world, checked on what the learner's simulated terraform, docker, kubectl and az commands left behind).
"""
from __future__ import annotations

from pathlib import Path
import json
import re
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

MISSION_ID = re.compile(r'^[a-z0-9][a-z0-9-]{0,47}$')
IDENT = re.compile(r'^[a-z][a-z0-9_]{0,40}$')
Scalar = Union[str, int, float, bool, None]


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')


def _join_lines(value: Any) -> Any:
    return '\n'.join(value) if isinstance(value, list) and all(isinstance(v, str) for v in value) else value


Lines = Annotated[str, BeforeValidator(_join_lines), Field(min_length=1, max_length=12000)]


def project_path(value: str) -> str:
    """A path inside the mission folder: relative, no `..`, simple characters."""
    parts = value.split('/')
    if (not re.fullmatch(r'[A-Za-z0-9_./-]{1,200}', value) or value.startswith('/') or '..' in parts
            or '' in parts or '.' in parts):
        raise ValueError(f'{value!r} is not a path inside the mission folder')
    return value


ProjectPath = Annotated[str, BeforeValidator(project_path)]


def folder_path(value: str) -> str:
    """A folder inside the mission folder, or the mission folder itself ('.')."""
    return value if value == '.' else project_path(value)


FolderPath = Annotated[str, BeforeValidator(folder_path)]
# A Git revision the checker may name: a branch, a tag, HEAD, HEAD~2, main@{1}. Never an option (no leading '-').
GitRev = Annotated[str, Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9._/~^@{}-]{0,99}$')]
GitName = Annotated[str, Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9._/-]{0,79}$')]


class CheckBase(Contract):
    # What the learner sees when the check fails (never the answer). Defaults to a generic sentence per kind.
    fail: str | None = Field(default=None, max_length=400)


class SqlCheck(CheckBase):
    """Read-only SQL on the workspace catalog, compared (order-independent) to the expected rows."""
    kind: Literal['sql']
    sql: str = Field(min_length=1, max_length=4000)
    expected: list[dict[str, Scalar]] = Field(max_length=60)


class NodeCheck(CheckBase):
    """A node of target/manifest.json and its configuration."""
    kind: Literal['node']
    name: str = Field(pattern=r'^[A-Za-z0-9_]{1,100}$')
    resource_type: Literal['model', 'seed', 'snapshot'] = 'model'
    materialized: str | None = None
    unique_key: list[str] | None = None
    tags: list[str] = Field(default_factory=list)
    # The compiled or raw SQL must mention these (lower-cased), e.g. is_incremental.
    code_contains: list[str] = Field(default_factory=list)
    # The model contract (config.contract.enforced) and the data_type each listed column declares in the YAML.
    contract_enforced: bool | None = None
    column_types: dict[str, str] = Field(default_factory=dict, max_length=40)


class TestCheck(CheckBase):
    """A generic data test on a model's column, still there and still an error (not warn, no where filter)."""
    kind: Literal['test']
    test: str = Field(pattern=r'^[a-z_]{1,40}$')
    model: str = Field(pattern=r'^[A-Za-z0-9_]{1,100}$')
    column: str = Field(pattern=r'^[A-Za-z0-9_]{1,100}$')
    severity: Literal['error', 'warn'] = 'error'


class UnitTestCheck(CheckBase):
    """dbt unit tests (dbt Core 1.8+) of a model in target/manifest.json: how many, which columns their expected rows
    pin, and that each one passed in the learner's last dbt command."""
    kind: Literal['unit_test']
    model: str = Field(pattern=r'^[A-Za-z0-9_]{1,100}$')
    min_count: int = Field(default=1, ge=1, le=20)
    # At least one unit test's expected rows give these columns.
    expect_columns: list[str] = Field(default_factory=list, max_length=20)
    passed_in_last_run: bool = True


class RunCheck(CheckBase):
    """target/run_results.json of the learner's last dbt command."""
    kind: Literal['run']
    command: str | None = Field(default=None, pattern=r'^[a-z ]{1,30}$')
    nodes: dict[str, list[str]] = Field(default_factory=dict)
    no_failures: bool = False
    select_includes: list[str] = Field(default_factory=list)
    full_refresh: bool | None = None
    # Variables of the last command (--vars) and the values each may have.
    vars: dict[str, list[Scalar]] = Field(default_factory=dict)


class FreshnessConfigCheck(CheckBase):
    """A source table's freshness rules in target/manifest.json."""
    kind: Literal['freshness_config']
    source: str = Field(pattern=r'^[A-Za-z0-9_]+\.[A-Za-z0-9_]+$')
    loaded_at_field: str
    warn_after: tuple[int, Literal['minute', 'hour', 'day']]
    error_after: tuple[int, Literal['minute', 'hour', 'day']]


class FreshnessResultCheck(CheckBase):
    """target/sources.json written by `dbt source freshness`: the status of each listed source table."""
    kind: Literal['freshness_result']
    expect: dict[str, list[Literal['pass', 'warn', 'error', 'runtime error']]]


class DctValidateCheck(CheckBase):
    """`dct validate --json <board>`: the result comes with the check request (the host ran the real dct)."""
    kind: Literal['dct_validate']
    board: ProjectPath


class BoardCheck(CheckBase):
    """The board file itself: a query on ref(model), a filter variable, a chart type."""
    kind: Literal['board']
    board: ProjectPath
    ref: str = Field(pattern=r'^[A-Za-z0-9_]{1,100}$')
    variable_column: str | None = Field(default=None, pattern=r'^[A-Za-z0-9_]{1,100}$')
    chart_types: list[str] = Field(default_factory=list)


class RenderCheck(CheckBase):
    """A `dct render --format json` output: a chart's data must add up to the same total as a SQL query."""
    kind: Literal['render']
    file: ProjectPath
    chart_types: list[str] = Field(default_factory=list)
    total_sql: str = Field(min_length=1, max_length=2000)
    tolerance: float = 0.01


class FileCheck(CheckBase):
    kind: Literal['file']
    path: ProjectPath
    min_bytes: int = 1


class AirflowRun(Contract):
    logical_date: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    # The run's rendered bash_command must contain all of these (for example the day it loads).
    command_contains: list[str] = Field(default_factory=list, max_length=10)


class AirflowCheck(CheckBase):
    """An Airflow DAG file, parsed (never executed) and its schedule simulated up to `now` (Airflow 3 semantics)."""
    kind: Literal['airflow']
    dag: ProjectPath
    now: str
    # Exactly these runs, in any order.
    runs: list[AirflowRun] = Field(min_length=1, max_length=31)


# ---- Terminal Lab: the learner's files and Git repository, read after their own commands --------------------------


class PathCheck(CheckBase):
    """A path in the mission folder is a file, a folder, or absent."""
    kind: Literal['path']
    path: ProjectPath
    type: Literal['file', 'dir', 'absent'] = 'file'
    min_bytes: int = Field(default=0, ge=0)


class TextCheck(CheckBase):
    """A text file (UTF-8, or UTF-16 with a BOM as Windows PowerShell 5.1 writes it)."""
    kind: Literal['text']
    path: ProjectPath
    # The exact lines, compared after normalizing line endings, trailing spaces and trailing blank lines.
    equals: list[str] | None = Field(default=None, max_length=400)
    contains: list[str] = Field(default_factory=list, max_length=20)
    not_contains: list[str] = Field(default_factory=list, max_length=20)
    # Regular expressions (multiline) that must all match.
    regex: list[str] = Field(default_factory=list, max_length=10)
    line_endings: Literal['lf', 'crlf'] | None = None


class ListingCheck(CheckBase):
    """The entries of a folder (relative POSIX paths; `.git` is never listed), filtered by a name pattern."""
    kind: Literal['listing']
    dir: FolderPath = '.'
    pattern: str = Field(default='*', min_length=1, max_length=60)
    recursive: bool = False
    type: Literal['file', 'dir', 'any'] = 'any'
    equals: list[str] | None = Field(default=None, max_length=200)
    includes: list[str] = Field(default_factory=list, max_length=50)
    excludes: list[str] = Field(default_factory=list, max_length=50)
    count: int | None = Field(default=None, ge=0)


class CsvCheck(CheckBase):
    """A CSV file: its header and rows (values compared as trimmed text; quoting does not matter)."""
    kind: Literal['csv']
    path: ProjectPath
    header: list[str] = Field(min_length=1, max_length=30)
    rows: list[list[str]] = Field(max_length=300)
    ordered: bool = True


class ScriptCheck(CheckBase):
    """A shell script's TEXT, comments removed. Datapass never runs it."""
    kind: Literal['script']
    path: ProjectPath
    shell: Literal['bash', 'powershell']
    # A regular expression the first line must match (bash: the shebang).
    shebang: str | None = Field(default=None, max_length=200)
    # Regular expressions the code (without comments) must all match, or must not match. PowerShell is matched
    # case-insensitively, as PowerShell reads it.
    uses: list[str] = Field(default_factory=list, max_length=12)
    not_uses: list[str] = Field(default_factory=list, max_length=12)


class GitRepoCheck(CheckBase):
    """The repository itself: rooted at `repo`, the current branch, a clean tree, no merge or rebase in progress."""
    kind: Literal['git_repo']
    repo: FolderPath = '.'
    branch: GitName | None = None
    clean: bool | None = None
    in_progress: bool | None = None


class GitBranchCheck(CheckBase):
    kind: Literal['git_branch']
    repo: FolderPath = '.'
    name: GitName
    exists: bool = True


class GitLogCheck(CheckBase):
    """The commits of `ref` (only those not in `since`, when given): subjects, merges, ancestry, message format."""
    kind: Literal['git_log']
    repo: FolderPath = '.'
    ref: GitRev = 'HEAD'
    since: GitRev | None = None
    # Exactly these subjects, newest first.
    subjects: list[str] | None = Field(default=None, max_length=50)
    includes_subjects: list[str] = Field(default_factory=list, max_length=20)
    excludes_subjects: list[str] = Field(default_factory=list, max_length=20)
    min_count: int | None = Field(default=None, ge=0)
    max_count: int | None = Field(default=None, ge=0)
    linear: bool | None = None
    min_merges: int | None = Field(default=None, ge=0)
    # Each of these is an ancestor of ref (merge-base --is-ancestor), or is not.
    ancestors: list[GitRev] = Field(default_factory=list, max_length=10)
    not_ancestors: list[GitRev] = Field(default_factory=list, max_length=10)
    # Every subject in the range must match this regular expression (e.g. Conventional Commits).
    subject_regex: str | None = Field(default=None, max_length=300)
    # The message body of the commit with this subject must contain these texts (e.g. cherry-pick -x).
    bodies: dict[str, list[str]] = Field(default_factory=dict, max_length=10)


class GitFileCheck(CheckBase):
    """A file as committed at `ref` (not the working tree): content, mode, line endings."""
    kind: Literal['git_file']
    repo: FolderPath = '.'
    ref: GitRev = 'HEAD'
    path: ProjectPath
    exists: bool = True
    contains: list[str] = Field(default_factory=list, max_length=20)
    not_contains: list[str] = Field(default_factory=list, max_length=20)
    no_conflict_markers: bool = False
    mode: Literal['100644', '100755'] | None = None
    line_endings: Literal['lf', 'crlf'] | None = None


class GitTagCheck(CheckBase):
    kind: Literal['git_tag']
    repo: FolderPath = '.'
    name: GitName
    annotated: bool | None = None
    # The tag points at the same commit as this revision.
    target: GitRev | None = None
    message_contains: list[str] = Field(default_factory=list, max_length=5)


class GitIgnoreCheck(CheckBase):
    """The repository's own ignore rules (.gitignore files, .git/info/exclude; not the learner's global excludes
    file) and what the index tracks."""
    kind: Literal['git_ignore']
    repo: FolderPath = '.'
    ignored: list[ProjectPath] = Field(default_factory=list, max_length=20)
    not_ignored: list[ProjectPath] = Field(default_factory=list, max_length=20)
    tracked: list[ProjectPath] = Field(default_factory=list, max_length=20)
    untracked: list[ProjectPath] = Field(default_factory=list, max_length=20)


class GitStashCheck(CheckBase):
    kind: Literal['git_stash']
    repo: FolderPath = '.'
    count: int | None = Field(default=None, ge=0)
    message_contains: str | None = Field(default=None, max_length=120)


class AnyOfCheck(CheckBase):
    """Passes when one of its checks passes (for example: the script in bash or in PowerShell)."""
    kind: Literal['any_of']
    checks: list['Check'] = Field(min_length=2, max_length=4)


# ---- Infra Lab: the simulated world the learner's simulated commands left behind (runtime/infralab) ---------------

TfAddress = Annotated[str, Field(pattern=r'^(module\.[A-Za-z_][A-Za-z0-9_-]*\.){0,3}(data\.)?[a-z][a-z0-9_]*\.[A-Za-z_][A-Za-z0-9_-]*(\[("[^"]{1,80}"|\d{1,4})\])?$')]
UtcTime = Annotated[str, Field(pattern=r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')]


class TfStateCheck(CheckBase):
    """terraform.tfstate (written by the simulated apply): addresses present or absent, attribute values."""
    kind: Literal['tf_state']
    includes: list[TfAddress] = Field(default_factory=list, max_length=20)
    excludes: list[TfAddress] = Field(default_factory=list, max_length=20)
    attributes: dict[TfAddress, dict[str, Any]] = Field(default_factory=dict, max_length=10)
    # Every instance of this resource (all its count / for_each keys), in order: e.g. the three containers.
    instance_keys: dict[TfAddress, list[str | int]] = Field(default_factory=dict, max_length=5)
    # Root outputs recorded in the state, with their value.
    outputs: dict[str, Any] = Field(default_factory=dict, max_length=10)


class TfPlanCheck(CheckBase):
    """A fresh simulated `terraform plan` of the files as they are now (with the -var and -var-file options of the
    learner's last successful apply): it must succeed, and show no changes when `changes` is false."""
    kind: Literal['tf_plan']
    changes: bool = False


class TfResourceShape(Contract):
    address: TfAddress
    for_each: bool | None = None
    count: bool | None = None
    prevent_destroy: bool | None = None
    # Names (var.x, local.y, azurerm_x.y) its arguments must refer to.
    references: list[str] = Field(default_factory=list, max_length=10)


class TfVariableShape(Contract):
    name: str = Field(pattern=r'^[A-Za-z_][A-Za-z0-9_-]{0,60}$')
    type: str | None = Field(default=None, max_length=80)
    validation: bool | None = None
    default: bool | None = None


class TfModuleShape(Contract):
    # A module block of the root module: its name, its local source, the inputs it sets.
    name: str = Field(pattern=r'^[A-Za-z_][A-Za-z0-9_-]{0,60}$')
    source: str | None = Field(default=None, max_length=200)
    inputs: list[str] = Field(default_factory=list, max_length=10)


class TfConfigCheck(CheckBase):
    """The .tf files themselves (read, never executed): resources and how they are declared, variables, outputs,
    module calls, and whether every .tf file of the folder is laid out as terraform fmt would."""
    kind: Literal['tf_config']
    resources: list[TfResourceShape] = Field(default_factory=list, max_length=10)
    absent: list[TfAddress] = Field(default_factory=list, max_length=10)
    variables: list[TfVariableShape] = Field(default_factory=list, max_length=10)
    outputs: list[str] = Field(default_factory=list, max_length=10)
    modules: list[TfModuleShape] = Field(default_factory=list, max_length=5)
    # The root module declares no resource itself (everything goes through modules).
    root_resources: bool | None = None
    formatted: bool | None = None


class AzureResourceCheck(CheckBase):
    """A resource of the simulated subscription, by ARM type and name."""
    kind: Literal['azure_resource']
    type: str = Field(pattern=r'^[A-Za-z]+\.[A-Za-z]+/[A-Za-z/]+$')
    name: str = Field(min_length=1, max_length=120)
    group: str | None = Field(default=None, max_length=90)
    exists: bool = True
    managed_by: Literal['terraform', 'portal'] | None = None
    attributes: dict[str, Any] = Field(default_factory=dict, max_length=12)
    count: int | None = Field(default=None, ge=0)


class JournalCheck(CheckBase):
    """The Infra Lab shell's journal (.infralab/journal.jsonl): commands the learner ran, by regular expression."""
    kind: Literal['journal']
    includes: list[str] = Field(default_factory=list, max_length=10)
    excludes: list[str] = Field(default_factory=list, max_length=10)
    # Each pair: the last successful match of the first must come before the last successful match of the second.
    before: list[tuple[str, str]] = Field(default_factory=list, max_length=5)
    successful_only: bool = True


class DockerImageCheck(CheckBase):
    """An image of the simulated Docker engine."""
    kind: Literal['docker_image']
    tag: str = Field(pattern=r'^[a-z0-9][a-z0-9._/-]*:[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$')
    # Built from the Dockerfile as it is now (not an older version of it).
    current: bool = True
    base: str | None = Field(default=None, max_length=200)
    not_root: bool | None = None
    max_size_mb: float | None = None
    # Lint findings that must not be reported for it (DL ids follow hadolint; DP are the lab's own).
    no_lint: list[str] = Field(default_factory=list, max_length=12)
    healthcheck: bool | None = None


class DockerBuildCheck(CheckBase):
    """The build itself, simulated from the Dockerfile and the build context (nothing is built): which steps stay
    cached after a code change, and which paths .dockerignore keeps out of the context."""
    kind: Literal['docker_build']
    dockerfile: ProjectPath = 'Dockerfile'
    context: FolderPath = '.'
    # Pretend these files changed, then every step whose text contains one of `cached` must still be CACHED.
    changed: list[ProjectPath] = Field(default_factory=list, max_length=5)
    cached: list[str] = Field(default_factory=list, max_length=5)
    context_excludes: list[str] = Field(default_factory=list, max_length=10)


class DockerContainerCheck(CheckBase):
    """A container of the simulated engine (by name, or by compose service), its state and whether it answers."""
    kind: Literal['docker_container']
    name: str | None = Field(default=None, max_length=120)
    service: str | None = Field(default=None, max_length=60)
    running: bool = True
    health: Literal['healthy', 'unhealthy', 'none'] | None = None
    # GET http://localhost:<port><path> through the published port must answer.
    reachable: tuple[int, str] | None = None
    # For a compose service: it waits for these services to be healthy (depends_on condition service_healthy).
    waits_healthy: list[str] = Field(default_factory=list, max_length=5)


class AzureAlertCheck(CheckBase):
    """A metric alert rule of the simulated subscription on `scope` and `metric` (its name is the learner's), and
    what it does when replayed over the mission's metric scenario."""
    kind: Literal['azure_alert']
    scope: str = Field(min_length=1, max_length=120)
    metric: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    max_severity: int | None = Field(default=None, ge=0, le=4)
    action_group: str | None = Field(default=None, max_length=120)
    # It must fire inside each window (UTC), and must not fire inside any `quiet` window.
    fires: list[tuple[UtcTime, UtcTime]] = Field(default_factory=list, max_length=5)
    quiet: list[tuple[UtcTime, UtcTime]] = Field(default_factory=list, max_length=5)


class RolloutShape(Contract):
    complete: bool | None = None
    # The fewest pods answering traffic during the rollout (zero downtime: at least the replica count).
    min_available: int | None = Field(default=None, ge=0)
    to_image: str | None = None


class K8sDeploymentCheck(CheckBase):
    """A Deployment of the simulated cluster: image, ready pods, probes, strategy, and its last rollout."""
    kind: Literal['k8s_deployment']
    name: str = Field(pattern=r'^[a-z0-9][a-z0-9.-]{0,62}$')
    namespace: str = 'default'
    image: str | None = None
    ready: int | None = Field(default=None, ge=0)
    readiness_probe: bool | None = None
    strategy: Literal['RollingUpdate', 'Recreate'] | None = None
    last_rollout: RolloutShape | None = None
    no_crashing_pods: bool = False


class K8sServiceCheck(CheckBase):
    """A Service of the simulated cluster: its endpoints (ready pods it selects) and whether traffic reaches the app."""
    kind: Literal['k8s_service']
    name: str = Field(pattern=r'^[a-z0-9][a-z0-9.-]{0,62}$')
    namespace: str = 'default'
    min_endpoints: int = Field(default=1, ge=0)
    reachable: bool = True


Check = Annotated[Union[SqlCheck, NodeCheck, TestCheck, UnitTestCheck, RunCheck, FreshnessConfigCheck,
                        FreshnessResultCheck, DctValidateCheck, BoardCheck, RenderCheck, FileCheck, AirflowCheck,
                        PathCheck, TextCheck, ListingCheck, CsvCheck, ScriptCheck, GitRepoCheck, GitBranchCheck,
                        GitLogCheck, GitFileCheck, GitTagCheck, GitIgnoreCheck, GitStashCheck, AnyOfCheck,
                        TfStateCheck, TfPlanCheck, TfConfigCheck, AzureResourceCheck, JournalCheck, DockerImageCheck,
                        DockerBuildCheck, DockerContainerCheck, AzureAlertCheck, K8sDeploymentCheck,
                        K8sServiceCheck],
                  Field(discriminator='kind')]
AnyOfCheck.model_rebuild()
# Check kinds that need the catalog or dbt artifacts, so they belong to the dbt Lab.
DBT_KINDS = {'sql', 'node', 'test', 'unit_test', 'run', 'freshness_config', 'freshness_result', 'dct_validate',
             'board', 'render'}
GIT_KINDS = {'git_repo', 'git_branch', 'git_log', 'git_file', 'git_tag', 'git_ignore', 'git_stash'}
# Check kinds that read the Infra Lab's simulated world, so they belong to the Infra Lab.
INFRA_KINDS = {'tf_state', 'tf_plan', 'tf_config', 'azure_resource', 'journal', 'docker_image', 'docker_build',
               'docker_container', 'azure_alert', 'k8s_deployment', 'k8s_service'}


class Criterion(Contract):
    id: str = Field(pattern=r'^[a-z0-9-]{1,40}$')
    text: str = Field(min_length=1, max_length=400)
    checks: list[Check] = Field(min_length=1, max_length=12)


class Requirement(Contract):
    """A precondition (for example: the second day's data was loaded), with what to do when it is not met."""
    message: str = Field(min_length=1, max_length=400)
    check: Check


class Batch(Contract):
    id: str = Field(pattern=r'^[a-z0-9-]{1,40}$')
    label: str = Field(min_length=1, max_length=200)
    # Fixture SQL files, relative to the pack folder; `${raw}` stands for the mission's raw schema.
    sql: list[str] = Field(min_length=1, max_length=8)


class Ticket(Contract):
    from_: str = Field(alias='from', min_length=1, max_length=120)
    subject: str = Field(min_length=1, max_length=200)
    body: Lines


class Workspace(Contract):
    raw_schema: str = Field(pattern=IDENT.pattern)
    # Every schema dbt builds for this mission starts with this (dbt's <target schema>_<custom schema>).
    dev_schema: str = Field(pattern=IDENT.pattern)


class ReferenceStep(Contract):
    """How the smokes play the reference solution. dbt Lab: steps in order (load a batch, run a real command).
    Terminal Lab: each step is a whole solution script (`solution/solve.sh`, `solution/solve.ps1`), played on a fresh
    fixture of its own by scripts/terminal_missions_smoke.py; every one must pass."""
    batch: str | None = None
    dbt: str | None = Field(default=None, max_length=300)
    dct: str | None = Field(default=None, max_length=300)
    dct_validate: str | None = None
    bash: ProjectPath | None = None
    powershell: ProjectPath | None = None
    # Infra Lab: one line typed in the simulated shell (terraform, docker, kubectl, az, curl, lab).
    infra: str | None = Field(default=None, max_length=500)
    # A command can be expected to fail, e.g. dbt source freshness with a stale source exits 1.
    exit_code: int = 0

    @model_validator(mode='after')
    def one(self) -> 'ReferenceStep':
        steps = (self.batch, self.dbt, self.dct, self.dct_validate, self.bash, self.powershell, self.infra)
        if sum(v is not None for v in steps) != 1:
            raise ValueError('a reference step does exactly one thing')
        return self


def _file_text(value: Any) -> Any:
    return '\n'.join(value) + '\n' if isinstance(value, list) and all(isinstance(v, str) for v in value) else value


# A fixture file's text: a string as is, or a list of lines (each ended by a newline).
FileText = Annotated[str, BeforeValidator(_file_text), Field(max_length=200_000)]


class FixtureFile(Contract):
    text: FileText
    eol: Literal['lf', 'crlf'] = 'lf'
    # Recorded as executable when committed (and chmod +x on disk where the file system has modes).
    executable: bool = False


FileSpec = Union[FileText, FixtureFile]


class GitCommit(Contract):
    message: Lines
    # Files written before the commit (None deletes one); everything is then staged with `git add -A`.
    files: dict[ProjectPath, FileSpec | None] = Field(default_factory=dict, max_length=40)


class GitStash(Contract):
    message: str = Field(min_length=1, max_length=120)
    files: dict[ProjectPath, FileSpec | None] = Field(min_length=1, max_length=20)


class GitTag(Contract):
    name: GitName
    # An annotated tag when a message is given, a lightweight one otherwise.
    message: str | None = Field(default=None, max_length=400)


class GitStep(Contract):
    """One step of a fixture's history, run by the runtime as fixed git commands (never a shell string)."""
    commit: GitCommit | None = None
    branch: GitName | None = None          # create a branch at HEAD
    switch: GitName | None = None
    merge: GitName | None = None           # --no-ff, with git's default message
    tag: GitTag | None = None
    delete_branch: GitName | None = None   # -D
    reset_hard: GitRev | None = None
    stash: GitStash | None = None

    @model_validator(mode='after')
    def one(self) -> 'GitStep':
        if sum(v is not None for v in self.__dict__.values()) != 1:
            raise ValueError('a git step does exactly one thing')
        return self


class GitFixture(Contract):
    # The repository's folder inside the mission folder.
    path: FolderPath = '.'
    branch: GitName = 'main'
    # Author and committer of the fixture's commits; the dates are fixed, so the fixture's hashes are reproducible.
    author: str = Field(default='Sam Rivera <sam.rivera@example.com>', pattern=r'^[^<>\n]{1,60} <[^<>\s]{3,80}>$')
    start: str = Field(default='2026-09-01T09:00:00+02:00', pattern=r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$')
    steps: list[GitStep] = Field(min_length=1, max_length=40)


class TerminalFixture(Contract):
    """What a Terminal Lab mission folder starts as: the pack's `project/` overlay, these files, a repository."""
    files: dict[ProjectPath, FileSpec] = Field(default_factory=dict, max_length=60)
    git: GitFixture | None = None


class InfraFixture(Contract):
    """What an Infra Lab mission folder starts as: the pack's `project/` overlay, these files, the simulated world
    (merged over the lab's default world: subscription, Docker engine, cluster, metric scenarios), then simulated
    commands played before the learner arrives (for example: deploy yesterday's version to the cluster)."""
    files: dict[ProjectPath, FileSpec] = Field(default_factory=dict, max_length=60)
    world: dict[str, Any] = Field(default_factory=dict)
    setup: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def bounded(self) -> 'InfraFixture':
        if len(json.dumps(self.world)) > 400_000:
            raise ValueError('the fixture world exceeds 400 KB')
        return self


class Mission(Contract):
    id: str = Field(pattern=MISSION_ID.pattern)
    version: str = Field(min_length=1, max_length=20)
    lab: Literal['dbt', 'terminal', 'infra']
    title: str = Field(min_length=1, max_length=120)
    level: Literal['intro', 'intermediate', 'advanced']
    estimate: str = Field(max_length=40)
    skills: list[str] = Field(default_factory=list, max_length=10)
    ticket: Ticket
    acceptance: list[Criterion] = Field(min_length=1, max_length=10)
    requires: list[Requirement] = Field(default_factory=list, max_length=6)
    hints: list[str] = Field(default_factory=list, max_length=8)
    # dbt Lab: the mission's schemas and its SQL fixture batches.
    workspace: Workspace | None = None
    batches: list[Batch] = Field(default_factory=list, max_length=6)
    # Terminal Lab: the files and repository the mission folder starts as.
    fixture: TerminalFixture | None = None
    # Infra Lab: the files and the simulated world the mission folder starts as.
    infra: InfraFixture | None = None
    reference: list[ReferenceStep] = Field(default_factory=list, max_length=40)

    @model_validator(mode='after')
    def consistent(self) -> 'Mission':
        ids = [c.id for c in self.acceptance]
        if len(ids) != len(set(ids)):
            raise ValueError('acceptance criteria ids must be unique')
        kinds = {check.kind for check in all_checks(self)}
        if self.lab != 'infra' and kinds & INFRA_KINDS:
            raise ValueError(f'check kinds {sorted(kinds & INFRA_KINDS)} need the Infra Lab')
        if self.lab != 'infra' and (self.infra is not None or any(step.infra for step in self.reference)):
            raise ValueError('only an Infra Lab mission has an infra fixture and infra reference steps')
        if self.lab == 'dbt':
            if self.workspace is None or not self.batches or self.fixture is not None:
                raise ValueError('a dbt mission has a workspace and fixture batches, and no terminal fixture')
            if any(step.bash or step.powershell for step in self.reference):
                raise ValueError('a dbt mission plays dbt and dct commands, not shell scripts')
        elif self.lab == 'infra':
            if self.infra is None or self.fixture is not None or self.workspace is not None or self.batches:
                raise ValueError('an infra mission has an infra fixture, and no terminal fixture, workspace or batches')
            if any(not step.infra for step in self.reference):
                raise ValueError('an infra mission is played by lines of the simulated shell (infra steps)')
            if kinds & (DBT_KINDS | GIT_KINDS):
                raise ValueError(f'check kinds {sorted(kinds & (DBT_KINDS | GIT_KINDS))} do not belong to the Infra Lab')
        else:
            if self.fixture is None or self.workspace is not None or self.batches:
                raise ValueError('a terminal mission has a fixture, and no catalog workspace or SQL batches')
            if any(not (step.bash or step.powershell) for step in self.reference):
                raise ValueError('a terminal mission is played by solution scripts (bash or powershell steps)')
            kinds = {check.kind for check in all_checks(self)}
            if kinds & DBT_KINDS:
                raise ValueError(f'check kinds {sorted(kinds & DBT_KINDS)} need the dbt Lab')
        batches = {b.id for b in self.batches}
        for step in self.reference:
            if step.batch is not None and step.batch not in batches:
                raise ValueError(f'reference step loads unknown batch {step.batch!r}')
        return self

    @property
    def folder(self) -> str:
        return f'missions/{self.id}'


def all_checks(mission: Mission) -> list:
    """Every check of a mission, including the ones inside any_of."""
    out: list = []
    pending = [c for criterion in mission.acceptance for c in criterion.checks] + [r.check for r in mission.requires]
    while pending:
        check = pending.pop(0)
        out.append(check)
        if isinstance(check, AnyOfCheck):
            pending.extend(check.checks)
    return out


def missions_root() -> Path:
    from datapass_runtime.content import CONTENT
    return CONTENT / 'missions'


def load_pack(pack_dir: Path) -> dict:
    pack = json.loads((pack_dir / 'pack.json').read_text(encoding='utf-8'))
    if not isinstance(pack, dict) or not isinstance(pack.get('missions'), list):
        raise ValueError(f'{pack_dir.name}/pack.json lists no missions')
    return pack


def find_mission(mission_id: str, root: Path | None = None) -> tuple[Mission, Path]:
    """The mission and its pack folder. Mission ids are unique across packs."""
    if not MISSION_ID.fullmatch(mission_id):
        raise ValueError('Invalid mission id.')
    root = root or missions_root()
    for pack_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        path = pack_dir / mission_id / 'mission.json'
        if path.is_file():
            return Mission.model_validate(json.loads(path.read_text(encoding='utf-8'))), pack_dir
    raise KeyError(f'Unknown mission {mission_id}.')


def load_missions(root: Path | None = None) -> list[tuple[Mission, Path]]:
    root = root or missions_root()
    found = []
    for pack_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for mission_id in load_pack(pack_dir)['missions']:
            found.append(find_mission(mission_id, root))
    return found
