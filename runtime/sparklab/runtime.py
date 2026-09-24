"""Deterministic virtual Spark runtime used by SparkLab.

The runtime does not start JVM executors. It schedules mathematical tasks over
case-study evidence so the learner can reason about stages, shuffle, skew,
AQE, memory pressure, capacity and cost without paid distributed compute.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from heapq import heappop, heappush
from math import ceil
from statistics import median as statistics_median
from typing import Any


@dataclass(frozen=True)
class ClusterProfile:
    id: str
    name: str
    min_workers: int
    max_workers: int
    cores_per_worker: int
    memory_gb_per_worker: float
    driver_cores: int
    driver_memory_gb: float
    scan_mb_s_per_core: float
    shuffle_mb_s_per_core: float
    disk_mb_s_per_worker: float
    dynamic_allocation: bool = True
    cold_start_seconds: float = 0.0
    fabric_cu_per_vcore_hour: float | None = None
    dbu_equivalent_per_node_hour: float | None = None
    schema_version: int = 1
    default_partitions: int = 64
    shuffle_partitions: int = 200
    broadcast_threshold_mb: float = 10.0
    aqe_default: bool = True
    advisory_partition_mb: float = 64.0
    scheduler_overhead_s: float = 0.08
    credits_per_core_hour: float = 1.0
    tags: tuple[str, ...] = ('balanced',)

    def contract(self) -> dict[str, Any]:
        return {**asdict(self), 'max_cores': self.max_cores,
                'executor_count': self.max_workers, 'executor_cores': self.cores_per_worker,
                'executor_memory_gb': self.memory_gb_per_worker,
                'total_virtual_cores': self.max_cores,
                'truth': 'Fictional teaching profile; no vendor capacity or billing parity'}

    @property
    def max_cores(self) -> int:
        return self.max_workers * self.cores_per_worker


@dataclass
class TaskRun:
    task_id: int
    partition_mb: float
    duration_s: float
    start_s: float
    finish_s: float
    worker_slot: int
    spill_mb: float = 0.0
    skewed: bool = False


@dataclass
class StageRun:
    stage_id: int
    name: str
    operator: str
    input_gb: float
    shuffle_read_gb: float
    shuffle_write_gb: float
    workers: int
    slots: int
    duration_s: float
    spill_gb: float
    tasks: list[TaskRun]
    notes: list[str]
    max_task_s: float
    p50_task_s: float
    p95_task_s: float
    max_partition_mb: float
    skewed_tasks: int


@dataclass
class JobRun:
    profile_id: str
    aqe_enabled: bool
    stages: list[StageRun]
    total_duration_s: float
    core_hours: float
    worker_core_hours: float
    driver_core_hours: float
    task_core_hours: float
    cluster_utilization_pct: float
    memory_gb_hours: float
    driver_memory_gb_hours: float
    node_hours: float
    worker_node_hours: float
    shuffle_gb: float
    spill_gb: float
    truth_confidence: dict[str, int]
    plan_decision: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_SPARK = {
    "shuffle_partitions": 200,
    "auto_broadcast_threshold_mb": 10.0,
    "adaptive_enabled": True,
    "advisory_partition_mb": 64.0,
    "skew_factor": 5.0,
    "skew_threshold_mb": 256.0,
}


def normalized_partitions(
    total_mb: float,
    count: int,
    median_mb: float,
    largest_mb: float,
    hot_index: int = 143,
) -> list[float]:
    """Build a deterministic partition vector matching the supplied evidence.

    Unlike the V0.7 generator, this construction preserves the requested total,
    median and largest partition instead of rescaling the median away. That lets
    downstream skew metrics remain internally consistent with the truth pack.
    """
    if count <= 1:
        return [round(total_mb, 3)]
    if count < 3:
        values = [median_mb, largest_mb]
        scale = total_mb / sum(values) if sum(values) else 1.0
        return [round(v * scale, 3) for v in values[:count]]

    hot_slot = hot_index % count
    median_count = 2 if count % 2 == 0 else 1
    lower_count = count // 2 - (1 if count % 2 == 0 else 0)
    upper_count = count - lower_count - median_count - 1  # hot partition occupies one upper slot

    # Keep every lower partition below the target median. For even partition
    # counts two exact median values make statistics.median() equal the supplied
    # truth-pack median rather than averaging a lower value with the median.
    lower = [median_mb * (0.68 + ((i * 17) % 29) / 100.0) for i in range(lower_count)]
    lower = [min(v, median_mb * 0.985) for v in lower]
    medians = [median_mb] * median_count

    remaining_target = total_mb - sum(lower) - sum(medians) - largest_mb
    if upper_count > 0:
        base = [1.04 + ((i * 19) % 37) / 100.0 for i in range(upper_count)]
        base_sum = sum(base)
        upper = [remaining_target * f / base_sum for f in base]
        if min(upper, default=median_mb + 1) <= median_mb:
            upper = [remaining_target / upper_count for _ in range(upper_count)]
    else:
        upper = []

    # Statistical values are built first; only the known hot partition is pinned
    # to a physical index. All other positions are irrelevant to the evidence.
    values = lower + medians + upper
    values.insert(min(hot_slot, len(values)), largest_mb)

    # Floating-point correction on one non-hot upper partition keeps total exact.
    delta = total_mb - sum(values)
    correction_candidates = [i for i, v in enumerate(values) if i != hot_slot and v > median_mb and v < largest_mb]
    if correction_candidates:
        values[correction_candidates[-1]] += delta
    else:
        values[-1] += delta
    return [round(v, 3) for v in values]


def partition_evidence(partitions: list[float]) -> dict[str, float]:
    if not partitions:
        return {"total_mb": 0.0, "median_mb": 0.0, "largest_mb": 0.0, "skew_ratio": 0.0}
    med = statistics_median(partitions)
    largest = max(partitions)
    return {
        "total_mb": round(sum(partitions), 3),
        "median_mb": round(med, 3),
        "largest_mb": round(largest, 3),
        "skew_ratio": round(largest / med, 3) if med else 0.0,
    }


def _aqe_split(partitions: list[float], cfg: dict[str, Any]) -> tuple[list[float], list[str]]:
    if not cfg.get("adaptive_enabled", True) or not partitions:
        return partitions, []
    med = statistics_median(partitions)
    threshold = max(float(cfg.get("skew_threshold_mb", 256.0)), med * float(cfg.get("skew_factor", 5.0)))
    advisory = float(cfg.get("advisory_partition_mb", 64.0))
    out: list[float] = []
    notes: list[str] = []
    for p in partitions:
        if p > threshold:
            n = max(2, ceil(p / advisory))
            out.extend([p / n] * n)
            notes.append(f"AQE split {p:.0f} MB skewed partition into {n} ~{p/n:.0f} MB tasks")
        else:
            out.append(p)
    return out, notes


def _task_duration(
    partition_mb: float,
    operator: str,
    profile: ClusterProfile,
    memory_per_task_gb: float,
) -> tuple[float, float]:
    if operator == "scan":
        throughput = profile.scan_mb_s_per_core
        cpu_factor = 1.0
    elif operator in {"shuffle_join", "aggregate", "window"}:
        throughput = profile.shuffle_mb_s_per_core
        cpu_factor = 1.35 if operator == "shuffle_join" else 1.2
    else:
        throughput = profile.scan_mb_s_per_core
        cpu_factor = 1.05
    base = 0.22 + (partition_mb / max(throughput, 1.0)) * cpu_factor
    working_set_gb = partition_mb / 1024 * (1.65 if operator in {"aggregate", "shuffle_join", "window"} else 0.35)
    spill_gb = max(0.0, working_set_gb - memory_per_task_gb)
    spill_mb = spill_gb * 1024
    if spill_mb:
        base += spill_mb / max(profile.disk_mb_s_per_worker, 1.0)
    return round(base, 4), round(spill_mb, 3)


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, ceil(q * len(ordered)) - 1))
    return ordered[index]


def _schedule_stage(
    stage_id: int,
    name: str,
    operator: str,
    partitions_mb: list[float],
    profile: ClusterProfile,
    shuffle_read_gb: float = 0.0,
    shuffle_write_gb: float = 0.0,
    notes: list[str] | None = None,
) -> StageRun:
    requested_workers = max(profile.min_workers, ceil(len(partitions_mb) / max(profile.cores_per_worker * 2, 1)))
    workers = min(profile.max_workers, requested_workers) if profile.dynamic_allocation else profile.max_workers
    slots = max(1, workers * profile.cores_per_worker)
    slot_heap = [(0.0, slot) for slot in range(slots)]
    task_memory_gb = profile.memory_gb_per_worker / max(profile.cores_per_worker, 1) * 0.62
    med = statistics_median(partitions_mb) if partitions_mb else 0.0
    tasks: list[TaskRun] = []
    for i, mb in enumerate(partitions_mb):
        available, slot = heappop(slot_heap)
        duration, spill_mb = _task_duration(mb, operator, profile, task_memory_gb)
        start = available
        finish = start + duration
        task = TaskRun(
            i,
            round(mb, 3),
            duration,
            round(start, 4),
            round(finish, 4),
            slot,
            spill_mb,
            bool(med and mb >= med * 5),
        )
        tasks.append(task)
        heappush(slot_heap, (finish, slot))
    duration = max((t.finish_s for t in tasks), default=0.0)
    spill_gb = sum(t.spill_mb for t in tasks) / 1024
    durations = [t.duration_s for t in tasks]
    return StageRun(
        stage_id=stage_id,
        name=name,
        operator=operator,
        input_gb=round(sum(partitions_mb) / 1024, 3),
        shuffle_read_gb=round(shuffle_read_gb, 3),
        shuffle_write_gb=round(shuffle_write_gb, 3),
        workers=workers,
        slots=slots,
        duration_s=round(duration, 3),
        spill_gb=round(spill_gb, 3),
        tasks=tasks,
        notes=list(notes or []),
        max_task_s=round(max(durations, default=0.0), 3),
        p50_task_s=round(_percentile(durations, 0.50), 3),
        p95_task_s=round(_percentile(durations, 0.95), 3),
        max_partition_mb=round(max(partitions_mb, default=0.0), 3),
        skewed_tasks=sum(1 for t in tasks if t.skewed),
    )


def _finalize_job(
    profile: ClusterProfile,
    aqe_enabled: bool,
    stages: list[StageRun],
    plan_decision: dict[str, Any],
) -> JobRun:
    stage_seconds = sum(s.duration_s for s in stages)
    total_s = stage_seconds + profile.cold_start_seconds

    # Keep billed/allocated compute separate from useful task work. Spark-style
    # capacity is paid while executor slots are allocated, including idle tail
    # time in the final wave of a stage. The driver is also a live compute node
    # for the whole modeled job, including cold start.
    worker_core_hours = sum(s.duration_s * s.slots for s in stages) / 3600
    task_core_hours = sum(t.duration_s for s in stages for t in s.tasks) / 3600
    driver_core_hours = total_s * profile.driver_cores / 3600
    core_hours = worker_core_hours + driver_core_hours
    utilization = (task_core_hours / worker_core_hours * 100.0) if worker_core_hours else 0.0

    worker_memory_gb_hours = sum(s.duration_s * s.workers * profile.memory_gb_per_worker for s in stages) / 3600
    driver_memory_gb_hours = total_s * profile.driver_memory_gb / 3600
    memory_gb_hours = worker_memory_gb_hours + driver_memory_gb_hours

    worker_node_hours = sum(s.duration_s * s.workers for s in stages) / 3600
    driver_node_hours = total_s / 3600
    node_hours = worker_node_hours + driver_node_hours

    shuffle_gb = sum(s.shuffle_write_gb for s in stages)
    spill_gb = sum(s.spill_gb for s in stages)
    return JobRun(
        profile.id,
        aqe_enabled,
        stages,
        round(total_s, 3),
        round(core_hours, 4),
        round(worker_core_hours, 4),
        round(driver_core_hours, 4),
        round(task_core_hours, 4),
        round(utilization, 1),
        round(memory_gb_hours, 4),
        round(driver_memory_gb_hours, 4),
        round(node_hours, 4),
        round(worker_node_hours, 4),
        round(shuffle_gb, 3),
        round(spill_gb, 3),
        {
            "semantic_result": 100,
            "schema": 100,
            "partition_distribution": 97,
            "join_strategy": 97,
            "shuffle_bytes": 93,
            "task_runtime": 78,
            "cloud_cost": 74,
        },
        plan_decision,
    )


def _retail_partitions(pack: dict[str, Any]) -> tuple[list[float], list[float], dict[str, Any]]:
    stats = pack["statistics"]
    input_mb = float(stats["fact_bytes_gb"]) * 1024
    shuffle_parts = normalized_partitions(
        input_mb,
        int(stats["shuffle_partitions"]),
        float(stats["median_partition_mb"]),
        float(stats["largest_partition_mb"]),
        int(stats.get("hot_partition", 143)),
    )
    scan_median = input_mb / float(stats["source_files"])
    scan_parts = normalized_partitions(
        input_mb,
        int(stats["source_files"]),
        scan_median,
        max(scan_median * 1.6, 1.0),
        16,
    )
    return shuffle_parts, scan_parts, stats


def simulate_retail_job(
    pack: dict[str, Any],
    profile: ClusterProfile,
    aqe_enabled: bool = True,
    broadcast: bool = True,
) -> JobRun:
    """Retail join exercise: explicit broadcast vs shuffle join."""
    parts, scan_parts, stats = _retail_partitions(pack)
    cfg = dict(DEFAULT_SPARK)
    cfg.update(pack.get("spark_defaults", {}))
    cfg["adaptive_enabled"] = aqe_enabled

    stages: list[StageRun] = [_schedule_stage(1, "Parquet scan + filter", "scan", scan_parts, profile)]
    if broadcast:
        stages.append(
            _schedule_stage(
                2,
                "BroadcastHashJoin",
                "broadcast_join",
                scan_parts,
                profile,
                notes=[
                    f"Explicit broadcast build side: {stats['dimension_bytes_mb']} MB; fact-side join shuffle avoided"
                ],
            )
        )
        agg_parts, aqe_notes = _aqe_split(parts, cfg)
        stages.append(
            _schedule_stage(
                3,
                "Exchange + HashAggregate(customer_id)",
                "aggregate",
                agg_parts,
                profile,
                shuffle_read_gb=float(stats["fact_bytes_gb"]),
                shuffle_write_gb=float(stats["fact_bytes_gb"]),
                notes=aqe_notes,
            )
        )
        plan = {
            "initial_join": "BroadcastHashJoin",
            "final_join": "BroadcastHashJoin",
            "reason": "explicit broadcast hint",
            "join_shuffle_avoided": True,
        }
    else:
        dim_gb = float(stats["dimension_bytes_mb"]) / 1024
        join_parts, aqe_notes = _aqe_split(parts, cfg)
        stages.append(
            _schedule_stage(
                2,
                "SortMergeJoin + Exchange",
                "shuffle_join",
                join_parts,
                profile,
                shuffle_read_gb=float(stats["fact_bytes_gb"]) + dim_gb,
                shuffle_write_gb=float(stats["fact_bytes_gb"]) + dim_gb,
                notes=aqe_notes + ["Catalog statistics are intentionally unavailable in this exercise; no static auto-broadcast"],
            )
        )
        agg_parts, agg_notes = _aqe_split(parts, cfg)
        stages.append(
            _schedule_stage(
                3,
                "Exchange + HashAggregate(customer_id)",
                "aggregate",
                agg_parts,
                profile,
                shuffle_read_gb=float(stats["fact_bytes_gb"]),
                shuffle_write_gb=float(stats["fact_bytes_gb"]),
                notes=agg_notes,
            )
        )
        plan = {
            "initial_join": "SortMergeJoin",
            "final_join": "SortMergeJoin",
            "reason": "no broadcast hint and no catalog size statistics in this calibrated scenario",
            "join_shuffle_avoided": False,
        }
    return _finalize_job(profile, aqe_enabled, stages, plan)


def simulate_retail_skew_job(
    pack: dict[str, Any],
    profile: ClusterProfile,
    aqe_enabled: bool = True,
) -> JobRun:
    """Retail skew exercise: scan + customer-key aggregation with AQE evidence."""
    parts, scan_parts, stats = _retail_partitions(pack)
    cfg = dict(DEFAULT_SPARK)
    cfg.update(pack.get("spark_defaults", {}))
    cfg["adaptive_enabled"] = aqe_enabled
    agg_parts, aqe_notes = _aqe_split(parts, cfg)
    stages = [
        _schedule_stage(1, "Parquet scan + filter", "scan", scan_parts, profile),
        _schedule_stage(
            2,
            "Exchange + HashAggregate(customer_id)",
            "aggregate",
            agg_parts,
            profile,
            shuffle_read_gb=float(stats["fact_bytes_gb"]),
            shuffle_write_gb=float(stats["fact_bytes_gb"]),
            notes=aqe_notes + [f"Known hot key: {stats.get('hot_key', 'n/a')}"],
        ),
    ]
    plan = {
        "initial_join": None,
        "final_join": None,
        "reason": "aggregation-only skew exercise",
        "join_shuffle_avoided": None,
        "aqe_skew_split": bool(aqe_notes),
    }
    return _finalize_job(profile, aqe_enabled, stages, plan)



def _finance_window_characteristics(dataframe: Any) -> dict[str, Any]:
    expressions: list[str] = []
    for op in getattr(dataframe, "ops", []):
        if op.kind == "withColumn":
            sql = str(op.detail.get("expr").sql)
            if " OVER (" in sql:
                expressions.append(sql)
    combined = " ".join(expressions)
    return {
        "has_window": bool(expressions),
        "has_partition": "PARTITION BY" in combined,
        "expected_partition": 'PARTITION BY "account_id"' in combined,
        "expected_order": 'ORDER BY "transaction_ts"' in combined,
        "explicit_rows_frame": "ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW" in combined,
        "has_lag": 'LAG("amount"' in combined,
        "has_running_sum": 'SUM("amount")' in combined,
    }


def simulate_finance_window_job(
    pack: dict[str, Any],
    profile: ClusterProfile,
    dataframe: Any,
    aqe_enabled: bool = True,
) -> JobRun:
    """Finance ordered-window exercise grounded in the known account distribution.

    Unlike a skewed join, one account's ordered window cannot be split across
    independent tasks without changing semantics. AQE therefore does not split
    the hot account partition in this teaching model.
    """
    stats = pack["statistics"]
    input_mb = float(stats["fact_bytes_gb"]) * 1024
    scan_median = input_mb / float(stats["source_files"])
    scan_parts = normalized_partitions(
        input_mb,
        int(stats["source_files"]),
        scan_median,
        max(scan_median * 1.8, 1.0),
        17,
    )
    stages: list[StageRun] = [
        _schedule_stage(1, "Parquet scan", "scan", scan_parts, profile, notes=["Partitioned transaction Parquet input"])
    ]
    shape = _finance_window_characteristics(dataframe)

    if not shape["has_window"]:
        plan = {
            "window_present": False,
            "window_partitioned": False,
            "window_ordered": False,
            "aqe_skew_split": False,
            "reason": "submitted plan contains no supported window expression",
        }
        return _finalize_job(profile, aqe_enabled, stages, plan)

    if not shape["has_partition"]:
        # Spark warns and moves a global ordered window to one partition. This is
        # intentionally painful in the simulator because it is a classic notebook
        # anti-pattern for large datasets.
        global_parts = [input_mb]
        stages.append(
            _schedule_stage(
                2,
                "SinglePartition Exchange + Sort + Window",
                "window",
                global_parts,
                profile,
                shuffle_read_gb=float(stats["fact_bytes_gb"]),
                shuffle_write_gb=float(stats["fact_bytes_gb"]),
                notes=["No PARTITION BY: all rows are modeled on one executor task", "AQE cannot make a global window distributable"],
            )
        )
        plan = {
            "window_present": True,
            "window_partitioned": False,
            "window_ordered": bool(shape["expected_order"]),
            "explicit_rows_frame": bool(shape["explicit_rows_frame"]),
            "aqe_skew_split": False,
            "reason": "global ordered window collapses execution to one partition",
        }
        return _finalize_job(profile, aqe_enabled, stages, plan)

    window_parts = normalized_partitions(
        input_mb,
        int(stats["shuffle_partitions"]),
        float(stats["median_partition_mb"]),
        float(stats["largest_partition_mb"]),
        int(stats.get("hot_partition", 91)),
    )
    notes = [
        f"Known hot account key: {stats.get('hot_key', 'n/a')}",
        "Ordered windows require rows for one partition key to remain co-located",
    ]
    if aqe_enabled and max(window_parts, default=0) >= float(stats["largest_partition_mb"]):
        notes.append("AQE kept the hot account partition intact; splitting one account would change window semantics")
    if shape["expected_order"]:
        notes.append("Sort within account_id partitions by transaction_ts")
    stages.append(
        _schedule_stage(
            2,
            "Exchange(account_id) + Sort + Window",
            "window",
            window_parts,
            profile,
            shuffle_read_gb=float(stats["fact_bytes_gb"]),
            shuffle_write_gb=float(stats["fact_bytes_gb"]),
            notes=notes,
        )
    )
    plan = {
        "window_present": True,
        "window_partitioned": bool(shape["expected_partition"]),
        "window_ordered": bool(shape["expected_order"]),
        "explicit_rows_frame": bool(shape["explicit_rows_frame"]),
        "aqe_skew_split": False,
        "hot_key_splittable": False,
        "reason": "account_id window requires one account's ordered rows to stay together",
    }
    return _finalize_job(profile, aqe_enabled, stages, plan)

def simulate_workspace(capacity_cores: int = 128) -> dict[str, Any]:
    workloads = [
        {"name": "Analyst notebook", "requested_cores": 24, "duration_min": 18},
        {"name": "Nightly ETL", "requested_cores": 64, "duration_min": 31},
        {"name": "Historical backfill", "requested_cores": 64, "duration_min": 42},
    ]
    running: list[dict[str, Any]] = []
    queued: list[dict[str, Any]] = []
    used = 0
    for workload in workloads:
        if used + workload["requested_cores"] <= capacity_cores:
            running.append(workload)
            used += workload["requested_cores"]
        else:
            queued.append(workload)
    return {
        "capacity_cores": capacity_cores,
        "used_cores": used,
        "available_cores": capacity_cores - used,
        "running": running,
        "queued": queued,
    }


def load_cluster_profiles(path: str) -> dict[str, ClusterProfile]:
    import json

    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return {key: ClusterProfile(**value) for key, value in data.items()}
