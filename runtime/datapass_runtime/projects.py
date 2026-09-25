"""Projects: end-to-end stories whose steps are done in the Workbench labs.

Content lives in `content/projects/<id>/project.json` (schema below). Each step says which lab it happens in,
how to open it, and how Datapass verifies it:

- state checks run on the workspace catalog in the kernel: a table with its columns and rows, a read-only SQL
  assertion, a SQL pool table design, a registered MLflow model;
- run checks read the run journal (`run_journal.py`): what the labs really ran, recorded by the runtime when
  it answered (an exercise passed on Submit, a pipeline or job run that succeeded, a simulated Airflow run...).

A step without checks is manual: the learner ticks it and the extension labels it as a declaration. The
runtime never marks a manual step as verified, and every check result carries the truth of what it saw
(real, simulated, emulation, hybrid, or static for the SQL lineage). Check labels and messages are French,
like the Projects UI.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
from typing import Annotated, Any, Callable, Literal, Union

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from .run_journal import SUMMARIZERS, RunJournal

# The Workbench modules (src/modules.ts) and the sub-tabs a step can open.
MODULES = ('mosaic', 'practice', 'fabric', 'bi', 'sparklab', 'dbt', 'airflow', 'pipeline')
TABS = {'fabric': ('pipelines', 'sqlpool', 'databricks', 'lakehouse'),
        'bi': ('warehouse', 'model', 'lineage', 'dbt', 'concepts')}
# Workspace folders a step may open a file in, and project files may be copied to.
FILE_ROOTS = ('projects/', 'factory/', 'bi/', 'airflow/dags/', 'pipelines/', 'notebooks/', 'notes/', 'datasets/')
PROJECT_ID = re.compile(r'^[a-z0-9][a-z0-9-]{0,63}$')
STEP_ID = re.compile(r'^[a-z0-9][a-z0-9-]{0,63}$')
EXERCISE_KEY = re.compile(r'^([A-Za-z0-9_-]+)/([A-Za-z0-9_-]+)/([a-z0-9-]+)$')
TABLE = re.compile(r'^(source|bronze|silver|gold|warehouse|features|metrics)\.[A-Za-z][A-Za-z0-9_]{0,62}$')
POOL_TABLE = re.compile(r'^(dbo|source|bronze|silver|gold|warehouse|features|metrics)\.[A-Za-z][A-Za-z0-9_]{0,62}$')
Scalar = Union[str, int, float, bool, None]


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')


def _join_lines(value: Any) -> Any:
    return '\n'.join(value) if isinstance(value, list) and all(isinstance(v, str) for v in value) else value


# Markdown text, written in JSON as one string or as a list of lines.
Lines = Annotated[str, BeforeValidator(_join_lines), Field(min_length=1, max_length=8000)]


def safe_path(value: str) -> bool:
    parts = value.split('/')
    return (bool(re.fullmatch(r'[A-Za-z0-9_./ -]{1,200}', value)) and not value.startswith('/')
            and '..' not in parts and '' not in parts and value.startswith(FILE_ROOTS))


class CheckBase(Contract):
    label: str = Field(min_length=1, max_length=200)


# State checks: evaluated in the kernel on the workspace catalog.
class TableCheck(CheckBase):
    kind: Literal['table']
    table: str = Field(pattern=TABLE.pattern)
    columns: list[str] = Field(default_factory=list, max_length=40)
    # DuckDB column types by column; a type without precision also accepts its parametrised form.
    types: dict[str, str] = Field(default_factory=dict)
    min_rows: int = Field(default=1, ge=0)


class SqlCheck(CheckBase):
    kind: Literal['sql']
    sql: str = Field(min_length=1, max_length=4000)
    expected: list[dict[str, Scalar]] = Field(max_length=50)


class SqlPoolTableCheck(CheckBase):
    kind: Literal['sqlpool_table']
    table: str = Field(pattern=POOL_TABLE.pattern)
    distribution: Literal['HASH', 'ROUND_ROBIN', 'REPLICATE', 'AUTO'] | None = None
    hash_columns: list[str] | None = None
    partitioned: bool | None = None


class MlflowModelCheck(CheckBase):
    kind: Literal['mlflow_model']
    model: str = Field(pattern=r'^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$')
    alias: str | None = Field(default=None, pattern=r'^[a-z][a-z0-9_-]{0,40}$')
    min_versions: int = Field(default=1, ge=1)


STATE_KINDS = ('table', 'sql', 'sqlpool_table', 'mlflow_model')


# Run checks: a recorded run of a lab that succeeded and matches the constraints.
class RunSpec(Contract):
    lab: str
    subject: str | None = None
    expect: dict[str, Scalar] = Field(default_factory=dict)
    at_least: dict[str, float] = Field(default_factory=dict)
    at_most: dict[str, float] = Field(default_factory=dict)
    includes: dict[str, list[str]] = Field(default_factory=dict)


class RunCheck(CheckBase, RunSpec):
    """Generic form, for labs added later: any journal lab, subject and facts."""
    kind: Literal['run']

    @model_validator(mode='after')
    def known_lab(self) -> 'RunCheck':
        if self.lab not in SUMMARIZERS:
            raise ValueError(f'no lab records runs as {self.lab!r}')
        return self

    def spec(self) -> RunSpec:
        return RunSpec(**self.model_dump(include=set(RunSpec.model_fields)))


class ExerciseCheck(CheckBase):
    kind: Literal['exercise']
    exercise: str = Field(pattern=EXERCISE_KEY.pattern)

    def spec(self) -> RunSpec:
        _, exercise_id, language = EXERCISE_KEY.fullmatch(self.exercise).groups()
        return RunSpec(lab='exercise', subject=exercise_id, expect={'mode': 'submit', 'language': language})


class CloudPipelineCheck(CheckBase):
    kind: Literal['cloud_pipeline']
    flavor: Literal['fabric', 'adf', 'synapse']
    pipeline: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9 _-]{0,139}$')
    data_plane: Literal['local', 'simulated'] = 'local'
    activities: list[str] = Field(default_factory=list)  # activities that must have succeeded in that run
    min_attempts: int | None = Field(default=None, ge=2)

    def spec(self) -> RunSpec:
        return RunSpec(lab='factory', subject=f'{self.flavor}/{self.pipeline}', expect={'data_plane': self.data_plane},
                       includes={'succeeded': self.activities} if self.activities else {},
                       at_least={'max_attempts': self.min_attempts} if self.min_attempts else {})


class SqlPoolRunCheck(CheckBase):
    kind: Literal['sqlpool_run']
    flavor: Literal['synapse', 'fabric']
    script: str | None = None  # the workspace-relative path the SQL pool tab ran
    tables: list[str] = Field(default_factory=list)  # tables the script's run left in the pool

    def spec(self) -> RunSpec:
        return RunSpec(lab='sqlpool', subject=f'{self.flavor}:{self.script}' if self.script else None,
                       expect={'flavor': self.flavor}, includes={'tables': self.tables} if self.tables else {})


class DatabricksJobCheck(CheckBase):
    kind: Literal['databricks_job']
    job: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9 _.-]{0,99}$')
    data_plane: Literal['local', 'simulated'] = 'local'
    principal: str | None = None
    tasks: list[str] = Field(default_factory=list)  # tasks that must have succeeded in that run
    min_attempts: int | None = Field(default=None, ge=2)

    def spec(self) -> RunSpec:
        expect: dict[str, Scalar] = {'data_plane': self.data_plane}
        if self.principal:
            expect['principal'] = self.principal
        return RunSpec(lab='databricks', subject=self.job, expect=expect,
                       includes={'succeeded': self.tasks} if self.tasks else {},
                       at_least={'max_attempts': self.min_attempts} if self.min_attempts else {})


class BiModelCheck(CheckBase):
    kind: Literal['bi_model']
    facts: list[str] = Field(default_factory=list)  # fact tables the model must declare
    min_checks: int = Field(default=1, ge=1)

    def spec(self) -> RunSpec:
        return RunSpec(lab='bi', subject='warehouse', expect={'model_failed': 0, 'model_error': False},
                       at_least={'model_checks': self.min_checks}, includes={'facts': self.facts} if self.facts else {})


class BiLineageCheck(CheckBase):
    """The BI Lab's column lineage (a static analysis of the warehouse SQL) traces a column to its origins."""
    kind: Literal['bi_lineage']
    column: str = Field(pattern=r'^[a-z]+\.[A-Za-z][A-Za-z0-9_]*\.[A-Za-z][A-Za-z0-9_]*$')
    origins: list[str] = Field(min_length=1)

    def spec(self) -> RunSpec:
        return RunSpec(lab='bi', subject='warehouse', includes={'lineage_origins': [f'{self.column}<-{o}' for o in self.origins]})


