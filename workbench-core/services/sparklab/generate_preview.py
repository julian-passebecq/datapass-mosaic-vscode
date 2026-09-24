"""Generate the compact static SparkLab preview used by the offline UI.

The preview is derived from the same runtime code and truth packs as the API.
Keeping it generated prevents the standalone/reference UI from drifting away
from the authored virtual runtime after cost/scheduler changes.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.sparklab.cost import price_job
from services.sparklab.runtime import (
    JobRun,
    load_cluster_profiles,
    simulate_retail_job,
    simulate_retail_skew_job,
    simulate_workspace,
)

ROOT = Path(__file__).resolve().parent
JOIN_PACK = ROOT / "exercises" / "retail_broadcast_join_03.json"
SKEW_PACK = ROOT / "exercises" / "retail_customer_skew_04.json"
CLUSTERS = ROOT / "cluster_profiles.json"
OUTPUT_JSON = ROOT / "runtime_preview.json"
OUTPUT_TS = ROOT.parents[1] / "src" / "runtimePreview.ts"


def _stage(stage: Any) -> dict[str, Any]:
    return {
        "id": stage.stage_id,
        "name": stage.name,
        "tasks": len(stage.tasks),
        "workers": stage.workers,
        "slots": stage.slots,
        "duration_s": stage.duration_s,
        "spill_gb": stage.spill_gb,
        "max_task_s": stage.max_task_s,
        "p50_task_s": stage.p50_task_s,
        "p95_task_s": stage.p95_task_s,
        "max_partition_mb": stage.max_partition_mb,
        "skewed_tasks": stage.skewed_tasks,
        "notes": stage.notes,
    }


def _job(job: JobRun, profile: Any) -> dict[str, Any]:
    return {
        "duration_s": job.total_duration_s,
        "core_hours": job.core_hours,
        "worker_core_hours": job.worker_core_hours,
        "driver_core_hours": job.driver_core_hours,
        "task_core_hours": job.task_core_hours,
        "cluster_utilization_pct": job.cluster_utilization_pct,
        "memory_gb_hours": job.memory_gb_hours,
        "driver_memory_gb_hours": job.driver_memory_gb_hours,
        "node_hours": job.node_hours,
        "worker_node_hours": job.worker_node_hours,
        "shuffle_gb": job.shuffle_gb,
        "spill_gb": job.spill_gb,
        "plan_decision": job.plan_decision,
        "cost": price_job(job, profile),
        "stages": [_stage(stage) for stage in job.stages],
    }


def build_preview() -> dict[str, Any]:
    join_pack = json.loads(JOIN_PACK.read_text(encoding="utf-8"))
    skew_pack = json.loads(SKEW_PACK.read_text(encoding="utf-8"))
    profiles = load_cluster_profiles(str(CLUSTERS))
    out: dict[str, Any] = {"profiles": {}, "workspace": simulate_workspace(128)}
    for key, profile in profiles.items():
        baseline = simulate_retail_job(join_pack, profile, aqe_enabled=True, broadcast=False)
        optimized = simulate_retail_job(join_pack, profile, aqe_enabled=True, broadcast=True)
        skew = simulate_retail_skew_job(skew_pack, profile, aqe_enabled=True)
        out["profiles"][key] = {
            "baseline": _job(baseline, profile),
            "optimized": _job(optimized, profile),
            "skew": _job(skew, profile),
        }
    return out


def write_preview() -> dict[str, Any]:
    preview = build_preview()
    rendered = json.dumps(preview, indent=2, sort_keys=False)
    OUTPUT_JSON.write_text(rendered + "\n", encoding="utf-8")
    OUTPUT_TS.write_text("export const runtimePreview = " + rendered + " as const\n", encoding="utf-8")
    return preview


if __name__ == "__main__":
    write_preview()
