from contextlib import asynccontextmanager
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from airflowlab.lab import lab_view

from .pipeline_compiler import compile_response
from .kernels import KernelManager
from .retail_demo import run_retail_demo
from .native_pipeline import run_native_pipeline
from .projects import load_project, verify as verify_project
from .run_journal import RunJournal, summarize

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


def record_run(lab: str, request: dict[str, Any], response: object) -> object:
    """Journal what a lab really ran; Projects verify steps with it. A journal problem never fails the lab."""
    try:
        entry = summarize(lab, request, response)
        if entry is not None:
            RunJournal(workspace_data_dir()).record(entry)
    except Exception as error:  # noqa: BLE001 - the lab's answer matters more than its journal entry
        print(f"Datapass run journal: {error}", file=sys.stderr)
    return response


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


class SqlPoolRunRequest(BaseModel):
    """SQL pool Lab: a T-SQL script's TEXT, translated for a documented subset; data statements run on the local catalog."""
    model_config = ConfigDict(extra="forbid")
    flavor: Literal["synapse", "fabric"] = "synapse"
    script: str = Field(default="", max_length=60000)
    # How many real rows one lab row stands for, for tables without their own scale.
    scale: float = Field(default=1.0, ge=1, le=1e12)
    # The script's workspace-relative path, a label for the run journal only: the runtime never reads it.
    source: str = Field(default="", max_length=200, pattern=r"^[A-Za-z0-9_./ -]{0,200}$")


class DatabricksFiles(BaseModel):
    """Databricks Lab files the host sends with a job: notebooks, SQL files, compute and Unity Catalog settings."""
    model_config = ConfigDict(extra="forbid", strict=True)
    notebooks: dict[str, str] = Field(default_factory=dict, max_length=60)
    sql: dict[str, str] = Field(default_factory=dict, max_length=40)
    compute: dict[str, Any] | None = None
    unity_catalog: dict[str, Any] | None = None
    grants: str | None = Field(default=None, max_length=40000)

    @model_validator(mode="after")
    def bounded(self) -> "DatabricksFiles":
        for key, text in (*self.notebooks.items(), *self.sql.items()):
            if not re.fullmatch(r"databricks:/[A-Za-z0-9_./ -]{1,200}", key):
                raise ValueError(f"unexpected lab file key {key!r}")
            if len(text) > 40000:
                raise ValueError("a notebook or SQL file exceeds 40,000 characters")
        if len(json.dumps([self.compute, self.unity_catalog])) > 100_000:
            raise ValueError("compute and Unity Catalog settings exceed 100 KB")
        return self


class DatabricksRunRequest(BaseModel):
    """Databricks Lab: a job (Jobs API JSON), its lab files and a run scenario. Nothing connects to Databricks."""
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,99}$")
    document: dict[str, Any]
    files: DatabricksFiles = Field(default_factory=DatabricksFiles)
    scenario: dict[str, Any] = Field(default_factory=dict)
    # "local": notebook and SQL tasks run on the local catalog; "simulated": dry run.
    data_plane: Literal["local", "simulated"] = "local"

    @model_validator(mode="after")
    def bounded(self) -> "DatabricksRunRequest":
        if len(json.dumps([self.document, self.scenario])) > 400_000:
            raise ValueError("job document and scenario exceed 400 KB")
        return self


class DatabricksStateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    files: DatabricksFiles = Field(default_factory=DatabricksFiles)


class BiScript(BaseModel):
    """A script's workspace-relative path is only a label for messages: the runtime never reads it."""
    model_config = ConfigDict(extra="forbid", strict=True)
    path: str = Field(pattern=r"^[A-Za-z0-9_./ -]{1,200}$")
    text: str = Field(max_length=60000)

    @model_validator(mode="after")
    def relative(self) -> "BiScript":
        if self.path.startswith("/") or ".." in self.path.split("/"):
            raise ValueError("script paths are workspace-relative labels")
        return self


class BiLabRequest(BaseModel):
    """BI Lab: warehouse SQL scripts (TEXT, in order) and the star model file; the scripts run on the local catalog."""
    model_config = ConfigDict(extra="forbid", strict=True)
    scripts: list[BiScript] = Field(default_factory=list, max_length=40)
    model: dict[str, Any] | None = None
    # False: only analyze (lineage, model checks on the tables as they are); True: run the scripts first.
    run: bool = True

    @model_validator(mode="after")
    def bounded(self) -> "BiLabRequest":
        if sum(len(s.text) for s in self.scripts) > 400_000:
            raise ValueError("warehouse scripts exceed 400 KB")
        if len(json.dumps(self.model)) > 100_000:
            raise ValueError("the model file exceeds 100 KB")
        return self