class DbtCheck(CheckBase):
    kind: Literal['dbt']
    command: Literal['build', 'run', 'test', 'seed', 'snapshot'] = 'build'
    nodes: list[str] = Field(min_length=1)  # models, snapshots or tests that succeeded in that run

    def spec(self) -> RunSpec:
        return RunSpec(lab='dbt', expect={'command': self.command}, includes={'succeeded': self.nodes})


class AirflowCheck(CheckBase):
    kind: Literal['airflow']
    dag_id: str = Field(pattern=r'^[A-Za-z0-9_.-]{1,250}$')
    schedule: str | None = None
    catchup: bool | None = None
    min_runs: int = Field(default=1, ge=1)
    min_try_number: int | None = Field(default=None, ge=2)  # a retry was simulated
    tasks: list[str] = Field(default_factory=list)

    def spec(self) -> RunSpec:
        expect: dict[str, Scalar] = {'failed_runs': 0}
        if self.schedule is not None:
            expect['schedule'] = self.schedule
        if self.catchup is not None:
            expect['catchup'] = self.catchup
        at_least: dict[str, float] = {'simulated_runs': self.min_runs}
        if self.min_try_number:
            at_least['max_try_number'] = self.min_try_number
        return RunSpec(lab='airflow', subject=self.dag_id, expect=expect, at_least=at_least,
                       includes={'tasks': self.tasks} if self.tasks else {})


