"""The lab's MLflow tracking server and Unity Catalog model registry (a JSON document next to the catalog).

Experiments, runs (parameters, metrics with their history, tags, logged models)
and registered models (versions, aliases, owner) are kept as data. Models are
the lab's pyspark.ml parameters, so they can be loaded back and applied with SQL.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any

from .unity import CATALOG, LAB_USER, MODEL_SCHEMAS, UnityCatalog

MODEL_NAME = re.compile(r'^([A-Za-z_]\w*)\.([A-Za-z_]\w*)\.([A-Za-z_]\w*)$')
ALIAS = re.compile(r'^[A-Za-z_][\w-]{0,254}$')
MAX_RUNS = 500


class MlflowStoreError(ValueError):
    pass


def empty_state() -> dict[str, Any]:
    return {'experiments': {}, 'runs': {}, 'models': {}, 'counter': 0}


class MlflowStore:
    def __init__(self, state: dict[str, Any], unity: UnityCatalog, principal: str, clock: datetime,
                 context: dict[str, Any] | None = None):
        self.state = state
        for key, value in empty_state().items():
            self.state.setdefault(key, value)
        self.unity, self.principal, self.clock = unity, principal, clock
        self.context = dict(context or {})  # job run and task the runs belong to
        self.touched: list[str] = []

    # -- tracking ---------------------------------------------------------------------------------
    def set_experiment(self, name: str) -> str:
        experiments = self.state['experiments']
        if name not in experiments:
            experiments[name] = {'id': str(1000 + len(experiments)), 'name': name}
        return experiments[name]['id']

    def start_run(self, experiment: str | None, run_name: str | None) -> dict[str, Any]:
        experiment = experiment or self._default_experiment()
        experiment_id = self.set_experiment(experiment)
        self.state['counter'] += 1
        seed = f"{self.context.get('job_run_id', '')}:{self.state['counter']}"
        run_id = hashlib.md5(seed.encode()).hexdigest()
        run = {'run_id': run_id, 'run_name': run_name or f"run-{self.state['counter']}", 'experiment': experiment,
               'experiment_id': experiment_id, 'status': 'RUNNING', 'params': {}, 'metrics': {}, 'history': {},
               'tags': {}, 'models': {}, 'start': self.clock.isoformat(), 'user': self.principal,
               'job': self.context.get('job'), 'task': self.context.get('task')}
        runs = self.state['runs']
        runs[run_id] = run
        if len(runs) > MAX_RUNS:
            for old in list(runs)[:len(runs) - MAX_RUNS]:
                runs.pop(old)
        self.touched.append(run_id)
        return run

    def _default_experiment(self) -> str:
        notebook = self.context.get('notebook') or '/Shared/notebook'
        return notebook  # like a notebook experiment, named after the notebook

    def _run(self, run_id: str) -> dict[str, Any]:
        run = self.state['runs'].get(run_id)
        if run is None:
            raise MlflowStoreError(f"Run '{run_id}' not found")
        return run

    def end_run(self, run_id: str, status: str) -> None:
        self._run(run_id)['status'] = status

    def log_param(self, run_id: str, key: str, value: Any) -> None:
        params = self._run(run_id)['params']
        text = value if isinstance(value, str) else str(value)
        if key in params and params[key] != text:
            raise MlflowStoreError(f"Changing param values is not allowed. Param with key='{key}' was already logged "
                                   f"with value='{params[key]}' for run ID='{run_id}'. Attempted logging new value "
                                   f"'{text}'.")
        params[key] = text

    def log_metric(self, run_id: str, key: str, value: float, step: int | None) -> None:
        run = self._run(run_id)
        history = run['history'].setdefault(key, [])
        history.append({'step': step if step is not None else len(history), 'value': value})
        run['metrics'][key] = value

    def set_tag(self, run_id: str, key: str, value: Any) -> None:
        self._run(run_id)['tags'][key] = value if isinstance(value, str) else str(value)

    def log_model(self, run_id: str, path: str, payload: dict[str, Any], signature: dict[str, Any] | None) -> str:
        if not re.fullmatch(r'[\w./-]{1,100}', path):
            raise MlflowStoreError('The model artifact path is a simple name, for example "model"')
        self._run(run_id)['models'][path] = {'payload': payload, 'signature': signature}
        return f"runs:/{run_id}/{path}"

    # -- registry (Unity Catalog) -----------------------------------------------------------------
    def _model_name(self, name: str) -> str:
        match = MODEL_NAME.fullmatch(name or '')
        if not match:
            raise MlflowStoreError(f"Models in Unity Catalog have three-level names <catalog>.<schema>.<model>: {name!r}")
        catalog, schema, model = (g.lower() for g in match.groups())
        if catalog != CATALOG:
            raise MlflowStoreError(f"Catalog '{catalog}' does not exist: the lab has one catalog, '{CATALOG}'")
        if schema not in MODEL_SCHEMAS:
            raise MlflowStoreError(f"Schema '{catalog}.{schema}' does not exist (lab schemas: {', '.join(MODEL_SCHEMAS)})")
        return f"{catalog}.{schema}.{model}"

    def _logged(self, uri: str) -> tuple[dict[str, Any], str]:
        match = re.fullmatch(r'runs:/([0-9a-f]+)/([\w./-]+)', uri or '')
        if not match:
            raise MlflowStoreError(f"Expected a model URI runs:/<run_id>/<path>: {uri!r}")
        run = self._run(match.group(1))
        logged = run['models'].get(match.group(2))
        if logged is None:
            raise MlflowStoreError(f"No model was logged at '{match.group(2)}' in run {match.group(1)}")
        return logged, match.group(1)

    def register_model(self, model_uri: str, name: str) -> dict[str, Any]:
        full = self._model_name(name)
        logged, run_id = self._logged(model_uri)
        models = self.state['models']
        exists = full in models
        self.unity.check_model(self.principal, full, 'register', exists)
        if not logged.get('signature'):
            raise MlflowStoreError('Model passed for registration did not contain any signature metadata. All models '
                                   'in the Unity Catalog must be logged with a model signature: pass input_example= '
                                   'or signature=infer_signature(...) to log_model')
        entry = models.setdefault(full, {'name': full, 'owner': self.principal, 'versions': [], 'aliases': {}})
        version = len(entry['versions']) + 1
        entry['versions'].append({'version': version, 'source': model_uri, 'run_id': run_id,
                                  'payload': logged['payload'], 'signature': logged['signature'],
                                  'created': self.clock.isoformat(), 'metrics': dict(self._run(run_id)['metrics']),
                                  'user': self.principal})
        if not exists and self.principal != LAB_USER:
            self.unity.owners[full] = self.principal
        return {'name': full, 'version': version, 'aliases': [], 'run_id': run_id}

    def _entry(self, name: str) -> dict[str, Any]:
        full = self._model_name(name)
        entry = self.state['models'].get(full)
        if entry is None:
            raise MlflowStoreError(f"RESOURCE_DOES_NOT_EXIST: Registered model '{full}' does not exist")
        return entry

    def set_alias(self, name: str, alias: str, version: int) -> None:
        entry = self._entry(name)
        self.unity.check_model(self.principal, entry['name'], 'alias', True)
        if not ALIAS.fullmatch(alias or '') or alias.lower() == 'latest' or re.fullmatch(r'v\d+', alias.lower()):
            raise MlflowStoreError(f"Invalid alias {alias!r}: 'latest' and v<number> are reserved")
        if version > len(entry['versions']):
            raise MlflowStoreError(f"Model '{entry['name']}' has no version {version}")
        entry['aliases'][alias] = version

    def delete_alias(self, name: str, alias: str) -> None:
        entry = self._entry(name)
        self.unity.check_model(self.principal, entry['name'], 'alias', True)
        entry['aliases'].pop(alias, None)

    def version_by_alias(self, name: str, alias: str) -> dict[str, Any]:
        entry = self._entry(name)
        if alias not in entry['aliases']:
            raise MlflowStoreError(f"Registered model alias {alias} not found on model '{entry['name']}'")
        version = entry['aliases'][alias]
        return {'name': entry['name'], 'version': version,
                'aliases': [a for a, v in entry['aliases'].items() if v == version],
                'run_id': entry['versions'][version - 1]['run_id']}

    def load_model(self, uri: str) -> dict[str, Any]:
        if uri.startswith('runs:/'):
            return self._logged(uri)[0]['payload']
        match = re.fullmatch(r'models:/([\w.]+)(?:/(\d+)|@([\w-]+))', uri or '')
        if not match:
            raise MlflowStoreError(f"Model URIs are models:/<catalog>.<schema>.<model>/<version>, "
                                   f"models:/<name>@<alias> or runs:/<run_id>/<path>: {uri!r}")
        entry = self._entry(match.group(1))
        self.unity.check_model(self.principal, entry['name'], 'load', True)
        version = int(match.group(2)) if match.group(2) else entry['aliases'].get(match.group(3))
        if version is None:
            raise MlflowStoreError(f"Registered model alias {match.group(3)} not found on model '{entry['name']}'")
        if not 1 <= version <= len(entry['versions']):
            raise MlflowStoreError(f"Model '{entry['name']}' has no version {version}")
        return entry['versions'][version - 1]['payload']


def describe(state: dict[str, Any]) -> dict[str, Any]:
    """The tracking and registry state, for the lab view."""
    runs = list(state.get('runs', {}).values())
    return {
        'experiments': [{'name': e['name'], 'id': e['id'],
                         'runs': [_run_view(r) for r in runs if r['experiment'] == e['name']][-20:]}
                        for e in state.get('experiments', {}).values()],
        'models': [{'name': m['name'], 'owner': m.get('owner', LAB_USER), 'aliases': m['aliases'],
                    'versions': [{'version': v['version'], 'run_id': v['run_id'], 'created': v['created'],
                                  'metrics': v.get('metrics', {}), 'kind': v['payload'].get('kind'),
                                  'signature': v.get('signature'), 'user': v.get('user')}
                                 for v in m['versions']]}
                   for m in state.get('models', {}).values()],
    }


def _run_view(run: dict[str, Any]) -> dict[str, Any]:
    return {'run_id': run['run_id'], 'run_name': run['run_name'], 'status': run['status'], 'params': run['params'],
            'metrics': run['metrics'], 'tags': run['tags'], 'models': sorted(run['models']), 'start': run['start'],
            'job': run.get('job'), 'task': run.get('task'), 'user': run.get('user')}
