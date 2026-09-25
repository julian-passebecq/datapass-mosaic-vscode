"""Load and validate pipeline JSON (Fabric `pipeline-content.json`, or Azure Data Factory / Synapse `pipeline/*.json`).

Validation follows Data Factory's design-time rules for the supported subset:
activity names unique across the pipeline, dependencies only between siblings of
the same container, known dependency conditions, no cycles, no ForEach/Until
nested in ForEach/Until, required settings per activity type, declared
variables and parameters, AppendVariable only on Array variables, item() only
inside ForEach or Filter, and activity('X') outputs readable only from
activities that run after X (its descendants, or activities inside a container
that depends on it).
"""
from __future__ import annotations

import json
import re
from typing import Any

from .activities import CONTAINER_KEYS, FLAVORS, TYPES, availability_error
from .expressions import ExpressionError, references
from .model import (CONDITIONS, PARAMETER_TYPES, TYPE_SPELLINGS, VARIABLE_TYPES, Activity, Dependency, FactoryLabError,
                    Issue, Parameter, Pipeline, Policy, Variable)

_BAD_NAME = re.compile(r'[.+?/<>*%&:\\]')
_TIMESPAN = re.compile(r'^(?:(\d+)\.)?(\d{1,2}):(\d{2}):(\d{2})$')
MAX_ACTIVITIES = 120


def timespan_seconds(value: Any, path: str, issues: list[Issue], default: float) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    match = _TIMESPAN.match(str(value).strip())
    if not match:
        issues.append(Issue(path, f"timeout '{value}' must look like d.hh:mm:ss, for example 0.12:00:00"))
        return default
    days, hours, minutes, seconds = (int(g or 0) for g in match.groups())
    return float(((days * 24 + hours) * 60 + minutes) * 60 + seconds)


def _type_ok(kind: str, value: Any) -> bool:
    if value is None:
        return True
    checks = {
        'String': lambda v: isinstance(v, str), 'SecureString': lambda v: isinstance(v, str),
        'Int': lambda v: isinstance(v, int) and not isinstance(v, bool),
        'Integer': lambda v: isinstance(v, int) and not isinstance(v, bool),
        'Float': lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
        'Bool': lambda v: isinstance(v, bool), 'Boolean': lambda v: isinstance(v, bool),
        'Array': lambda v: isinstance(v, list), 'Object': lambda v: isinstance(v, dict),
    }
    return checks.get(kind, lambda v: True)(value)