class PipelineLabCheck(CheckBase):
    kind: Literal['pipeline_lab']
    pipeline: str = Field(pattern=r'^[A-Za-z_][A-Za-z0-9_-]{0,99}$')
    min_quality_tasks: int = Field(default=0, ge=0)
    tasks: list[str] = Field(default_factory=list)

    def spec(self) -> RunSpec:
        return RunSpec(lab='pipeline', subject=self.pipeline, at_least={'quality_tasks': self.min_quality_tasks},
                       includes={'tasks': self.tasks} if self.tasks else {})


class SparkLabCheck(CheckBase):
    kind: Literal['sparklab']
    columns: list[str] = Field(default_factory=list)
    max_exchanges: int | None = Field(default=None, ge=0)
    min_broadcast_joins: int | None = Field(default=None, ge=1)

    def spec(self) -> RunSpec:
        at_least = {'broadcast_joins': self.min_broadcast_joins} if self.min_broadcast_joins else {}
        at_most = {'exchanges': self.max_exchanges} if self.max_exchanges is not None else {}
        return RunSpec(lab='execute', subject='sparklab', at_least=at_least, at_most=at_most,
                       includes={'columns': self.columns} if self.columns else {})


class MosaicRunCheck(CheckBase):
    kind: Literal['mosaic']
    language: Literal['sql', 'python', 'polars']
    columns: list[str] = Field(default_factory=list)

    def spec(self) -> RunSpec:
        return RunSpec(lab='execute', subject=self.language, includes={'columns': self.columns} if self.columns else {})


