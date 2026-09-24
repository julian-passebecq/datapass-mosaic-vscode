from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .pipeline_compiler import compile_response
from .retail_demo import run_retail_demo

app = FastAPI(title="Datapass Runtime", version="0.1.0")


class PipelineCompileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source: str = Field(min_length=1, max_length=80000)


class RetailDemoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    dataset_path: str = Field(min_length=1, max_length=500)


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


@app.post("/api/pipeline/compile")
def compile_pipeline(body: PipelineCompileRequest) -> dict[str, object]:
    """Compile the bounded pipeline DSL into design IR without executing source."""
    return compile_response(body.source)


@app.post("/api/demo/retail/run")
def execute_retail_demo(body: RetailDemoRequest) -> dict[str, object]:
    """Execute the local retail medallion path with Polars + DuckDB."""
    try:
        return run_retail_demo(body.dataset_path)
    except (ValueError, FileNotFoundError, RuntimeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
