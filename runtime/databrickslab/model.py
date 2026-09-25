"""Job definitions (Jobs API JSON) read and validated with Databricks' design-time rules."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

TASK_KEY = re.compile(r'^[A-Za-z0-9_-]{1,100}$')
PARAMETER_NAME = re.compile(r'^[A-Za-z0-9_.-]{1,100}$')
RUN_IF = ('ALL_SUCCESS', 'AT_LEAST_ONE_SUCCESS', 'NONE_FAILED', 'ALL_DONE', 'AT_LEAST_ONE_FAILED', 'ALL_FAILED')
CONDITION_OPS = {'EQUAL_TO': '==', 'NOT_EQUAL': '!=', 'GREATER_THAN': '>', 'GREATER_THAN_OR_EQUAL': '>=',
                 'LESS_THAN': '<', 'LESS_THAN_OR_EQUAL': '<='}
TASK_TYPES = ('notebook_task', 'condition_task', 'sql_task', 'for_each_task')
NOT_SIMULATED = ('spark_python_task', 'python_wheel_task', 'spark_jar_task', 'spark_submit_task', 'pipeline_task',
                 'run_job_task', 'dbt_task', 'clean_rooms_notebook_task', 'dashboard_task', 'power_bi_task')
MAX_TASKS = 100
MAX_RETRIES_CAP = 10


class DatabricksLabError(Exception):
    """An invalid job definition: every issue found, as Databricks reports them before a run."""

    def __init__(self, issues: list[dict[str, str]]):
        super().__init__('; '.join(i['message'] for i in issues))
        self.issues = issues


@dataclass
class ClusterSpec:
    key: str
    spark_version: str
    node_type: str
    driver_node_type: str
    num_workers: int | None
    autoscale: tuple[int, int] | None
    pool: str | None
    photon: bool
    availability: str

    @property
    def billed_workers(self) -> float:
        if self.autoscale:
            return (self.autoscale[0] + self.autoscale[1]) / 2
        return float(self.num_workers or 0)

    def label(self) -> str:
        workers = (f"autoscale {self.autoscale[0]}-{self.autoscale[1]} workers" if self.autoscale
                   else f"{self.num_workers} workers")
        extras = [x for x in ('Photon' if self.photon else '', 'pool' if self.pool else '',
                              'spot' if self.availability.startswith('SPOT') else '') if x]
        return f"{self.node_type}, {workers}{', ' + ', '.join(extras) if extras else ''}"


@dataclass
class Task:
    key: str
    kind: str  # notebook | condition | sql | for_each
    depends_on: list[tuple[str, str | None]] = field(default_factory=list)
    run_if: str = 'ALL_SUCCESS'
    max_retries: int = 0
    min_retry_interval_s: float = 0.0
    retry_on_timeout: bool = False
    timeout_seconds: int = 0
    compute: tuple[str, str] = ('none', '')  # job_cluster | existing | serverless | warehouse | none
    notebook_path: str = ''
    base_parameters: dict[str, str] = field(default_factory=dict)
    condition: tuple[str, str, str] = ('', '', '')  # op, left, right
    sql_path: str = ''
    sql_parameters: dict[str, str] = field(default_factory=dict)
    inputs: str = ''
    concurrency: int = 1
    inner: 'Task | None' = None
    description: str = ''


@dataclass
class Job:
    name: str
    tasks: list[Task]
    parameters: dict[str, str]
    clusters: dict[str, ClusterSpec]
    run_as: str | None
    schedule: dict[str, Any] | None
    tags: dict[str, str]
    warnings: list[str] = field(default_factory=list)

    def task(self, key: str) -> Task:
        return next(t for t in self.tasks if t.key == key)

    def downstream(self, key: str) -> list[str]:
        return [t.key for t in self.tasks if any(d == key for d, _ in t.depends_on)]


def notebook_key(path: str) -> str:
    """A workspace notebook path as the lab keys notebook files: databricks:/Shared/nb_orders."""
    clean = path.strip()
    if clean.startswith('/Workspace/'):
        clean = clean[len('/Workspace'):]
    if clean.endswith('.py'):
        clean = clean[:-3]
    return 'databricks:' + (clean if clean.startswith('/') else '/' + clean)


def sql_key(path: str) -> str:
    clean = path.strip()
    if clean.startswith('/Workspace/'):
        clean = clean[len('/Workspace'):]
    return 'databricks:' + (clean if clean.startswith('/') else '/' + clean)


def load_job(document: Any, known_clusters: set[str], known_warehouses: set[str], node_types: set[str]) -> Job:
    issues: list[dict[str, str]] = []
    warnings: list[str] = []

    def issue(path: str, message: str) -> None:
        issues.append({'path': path, 'message': message, 'severity': 'error'})

    if not isinstance(document, dict):
        raise DatabricksLabError([{'path': '', 'message': 'A job definition is a JSON object (Jobs API format)',
                                   'severity': 'error'}])
    settings = document.get('settings') if isinstance(document.get('settings'), dict) else document
    name = settings.get('name') if isinstance(settings.get('name'), str) else ''
    if not name:
        issue('name', 'The job needs a name')
    raw_tasks = settings.get('tasks')
    if not isinstance(raw_tasks, list) or not raw_tasks:
        issue('tasks', 'The job needs a tasks array with at least one task')
        raw_tasks = []
    if len(raw_tasks) > MAX_TASKS:
        issue('tasks', f"The lab simulates at most {MAX_TASKS} tasks per job")

    parameters: dict[str, str] = {}
    for index, raw in enumerate(settings.get('parameters') or []):
        if not isinstance(raw, dict) or not isinstance(raw.get('name'), str):
            issue(f'parameters[{index}]', 'A job parameter is {"name": ..., "default": ...}')
            continue
        pname = raw['name']
        if not PARAMETER_NAME.fullmatch(pname):
            issue(f'parameters[{index}]', f"Job parameter keys can only contain _ - . or alphanumeric characters: {pname!r}")
        if pname in parameters:
            issue(f'parameters[{index}]', f"Duplicate job parameter {pname!r}")
        if 'default' not in raw:
            issue(f'parameters[{index}]', f"Job parameter {pname!r} needs a default value")
        default = raw.get('default', '')
        parameters[pname] = default if isinstance(default, str) else _json(default)

    clusters: dict[str, ClusterSpec] = {}
    for index, raw in enumerate(settings.get('job_clusters') or []):
        path = f'job_clusters[{index}]'
        if not isinstance(raw, dict) or not isinstance(raw.get('job_cluster_key'), str):
            issue(path, 'A job cluster needs a job_cluster_key and a new_cluster')
            continue
        key = raw['job_cluster_key']
        spec = _cluster(raw.get('new_cluster'), key, f'{path}.new_cluster', issue, node_types)
        if key in clusters:
            issue(path, f"Duplicate job_cluster_key {key!r}")
        if spec:
            clusters[key] = spec

    tasks: list[Task] = []
    keys: set[str] = set()
    for index, raw in enumerate(raw_tasks):
        task = _task(raw, f'tasks[{index}]', issue, clusters, known_clusters, known_warehouses, nested=False)
        if task is None:
            continue
        if task.key in keys:
            issue(f'tasks[{index}]', f"Duplicate task_key {task.key!r}")
        keys.add(task.key)
        tasks.append(task)

    kinds = {t.key: t.kind for t in tasks}
    for task in tasks:
        for dep, outcome in task.depends_on:
            where = f"tasks[{task.key}].depends_on"
            if dep not in kinds:
                issue(where, f"Task {task.key!r} depends on {dep!r}, which is not a task of this job")
            elif dep == task.key:
                issue(where, f"Task {task.key!r} cannot depend on itself")
            elif kinds[dep] == 'condition' and outcome not in ('true', 'false'):
                issue(where, f"{task.key!r} depends on the condition task {dep!r}: set outcome to \"true\" or \"false\"")
            elif kinds[dep] != 'condition' and outcome is not None:
                issue(where, f"outcome is only valid on a dependency on an If/else condition task ({dep!r} is not one)")
    cycle = _cycle({t.key: [d for d, _ in t.depends_on if d in kinds] for t in tasks})
    if cycle:
        issue('tasks', 'Task dependencies form a cycle: ' + ' -> '.join(cycle))
    used = {t.compute[1] for t in tasks if t.compute[0] == 'job_cluster'} | {
        t.inner.compute[1] for t in tasks if t.inner and t.inner.compute[0] == 'job_cluster'}
    for key in clusters:
        if key not in used:
            warnings.append(f"Job cluster {key!r} is not used by any task")

    run_as = None
    raw_run_as = settings.get('run_as')
    if isinstance(raw_run_as, dict):
        run_as = raw_run_as.get('user_name') or raw_run_as.get('service_principal_name')
        if not isinstance(run_as, str) or not run_as:
            issue('run_as', 'run_as takes user_name or service_principal_name')
            run_as = None
    elif raw_run_as is not None:
        issue('run_as', 'run_as is an object: {"service_principal_name": "..."} or {"user_name": "..."}')
    schedule = settings.get('schedule') if isinstance(settings.get('schedule'), dict) else None
    if schedule is not None and not isinstance(schedule.get('quartz_cron_expression'), str):
        issue('schedule', 'A schedule needs a quartz_cron_expression and a timezone_id')
    tags = {str(k): str(v) for k, v in (settings.get('tags') or {}).items()} if isinstance(settings.get('tags'), dict) else {}
    if issues:
        raise DatabricksLabError(issues)
    return Job(name, tasks, parameters, clusters, run_as, schedule, tags, warnings)


def _task(raw: Any, path: str, issue, clusters: dict[str, ClusterSpec], known_clusters: set[str],
          known_warehouses: set[str], nested: bool) -> Task | None:
    if not isinstance(raw, dict):
        issue(path, 'A task is a JSON object')
        return None
    key = raw.get('task_key')
    if not isinstance(key, str) or not TASK_KEY.fullmatch(key):
        issue(path, 'task_key is required: letters, digits, _ and -, at most 100 characters')
        return None
    path = f"{path} ({key})"
    types = [t for t in TASK_TYPES if t in raw]
    other = [t for t in NOT_SIMULATED if t in raw]
    if other:
        issue(path, f"{other[0]} is a real Databricks task type the lab does not simulate; use a notebook_task, "
                    "sql_task, condition_task or for_each_task")
        return None
    if len(types) != 1:
        issue(path, 'A task needs exactly one of notebook_task, sql_task, condition_task, for_each_task')
        return None
    task = Task(key, {'notebook_task': 'notebook', 'condition_task': 'condition', 'sql_task': 'sql',
                      'for_each_task': 'for_each'}[types[0]])
    task.description = raw.get('description', '') if isinstance(raw.get('description'), str) else ''
    deps = raw.get('depends_on') or []
    if nested and deps:
        issue(path, 'The task nested in a for_each_task cannot have depends_on')
    if not isinstance(deps, list):
        issue(path, 'depends_on is a list of {"task_key": ...}')
        deps = []
    for dep in deps:
        if not isinstance(dep, dict) or not isinstance(dep.get('task_key'), str):
            issue(path, 'depends_on entries are {"task_key": "...", "outcome": "true" | "false"}')
            continue
        outcome = dep.get('outcome')
        task.depends_on.append((dep['task_key'], outcome if isinstance(outcome, str) else None))
    run_if = raw.get('run_if', 'ALL_SUCCESS')
    if run_if not in RUN_IF:
        issue(path, f"run_if must be one of {', '.join(RUN_IF)}")
    task.run_if = run_if if run_if in RUN_IF else 'ALL_SUCCESS'
    if 'run_if' in raw and not task.depends_on:
        issue(path, 'run_if applies to a task with dependencies')
    retries = raw.get('max_retries', 0)
    if type(retries) is not int or retries < -1:
        issue(path, 'max_retries is an integer (0 = no retry, -1 = retry forever)')
        retries = 0
    task.max_retries = MAX_RETRIES_CAP if retries == -1 else min(retries, MAX_RETRIES_CAP)
    interval = raw.get('min_retry_interval_millis', 0)
    if type(interval) is not int or interval < 0:
        issue(path, 'min_retry_interval_millis is a non-negative integer')
        interval = 0
    task.min_retry_interval_s = interval / 1000
    task.retry_on_timeout = raw.get('retry_on_timeout') is True
    timeout = raw.get('timeout_seconds', 0)
    if type(timeout) is not int or timeout < 0:
        issue(path, 'timeout_seconds is a non-negative integer (0 = no timeout)')
        timeout = 0
    task.timeout_seconds = timeout

    spec = raw[types[0]]
    if not isinstance(spec, dict):
        issue(path, f"{types[0]} is a JSON object")
        return task
    compute_keys = [k for k in ('job_cluster_key', 'existing_cluster_id', 'environment_key', 'new_cluster') if k in raw]
    if task.kind == 'notebook':
        if not isinstance(spec.get('notebook_path'), str) or not spec['notebook_path'].strip():
            issue(path, 'notebook_task needs a notebook_path, for example /Workspace/Shared/nb_orders')
        task.notebook_path = spec.get('notebook_path', '') or ''
        if spec.get('source', 'WORKSPACE') != 'WORKSPACE':
            issue(path, 'Git notebook sources are not simulated: use source WORKSPACE (the lab files)')
        task.base_parameters = _string_map(spec.get('base_parameters'), f'{path}.notebook_task.base_parameters', issue)
        task.compute = _compute(raw, path, issue, clusters, known_clusters)
    elif task.kind == 'condition':
        op = spec.get('op')
        if op not in CONDITION_OPS:
            issue(path, f"condition_task op must be one of {', '.join(CONDITION_OPS)}")
        left, right = spec.get('left'), spec.get('right')
        if not isinstance(left, str) or not isinstance(right, str):
            issue(path, 'condition_task needs left and right operands (strings, dynamic value references allowed)')
        task.condition = (op or '', left if isinstance(left, str) else '', right if isinstance(right, str) else '')
        if compute_keys:
            issue(path, 'An If/else condition task runs without compute: remove ' + compute_keys[0])
    elif task.kind == 'sql':
        file = spec.get('file')
        if not isinstance(file, dict) or not isinstance(file.get('path'), str):
            issue(path, 'sql_task needs file.path (a .sql file of the lab); saved queries, alerts and dashboards are '
                        'not simulated')
        else:
            task.sql_path = file['path']
        warehouse = spec.get('warehouse_id')
        if not isinstance(warehouse, str) or not warehouse:
            issue(path, 'sql_task needs a warehouse_id: SQL tasks run on a SQL warehouse')
        elif warehouse not in known_warehouses:
            issue(path, f"SQL warehouse {warehouse!r} does not exist (lab warehouses: {', '.join(sorted(known_warehouses))})")
        task.compute = ('warehouse', warehouse if isinstance(warehouse, str) else '')
        task.sql_parameters = _string_map(spec.get('parameters'), f'{path}.sql_task.parameters', issue)
        if compute_keys:
            issue(path, f"A SQL task runs on its warehouse: remove {compute_keys[0]}")
    else:
        if nested:
            issue(path, 'for_each_task cannot be nested')
            return task
        inputs = spec.get('inputs')
        if not isinstance(inputs, str) or not inputs.strip():
            issue(path, 'for_each_task needs inputs: a JSON array as text or a dynamic value reference')
        task.inputs = inputs if isinstance(inputs, str) else ''
        concurrency = spec.get('concurrency', 1)
        if type(concurrency) is not int or not 1 <= concurrency <= 100:
            issue(path, 'for_each_task concurrency is an integer from 1 to 100')
            concurrency = 1
        task.concurrency = concurrency
        inner = _task(spec.get('task'), f'{path}.for_each_task.task', issue, clusters, known_clusters,
                      known_warehouses, nested=True)
        if inner is not None and inner.kind not in ('notebook', 'sql'):
            issue(path, 'The task inside for_each_task must be a notebook_task or a sql_task')
        task.inner = inner
        if compute_keys:
            issue(path, 'Set compute on the nested task, not on the for_each_task')
    return task


def _compute(raw: dict[str, Any], path: str, issue, clusters: dict[str, ClusterSpec],
             known_clusters: set[str]) -> tuple[str, str]:
    if 'new_cluster' in raw:
        issue(path, 'Define the cluster in job_clusters and reference it with job_cluster_key (a task-level '
                    'new_cluster is not simulated)')
    chosen = [k for k in ('job_cluster_key', 'existing_cluster_id', 'environment_key') if k in raw]
    if len(chosen) > 1:
        issue(path, f"A task uses one compute: {', '.join(chosen)} are exclusive")
    if 'job_cluster_key' in raw:
        key = raw['job_cluster_key']
        if key not in clusters:
            issue(path, f"job_cluster_key {key!r} is not in job_clusters")
        return ('job_cluster', str(key))
    if 'existing_cluster_id' in raw:
        cluster = raw['existing_cluster_id']
        if cluster not in known_clusters:
            issue(path, f"All-purpose cluster {cluster!r} does not exist (lab clusters: "
                        f"{', '.join(sorted(known_clusters)) or 'none'}; see factory/databricks/compute.json)")
        return ('existing', str(cluster))
    return ('serverless', str(raw.get('environment_key', 'default')))


def _cluster(raw: Any, key: str, path: str, issue, node_types: set[str]) -> ClusterSpec | None:
    if not isinstance(raw, dict):
        issue(path, 'new_cluster is a JSON object')
        return None
    version = raw.get('spark_version')
    if not isinstance(version, str) or not version:
        issue(path, 'new_cluster needs a spark_version, for example 15.4.x-scala2.12')
    node = raw.get('node_type_id')
    pool = raw.get('instance_pool_id') if isinstance(raw.get('instance_pool_id'), str) else None
    if pool is None and node not in node_types:
        issue(path, f"node_type_id must be one of the lab's node types: {', '.join(sorted(node_types))}")
    workers, autoscale = raw.get('num_workers'), raw.get('autoscale')
    scale: tuple[int, int] | None = None
    if autoscale is not None:
        if workers is not None:
            issue(path, 'Set num_workers or autoscale, not both')
        if not isinstance(autoscale, dict) or type(autoscale.get('min_workers')) is not int or type(
                autoscale.get('max_workers')) is not int or not 0 <= autoscale['min_workers'] <= autoscale['max_workers']:
            issue(path, 'autoscale needs integers min_workers <= max_workers')
        else:
            scale = (autoscale['min_workers'], autoscale['max_workers'])
    elif type(workers) is not int or not 0 <= workers <= 100:
        issue(path, 'num_workers is an integer from 0 (single node) to 100 in the lab')
        workers = 0
    availability = ((raw.get('azure_attributes') or {}).get('availability') or 'ON_DEMAND_AZURE') if isinstance(
        raw.get('azure_attributes') or {}, dict) else 'ON_DEMAND_AZURE'
    if availability not in ('ON_DEMAND_AZURE', 'SPOT_AZURE', 'SPOT_WITH_FALLBACK_AZURE'):
        issue(path, 'azure_attributes.availability is ON_DEMAND_AZURE, SPOT_AZURE or SPOT_WITH_FALLBACK_AZURE')
    engine = raw.get('runtime_engine', 'STANDARD')
    if engine not in ('STANDARD', 'PHOTON'):
        issue(path, 'runtime_engine is STANDARD or PHOTON')
    node_type = node if isinstance(node, str) and node in node_types else (sorted(node_types)[0] if pool else '')
    return ClusterSpec(key, version if isinstance(version, str) else '', node_type,
                       raw.get('driver_node_type_id') if raw.get('driver_node_type_id') in node_types else node_type,
                       workers if scale is None and type(workers) is int else None, scale, pool,
                       engine == 'PHOTON' or '-photon-' in str(version), availability)


def _string_map(raw: Any, path: str, issue) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        issue(path, 'Parameters are a JSON object of text values')
        return {}
    out = {}
    for key, value in raw.items():
        if not isinstance(value, str):
            issue(path, f"Parameter {key!r} must be text (every notebook parameter is a string)")
            continue
        out[str(key)] = value
    return out


def _cycle(graph: dict[str, list[str]]) -> list[str]:
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(node: str) -> list[str]:
        state[node] = 1
        stack.append(node)
        for nxt in graph.get(node, []):
            if state.get(nxt) == 1:
                return stack[stack.index(nxt):] + [nxt]
            if nxt not in state:
                found = visit(nxt)
                if found:
                    return found
        stack.pop()
        state[node] = 2
        return []

    for node in graph:
        if node not in state:
            found = visit(node)
            if found:
                return found
    return []


def _json(value: Any) -> str:
    import json
    return json.dumps(value)