class LakehouseDemoCheck(CheckBase):
    kind: Literal['lakehouse_demo']

    def spec(self) -> RunSpec:
        return RunSpec(lab='lakehouse', subject='retail-demo')


Check = Annotated[Union[TableCheck, SqlCheck, SqlPoolTableCheck, MlflowModelCheck, RunCheck, ExerciseCheck,
                        CloudPipelineCheck, SqlPoolRunCheck, DatabricksJobCheck, BiModelCheck, BiLineageCheck, DbtCheck, AirflowCheck,
                        PipelineLabCheck, SparkLabCheck, MosaicRunCheck, LakehouseDemoCheck],
                  Field(discriminator='kind')]

# What each kind of check sees; run checks report the truth recorded with the run they matched, except the
# lineage, a static analysis of the SQL text that the run only computed.
STATE_TRUTH = {'table': 'real', 'sql': 'real', 'sqlpool_table': 'simulated', 'mlflow_model': 'simulated'}
FIXED_RUN_TRUTH = {'bi_lineage': 'static'}
# Journal facts as the learner reads them in a check message.
FACT_LABELS = {
    'data_plane': 'plan de données', 'succeeded': 'étapes réussies', 'max_attempts': 'nombre de tentatives',
    'model_failed': 'contrôles du modèle en échec', 'model_checks': 'contrôles du modèle',
    'model_error': 'erreur dans le fichier du modèle', 'facts': 'tables de faits du modèle', 'lineage_origins': 'lignage',
    'schedule': 'planification', 'catchup': 'rattrapage (catchup)', 'simulated_runs': 'runs simulés',
    'failed_runs': 'runs en échec', 'max_try_number': 'numéro de tentative maximum', 'quality_tasks': 'contrôles qualité réussis',
    'tasks': 'tâches', 'columns': 'colonnes', 'exchanges': 'échanges (plan simulé)',
    'broadcast_joins': 'jointures broadcast (plan simulé)', 'mode': 'mode', 'language': 'langage',
    'principal': "principal d'exécution", 'flavor': 'produit', 'tables': 'tables', 'command': 'commande',
}


class OpenAction(Contract):
    module: str
    tab: str | None = None
    file: str | None = None  # workspace-relative, opened beside the Workbench
    exercise: str | None = Field(default=None, pattern=EXERCISE_KEY.pattern)
    # Lab files the extension creates before opening the step, never overwriting the learner's files.
    scaffold: list[Literal['project', 'factory', 'bi', 'retail_demo', 'airflow', 'pipeline', 'sparklab']] = \
        Field(default_factory=list)

    @model_validator(mode='after')
    def coherent(self) -> 'OpenAction':
        if self.module not in MODULES:
            raise ValueError(f'unknown Workbench module {self.module!r}')
        if self.tab is not None and self.tab not in TABS.get(self.module, ()):
            raise ValueError(f'{self.module} has no tab {self.tab!r}')
        if self.file is not None and not safe_path(self.file):
            raise ValueError(f'{self.file!r} is not a workspace path under {", ".join(FILE_ROOTS)}')
        if self.exercise is not None and self.module != 'practice':
            raise ValueError('an exercise opens in the practice module')
        return self


class Step(Contract):
    id: str = Field(pattern=STEP_ID.pattern)
    title: str = Field(min_length=1, max_length=120)
    module: str
    optional: bool = False
    # Markdown subset (paragraphs, lists, **bold**, `code`, fenced code); a list is joined line by line.
    instructions: Lines
    open: OpenAction
    checks: list[Check] = Field(default_factory=list, max_length=6)

    @model_validator(mode='after')
    def coherent(self) -> 'Step':
        if self.module not in MODULES:
            raise ValueError(f'unknown Workbench module {self.module!r}')
        if self.open.module != self.module:
            raise ValueError(f'step {self.id} opens {self.open.module}, not its module {self.module}')
        return self