class _Loader:
    def __init__(self, flavor: str):
        if flavor not in FLAVORS:
            raise FactoryLabError([Issue('', f"Unknown product flavor '{flavor}'; use one of {', '.join(FLAVORS)}")])
        self.flavor = flavor
        self.issues: list[Issue] = []
        self.warnings: list[Issue] = []
        self.names: dict[str, str] = {}
        self.parallel_foreach_depth = 0

    def error(self, path: str, message: str) -> None:
        self.issues.append(Issue(path, message))

    def activities(self, raw: Any, parent: str, loop_depth: int) -> list[Activity]:
        if raw is None:
            return []
        if not isinstance(raw, list):
            self.error(parent, 'activities must be a JSON array')
            return []
        parsed = [a for a in (self.activity(item, parent, loop_depth) for item in raw) if a is not None]
        self.check_container(parsed, parent)
        return parsed

    def activity(self, raw: Any, parent: str, loop_depth: int) -> Activity | None:
        if not isinstance(raw, dict):
            self.error(parent, 'each activity must be a JSON object')
            return None
        name = raw.get('name')
        path = f"{parent}/{name}" if parent else str(name)
        if not isinstance(name, str) or not name.strip():
            self.error(parent or 'activities', 'an activity has no name')
            return None
        if len(name) > 55 or _BAD_NAME.search(name):
            self.error(path, "activity names are at most 55 characters and cannot contain . + ? / < > * % & : \\")
        if name in self.names:
            self.error(path, f"activity name '{name}' is already used at {self.names[name]}; names are unique across "
                             "the whole pipeline")
        self.names[name] = path
        kind = raw.get('type')
        if not isinstance(kind, str):
            self.error(path, 'activity type is missing')
            return None
        problem = availability_error(kind, self.flavor)
        if problem:
            self.error(path, problem)
            return None
        spec = TYPES[kind]
        props = raw.get('typeProperties') or {}
        if not isinstance(props, dict):
            self.error(path, 'typeProperties must be an object')
            props = {}
        for key in spec.required:
            if key not in props:
                self.error(path, f"{spec.label} needs typeProperties.{key}")
        depends = []
        for dep in raw.get('dependsOn') or []:
            if not isinstance(dep, dict) or not isinstance(dep.get('activity'), str):
                self.error(path, 'dependsOn entries need an activity name')
                continue
            conditions = dep.get('dependencyConditions') or ['Succeeded']
            bad = [c for c in conditions if c not in CONDITIONS]
            if bad or not conditions:
                self.error(path, f"unknown dependency condition(s) {bad}; use {', '.join(CONDITIONS)}")
            depends.append(Dependency(dep['activity'], tuple(c for c in conditions if c in CONDITIONS)))
        policy_raw = raw.get('policy') or {}
        policy = Policy(
            timeout_s=timespan_seconds(policy_raw.get('timeout'), path, self.issues, 12 * 3600.0),
            retry=int(policy_raw.get('retry', 0) or 0),
            retry_interval_s=float(policy_raw.get('retryIntervalInSeconds', 30) or 30),
            secure_input=bool(policy_raw.get('secureInput', False)),
            secure_output=bool(policy_raw.get('secureOutput', False)),
        )
        if policy.retry < 0 or policy.retry > 1000:
            self.error(path, 'policy.retry must be between 0 and 1000')
        if policy.retry and not 30 <= policy.retry_interval_s <= 86400:
            self.error(path, 'policy.retryIntervalInSeconds must be between 30 and 86400')
        state = raw.get('state', 'Active')
        mark = raw.get('onInactiveMarkAs', 'Succeeded')
        if state not in {'Active', 'Inactive'} or mark not in {'Succeeded', 'Failed', 'Skipped'}:
            self.error(path, "state is Active or Inactive, and onInactiveMarkAs is Succeeded, Failed or Skipped")
        activity = Activity(name=name, type=kind, path=path, depends_on=depends, policy=policy, type_properties=props,
                            inputs=list(raw.get('inputs') or []), outputs=list(raw.get('outputs') or []),
                            state=state, on_inactive_mark_as=mark, raw=raw)
        loop = kind in {'ForEach', 'Until'}
        if loop and loop_depth > 0:
            self.error(path, f"{spec.label} cannot be nested in ForEach or Until; call a child pipeline with "
                             f"{'InvokePipeline' if self.flavor == 'fabric' else 'ExecutePipeline'} for the inner loop")
        inner_depth = loop_depth + (1 if loop else 0)
        for key in CONTAINER_KEYS.get(kind, ()):
            activity.children[key] = self.activities(props.get(key), path, inner_depth)
        if kind == 'Switch':
            for index, case in enumerate(props.get('cases') or []):
                if not isinstance(case, dict) or 'value' not in case:
                    self.error(path, f"cases[{index}] needs a value and activities")
                    continue
                activity.children[f"case:{case['value']}"] = self.activities(case.get('activities'), path, inner_depth)
        if kind == 'ForEach':
            batch = props.get('batchCount', 20)
            if not isinstance(batch, int) or not 1 <= batch <= 50:
                self.error(path, 'ForEach batchCount must be an integer from 1 to 50')
        return activity

    def check_container(self, activities: list[Activity], path: str) -> None:
        names = {a.name for a in activities}
        for activity in activities:
            for dep in activity.depends_on:
                if dep.activity == activity.name:
                    self.error(activity.path, 'an activity cannot depend on itself')
                elif dep.activity not in names:
                    where = f" in {path}" if path else ''
                    self.error(activity.path, f"depends on '{dep.activity}', which is not an activity of the same "
                                              f"container{where}; dependencies only link siblings")
        order: list[str] = []
        remaining = {a.name: {d.activity for d in a.depends_on if d.activity in names} for a in activities}
        while remaining:
            ready = [n for n, deps in remaining.items() if deps <= set(order)]
            if not ready:
                self.error(path or 'pipeline', f"dependency cycle between {', '.join(sorted(remaining))}")
                return
            order.extend(ready)
            for n in ready:
                remaining.pop(n)


def _ancestors(container: list[Activity], name: str) -> set[str]:
    parents = {a.name: [d.activity for d in a.depends_on] for a in container}
    seen: set[str] = set()
    stack = list(parents.get(name, []))
    while stack:
        current = stack.pop()
        if current not in seen:
            seen.add(current)
            stack.extend(parents.get(current, []))
    return seen


