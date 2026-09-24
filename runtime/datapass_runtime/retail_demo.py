from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

import duckdb
import polars as pl

MAX_PREVIEW_ROWS = 50


def _workspace_root() -> Path:
    configured = os.getenv("DATAPASS_WORKSPACE_ROOT")
    if not configured:
        raise RuntimeError("DATAPASS_WORKSPACE_ROOT is not configured. Start the runtime from an open VS Code workspace.")
    root = Path(configured).expanduser().resolve()
    if not root.is_dir():
        raise RuntimeError(f"Datapass workspace root does not exist: {root}")
    return root


def _workspace_file(relative_path: str) -> Path:
    normalized = relative_path.replace("\\", "/").strip()
    posix = PurePosixPath(normalized)
    if (
        not normalized
        or posix.is_absolute()
        or any(part in {"", ".", ".."} for part in posix.parts)
        or ":" in normalized
    ):
        raise ValueError("Dataset path must be a safe workspace-relative path.")
    root = _workspace_root()
    target = (root / Path(*posix.parts)).resolve()
    if not target.is_relative_to(root):
        raise ValueError("Dataset path must stay inside the active workspace.")
    return target


def run_retail_demo(dataset_path: str) -> dict[str, object]:
    source_path = _workspace_file(dataset_path)
    if not source_path.is_file():
        raise FileNotFoundError(f"Retail dataset was not found: {dataset_path}")

    root = _workspace_root()
    data_dir = root / ".datapass" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    database_path = data_dir / "workspace.duckdb"

    orders = pl.read_csv(source_path)
    expected = {"order_id", "customer_id", "order_date", "amount", "status"}
    missing = expected.difference(orders.columns)
    if missing:
        raise ValueError(f"Retail dataset is missing required columns: {', '.join(sorted(missing))}")

    silver_polars = orders.filter(
        (pl.col("amount") > 0) & (pl.col("status") == "completed")
    )
    quality = silver_polars.select(
        pl.len().alias("rows"),
        pl.col("customer_id").n_unique().alias("customers"),
        pl.col("amount").sum().alias("revenue"),
    ).to_dicts()[0]

    connection = duckdb.connect(str(database_path))
    try:
        connection.execute("CREATE SCHEMA IF NOT EXISTS bronze")
        connection.execute("CREATE SCHEMA IF NOT EXISTS silver")
        connection.execute("CREATE SCHEMA IF NOT EXISTS gold")

        connection.execute("DROP TABLE IF EXISTS bronze.orders")
        connection.execute(
            """
            CREATE TABLE bronze.orders (
                order_id VARCHAR,
                customer_id VARCHAR,
                order_date VARCHAR,
                amount DOUBLE,
                status VARCHAR
            )
            """
        )
        rows = [
            (
                str(row["order_id"]),
                str(row["customer_id"]),
                str(row["order_date"]),
                float(row["amount"]),
                str(row["status"]),
            )
            for row in orders.to_dicts()
        ]
        connection.executemany(
            "INSERT INTO bronze.orders VALUES (?, ?, ?, ?, ?)",
            rows,
        )

        connection.execute(
            """
            CREATE OR REPLACE TABLE silver.orders AS
            SELECT *
            FROM bronze.orders
            WHERE amount > 0 AND status = 'completed'
            """
        )
        connection.execute(
            """
            CREATE OR REPLACE TABLE gold.customer_revenue AS
            SELECT
                customer_id,
                COUNT(*)::BIGINT AS orders,
                SUM(amount)::DOUBLE AS revenue
            FROM silver.orders
            GROUP BY customer_id
            ORDER BY revenue DESC, customer_id
            """
        )

        bronze_count = int(connection.execute("SELECT COUNT(*) FROM bronze.orders").fetchone()[0])
        silver_count = int(connection.execute("SELECT COUNT(*) FROM silver.orders").fetchone()[0])
        gold_count = int(connection.execute("SELECT COUNT(*) FROM gold.customer_revenue").fetchone()[0])
        result = connection.execute(
            """
            SELECT customer_id, orders, revenue
            FROM gold.customer_revenue
            ORDER BY revenue DESC, customer_id
            LIMIT ?
            """,
            [MAX_PREVIEW_ROWS],
        )
        columns = [column[0] for column in result.description]
        preview = [
            dict(zip(columns, row))
            for row in result.fetchall()
        ]
    finally:
        connection.close()

    return {
        "status": "success",
        "truth": "real local DuckDB + Polars execution",
        "dataset_path": dataset_path,
        "database_path": str(database_path.relative_to(root)).replace("\\", "/"),
        "stages": [
            {"id": "source", "label": "CSV source", "rows": int(orders.height), "engine": "Polars"},
            {"id": "bronze", "label": "bronze.orders", "rows": bronze_count, "engine": "DuckDB"},
            {"id": "silver", "label": "silver.orders", "rows": silver_count, "engine": "DuckDB"},
            {"id": "gold", "label": "gold.customer_revenue", "rows": gold_count, "engine": "DuckDB"},
        ],
        "polars_quality": {
            "rows": int(quality["rows"]),
            "customers": int(quality["customers"]),
            "revenue": float(quality["revenue"] or 0),
        },
        "preview": {
            "columns": columns,
            "rows": preview,
            "truncated": gold_count > MAX_PREVIEW_ROWS,
        },
    }
