"""Factory Lab panel view: validate a pipeline document, simulate a scenario, return what the panel shows."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from pydantic import ValidationError

from .activities import FLAVOR_LABELS, TYPES
from .engine import FactoryScenario, PipelineRunResult, Simulator, Workspace
from .loader import load_pipeline
from .model import Activity, FactoryLabError, Pipeline

TRUTH = ("Simulated Data Factory orchestration. Copy, Lookup, Script, stored procedures and lab notebooks can run on "
         "the local catalog (DuckDB, SparkLab); every other activity follows the scenario. Nothing connects to "
         "Microsoft Fabric, Azure or Databricks.")


def _activity_view(activity: Activity) -> dict[str, Any]:
    spec = TYPES[activity.type]
    return {
        'name': activity.name, 'type': activity.type, 'label': spec.label, 'category': spec.category,
        'path': activity.path, 'state': activity.state, 'depends_on': [
            {'activity': d.activity, 'conditions': list(d.conditions)} for d in activity.depends_on],
        'policy': {'timeout_s': activity.policy.timeout_s, 'retry': activity.policy.retry,
                   'retry_interval_s': activity.policy.retry_interval_s},
        'children': {key: [_activity_view(inner) for inner in inner_list] for key, inner_list in activity.children.items()},
    }


def pipeline_view(pipeline: Pipeline) -> dict[str, Any]:
    return {
        'name': pipeline.name, 'flavor': pipeline.flavor, 'description': pipeline.description,
        'parameters': [{'name': p.name, 'type': p.type, 'default': p.default} for p in pipeline.parameters.values()],
        'variables': [{'name': v.name, 'type': v.type, 'default': v.default} for v in pipeline.variables.values()],
        'activities': [_activity_view(a) for a in pipeline.activities],
        'warnings': [w.message if not w.path else f"{w.path}: {w.message}" for w in pipeline.warnings],
    }


def run_view(result: PipelineRunResult) -> dict[str, Any]:
    return {
        'pipeline': result.pipeline, 'run_id': result.run_id, 'status': result.status,
        'evaluated': result.evaluated, 'duration_s': result.duration_s, 'parameters': result.parameters,
        'variables': result.variables, 'return_value': result.return_value,
        'activity_runs': [asdict(run) for run in result.runs],
        'children': [run_view(child) for child in result.children],
    }


def factory_view(document: Any, name: str, flavor: str, scenario: dict[str, Any],
                 workspace: Workspace | None = None) -> dict[str, Any]:
    view: dict[str, Any] = {'status': 'invalid', 'flavor': flavor, 'flavor_label': FLAVOR_LABELS.get(flavor, flavor),
                            'truth': TRUTH, 'issues': [], 'pipeline': None, 'run': None, 'hints': []}
    try:
        pipeline = load_pipeline(document, name, flavor)
    except FactoryLabError as exc:
        view['issues'] = [{'path': i.path, 'message': i.message, 'severity': i.severity} for i in exc.issues]
        return view
    view['pipeline'] = pipeline_view(pipeline)
    try:
        parsed = FactoryScenario.model_validate(scenario)
        result = Simulator(pipeline, parsed, workspace).run()
    except FactoryLabError as exc:
        view.update(status='error', issues=[{'path': i.path, 'message': i.message, 'severity': i.severity}
                                            for i in exc.issues])
        return view
    except ValidationError as exc:
        view.update(status='error', issues=[{'path': 'scenario', 'message': str(exc), 'severity': 'error'}])
        return view
    view.update(status='simulated', run=run_view(result), hints=_hints(result, workspace))
    return view


def _all_runs(result: PipelineRunResult) -> list[Any]:
    return list(result.runs) + [run for child in result.children for run in _all_runs(child)]


def _hints(result: PipelineRunResult, workspace: Workspace | None) -> list[str]:
    hints = []
    local = workspace is not None and bool(getattr(workspace, 'local', False))
    missing = any(run.error and "doesn't exist" in str(run.error.get('message', '')) for run in _all_runs(result))
    if missing and not local:
        hints.append("Dry run: work activities return placeholder outputs, so expressions that read them can fail. "
                     "Give those activities an output in the scenario (for example a Lookup's "
                     "{\"firstRow\": {...}}), or run on the local lakehouse.")
    return hints
