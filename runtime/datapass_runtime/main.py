from fastapi import FastAPI

app = FastAPI(title="Datapass Runtime", version="0.1.0")

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
        "pipeline_lab": {"mode": "simulation", "activities": ["notebook", "sql", "stored-procedure", "copy", "wait"]},
    }