def _check_references(loader: _Loader, pipeline: Pipeline) -> None:
    """Parameters/variables must be declared; activity('X') must be an ancestor; item() only in loops."""

    def visit(container: list[Activity], inherited: set[str], in_foreach: bool) -> None:
        for activity in container:
            visible = inherited | _ancestors(container, activity.name)
            props = {k: v for k, v in activity.type_properties.items()
                     if k not in CONTAINER_KEYS.get(activity.type, ()) and k not in {'cases', 'activities'}}
            if activity.type == 'Until':
                # The Until expression is evaluated after each iteration and may read inner activities.
                visible = visible | {a.name for inner in activity.children.values() for a in inner}
            try:
                found = references([props, activity.inputs, activity.outputs])
            except ExpressionError as exc:
                loader.error(activity.path, f"invalid expression: {exc}")
                found = {'activity': set(), 'variables': set(), 'parameters': set(), 'item': set()}
            for name in found['parameters'] - set(pipeline.parameters):
                loader.error(activity.path, f"pipeline parameter '{name}' is not declared")
            for name in found['variables'] - set(pipeline.variables):
                loader.error(activity.path, f"variable '{name}' is not declared")
            item_allowed = in_foreach or activity.type == 'Filter'
            if found['item'] and not item_allowed:
                loader.error(activity.path, "item() is only available inside a ForEach (or in a Filter condition)")
            for name in found['activity'] - visible:
                loader.error(activity.path, f"the output of activity '{name}' can't be referenced here: it is not an "
                                            "ancestor of this activity (add a dependency or move the reference)")
            if activity.type in {'SetVariable', 'AppendVariable'}:
                variable = activity.type_properties.get('variableName')
                if activity.type_properties.get('setSystemVariable'):
                    pass
                elif variable not in pipeline.variables:
                    loader.error(activity.path, f"variable '{variable}' is not declared")
                elif activity.type == 'AppendVariable' and pipeline.variables[variable].type != 'Array':
                    loader.error(activity.path, f"AppendVariable needs an Array variable; '{variable}' is "
                                                f"{pipeline.variables[variable].type}")
                elif activity.type == 'SetVariable' and in_foreach and loader.parallel_foreach_depth:
                    loader.warnings.append(Issue(activity.path, "SetVariable inside a parallel ForEach: variables are "
                                                                "pipeline-scoped, so iterations overwrite each other",
                                                 'warning'))
            # Inner activities see what their container sees, not the container itself.
            outer = inherited | _ancestors(container, activity.name)
            parallel = activity.type == 'ForEach' and not activity.type_properties.get('isSequential', False)
            for inner in activity.children.values():
                loader.parallel_foreach_depth += parallel
                visit(inner, outer, in_foreach or activity.type == 'ForEach')
                loader.parallel_foreach_depth -= parallel

    visit(pipeline.activities, set(), False)


def load_pipeline(raw: Any, name: str, flavor: str) -> Pipeline:
    """Parse a pipeline document; raise FactoryLabError with every issue found."""
    loader = _Loader(flavor)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise FactoryLabError([Issue('', f"Invalid JSON at line {exc.lineno}: {exc.msg}")]) from exc
    if not isinstance(raw, dict):
        raise FactoryLabError([Issue('', 'a pipeline document is a JSON object')])
    properties = raw.get('properties', raw)
    if not isinstance(properties, dict) or 'activities' not in properties:
        raise FactoryLabError([Issue('', 'no properties.activities found; export the pipeline JSON '
                                         '(Fabric pipeline-content.json or Data Factory pipeline/<name>.json)')])
    name = str(raw.get('name') or name)
    parameters: dict[str, Parameter] = {}
    for key, spec in (properties.get('parameters') or {}).items():
        spec = spec if isinstance(spec, dict) else {}
        kind = TYPE_SPELLINGS.get(str(spec.get('type', 'String')).lower(), str(spec.get('type')))
        if kind not in PARAMETER_TYPES:
            loader.error(f"parameters.{key}", f"type {kind} is not one of {', '.join(sorted(PARAMETER_TYPES))}")
        elif not _type_ok(kind, spec.get('defaultValue')):
            loader.error(f"parameters.{key}", f"defaultValue does not match type {kind}")
        parameters[key] = Parameter(key, kind, spec.get('defaultValue'))
    variables: dict[str, Variable] = {}
    for key, spec in (properties.get('variables') or {}).items():
        spec = spec if isinstance(spec, dict) else {}
        kind = TYPE_SPELLINGS.get(str(spec.get('type', 'String')).lower(), str(spec.get('type')))
        if kind not in VARIABLE_TYPES:
            loader.error(f"variables.{key}", f"type {kind} is not one of {', '.join(sorted(VARIABLE_TYPES))}")
        elif not _type_ok(kind, spec.get('defaultValue')):
            loader.error(f"variables.{key}", f"defaultValue does not match type {kind}")
        variables[key] = Variable(key, 'Boolean' if kind == 'Bool' else 'Integer' if kind == 'Int' else kind,
                                  spec.get('defaultValue'))
    activities = loader.activities(properties.get('activities'), '', 0)
    pipeline = Pipeline(name, flavor, str(properties.get('description') or ''), parameters, variables, activities)
    if len(pipeline.walk()) > MAX_ACTIVITIES:
        loader.error('', f"the simulator reads at most {MAX_ACTIVITIES} activities per pipeline")
    if not loader.issues:
        _check_references(loader, pipeline)
    if loader.issues:
        raise FactoryLabError(loader.issues)
    pipeline.warnings = loader.warnings
    return pipeline
