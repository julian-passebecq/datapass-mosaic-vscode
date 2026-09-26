from contextlib import asynccontextmanager
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from airflowlab.lab import lab_view
from sqldialects import dialects as sql_dialect_list
from missionlab.check import evaluate as evaluate_mission, fixture_statements, sql_queries as mission_queries
from missionlab.model import find_mission
from missionlab.terminal import FixtureError, build_fixture
from missionlab.infra import build_fixture as build_infra_fixture
from infralab.shell import run_line as infra_run_line, state_view as infra_state_view
from infralab.world import WorldError
from lakehouselab.api import router as lakehouse_router

from .auth import RuntimeAuthMiddleware
from .catalog_lease import CatalogLease, CatalogLocked, CatalogReleased, is_lock_error
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
# Every request needs this launch's token and a loopback Host header (see auth.py).
app.add_middleware(RuntimeAuthMiddleware)
# Lakehouse Lab routes (/api/local/lakehouse/*): runtime/lakehouselab.
app.include_router(lakehouse_router)
catalog_lease = CatalogLease()


@app.exception_handler(CatalogReleased)
@app.exception_handler(CatalogLocked)
async def catalog_unavailable(_request: Request, error: Exception) -> JSONResponse:
    # 409: the catalog exists but another process has it; the request can be retried after a reattach.
    return JSONResponse(status_code=409, content={"detail": str(error), "catalog": catalog_lease.view()})


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
    # The lease check and the call share the workspace gate, so a release cannot slip between them.
    with kernel_manager.workspace_lease(NATIVE_WORKSPACE_ID):
        catalog_lease.check()
        try:
            # Trusted Python resolves relative paths from the workspace root, like `python file.py`.
            return kernel_manager.call(NATIVE_WORKSPACE_ID, workspace_data_dir(), body, cwd=workspace_root())
        except RuntimeError as error:
            if is_lock_error(error):
                raise CatalogLocked(
                    "Another process holds .datapass/data/workspace.duckdb (a dbt Core or dct run started outside "
                    "the dbt Lab?). DuckDB allows one writer per file: wait for it to end, then retry.") from error
            raise


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


class CatalogReleaseRequest(BaseModel):
    """Who borrows the catalog file: the command line shown in the UI, e.g. `dbt build --select tag:daily`."""
    model_config = ConfigDict(extra="forbid", strict=True)
    holder: str = Field(min_length=1, max_length=200)

    @field_validator("holder")
    @classmethod
    def printable(cls, value: str) -> str:
        if not value.isprintable():
            raise ValueError("holder must be one printable line")
        return value


class MissionSetupRequest(BaseModel):
    """Missions: load one fixture batch of a dbt Lab mission, or (re)build a Terminal Lab mission's folder. The SQL,
    files and Git history come from the shipped content, never from the request."""
    model_config = ConfigDict(extra="forbid", strict=True)
    mission_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,47}$")
    batch_id: str | None = Field(default=None, pattern=r"^[a-z0-9-]{1,40}$")


class MissionCheckRequest(BaseModel):
    """Missions: run the hidden checker. `dct` carries the real `dct validate --json` results the host ran."""
    model_config = ConfigDict(extra="forbid")
    mission_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,47}$")
    dct: dict[str, dict[str, Any]] = Field(default_factory=dict, max_length=10)

    @model_validator(mode="after")
    def bounded(self) -> "MissionCheckRequest":
        if len(json.dumps(self.dct)) > 200_000:
            raise ValueError("dct results exceed 200 KB")
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
                      "dbt-sql", "dbt-yml", "snowflake", "tsql", "bigquery", "sparksql"]
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


class FileImportRequest(BaseModel):
    """Parquet or JSON CONTENT as base64, never a path: the runtime writes and reads its own temporary copy."""
    model_config = ConfigDict(extra="forbid", strict=True)
    asset: str = Field(pattern=r"^bronze\.[A-Za-z][A-Za-z0-9_]{0,62}$")
    format: Literal["parquet", "json"]
    # local_data.import_file enforces the exact 10 MB decoded limit.
    data: str = Field(min_length=4, max_length=13_400_000)


class TableProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    asset: str = Field(pattern=r"^(source|bronze|silver|gold|warehouse|features|metrics)\.[A-Za-z][A-Za-z0-9_]{0,62}$")


SqlDialect = Literal["tsql", "snowflake", "bigquery", "spark", "postgres"]


class ExplainRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    query: str = Field(min_length=1, max_length=40000)
    dialect: SqlDialect | None = None


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
    # SQL written in another dialect, translated to DuckDB (runtime/sqldialects): Mosaic's `-- dialect:` header.
    dialect: SqlDialect | None = None

    @model_validator(mode="after")
    def dialect_is_sql(self) -> "LocalExecuteRequest":
        if self.dialect is not None and (self.language != "sql" or self.output_asset is not None):
            raise ValueError("A SQL dialect applies to SQL runs without an output asset.")
        return self


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
            "file_import": "new bronze tables only; Parquet (types from the file) or JSON (read_json_auto types) up to 10 MB / 100,000 rows; never overwrites",
            "profile": "DuckDB SUMMARIZE of a catalog table",
            "explain": "DuckDB EXPLAIN ANALYZE of one read-only query (it runs once)",
            "sql_dialects": sql_dialect_list(),
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
        "infra_lab": {
            "mode": "simulated",
            "terraform": "HCL read by a whitelisted reader and evaluated (never executed); plan and apply against a "
                         "simulated azurerm provider and subscription; terraform.tfstate marked as simulated",
            "docker": "Dockerfile and compose read, never executed; build, cache, run and compose simulated",
            "monitoring": "az CLI subset on a simulated subscription; metric scenarios; Azure Monitor alert replay",
            "kubernetes": "manifests validated strictly and applied to a simulated cluster; rollouts simulated",
            "real_tools": False,
        },
        "missions": {
            "labs": ["dbt", "terminal", "infra"],
            "work": "real tools on a real project folder (missions/<id>/): dbt Core, dbt Charts, an Airflow DAG file; "
                    "the learner's own bash, PowerShell and Git commands in a VS Code terminal",
            "checker": "read-only SQL on the catalog, the learner's dbt artifacts and files, dct validate, the Airflow "
                       "simulator; for the Terminal Lab the resulting files and Git repository (read-only git), never "
                       "the learner's commands or scripts",
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


@app.get("/api/local/catalog")
def local_catalog() -> object:
    return native_command({"op": "catalog"})


@app.get("/api/local/catalog/schema")
def local_catalog_schema() -> object:
    """Catalog tree view: every schema's tables and views with columns, types and row counts."""
    return native_command({"op": "catalog_schema"})


@app.get("/api/local/catalog/lease")
def catalog_lease_view() -> dict[str, object]:
    return catalog_lease.view()


@app.post("/api/local/catalog/release")
def release_catalog(body: CatalogReleaseRequest) -> dict[str, object]:
    """Close the workspace catalog so an external process (dbt Core, dct) can open the DuckDB file.

    Waits for a running request to finish; every catalog request is then refused (HTTP 409) until reattached.
    """
    with kernel_manager.workspace_lease(NATIVE_WORKSPACE_ID):
        catalog_lease.hold(body.holder)
        kernel_manager.restart(NATIVE_WORKSPACE_ID)
    return catalog_lease.view()


@app.post("/api/local/catalog/reattach")
def reattach_catalog() -> dict[str, object]:
    """Reopen the workspace catalog. If the file is still held, the catalog stays lent and HTTP 409 says why."""
    with kernel_manager.workspace_lease(NATIVE_WORKSPACE_ID):
        previous = catalog_lease.clear()
        try:
            native_command({"op": "capabilities"})
        except CatalogLocked:
            catalog_lease.hold(previous or "another process")
            raise CatalogLocked(
                "The catalog file is still held by another process (is a dbt or dct command still running, "
                "such as dct serve?). Stop it, then reattach.") from None
        except (RuntimeError, ValueError) as error:
            # Any other reopen failure: the catalog stays lent and the reason is shown; a retry may succeed.
            catalog_lease.hold(previous or "another process")
            raise CatalogLocked(f"The catalog could not be reopened yet: {error}") from None
    return catalog_lease.view()


def _mission(mission_id: str):
    try:
        return find_mission(mission_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/local/missions/setup")
def mission_setup(body: MissionSetupRequest) -> dict[str, object]:
    """Load a mission's fixture batch into the catalog (the first batch starts the mission over), or build a Terminal
    Lab or Infra Lab mission's folder from the pack (an existing folder is moved to .datapass/missions/attic/, never
    deleted)."""
    mission, pack_dir = _mission(body.mission_id)
    if mission.lab in ("terminal", "infra"):
        builder = build_fixture if mission.lab == "terminal" else build_infra_fixture
        try:
            built = builder(mission, pack_dir, workspace_root())
        except FixtureError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {"mission_id": mission.id, "batch_id": None, **built}
    if body.batch_id is None:
        raise HTTPException(status_code=400, detail=f"Mission {mission.id} needs a batch id.")
    try:
        statements = fixture_statements(mission, pack_dir, body.batch_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    result = native_command({"op": "mission_setup", "statements": statements})
    return {"mission_id": mission.id, "batch_id": body.batch_id, "statements": result["executed"]}


@app.post("/api/local/missions/check")
def mission_check(body: MissionCheckRequest) -> dict[str, object]:
    """The hidden checker: read-only SQL on the catalog, the learner's dbt artifacts and files, dct, Airflow; for the
    Terminal Lab, the mission folder's files and Git repository (no catalog query)."""
    mission, _pack_dir = _mission(body.mission_id)
    queries = mission_queries(mission)
    results = native_command({"op": "mission_sql", "queries": queries}) if queries else []
    return evaluate_mission(mission, workspace_root() / mission.folder, dict(zip(queries, results)), body.dct)


class InfraCommandRequest(BaseModel):
    """Infra Lab: one line typed in the simulated shell, run in a folder of the workspace (a mission folder or any lab
    folder). `answer` replies to a prompt (terraform apply's "Enter a value")."""
    model_config = ConfigDict(extra="forbid", strict=True)
    folder: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_.][A-Za-z0-9_./-]*$")
    line: str = Field(max_length=2000)
    answer: str | None = Field(default=None, max_length=200)


class InfraStateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    folder: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_.][A-Za-z0-9_./-]*$")


def infra_folder(relative: str) -> Path:
    """A folder inside the workspace (never the workspace's .datapass state), for the Infra Lab shell."""
    root = workspace_root()
    parts = relative.split("/")
    if ".." in parts or parts[0] in (".datapass", ".git"):
        raise HTTPException(status_code=400, detail="The Infra Lab works in a folder of the workspace.")
    folder = (root / relative).resolve()
    if not folder.is_relative_to(root) or not folder.is_dir():
        raise HTTPException(status_code=404, detail=f"No folder {relative} in the workspace.")
    return folder


@app.post("/api/local/infra/command")
def infra_command(body: InfraCommandRequest) -> dict[str, object]:
    """Run one line of the Infra Lab shell. Everything is simulated (runtime/infralab): the learner's files are read,
    never executed, and nothing is provisioned, built or deployed."""
    try:
        return infra_run_line(infra_folder(body.folder), body.line, body.answer)
    except WorldError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/local/infra/state")
def infra_state(body: InfraStateRequest) -> dict[str, object]:
    """What the simulated world of an Infra Lab folder holds (Terraform state, subscription, Docker, cluster)."""
    try:
        return infra_state_view(infra_folder(body.folder))
    except WorldError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


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


@app.post("/api/local/import-file")
def local_import_file(body: FileImportRequest) -> object:
    """Create a NEW bronze table from Parquet or JSON content. Never overwrites; types come from the file."""
    try:
        return record_run("file_import", {}, native_command(
            {"op": "import_file", "asset": body.asset, "format": body.format, "data": body.data}))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/local/profile")
def local_profile(body: TableProfileRequest) -> object:
    """DuckDB SUMMARIZE of one catalog table (read-only)."""
    try:
        return native_command({"op": "profile_table", "asset": body.asset})
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/local/explain")
def local_explain(body: ExplainRequest) -> object:
    """EXPLAIN ANALYZE of one read-only query: it runs once on the local catalog."""
    try:
        return native_command({"op": "explain_query", "query": body.query, "dialect": body.dialect})
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
    return record_run("execute", body.model_dump(include={"language", "profile", "aqe", "dialect"}), native_command({
        "op": "execute",
        "language": body.language,
        "code": body.code,
        "notebook_id": body.notebook_id,
        "cell_id": body.cell_id,
        "output_asset": body.output_asset,
        "profile": body.profile,
        "aqe": body.aqe,
        "dialect": body.dialect,
    }))


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
    catalog_lease.check()
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
        raise HTTPException(status_code=404, detail=error.args[0]) from error
    try:
        return verify_project(project, body.steps, RunJournal(workspace_data_dir()), native_command)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