class BiDbtRequest(BaseModel):
    """BI Lab dbt tab: a dbt project's files (TEXT, never read from disk here) and one command for the emulation."""
    model_config = ConfigDict(extra="forbid", strict=True)
    files: dict[str, str] = Field(max_length=200)
    command: Literal["build", "run", "test", "seed", "snapshot", "compile", "parse"] = "build"
    select: list[str] = Field(default_factory=list, max_length=10)
    exclude: list[str] = Field(default_factory=list, max_length=10)
    full_refresh: bool = False
    vars: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def bounded(self) -> "BiDbtRequest":
        for path in self.files:
            parts = path.split("/")
            if not re.fullmatch(r"[A-Za-z0-9_./ -]{1,200}", path) or path.startswith("/") or ".." in parts:
                raise ValueError(f"unexpected project path {path!r}")
        if sum(len(text) for text in self.files.values()) > 600_000:
            raise ValueError("the dbt project exceeds 600 KB")
        for selector in [*self.select, *self.exclude]:
            if not re.fullmatch(r"[A-Za-z0-9_.*+:/@-]{1,120}", selector) or selector.startswith("-"):
                raise ValueError(f"{selector!r} is not a dbt selector")
        if len(json.dumps(self.vars)) > 10_000:
            raise ValueError("vars exceed 10 KB")
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
    language: Literal["sql", "sparklab", "python", "polars", "dbt", "airflow", "factory", "factory-notebook", "sqlpool",
                      "databricks-job", "databricks-notebook", "databricks-grants", "warehouse", "bi-model",
                      "dbt-sql", "dbt-yml", "snowflake"]
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


