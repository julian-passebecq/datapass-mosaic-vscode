"""Deterministic pipeline run simulation with Data Factory semantics.

Orchestration (the same in Fabric Data Factory, Azure Data Factory and Synapse):

- An activity starts when all its dependencies have finished. It runs only if
  every dependency ended in one of the listed conditions (Succeeded, Failed,
  Skipped, or Completed = Succeeded or Failed); otherwise it is Skipped.
- Retries follow policy.retry and policy.retryIntervalInSeconds; an attempt
  longer than policy.timeout fails. Expression errors fail the activity at once.
- Inactive activities are not run and take their onInactiveMarkAs status.
- The pipeline (and each container iteration) is evaluated from its leaf
  activities: a skipped leaf is replaced by its parents; the run succeeds only if
  every evaluated activity succeeded. This is why "try/catch" with an
  on-failure handler succeeds while "do if / else" with a failed branch fails.
- ForEach runs iterations sequentially or up to batchCount in parallel and fails
  if an iteration fails; If Condition, Switch and Until run their inner
  activities as a unit when they start; Until stops when its expression is true
  (at most 100 iterations here).

Work activities (Copy, Lookup, Script, stored procedures, notebooks) run against
the local catalog when a workspace adapter can resolve them; everything else
follows the scenario (duration, failing attempts, output). Times are logical
seconds from the pipeline start.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .activities import TYPES
from .expressions import ExpressionError, Scope, format_timestamp, resolve, type_name, _equal
from .loader import load_pipeline, timespan_seconds
from .model import Activity, FactoryLabError, Issue, Pipeline

MAX_UNTIL = 100
MAX_DEPTH = 5
DATA_FACTORY_NAMES = {'fabric': 'datapass-lab-workspace', 'adf': 'datapass-lab-adf', 'synapse': 'datapass-lab-synapse'}


class ActivityBehavior(BaseModel):
    model_config = ConfigDict(extra='forbid')
    duration_seconds: float | None = Field(default=None, ge=0, le=7 * 86400)
    fail_attempts: list[int] | Literal['all'] = Field(default_factory=list)
    # Fail only the iterations whose item() equals one of these (or contains it as a value).
    fail_on_items: list[Any] = Field(default_factory=list)
    output: dict[str, Any] | None = None
    # Successive outputs: the n-th run of the activity gets outputs[n] (the last one repeats), for polling loops.
    outputs: list[dict[str, Any]] | None = Field(default=None, min_length=1, max_length=100)
    error_message: str | None = None
    error_code: str | None = None


class FactoryScenario(BaseModel):
    model_config = ConfigDict(extra='forbid')
    now: datetime | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    trigger_type: str = 'Manual'
    activities: dict[str, ActivityBehavior] = Field(default_factory=dict)


class Workspace(Protocol):
    """Lab files and the local data plane. Implemented by the runtime over the shared catalog; optional.

    When `local` is false (a dry run), work activities are simulated but child
    pipelines and datasets still resolve from the lab files.
    """

    local: bool

    def query(self, sql: str) -> dict[str, Any]: ...
    def execute(self, sql: str, producer: str) -> dict[str, Any]: ...
    def table_exists(self, name: str) -> bool: ...
    def procedure_source(self, name: str) -> str | None: ...
    # kind: fabric (notebookId), synapse (notebook referenceName) or databricks (/workspace/path)
    def run_notebook(self, kind: str, reference: str, parameters: dict[str, Any]) -> dict[str, Any] | None: ...
    def pipeline_document(self, name: str) -> Any | None: ...
    def dataset_document(self, name: str) -> Any | None: ...


class ActivityFailure(Exception):
    def __init__(self, message: str, code: str = '2011', output: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.output = output or {}


@dataclass
class ActivityRun:
    name: str
    type: str
    path: str
    status: str
    start_s: float
    end_s: float
    attempts: int = 0
    input: Any = None
    output: Any = None
    error: dict[str, Any] | None = None
    iteration: str | None = None
    truth: str = 'simulated'
    note: str = ''
    parent: str | None = None


@dataclass
class PipelineRunResult:
    pipeline: str
    flavor: str
    run_id: str
    status: str
    parameters: dict[str, Any]
    variables: dict[str, Any]
    runs: list[ActivityRun]
    evaluated: list[str]
    duration_s: float
    return_value: Any = None
    children: list['PipelineRunResult'] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _run_id(pipeline: str, parameters: dict[str, Any], now: datetime) -> str:
    digest = hashlib.sha256(f"{pipeline}|{json.dumps(parameters, sort_keys=True, default=str)}|{now.isoformat()}".encode()).hexdigest()
    return f"{digest[:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}"


def _coerce_parameter(kind: str, value: Any, name: str) -> Any:
    """Typed parameter values; text from a trigger form is converted like Data Factory does."""
    if value is None:
        return None
    if isinstance(value, str) and kind not in {'String', 'SecureString'}:
        try:
            value = json.loads(value) if kind in {'Array', 'Object'} else (
                value.strip().lower() == 'true' if kind == 'Bool' and value.strip().lower() in {'true', 'false'}
                else int(value) if kind == 'Int' else float(value) if kind == 'Float' else value)
        except ValueError as exc:
            raise _error(f"parameter '{name}' expects {kind}; '{value}' cannot be converted") from exc
    ok = {
        'String': isinstance(value, str), 'SecureString': isinstance(value, str),
        'Int': isinstance(value, int) and not isinstance(value, bool),
        'Float': isinstance(value, (int, float)) and not isinstance(value, bool),
        'Bool': isinstance(value, bool), 'Array': isinstance(value, list), 'Object': isinstance(value, dict),
    }.get(kind, True)
    if not ok:
        raise _error(f"parameter '{name}' expects {kind}, got {type_name(value)}")
    return value


def _error(message: str) -> FactoryLabError:
    return FactoryLabError([Issue('', message)])


class Simulator:
    def __init__(self, pipeline: Pipeline, scenario: FactoryScenario, workspace: Workspace | None, depth: int = 0,
                 parameters: dict[str, Any] | None = None, caller: tuple[str, str] | None = None):
        self.pipeline = pipeline
        self.scenario = scenario
        self.workspace = workspace
        self.depth = depth
        self.now = (scenario.now or datetime(2026, 3, 5, 12, tzinfo=timezone.utc)).astimezone(timezone.utc)
        supplied = dict(scenario.parameters if parameters is None else parameters)
        unknown = set(supplied) - set(pipeline.parameters)
        if unknown:
            raise _error(f"unknown pipeline parameter(s): {', '.join(sorted(unknown))}")
        self.parameters = {name: _coerce_parameter(p.type, supplied.get(name, p.default), name)
                           for name, p in pipeline.parameters.items()}
        self.variables = {name: v.default for name, v in pipeline.variables.items()}
        self.run_id = _run_id(pipeline.name, self.parameters, self.now)
        self.outputs: dict[str, dict[str, Any]] = {}
        self.runs: list[ActivityRun] = []
        self.children: list[PipelineRunResult] = []
        self.return_value: Any = None
        self.calls: dict[str, int] = {}  # runs per work activity, for scenario output sequences
        # System variables. DataFactory is the factory name (ADF) or the workspace name (Synapse, Fabric).
        manual = scenario.trigger_type == 'Manual'
        info = {'DataFactory': DATA_FACTORY_NAMES[pipeline.flavor], 'Pipeline': pipeline.name, 'RunId': self.run_id,
                'TriggerId': self.run_id if manual else hashlib.sha256(scenario.trigger_type.encode()).hexdigest()[:32],
                'TriggerName': 'Sandbox' if manual else scenario.trigger_type,
                'TriggerTime': format_timestamp(self.now), 'TriggerType': scenario.trigger_type,
                'GroupId': self.run_id,
                'TriggeredByPipelineName': caller[0] if caller else None,
                'TriggeredByPipelineRunId': caller[1] if caller else None}
        self.base_scope = Scope(self.parameters, self.variables, self.outputs, info, self.now)

    # -- containers ----------------------------------------------------------------------------
    def run(self) -> PipelineRunResult:
        status, evaluated, end = self.container(self.pipeline.activities, 0.0, self.base_scope, None, None)
        return PipelineRunResult(self.pipeline.name, self.pipeline.flavor, self.run_id, status, self.parameters,
                                 dict(self.variables), self.runs, evaluated, end, self.return_value, self.children,
                                 [w.message for w in self.pipeline.warnings])

    def container(self, activities: list[Activity], t0: float, scope: Scope, iteration: str | None,
                  parent: str | None) -> tuple[str, list[str], float]:
        status: dict[str, str] = {}
        end: dict[str, float] = {}
        pending = list(activities)
        while pending:
            ready = [a for a in pending if all(d.activity in status for d in a.depends_on)]
            start = {a.name: max([end[d.activity] for d in a.depends_on], default=t0) for a in ready}
            activity = min(ready, key=lambda a: (start[a.name], activities.index(a)))
            pending.remove(activity)
            begin = start[activity.name]
            satisfied = all(self._condition_met(status[d.activity], d.conditions) for d in activity.depends_on)
            if activity.state == 'Inactive':
                run = ActivityRun(activity.name, activity.type, activity.path, activity.on_inactive_mark_as, begin, begin,
                                  note='Deactivated: not run, marked ' + activity.on_inactive_mark_as, iteration=iteration,
                                  parent=parent)
                self.runs.append(run)
            elif not satisfied:
                unmet = [f"{d.activity} is {status[d.activity]}, needs {' or '.join(d.conditions)}"
                         for d in activity.depends_on if not self._condition_met(status[d.activity], d.conditions)]
                run = ActivityRun(activity.name, activity.type, activity.path, 'Skipped', begin, begin,
                                  note='Dependency condition not met: ' + '; '.join(unmet), iteration=iteration,
                                  parent=parent)
                self.runs.append(run)
            else:
                run = self.execute(activity, begin, scope, iteration, parent)
            status[activity.name] = run.status
            end[activity.name] = run.end_s
            self.outputs[activity.name] = {'output': run.output if run.output is not None else {},
                                           **({'error': run.error} if run.error else {})}
        outcome, evaluated = self.leaf_outcome(activities, status)
        return outcome, evaluated, max(end.values(), default=t0)

    @staticmethod
    def _condition_met(state: str, conditions: tuple[str, ...]) -> bool:
        return any(state == c or (c == 'Completed' and state in {'Succeeded', 'Failed'}) for c in conditions)

    @staticmethod
    def leaf_outcome(activities: list[Activity], status: dict[str, str]) -> tuple[str, list[str]]:
        """Data Factory's rule: evaluate leaves; a skipped leaf is replaced by its parents."""
        parents = {a.name: [d.activity for d in a.depends_on] for a in activities}
        has_child = {d.activity for a in activities for d in a.depends_on}
        evaluated: list[str] = []

        def evaluate(name: str, seen: set[str]) -> None:
            if name in seen:
                return
            seen.add(name)
            if status.get(name) == 'Skipped':
                for parent in parents.get(name, []):
                    evaluate(parent, seen)
            elif name not in evaluated:
                evaluated.append(name)

        seen: set[str] = set()
        for activity in activities:
            if activity.name not in has_child:
                evaluate(activity.name, seen)
        ok = all(status[name] == 'Succeeded' for name in evaluated)
        return ('Succeeded' if ok else 'Failed'), evaluated

    # -- one activity ----------------------------------------------------------------------------
    def behavior(self, activity: Activity) -> ActivityBehavior:
        return self.scenario.activities.get(activity.name) or ActivityBehavior()

    def execute(self, activity: Activity, begin: float, scope: Scope, iteration: str | None,
                parent: str | None) -> ActivityRun:
        run = ActivityRun(activity.name, activity.type, activity.path, 'InProgress', begin, begin,
                          iteration=iteration, parent=parent)
        self.runs.append(run)
        spec = TYPES[activity.type]
        try:
            resolved = self.resolve_inputs(activity, scope)
        except ExpressionError as exc:
            run.status, run.end_s, run.attempts = 'Failed', begin, 1
            run.error = {'errorCode': 'InvalidTemplate', 'message': f"Expression evaluation failed: {exc}",
                         'failureType': 'UserError', 'target': activity.name}
            return run
        run.input = '(secure input)' if activity.policy.secure_input else resolved
        if spec.control:
            try:
                self.control(activity, resolved, run, scope, iteration)
            except (ActivityFailure, ExpressionError) as exc:
                run.status = 'Failed'
                run.error = {'errorCode': getattr(exc, 'code', 'InvalidTemplate'), 'message': str(exc),
                             'failureType': 'UserError', 'target': activity.name}
                run.end_s = max(run.end_s, begin)
            return run
        behavior = self.behavior(activity)
        call = self.calls.get(activity.name, 0)
        self.calls[activity.name] = call + 1
        extra = behavior.output
        if behavior.outputs:
            extra = {**(extra or {}), **behavior.outputs[min(call, len(behavior.outputs) - 1)]}
        t = begin
        for attempt in range(1, activity.policy.retry + 2):
            run.attempts = attempt
            fails = behavior.fail_attempts == 'all' or attempt in behavior.fail_attempts
            if behavior.fail_on_items and scope.item is not None and self._item_matches(scope.item, behavior.fail_on_items):
                fails = True
            duration = behavior.duration_seconds if behavior.duration_seconds is not None else spec.default_seconds
            error: dict[str, Any] | None = None
            output: Any = None
            if duration > activity.policy.timeout_s:
                duration = activity.policy.timeout_s
                error = {'errorCode': '2103', 'message': f"Activity timed out after {activity.policy.timeout_s:g}s "
                                                          "(policy.timeout)", 'failureType': 'SystemError'}
                run.note = f"Attempt {attempt} ran longer than policy.timeout"
            elif fails:
                error = {'errorCode': behavior.error_code or '2200',
                         'message': behavior.error_message or f"Simulated failure on attempt {attempt}",
                         'failureType': 'UserError' if behavior.error_code else 'SystemError'}
                run.note = f"Failure injected by the scenario on attempt {attempt}"
            else:
                try:
                    output, truth, note = self.work(activity, resolved)
                    run.truth, run.note = truth, note
                    if extra is not None:
                        output = {**(output or {}), **extra}
                        run.note = (run.note + '; ' if run.note else '') + 'output completed from the scenario'
                except ActivityFailure as exc:
                    error = {'errorCode': exc.code, 'message': exc.message, 'failureType': 'UserError'}
                    output = exc.output or None
                    run.truth, run.note = 'local', 'Failed on the local catalog'
            t += duration
            if error is None:
                run.status, run.end_s, run.error = 'Succeeded', t, None  # earlier attempts' errors are not the result
                run.output = '(secure output)' if activity.policy.secure_output else output
                if attempt > 1:
                    run.note = f"Succeeded on attempt {attempt} after {attempt - 1} retr{'y' if attempt == 2 else 'ies'}; " + run.note
                return run
            error['target'] = activity.name
            run.error, run.output = error, output
            if attempt <= activity.policy.retry:
                t += activity.policy.retry_interval_s
        run.status, run.end_s = 'Failed', t
        return run

    @staticmethod
    def _item_matches(item: Any, values: list[Any]) -> bool:
        for value in values:
            if _equal(item, value) or (isinstance(item, dict) and any(_equal(v, value) for v in item.values())):
                return True
        return False

    def resolve_inputs(self, activity: Activity, scope: Scope) -> dict[str, Any]:
        """Resolve dynamic content in typeProperties, except nested activities and per-item expressions."""
        deferred = set(TYPES[activity.type].required) & {'expression', 'condition'} if activity.type == 'Until' else set()
        skip = {'activities', 'ifTrueActivities', 'ifFalseActivities', 'defaultActivities', 'cases'} | deferred
        if activity.type == 'Filter':
            skip.add('condition')
        props = {k: v for k, v in activity.type_properties.items() if k not in skip}
        resolved = resolve(props, scope)
        if activity.inputs:
            resolved['_inputs'] = resolve(activity.inputs, scope)
        if activity.outputs:
            resolved['_outputs'] = resolve(activity.outputs, scope)
        return resolved

    # -- control activities ---------------------------------------------------------------------
    def control(self, activity: Activity, props: dict[str, Any], run: ActivityRun, scope: Scope,
                iteration: str | None) -> None:
        kind, begin = activity.type, run.start_s
        run.truth = 'simulated'
        run.attempts = 1
        if kind == 'SetVariable':
            if activity.type_properties.get('setSystemVariable') or props.get('variableName') == 'pipelineReturnValue':
                self.return_value = props.get('value')
                run.output = {'value': props.get('value')}
                run.note = 'Pipeline return value set'
            else:
                name = props['variableName']
                value = props.get('value')
                self._check_variable(name, value)
                self.variables[name] = value
                run.output = {'name': name, 'value': value}
                run.note = f"{name} = {json.dumps(value, default=str)[:80]}"
            run.status, run.end_s = 'Succeeded', begin
        elif kind == 'AppendVariable':
            name = props['variableName']
            current = list(self.variables.get(name) or [])
            current.append(props.get('value'))
            self.variables[name] = current
            run.output, run.status, run.end_s = {'name': name, 'value': current}, 'Succeeded', begin
            run.note = f"{name} now has {len(current)} item(s)"
        elif kind == 'Wait':
            seconds = props.get('waitTimeInSeconds')
            if isinstance(seconds, str) and seconds.strip().lstrip('-').isdigit():
                seconds = int(seconds)
            if not isinstance(seconds, int) or isinstance(seconds, bool) or seconds < 0:
                raise ActivityFailure("waitTimeInSeconds must be a non-negative integer")
            run.status, run.end_s = 'Succeeded', begin + seconds
            run.note = f"Waited {seconds} s"
        elif kind == 'Fail':
            run.status, run.end_s = 'Failed', begin
            run.error = {'errorCode': str(props.get('errorCode')), 'message': str(props.get('message')),
                         'failureType': 'UserError', 'target': activity.name}
            run.note = f"Fail activity raised {props.get('errorCode')}"
        elif kind == 'Filter':
            items = props.get('items')
            if not isinstance(items, list):
                raise ActivityFailure(f"Filter items must be an array, got {type_name(items)}")
            condition = activity.type_properties.get('condition')
            kept = []
            for item in items:
                value = resolve(condition, scope.with_item(item))
                if not isinstance(value, bool):
                    raise ActivityFailure(f"Filter condition must be a Boolean, got {type_name(value)}")
                if value:
                    kept.append(item)
            run.output = {'ItemsCount': len(items), 'FilteredItemsCount': len(kept), 'Value': kept}
            run.status, run.end_s = 'Succeeded', begin
            run.note = f"Kept {len(kept)} of {len(items)} item(s)"
        elif kind == 'IfCondition':
            condition = props.get('expression')
            if not isinstance(condition, bool):
                raise ActivityFailure(f"If Condition expression must be a Boolean, got {type_name(condition)}")
            branch = 'ifTrueActivities' if condition else 'ifFalseActivities'
            outcome, _, end = self.container(activity.children.get(branch, []), begin, scope, iteration, activity.name)
            run.output = {'branch': 'True' if condition else 'False'}
            run.status, run.end_s = outcome, end
            run.note = f"Expression is {'true' if condition else 'false'}: ran {branch}"
            if outcome == 'Failed':
                run.error = {'errorCode': 'ActivityFailed', 'message': f"An activity in the {branch} branch failed",
                             'failureType': 'UserError', 'target': activity.name}
        elif kind == 'Switch':
            on = props.get('on')
            key = next((k for k in activity.children if k.startswith('case:') and k[5:] == str(on)), 'defaultActivities')
            outcome, _, end = self.container(activity.children.get(key, []), begin, scope, iteration, activity.name)
            run.output = {'case': key[5:] if key.startswith('case:') else 'default'}
            run.status, run.end_s = outcome, end
            run.note = (f"on = {json.dumps(on, default=str)}: ran case {run.output['case']}" if key != 'defaultActivities'
                        else f"on = {json.dumps(on, default=str)} matches no case: ran defaultActivities")
            if outcome == 'Failed':
                run.error = {'errorCode': 'ActivityFailed', 'message': f"An activity in case {run.output['case']} failed",
                             'failureType': 'UserError', 'target': activity.name}
        elif kind == 'ForEach':
            self.for_each(activity, props, run, scope)
        elif kind == 'Until':
            self.until(activity, run, scope, iteration)
        elif kind in {'ExecutePipeline', 'InvokePipeline'}:
            self.invoke(activity, props, run)
        else:
            raise ActivityFailure(f"{kind} is not simulated")

    def _check_variable(self, name: str, value: Any) -> None:
        declared = self.pipeline.variables[name].type
        actual = type_name(value)
        compatible = (declared == actual or (declared == 'Float' and actual == 'Integer')
                      or value is None)
        if not compatible:
            raise ActivityFailure(f"The variable '{name}' of type '{declared}' cannot be updated with a value of type "
                                  f"'{actual}'; convert it (for example string(...) or int(...))", 'InvalidTemplate')

    def for_each(self, activity: Activity, props: dict[str, Any], run: ActivityRun, scope: Scope) -> None:
        items = props.get('items')
        if not isinstance(items, list):
            raise ActivityFailure(f"ForEach items must be an array, got {type_name(items)}")
        sequential = bool(props.get('isSequential', False))
        slots = 1 if sequential else int(props.get('batchCount', 20) or 20)
        free = [run.start_s] * max(1, slots)
        failed, ends = 0, [run.start_s]
        inner = activity.children.get('activities', [])
        for index, item in enumerate(items):
            slot = min(range(len(free)), key=lambda i: free[i])
            label = f"{activity.name}[{index}] = {json.dumps(item, default=str)[:60]}"
            outcome, _, end = self.container(inner, free[slot], scope.with_item(item), label, activity.name)
            free[slot] = end
            ends.append(end)
            failed += outcome == 'Failed'
        run.end_s = max(ends)
        run.output = {'iterations': len(items), 'failedIterations': failed, 'mode': 'sequential' if sequential else f"parallel ({slots})"}
        run.status = 'Failed' if failed else 'Succeeded'
        run.note = (f"{len(items)} iteration(s), " + ('sequential' if sequential else f"up to {slots} in parallel")
                    + (f"; {failed} failed" if failed else ''))
        if failed:
            run.error = {'errorCode': 'ActivityFailed', 'message': f"{failed} of {len(items)} iterations failed",
                         'failureType': 'UserError', 'target': activity.name}

    def until(self, activity: Activity, run: ActivityRun, scope: Scope, iteration: str | None) -> None:
        timeout = timespan_seconds(activity.type_properties.get('timeout'), activity.path, [], 12 * 3600.0)
        t, count = run.start_s, 0
        inner = activity.children.get('activities', [])
        while True:
            count += 1
            outcome, _, t = self.container(inner, t, scope, f"{activity.name} #{count}", activity.name)
            if outcome == 'Failed':
                run.status, run.end_s = 'Failed', t
                run.error = {'errorCode': 'ActivityFailed', 'message': f"iteration {count} failed",
                             'failureType': 'UserError', 'target': activity.name}
                break
            done = resolve(activity.type_properties.get('expression'), scope)
            if not isinstance(done, bool):
                raise ActivityFailure(f"Until expression must be a Boolean, got {type_name(done)}")
            if done:
                run.status, run.end_s = 'Succeeded', t
                break
            if t - run.start_s > timeout or count >= MAX_UNTIL:
                run.status, run.end_s = 'Failed', t
                run.error = {'errorCode': '2103', 'message': f"Until did not finish after {count} iterations "
                                                            f"({'timeout' if t - run.start_s > timeout else 'lab limit'})",
                             'failureType': 'UserError', 'target': activity.name}
                break
        run.output = {'iterations': count}
        run.note = f"{count} iteration(s)" + (': expression became true' if run.status == 'Succeeded' else '')

    def invoke(self, activity: Activity, props: dict[str, Any], run: ActivityRun) -> None:
        reference = props.get('pipeline') or {}
        name = reference.get('referenceName') if isinstance(reference, dict) else None
        name = name or props.get('pipelineId') or props.get('pipelineName')
        if not name or self.workspace is None or self.depth >= MAX_DEPTH:
            raise ActivityFailure(f"Invoked pipeline '{name}' is not available in this lab workspace"
                                  + (" (nesting limit)" if self.depth >= MAX_DEPTH else ''))
        document = self.workspace.pipeline_document(str(name))
        if document is None:
            raise ActivityFailure(f"Invoked pipeline '{name}' was not found next to this pipeline")
        try:
            child_pipeline = load_pipeline(document, str(name), self.pipeline.flavor)
            child = Simulator(child_pipeline, self.scenario, self.workspace, self.depth + 1,
                              parameters=props.get('parameters') or {},
                              caller=(self.pipeline.name, self.run_id)).run()
        except FactoryLabError as exc:
            problems = '; '.join(f"{i.path}: {i.message}" if i.path else i.message for i in exc.issues[:5])
            raise ActivityFailure(f"Invoked pipeline '{name}' cannot run: {problems}") from exc
        self.children.append(child)
        wait = props.get('waitOnCompletion', True)
        run.output = {'pipelineName': child.pipeline, 'pipelineRunId': child.run_id,
                      **({'pipelineReturnValue': child.return_value} if child.return_value is not None else {})}
        run.truth = 'simulated'
        if wait:
            run.status, run.end_s = child.status, run.start_s + child.duration_s
            run.note = f"Child pipeline {child.pipeline} {child.status.lower()} (waited for completion)"
            if child.status == 'Failed':
                run.error = {'errorCode': '2011', 'message': f"Operation on target {child.pipeline} failed",
                             'failureType': 'UserError', 'target': activity.name}
        else:
            run.status, run.end_s = 'Succeeded', run.start_s
            run.note = 'waitOnCompletion is false: the child run continues on its own'

    # -- work activities --------------------------------------------------------------------------
    def work(self, activity: Activity, props: dict[str, Any]) -> tuple[Any, str, str]:
        from .work import run_work  # local adapters for Copy, Lookup, Script, procedures, notebooks
        return run_work(self, activity, props)


def simulate_pipeline(document: Any, name: str, flavor: str, scenario: FactoryScenario,
                      workspace: Workspace | None = None) -> PipelineRunResult:
    pipeline = load_pipeline(document, name, flavor)
    return Simulator(pipeline, scenario, workspace).run()
