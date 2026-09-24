from __future__ import annotations

import time
import uuid
from typing import Callable

from .pipeline_compiler import compile_pipeline, topological

DBT_NOT_WIRED = (
    "Not executed: the Pipeline Lab dbt activity is declared by the design compiler but is not wired "
    "to dbt Core. Nothing was run and no success is reported. Use dbt Lab for real dbt Core execution."
)


def run_native_pipeline(
    source: str,
    command: Callable[[dict[str, object]], object],
) -> dict[str, object]:
    """Execute the bounded pipeline DSL against the shared native kernel.

    This adapter deliberately reuses the canonical compiler and kernel. It does
    not eval/exec the Python-like pipeline source.
    """
    ir = compile_pipeline(source)
    ordered = topological(ir)
    tasks = {task["id"]: task for task in ir["tasks"]}
    parents: dict[str, set[str]] = {task_id: set() for task_id in tasks}
    for edge in ir["edges"]:
        parents[edge["target"]].add(edge["source"])

    results: dict[str, dict[str, object]] = {}
    run_rows: list[dict[str, object]] = []

    for task_id in ordered:
        task = tasks[task_id]
        blocked = [parent for parent in parents[task_id] if results[parent]["status"] != "success"]
        if blocked:
            row = {
                "id": task_id,
                "kind": task["kind"],
                "status": "skipped",
                "attempts": 0,
                "elapsed_ms": 0.0,
                "error": f"Skipped because upstream task(s) failed: {', '.join(sorted(blocked))}",
                "result": None,
            }
            results[task_id] = row
            run_rows.append(row)
            continue

        if task["kind"] == "dbt":
            # Deterministically unsupported: fail once, never burn retries on it.
            row = {
                "id": task_id,
                "kind": task["kind"],
                "status": "failed",
                "attempts": 1,
                "elapsed_ms": 0.0,
                "error": DBT_NOT_WIRED,
                "result": None,
            }
            results[task_id] = row
            run_rows.append(row)
            continue

        attempts = 0
        last_error: str | None = None
        result: object | None = None
        started = time.perf_counter()

        while attempts <= int(task["retries"]):
            attempts += 1
            try:
                kind = str(task["kind"])
                if kind == "quality":
                    response = command({"op": "read_query", "query": task["source"]})
                    payload = response if isinstance(response, dict) else {}
                    query_result = payload.get("result", {}) if isinstance(payload, dict) else {}
                    rows = query_result.get("rows", []) if isinstance(query_result, dict) else []
                    if rows:
                        raise ValueError(f"Quality query returned {len(rows)} failing row(s).")
                    result = query_result
                elif kind in {"sql", "python", "polars"}:
                    response = command({
                        "op": "execute",
                        "language": kind,
                        "code": task["source"],
                        "notebook_id": f"pipeline-{ir['id']}",
                        "cell_id": task_id,
                        "output_asset": None,
                        "profile": "generic_8x8",
                        "aqe": True,
                    })
                    if not isinstance(response, dict):
                        raise RuntimeError("Kernel returned an invalid task response.")
                    if response.get("status") != "success":
                        error = response.get("error")
                        message = error.get("message") if isinstance(error, dict) else "Task execution failed."
                        raise RuntimeError(str(message))
                    result = response.get("result")
                else:
                    raise ValueError(f"Unsupported pipeline activity: {kind}")
                last_error = None
                break
            except Exception as error:
                last_error = str(error)
                if attempts <= int(task["retries"]) and float(task["retry_delay"]) > 0:
                    time.sleep(float(task["retry_delay"]))

        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        row = {
            "id": task_id,
            "kind": task["kind"],
            "status": "failed" if last_error is not None else "success",
            "attempts": attempts,
            "elapsed_ms": elapsed_ms,
            "error": last_error,
            "result": result,
        }
        results[task_id] = row
        run_rows.append(row)

    status = "success" if all(row["status"] == "success" for row in run_rows) else "failed"
    return {
        "run_id": uuid.uuid4().hex,
        "pipeline_id": ir["id"],
        "status": status,
        "truth": "real local shared-kernel execution; scheduling metadata is not a scheduler",
        "tasks": run_rows,
    }