class ProjectCheckRequest(BaseModel):
    """Projects: verify steps of a project shipped in content/projects. Checks come from the content only."""
    model_config = ConfigDict(extra="forbid", strict=True)
    project_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    # Step ids to verify; empty verifies every step.
    steps: list[str] = Field(default_factory=list, max_length=40)


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
        "databricks_lab": {
            "mode": "hybrid",
            "jobs": "Jobs API JSON: run_if, If/else condition, for each, retries, timeouts, parameters, task values",
            "tasks": "notebook tasks on SparkLab (never eval/exec) and SQL tasks on DuckDB, under Unity Catalog rules",
            "compute": "job clusters, all-purpose clusters, serverless and SQL warehouses modelled with lab DBU figures",
            "mlflow": "tracking and a Unity Catalog model registry (versions, aliases) kept as local data",
            "cloud_connection": False,
        },
        "sqlpool_lab": {
            "mode": "hybrid",
            "flavors": ["synapse", "fabric"],
            "data": "T-SQL translated to DuckDB for a documented subset; data statements run on the local catalog",
            "physical_model": "60 distributions, partitions, columnstore rowgroups and data movement, modelled for teaching",
            "cloud_connection": False,
        },
        "bi_lab": {
            "mode": "real",
            "sql": "warehouse scripts run on the local DuckDB catalog",
            "lineage": "column-level lineage and impact from the SQL text (sqlglot); nothing executed",
            "model": "star model checks (keys, grain, SCD2 validity, relationships) are real queries",
            "power_bi": False,
            "dbt": "Datapass dbt emulation: sandboxed Jinja, real DuckDB SQL, dbt Core semantics for a documented subset; not dbt Core",
        },
        "projects": {
            "mode": "verification",
            "checks": "catalog state (tables, read-only SQL, SQL pool designs, MLflow models) and the run journal of what the labs really ran",
            "manual_steps": "declared by the learner, never marked verified",
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


@app.get("/api/local/catalog/schema")
def local_catalog_schema() -> object:
    """Catalog tree view: every schema's tables and views with columns, types and row counts."""
    return native_command({"op": "catalog_schema"})


@app.post("/api/local/query")
def local_query(body: LocalQueryRequest) -> object:
    return native_command({"op": "read_query", "query": body.query})


@app.post("/api/local/import-csv")
def local_import_csv(body: CsvImportRequest) -> object:
    """Create a NEW bronze table from CSV text. Never overwrites; every column is VARCHAR."""
    try:
        return record_run("csv_import", {}, native_command({"op": "import_csv", "asset": body.asset, "text": body.text}))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/local/exercise")
def local_exercise(body: ExerciseGradeRequest) -> object:
    try:
        result = native_command({
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
    return record_run("exercise", body.model_dump(include={"exercise_id", "exercise_version", "language", "mode"}), result)


@app.post("/api/local/execute")
def local_execute(body: LocalExecuteRequest) -> object:
    return record_run("execute", body.model_dump(include={"language", "profile", "aqe"}), native_command({
        "op": "execute",
        "language": body.language,
        "code": body.code,
        "notebook_id": body.notebook_id,
        "cell_id": body.cell_id,
        "output_asset": body.output_asset,
        "profile": body.profile,
        "aqe": body.aqe,
    }))


@app.post("/api/local/restart")
def local_restart() -> object:
    return kernel_manager.restart(NATIVE_WORKSPACE_ID)


@app.post("/api/pipeline/run")
def execute_pipeline(body: PipelineCompileRequest) -> dict[str, object]:
    try:
        return record_run("pipeline", {}, run_native_pipeline(body.source, native_command))
    except (ValueError, RuntimeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/pipeline/compile")
def compile_pipeline(body: PipelineCompileRequest) -> dict[str, object]:
    """Compile the bounded pipeline DSL into design IR without executing source."""
    return compile_response(body.source)


@app.post("/api/local/airflow/simulate")
def simulate_airflow(body: AirflowSimulateRequest) -> dict[str, object]:
    """Airflow Lab: parse the DAG file (never executed) and simulate the scenario deterministically."""
    return record_run("airflow", {}, lab_view(body.source, body.scenario))


@app.post("/api/local/factory/simulate")
def simulate_factory(body: FactorySimulateRequest) -> object:
    """Factory Lab: validate and simulate a Fabric / Azure Data Factory / Synapse pipeline.

    Supported work activities run on the local catalog (notebooks on SparkLab); the rest follows the scenario.
    """
    return record_run("factory", body.model_dump(include={"flavor", "name"}), native_command({
        "op": "factory_simulate",
        "flavor": body.flavor,
        "name": body.name,
        "document": body.document,
        "files": body.files.model_dump(),
        "scenario": body.scenario,
        "data_plane": body.data_plane,
    }))


@app.post("/api/local/sqlpool/run")
def run_sqlpool(body: SqlPoolRunRequest) -> object:
    """SQL pool Lab: run a script on the simulated dedicated SQL pool (or Fabric Warehouse) and describe its tables."""
    return record_run("sqlpool", body.model_dump(include={"flavor", "script", "source"}),
                      native_command({"op": "sqlpool_run", "flavor": body.flavor, "script": body.script, "scale": body.scale}))


@app.post("/api/local/bi/lab")
def bi_lab(body: BiLabRequest) -> object:
    """BI Lab: run the warehouse scripts on the local catalog, then report tables, SQL lineage and model checks."""
    return record_run("bi", {}, native_command({"op": "bi_lab", "scripts": [s.model_dump() for s in body.scripts],
                                               "model": body.model, "run": body.run}))


@app.post("/api/local/bi/dbt")
def bi_dbt(body: BiDbtRequest) -> object:
    """BI Lab dbt tab: run a dbt command with the emulation on the local catalog; report nodes, results, lineage."""
    return record_run("dbt", body.model_dump(include={"command", "select", "full_refresh"}),
                      native_command({"op": "bi_dbt", "files": body.files, "command": body.command, "select": body.select,
                                      "exclude": body.exclude, "full_refresh": body.full_refresh, "vars": body.vars}))


@app.post("/api/local/databricks/run")
def run_databricks_job(body: DatabricksRunRequest) -> object:
    """Databricks Lab: validate and simulate a job; notebook and SQL tasks run on the local catalog."""
    return record_run("databricks", body.model_dump(include={"name"}),
                      native_command({"op": "databricks_run", "name": body.name, "document": body.document,
                                      "files": body.files.model_dump(), "scenario": body.scenario,
                                      "data_plane": body.data_plane}))


@app.post("/api/local/databricks/state")
def databricks_state(body: DatabricksStateRequest) -> object:
    """Databricks Lab: Unity Catalog (owners, grants) and MLflow (experiments, models) as they are."""
    return native_command({"op": "databricks_state", "files": body.files.model_dump()})


@app.post("/api/demo/retail/run")
def execute_retail_demo(body: RetailDemoRequest) -> dict[str, object]:
    """Execute the local retail medallion path with Polars + DuckDB."""
    try:
        kernel_manager.restart(NATIVE_WORKSPACE_ID)
        return record_run("lakehouse", {}, run_retail_demo(body.dataset_path))
    except (ValueError, FileNotFoundError, RuntimeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/local/projects/check")
def check_project(body: ProjectCheckRequest) -> dict[str, object]:
    """Projects: verify steps on the workspace catalog and the run journal. Manual steps are never verified."""
    try:
        project = load_project(body.project_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    try:
        return verify_project(project, body.steps, RunJournal(workspace_data_dir()), native_command)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
