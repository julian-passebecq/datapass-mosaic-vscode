from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from airflowlab.lab import lab_view

from .pipeline_compiler import compile_response
from .kernels import KernelManager
from .retail_demo import run_retail_demo
from .native_pipeline import run_native_pipeline

NATIVE_WORKSPACE_ID = "vscode-native"
kernel_manager = KernelManager(
    mode=os.getenv("DATAPASS_STORAGE", "duckdb"),
    trusted=os.getenv("DATAPASS_TRUSTED_PYTHON") == "1",
    timeout=20.0,
    max_workers=1,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    kernel_manager.close()


app = FastAPI(title="Datapass Runtime", version="0.1.0", lifespan=lifespan)


def workspace_root() -> Path:
    configured = os.getenv("DATAPASS_WORKSPACE_ROOT")
    if not configured:
        raise RuntimeError("DATAPASS_WORKSPACE_ROOT is not configured.")
    root = Path(configured).expanduser().resolve()
    if not root.is_dir():
        raise RuntimeError(f"Datapass workspace root does not exist: {root}")
    return root


def workspace_data_dir() -> Path:
    data = workspace_root() / ".datapass" / "data"
    data.mkdir(parents=True, exist_ok=True)
    return data


def native_command(body: dict[str, object]) -> object:
    # Trusted Python resolves relative paths from the workspace root, like `python file.py`.
    return kernel_manager.call(NATIVE_WORKSPACE_ID, workspace_data_dir(), body, cwd=workspace_root())


class PipelineCompileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source: str = Field(min_length=1, max_length=80000)


class AirflowSimulateRequest(BaseModel):
    """An Airflow DAG file's TEXT and a simulation scenario. The source is parsed, never executed."""
    model_config = ConfigDict(extra="forbid", strict=True)
    source: str = Field(min_length=1, max_length=60000)
    scenario: dict[str, Any] = Field(default_factory=dict)


class FactoryFiles(BaseModel):
    """Lab files the host sends with a pipeline: invoked pipelines, datasets, procedures and notebooks."""
    model_config = ConfigDict(extra="forbid", strict=True)
    pipelines: dict[str, dict[str, Any]] = Field(default_factory=dict, max_length=40)
    datasets: dict[str, dict[str, Any]] = Field(default_factory=dict, max_length=80)
    procedures: dict[str, str] = Field(default_factory=dict, max_length=40)
    notebooks: dict[str, str] = Field(default_factory=dict, max_length=40)

    @model_validator(mode="after")
    def bounded(self) -> "FactoryFiles":
        for text in (*self.procedures.values(), *self.notebooks.values()):
            if len(text) > 40000:
                raise ValueError("a procedure or notebook exceeds 40,000 characters")
        if len(json.dumps([self.pipelines, self.datasets])) > 600_000:
            raise ValueError("pipeline and dataset files exceed 600 KB")
        return self


class FactorySimulateRequest(BaseModel):
    """Factory Lab: a pipeline JSON document, the lab files it references and a scenario. Nothing connects to a cloud."""
    model_config = ConfigDict(extra="forbid", strict=True)
    flavor: Literal["fabric", "adf", "synapse"]
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,139}$")
    document: dict[str, Any]
    files: FactoryFiles = Field(default_factory=FactoryFiles)
    scenario: dict[str, Any] = Field(default_factory=dict)
    # "local": Copy, Lookup, Script, procedures and notebooks act on the local catalog; "simulated": dry run.
    data_plane: Literal["local", "simulated"] = "local"

    @model_validator(mode="after")
    def bounded(self) -> "FactorySimulateRequest":
        if len(json.dumps([self.document, self.scenario])) > 400_000:
            raise ValueError("pipeline document and scenario exceed 400 KB")
        return self


class RetailDemoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    dataset_path: str = Field(min_length=1, max_length=500)


class LocalQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    query: str = Field(min_length=1, max_length=40000)


class ExerciseGradeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    exercise_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    exercise_version: str = Field(min_length=1, max_length=40)
    language: Literal["sql", "sparklab", "python", "polars", "dbt", "airflow", "factory", "factory-notebook"]
    code: str = Field(min_length=1, max_length=40000)
    mode: Literal["run", "submit"]
    notebook_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    cell_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    source_revision: int = Field(ge=0)
    profile: str = Field(default="generic_8x8", max_length=80)
    aqe: bool = True


class CsvImportRequest(BaseModel):
    """CSV CONTENT, never a path: the runtime does not read files for this route."""
    model_config = ConfigDict(extra="forbid", strict=True)
    asset: str = Field(pattern=r"^bronze\.[A-Za-z][A-Za-z0-9_]{0,62}$")
    # local_data.parse_csv enforces the exact 1 MB UTF-8 byte limit.
    text: str = Field(min_length=1, max_length=1_000_000)


class LocalExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    language: Literal["sql", "sparklab", "python", "polars"]
    code: str = Field(min_length=1, max_length=40000)
    notebook_id: str = Field(default="vscode-notebook", pattern=r"^[A-Za-z0-9_-]{1,100}$")
    cell_id: str = Field(default="cell", pattern=r"^[A-Za-z0-9_-]{1,100}$")
    output_asset: str | None = Field(default=None, max_length=100)
    profile: str = Field(default="generic_8x8", max_length=80)
    aqe: bool = True


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "runtime": "local", "version": "0.1.0"}


