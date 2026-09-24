from contextlib import asynccontextmanager
import os
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

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


def workspace_data_dir() -> Path:
    configured = os.getenv("DATAPASS_WORKSPACE_ROOT")
    if not configured:
        raise RuntimeError("DATAPASS_WORKSPACE_ROOT is not configured.")
    root = Path(configured).expanduser().resolve()
    if not root.is_dir():
        raise RuntimeError(f"Datapass workspace root does not exist: {root}")
    data = root / ".datapass" / "data"
    data.mkdir(parents=True, exist_ok=True)
    return data


def native_command(body: dict[str, object]) -> object:
    return kernel_manager.call(NATIVE_WORKSPACE_ID, workspace_data_dir(), body)


class PipelineCompileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source: str = Field(min_length=1, max_length=80000)


class RetailDemoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    dataset_path: str = Field(min_length=1, max_length=500)


class LocalQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    query: str = Field(min_length=1, max_length=40000)


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
        "mosaic": {"mode": "real", "engines": ["polars", "duckdb"], "spark_by_default": False},
        "practice": {"mode": "local-tests", "editors": "vscode-native"},
        "fabric_lab": {"mode": "simulation", "notebook": "fabric-inspired", "lakehouse": "duckdb-ducklake", "kernel": "sparklab", "cloud_connection": False},
        "sparklab": {"mode": "simulation", "goal": "pyspark-dataframe-concepts"},
        "dbt_lab": {"mode": "hybrid", "runner": "dbt-core", "lineage": "manifest"},
        "airflow_lab": {"mode": "simulation", "scheduler": "deterministic-local"},
        "pipeline_lab": {
            "mode": "simulation",
            "compiler": "bounded-ast-design",
            "source_execution": False,
            "activities": ["sql", "quality", "python", "polars", "dbt"],
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


@app.post("/api/demo/retail/run")
def execute_retail_demo(body: RetailDemoRequest) -> dict[str, object]:
    """Execute the local retail medallion path with Polars + DuckDB."""
    try:
        kernel_manager.restart(NATIVE_WORKSPACE_ID)
        return run_retail_demo(body.dataset_path)
    except (ValueError, FileNotFoundError, RuntimeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
