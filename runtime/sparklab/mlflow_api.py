"""The MLflow API subset a lab notebook can call. The store behind it belongs to the runtime.

Notebooks call these objects through SparkLab's whitelisted interpreter; nothing
imports the real mlflow package. Supported:

- `mlflow.set_experiment(name)`, `mlflow.set_registry_uri("databricks-uc")`;
- `with mlflow.start_run(run_name=...) as run:` (or start_run / end_run), `run.info.run_id`;
- `mlflow.log_param(s)`, `mlflow.log_metric(s)`, `mlflow.set_tag`; logging without an
  active run starts one, as MLflow's fluent API does;
- `mlflow.spark.log_model(model, "model", registered_model_name=..., input_example=df
  or signature=infer_signature(...))` and `mlflow.spark.load_model(uri)` with
  `runs:/<run_id>/<path>`, `models:/<catalog>.<schema>.<model>/<version>` or `@<alias>` URIs;
- `mlflow.register_model(uri, "<catalog>.<schema>.<model>")`;
- `MlflowClient().set_registered_model_alias / get_model_version_by_alias /
  delete_registered_model_alias`;
- `mlflow.models.infer_signature(input_df, output_df)`.

Models in Unity Catalog need a signature, a three-level name, and privileges the
store checks; stages (Staging/Production) do not exist there: use aliases.
"""
from __future__ import annotations

from typing import Any, Protocol

from .ml import MODEL_TYPES, model_from_payload


class MlflowError(ValueError):
    pass


class MlflowStore(Protocol):
    def set_experiment(self, name: str) -> str: ...
    def start_run(self, experiment: str | None, run_name: str | None) -> dict[str, Any]: ...
    def end_run(self, run_id: str, status: str) -> None: ...
    def log_param(self, run_id: str, key: str, value: Any) -> None: ...
    def log_metric(self, run_id: str, key: str, value: float, step: int | None) -> None: ...
    def set_tag(self, run_id: str, key: str, value: Any) -> None: ...
    def log_model(self, run_id: str, path: str, payload: dict[str, Any], signature: dict[str, Any] | None) -> str: ...
    def register_model(self, model_uri: str, name: str) -> dict[str, Any]: ...
    def set_alias(self, name: str, alias: str, version: int) -> None: ...
    def delete_alias(self, name: str, alias: str) -> None: ...
    def version_by_alias(self, name: str, alias: str) -> dict[str, Any]: ...
    def load_model(self, uri: str) -> dict[str, Any]: ...


class RunInfo:
    def __init__(self, run: dict[str, Any]):
        self.run_id = run['run_id']
        self.run_name = run.get('run_name')
        self.experiment_id = run.get('experiment_id')


class ActiveRun:
    def __init__(self, api: 'MLflowApi', run: dict[str, Any]):
        self.api, self.info = api, RunInfo(run)

    # `with mlflow.start_run() as run:` (driven by the safe interpreter)
    def _lab_enter(self) -> 'ActiveRun':
        return self

    def _lab_exit(self, failed: bool) -> None:
        if self.api.active is self:
            self.api.end_run('FAILED' if failed else 'FINISHED')


class ModelVersion:
    def __init__(self, data: dict[str, Any]):
        self.name = data['name']
        self.version = data['version']
        self.aliases = list(data.get('aliases', []))
        self.run_id = data.get('run_id')


class ModelInfo:
    def __init__(self, model_uri: str, version: ModelVersion | None):
        self.model_uri = model_uri
        self.registered_model_version = version.version if version else None


class Signature:
    def __init__(self, inputs: list[str], outputs: list[str] | None = None):
        self.inputs, self.outputs = list(inputs), list(outputs or [])

    def as_dict(self) -> dict[str, Any]:
        return {'inputs': self.inputs, 'outputs': self.outputs}


def infer_signature(model_input: Any, model_output: Any = None) -> Signature:
    inputs = _columns(model_input, 'infer_signature needs the model input as a DataFrame')
    outputs = _columns(model_output, '') if model_output is not None else []
    return Signature(inputs, outputs)


def _columns(value: Any, message: str) -> list[str]:
    columns = getattr(value, 'current_columns', lambda: None)()
    if columns is None:
        raise MlflowError(message or 'Expected a DataFrame')
    return [c for c in columns]