@app.get("/api/capabilities")
def capabilities() -> dict[str, object]:
    return {
        "runtime": {
            # Set only by the extension after an explicit, workspace-scoped opt-in.
            "trusted_local_python": kernel_manager.trusted,
            "python_sandboxed": False,
            "python_truth": "trusted local CPython worker; process isolation is lifecycle management, not a security sandbox",
        },
        "mosaic": {
            "mode": "real",
            "engines": ["polars", "duckdb"],
            "spark_by_default": False,
            "csv_import": "new bronze tables only; CSV text up to 1 MB / 5,000 rows; all columns VARCHAR; never overwrites",
        },
        "practice": {"mode": "local-tests", "editors": "vscode-native"},
        "fabric_lab": {"mode": "simulation", "notebook": "fabric-inspired", "lakehouse": "duckdb-ducklake", "kernel": "sparklab", "cloud_connection": False},
        "factory_lab": {
            "mode": "hybrid",
            "flavors": ["fabric", "adf", "synapse"],
            "orchestration": "deterministic Data Factory semantics: dependency conditions, leaf evaluation, retries, timeouts, containers, expressions",
            "local_activities": ["Copy", "Lookup", "Script", "SqlServerStoredProcedure", "SqlPoolStoredProcedure", "TridentNotebook", "SynapseNotebook", "DatabricksNotebook"],
            "notebooks": "SparkLab whitelisted AST interpreter; never eval/exec",
            "cloud_connection": False,
        },
        "sparklab": {"mode": "simulation", "goal": "pyspark-dataframe-concepts"},
        "dbt_lab": {"mode": "hybrid", "runner": "dbt-core", "lineage": "manifest"},
        "airflow_lab": {
            "mode": "simulation",
            "scheduler": "deterministic-local",
            "dag_source": "Airflow DAG files parsed by a whitelisted AST reader; never executed",
            "semantics": "Airflow 3 timetables, catchup, trigger rules, retries, sensors, branching and templates for the supported subset",
        },
        "pipeline_lab": {
            "mode": "hybrid",
            "compiler": "bounded-ast-design",
            "source_execution": False,
            "activity_execution": "real-local-where-supported",
            "activities": ["sql", "quality", "python", "polars", "dbt"],
            "wired_activities": ["sql", "quality", "python", "polars"],
            "declared_but_not_wired": ["dbt"],
            "scheduling": "metadata-only",
        },
    }


@app.get("/api/local/capabilities")
def local_capabilities() -> object:
    return native_command({"op": "capabilities"})


@app.get("/api/local/catalog")
def local_catalog() -> object:
    return native_command({"op": "catalog"})


@app.post("/api/local/query")
def local_query(body: LocalQueryRequest) -> object:
    return native_command({"op": "read_query", "query": body.query})


@app.post("/api/local/import-csv")
def local_import_csv(body: CsvImportRequest) -> object:
    """Create a NEW bronze table from CSV text. Never overwrites; every column is VARCHAR."""
    try:
        return native_command({"op": "import_csv", "asset": body.asset, "text": body.text})
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/local/exercise")
def local_exercise(body: ExerciseGradeRequest) -> object:
    try:
        return native_command({
            "op": "exercise",
            "exercise_id": body.exercise_id,
            "exercise_version": body.exercise_version,
            "language": body.language,
            "code": body.code,
            "mode": body.mode,
            "notebook_id": body.notebook_id,
            "cell_id": body.cell_id,
            "source_revision": body.source_revision,
            "profile": body.profile,
            "aqe": body.aqe,
        })
    except (KeyError, ValueError, RuntimeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/local/execute")
def local_execute(body: LocalExecuteRequest) -> object:
    return native_command({
        "op": "execute",
        "language": body.language,
        "code": body.code,
        "notebook_id": body.notebook_id,
        "cell_id": body.cell_id,
        "output_asset": body.output_asset,
        "profile": body.profile,
        "aqe": body.aqe,
    })


@app.post("/api/local/restart")
def local_restart() -> object:
    return kernel_manager.restart(NATIVE_WORKSPACE_ID)


@app.post("/api/pipeline/run")
def execute_pipeline(body: PipelineCompileRequest) -> dict[str, object]:
    try:
        return run_native_pipeline(body.source, native_command)
    except (ValueError, RuntimeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/pipeline/compile")
def compile_pipeline(body: PipelineCompileRequest) -> dict[str, object]:
    """Compile the bounded pipeline DSL into design IR without executing source."""
    return compile_response(body.source)


@app.post("/api/local/airflow/simulate")
def simulate_airflow(body: AirflowSimulateRequest) -> dict[str, object]:
    """Airflow Lab: parse the DAG file (never executed) and simulate the scenario deterministically."""
    return lab_view(body.source, body.scenario)


@app.post("/api/local/factory/simulate")
def simulate_factory(body: FactorySimulateRequest) -> object:
    """Factory Lab: validate and simulate a Fabric / Azure Data Factory / Synapse pipeline.

    Supported work activities run on the local catalog (notebooks on SparkLab); the rest follows the scenario.
    """
    return native_command({
        "op": "factory_simulate",
        "flavor": body.flavor,
        "name": body.name,
        "document": body.document,
        "files": body.files.model_dump(),
        "scenario": body.scenario,
        "data_plane": body.data_plane,
    })


@app.post("/api/demo/retail/run")
def execute_retail_demo(body: RetailDemoRequest) -> dict[str, object]:
    """Execute the local retail medallion path with Polars + DuckDB."""
    try:
        kernel_manager.restart(NATIVE_WORKSPACE_ID)
        return run_retail_demo(body.dataset_path)
    except (ValueError, FileNotFoundError, RuntimeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