class Project(Contract):
    schema_version: Literal[1] = 1
    id: str = Field(pattern=PROJECT_ID.pattern)
    version: str = Field(pattern=r'^[0-9]{1,4}$')
    order: int = Field(ge=0)
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=300)
    level: Literal['beginner', 'intermediate', 'advanced']
    duration_minutes: int = Field(ge=10, le=2000)
    story: Lines
    goals: list[str] = Field(min_length=1, max_length=10)
    steps: list[Step] = Field(min_length=1, max_length=20)

    @model_validator(mode='after')
    def coherent(self) -> 'Project':
        ids = [step.id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError('step ids must be unique')
        for step in self.steps:
            if step.open.file and step.open.file.startswith('projects/') and \
                    not step.open.file.startswith(f'projects/{self.id}/'):
                raise ValueError(f'step {step.id} opens another project\'s file')
        return self


def projects_root() -> Path:
    from .content import CONTENT
    return CONTENT / 'projects'


def load_project(project_id: str, root: Path | None = None) -> Project:
    if not PROJECT_ID.fullmatch(project_id):
        raise ValueError('Invalid project id.')
    path = (root or projects_root()) / project_id / 'project.json'
    if not path.is_file():
        raise KeyError(f'Unknown project: {project_id}')
    project = Project.model_validate(json.loads(path.read_text(encoding='utf-8')))
    if project.id != project_id:
        raise ValueError(f'{path} declares the id {project.id}')
    return project


def load_projects(root: Path | None = None) -> list[Project]:
    root = root or projects_root()
    found = [load_project(p.name, root) for p in sorted(root.iterdir()) if (p / 'project.json').is_file()] \
        if root.is_dir() else []
    return sorted(found, key=lambda p: (p.order, p.id))


# ---- State checks (kernel side) -------------------------------------------------------------------------


def _type_matches(actual: str, wanted: str) -> bool:
    actual, wanted = actual.upper().replace(' ', ''), wanted.upper().replace(' ', '')
    return actual == wanted or ('(' not in wanted and actual.startswith(wanted + '('))


def _table(catalog, spec: dict) -> tuple[bool, str]:
    name = spec['table']
    if not catalog.exists(name):
        return False, f'La table {name} n\'existe pas encore.'
    described = {str(r[0]).lower(): str(r[1]) for r in catalog.db.execute(f'DESCRIBE {name}').fetchall()}
    missing = [c for c in spec['columns'] if c.lower() not in described]
    if missing:
        return False, f'{name} n\'a pas la colonne {", ".join(missing)}.'
    for column, wanted in spec['types'].items():
        actual = described.get(column.lower())
        if actual is None or not _type_matches(actual, wanted):
            return False, f'{name}.{column} est de type {actual}, {wanted} attendu.'
    rows = int(catalog.db.execute(f'SELECT COUNT(*) FROM {name}').fetchone()[0])
    if rows < spec['min_rows']:
        return False, f'{name} a {rows} ligne(s), au moins {spec["min_rows"]} attendue(s).'
    return True, f'{name} existe : {rows} ligne(s).'


def _sql(catalog, spec: dict) -> tuple[bool, str]:
    from .execution import compare_rows
    try:
        result = catalog.query(spec['sql'])
    except Exception as error:  # a missing table is a failed check, not an outage
        return False, f'La requête de vérification échoue : {error}'
    if result['truncated']:
        return False, 'Le résultat de la vérification est tronqué.'
    if compare_rows(result['rows'], spec['expected']):
        return True, 'Le résultat attendu est obtenu.'
    shown = json.dumps(result['rows'][:5], ensure_ascii=False, default=str)
    return False, f'Résultat obtenu : {shown}; attendu : {json.dumps(spec["expected"][:5], ensure_ascii=False)}.'


def _pool_table(catalog, spec: dict) -> tuple[bool, str]:
    from sqlpoollab.model import Metadata
    metadata = Metadata(catalog.directory / 'sqlpool.json')
    schema, table = spec['table'].lower().split('.')
    candidates = [f'{schema}.{table}'] + ([f'warehouse.{table}'] if schema == 'dbo' else
                                          [f'dbo.{table}'] if schema == 'warehouse' else [])
    design = next((metadata.tables[k] for k in candidates if k in metadata.tables), None)
    if design is None:
        return False, f'Le pool SQL n\'a pas de table {spec["table"]}.'
    if spec.get('distribution') and design.distribution != spec['distribution']:
        return False, f'{spec["table"]} est distribuée en {design.label()}, {spec["distribution"]} attendu.'
    if spec.get('hash_columns') is not None and [c.lower() for c in design.hash_columns] != \
            [c.lower() for c in spec['hash_columns']]:
        return False, f'{spec["table"]} est distribuée en {design.label()}.'
    if spec.get('partitioned') is not None and (design.partition is not None) != spec['partitioned']:
        state = "n'est pas" if spec['partitioned'] else 'est'
        return False, f'{spec["table"]} {state} partitionnée.'
    return True, f'{spec["table"]} : {design.label()}.'


def _mlflow_model(catalog, spec: dict) -> tuple[bool, str]:
    from .databricks_workspace import load_state
    model = (load_state(catalog).get('mlflow') or {}).get('models', {}).get(spec['model'])
    if not model:
        return False, f'Le modèle {spec["model"]} n\'est pas enregistré.'
    versions = len(model.get('versions') or [])
    if versions < spec['min_versions']:
        return False, f'{spec["model"]} a {versions} version(s), au moins {spec["min_versions"]} attendue(s).'
    aliases = model.get('aliases') or {}
    if spec.get('alias') and spec['alias'] not in aliases:
        return False, f'{spec["model"]} n\'a pas d\'alias {spec["alias"]}.'
    detail = f', alias {spec["alias"]} → version {aliases[spec["alias"]]}' if spec.get('alias') else ''
    return True, f'{spec["model"]} : {versions} version(s){detail}.'


STATE_CHECKS: dict[str, Callable[[Any, dict], tuple[bool, str]]] = {
    'table': _table, 'sql': _sql, 'sqlpool_table': _pool_table, 'mlflow_model': _mlflow_model,
}


def evaluate_state_checks(catalog, specs: list[dict]) -> list[dict]:
    """Kernel op project_state_checks: read-only checks on the workspace catalog and the labs' local state."""
    results = []
    for spec in specs:
        if catalog.kind == 'sqlite':
            results.append({'passed': False, 'message': 'Les projets ont besoin du catalogue DuckDB.'})
            continue
        try:
            passed, message = STATE_CHECKS[spec['kind']](catalog, spec)
        except Exception as error:
            passed, message = False, f'Vérification impossible : {error}'
        results.append({'passed': passed, 'message': message})
    return results


# ---- Run checks (API side) ------------------------------------------------------------------------------


def _fact_problem(entry: dict, spec: RunSpec) -> str | None:
    facts = entry.get('facts') or {}

    def name(key: str) -> str:
        return f'« {FACT_LABELS.get(key, key)} »'

    for key, wanted in spec.expect.items():
        if facts.get(key) != wanted:
            return f'{name(key)} vaut {json.dumps(facts.get(key), ensure_ascii=False)}, {json.dumps(wanted, ensure_ascii=False)} attendu'
    for key, minimum in spec.at_least.items():
        value = facts.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < minimum:
            return f'{name(key)} vaut {value}, au moins {_number(minimum)} attendu'
    for key, maximum in spec.at_most.items():
        value = facts.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value > maximum:
            return f'{name(key)} vaut {value}, au plus {_number(maximum)} attendu'
    for key, wanted in spec.includes.items():
        have = {str(v).lower() for v in facts.get(key) or []}
        missing = [w for w in wanted if w.lower() not in have]
        if missing:
            return f'{name(key)} ne contient pas {", ".join(missing)}'
    return None


def _number(value: float) -> str:
    return str(int(value)) if math.isfinite(value) and value == int(value) else str(value)


def match_run(journal: RunJournal, spec: RunSpec) -> dict:
    entries = journal.entries(spec.lab, spec.subject)
    if not entries:
        return {'passed': False, 'truth': None, 'message': 'Aucune exécution enregistrée pour l\'instant.'}
    problems = []
    for entry in entries:
        if not entry.get('ok'):
            continue
        problem = _fact_problem(entry, spec)
        if problem is None:
            return {'passed': True, 'truth': entry.get('truth'), 'at': entry.get('at'),
                    'message': f'Exécution du {_when(entry.get("at"))} : {entry.get("status")}.'}
        problems.append(problem)
    latest = entries[0]
    if problems:
        return {'passed': False, 'truth': latest.get('truth'), 'at': latest.get('at'),
                'message': f'Une exécution a réussi, mais {problems[0]}.'}
    return {'passed': False, 'truth': latest.get('truth'), 'at': latest.get('at'),
            'message': f'Dernière exécution du {_when(latest.get("at"))} : {latest.get("status")}.'}


def _when(value: Any) -> str:
    try:
        return datetime.fromisoformat(str(value)).strftime('%Y-%m-%d %H:%M UTC')
    except ValueError:
        return str(value)


def verify(project: Project, step_ids: list[str], journal: RunJournal,
           kernel: Callable[[dict], Any]) -> dict[str, Any]:
    """Verify the automatic checks of some steps (all when step_ids is empty); manual steps stay manual."""
    unknown = sorted(set(step_ids) - {s.id for s in project.steps})
    if unknown:
        raise ValueError(f'Unknown step: {", ".join(unknown)}')
    steps = [s for s in project.steps if not step_ids or s.id in step_ids]
    state = [(step.id, i, check) for step in steps for i, check in enumerate(step.checks) if check.kind in STATE_KINDS]
    state_results: dict[tuple[str, int], dict] = {}
    if state:
        answers = kernel({'op': 'project_state_checks', 'checks': [c.model_dump() for _, _, c in state]})
        for (step_id, index, _), answer in zip(state, answers):
            state_results[(step_id, index)] = answer
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    out = []
    for step in steps:
        results = []
        for index, check in enumerate(step.checks):
            if check.kind in STATE_KINDS:
                answer = state_results[(step.id, index)]
                result = {'passed': answer['passed'], 'truth': STATE_TRUTH[check.kind], 'message': answer['message']}
            else:
                result = match_run(journal, check.spec())
            truth = FIXED_RUN_TRUTH.get(check.kind) or result.get('truth') or _default_truth(check)
            results.append({'kind': check.kind, 'label': check.label, 'status': 'passed' if result['passed'] else 'failed',
                            'truth': truth, 'message': result['message'],
                            **({'at': result['at']} if result.get('at') else {})})
        status = 'manual' if not step.checks else 'passed' if all(r['status'] == 'passed' for r in results) else 'failed'
        out.append({'id': step.id, 'status': status, 'checks': results})
    return {'project_id': project.id, 'version': project.version, 'checked_at': now, 'steps': out}


def _default_truth(check) -> str:
    """The truth a run check reports before any run was recorded."""
    return {'exercise': 'real', 'cloud_pipeline': 'hybrid', 'sqlpool_run': 'hybrid', 'databricks_job': 'hybrid',
            'bi_model': 'real', 'dbt': 'emulation', 'airflow': 'simulated', 'pipeline_lab': 'real',
            'sparklab': 'emulation', 'mosaic': 'real', 'lakehouse_demo': 'real'}.get(check.kind, 'simulated')