class _SparkFlavor:
    def __init__(self, api: 'MLflowApi'):
        self.api = api

    def log_model(self, spark_model: Any = None, artifact_path: str | None = None, registered_model_name: str | None = None,
                  input_example: Any = None, signature: Any = None, name: str | None = None) -> ModelInfo:
        if not isinstance(spark_model, MODEL_TYPES):
            raise MlflowError('mlflow.spark.log_model logs a fitted model (LinearRegressionModel, '
                              'LogisticRegressionModel or PipelineModel)')
        path = name or artifact_path or 'model'
        if signature is None and input_example is not None:
            signature = infer_signature(input_example)
        if signature is not None and not isinstance(signature, Signature):
            raise MlflowError('signature must come from mlflow.models.infer_signature')
        run = self.api._ensure_run()
        uri = self.api.store.log_model(run.info.run_id, path, spark_model.payload(),
                                       signature.as_dict() if signature else None)
        version = self.api.register_model(uri, registered_model_name) if registered_model_name else None
        return ModelInfo(uri, version)

    def load_model(self, model_uri: str) -> Any:
        if not isinstance(model_uri, str):
            raise MlflowError('load_model needs a model URI such as models:/main.ml.power_model@champion')
        return model_from_payload(self.api.store.load_model(model_uri))


class _ModelsModule:
    infer_signature = staticmethod(infer_signature)


class MlflowClient:
    def __init__(self, api: 'MLflowApi'):
        self.api = api

    def set_registered_model_alias(self, name: str, alias: str, version: Any) -> None:
        self.api.store.set_alias(name, alias, _version(version))

    def delete_registered_model_alias(self, name: str, alias: str) -> None:
        self.api.store.delete_alias(name, alias)

    def get_model_version_by_alias(self, name: str, alias: str) -> ModelVersion:
        return ModelVersion(self.api.store.version_by_alias(name, alias))


def _version(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise MlflowError(f"Model versions are numbers, not {value!r}") from None
    if number < 1:
        raise MlflowError('Model versions start at 1')
    return number


class MLflowApi:
    """The `mlflow` module as a notebook sees it."""

    def __init__(self, store: MlflowStore):
        self.store = store
        self.experiment: str | None = None
        self.registry_uri = 'databricks-uc'
        self.active: ActiveRun | None = None
        self.last: ActiveRun | None = None
        self.spark = _SparkFlavor(self)
        self.models = _ModelsModule()

    def set_experiment(self, experiment_name: str | None = None, experiment_id: str | None = None) -> None:
        name = experiment_name or experiment_id
        if not isinstance(name, str) or not name:
            raise MlflowError('set_experiment needs an experiment name, for example /Shared/power-forecast')
        self.store.set_experiment(name)
        self.experiment = name

    def set_registry_uri(self, uri: str) -> None:
        if uri != 'databricks-uc':
            raise MlflowError("The lab's model registry is Unity Catalog: set_registry_uri('databricks-uc'). The "
                              "legacy workspace model registry is not simulated")
        self.registry_uri = uri

    def start_run(self, run_name: str | None = None, nested: bool = False, run_id: str | None = None) -> ActiveRun:
        if run_id is not None:
            raise MlflowError('Resuming a run by run_id is not simulated')
        if self.active is not None and not nested:
            raise MlflowError(f"Run with UUID {self.active.info.run_id} is already active. To start a nested run, "
                              "call start_run with nested=True")
        self.active = ActiveRun(self, self.store.start_run(self.experiment, run_name))
        self.last = self.active
        return self.active

    def end_run(self, status: str = 'FINISHED') -> None:
        if self.active is not None:
            self.store.end_run(self.active.info.run_id, status)
            self.active = None

    def active_run(self) -> ActiveRun | None:
        return self.active

    def last_active_run(self) -> ActiveRun | None:
        return self.last

    def _ensure_run(self) -> ActiveRun:
        return self.active or self.start_run()

    def log_param(self, key: str, value: Any) -> Any:
        self.store.log_param(self._ensure_run().info.run_id, _key(key), value)
        return value

    def log_params(self, params: dict[str, Any]) -> None:
        if not isinstance(params, dict):
            raise MlflowError('log_params needs a dict')
        for key, value in params.items():
            self.log_param(key, value)

    def log_metric(self, key: str, value: Any, step: int | None = None) -> None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise MlflowError(f"Metric {key!r} must be a number")
        self.store.log_metric(self._ensure_run().info.run_id, _key(key), float(value), step)

    def log_metrics(self, metrics: dict[str, Any], step: int | None = None) -> None:
        if not isinstance(metrics, dict):
            raise MlflowError('log_metrics needs a dict')
        for key, value in metrics.items():
            self.log_metric(key, value, step)

    def set_tag(self, key: str, value: Any) -> None:
        self.store.set_tag(self._ensure_run().info.run_id, _key(key), value)

    def register_model(self, model_uri: str, name: str) -> ModelVersion:
        if not isinstance(model_uri, str) or not isinstance(name, str):
            raise MlflowError('register_model(model_uri, name) takes two strings')
        return ModelVersion(self.store.register_model(model_uri, name))

    def MlflowClient(self) -> MlflowClient:  # `from mlflow import MlflowClient` binds this factory
        return MlflowClient(self)


def _key(key: Any) -> str:
    if not isinstance(key, str) or not key or len(key) > 250:
        raise MlflowError('Parameter, metric and tag keys are non-empty strings')
    return key
