"""Truth-pack graders for calibrated SparkLab exercises.

Grades are derived from the compiled relational plan plus modeled engineering
outcomes. Source text is consulted only for unsafe/unsupported driver patterns
that are intentionally outside the relational IR.
"""
from __future__ import annotations

from typing import Any

from .sparklab import DataFrame


def _common_anti_patterns(code: str, dataframe: DataFrame) -> list[str]:
    code_lower = code.lower()
    anti: list[str] = []
    if ".collect(" in code_lower or ".topandas(" in code_lower:
        anti.append("driver collection is unsafe for this large fact workload")
    for op in dataframe.ops:
        if op.kind == "repartition" and int(op.detail.get("n", 0)) == 1:
            anti.append("repartition(1) creates a single-partition bottleneck")
    return anti


def _semantic_checks(dataframe: DataFrame, require_join: bool) -> dict[str, bool]:
    sql = dataframe.sql.lower()
    checks = {
        "customer_grain": 'group by "customer_id"' in sql,
        "revenue_metric": 'sum("net_amount")' in sql,
        "order_count_metric": 'count(*)' in sql,
    }
    if require_join:
        checks["join_present"] = " join " in sql
    return checks


def _weighted_result(
    checks: dict[str, bool],
    engineering_checks: dict[str, bool],
    anti_patterns: list[str],
    performance: int,
    cost: int,
    feedback: list[str],
    semantic_verified: bool | None = None,
) -> dict[str, Any]:
    heuristic_semantic = round(100 * sum(checks.values()) / max(len(checks), 1))
    semantic = heuristic_semantic if semantic_verified is None else (100 if semantic_verified else 0)
    engineering = round(100 * sum(engineering_checks.values()) / max(len(engineering_checks), 1))
    engineering = max(0, engineering - 25 * len(anti_patterns))
    overall = round(semantic * 0.45 + engineering * 0.25 + performance * 0.20 + cost * 0.10)
    return {
        "overall": overall,
        "scores": {
            "semantic": semantic,
            "engineering": engineering,
            "performance": performance,
            "cost": cost,
        },
        "checks": {**checks, **engineering_checks, **({"fixture_result_match": semantic_verified} if semantic_verified is not None else {})},
        "anti_patterns": anti_patterns,
        "pass": semantic == 100 and engineering >= 75,
        "feedback": feedback,
    }


def _grade_broadcast(code: str, dataframe: DataFrame, simulation: dict[str, Any], pack: dict[str, Any], semantic_verified: bool | None = None) -> dict[str, Any]:
    checks = _semantic_checks(dataframe, require_join=True)
    joins = [op for op in dataframe.ops if op.kind == "join"]
    explicit_broadcast = any(bool(op.detail.get("broadcast")) for op in joins)
    fact_gb = float(pack["statistics"]["fact_bytes_gb"])
    engineering = {
        "explicit_broadcast": explicit_broadcast,
        "join_shuffle_avoided": bool(simulation.get("plan_decision", {}).get("join_shuffle_avoided")),
        "aggregation_shuffle_understood": simulation.get("shuffle_gb", 0) >= fact_gb * 0.95,
    }
    anti = _common_anti_patterns(code, dataframe)
    for op in dataframe.ops:
        if op.kind == "repartition" and not op.detail.get("keys"):
            anti.append("unjustified repartition without a business/distribution key")
    shuffle = float(simulation.get("shuffle_gb", 999))
    performance = 100 if shuffle <= fact_gb + 0.6 else 55 if shuffle <= fact_gb * 2.1 else 25
    cost = 100 if shuffle <= fact_gb + 0.6 else 65
    return _weighted_result(
        checks,
        engineering,
        anti,
        performance,
        cost,
        [
            "Correctness uses bounded fixture execution when available; plan checks remain explanatory evidence.",
            "This exercise intentionally withholds catalog size statistics so an explicit broadcast hint changes the physical plan.",
            "Broadcast removes the join shuffle; the downstream groupBy(customer_id) shuffle remains.",
        ],
        semantic_verified=semantic_verified,
    )


def _grade_skew(code: str, dataframe: DataFrame, simulation: dict[str, Any], pack: dict[str, Any], semantic_verified: bool | None = None) -> dict[str, Any]:
    checks = _semantic_checks(dataframe, require_join=False)
    engineering = {
        "aqe_skew_split_observed": bool(simulation.get("plan_decision", {}).get("aqe_skew_split")),
        "aggregation_shuffle_understood": simulation.get("shuffle_gb", 0) >= float(pack["statistics"]["fact_bytes_gb"]) * 0.95,
    }
    anti = _common_anti_patterns(code, dataframe)
    for op in dataframe.ops:
        if op.kind == "repartition":
            keys = tuple(op.detail.get("keys", ()))
            if "customer_id" in keys:
                anti.append("repartitioning by the same skewed customer_id key does not remove the hot key")
            elif not keys:
                anti.append("random repartition adds a shuffle without addressing customer-key skew")
    shuffle = float(simulation.get("shuffle_gb", 999))
    fact_gb = float(pack["statistics"]["fact_bytes_gb"])
    performance = 100 if shuffle <= fact_gb + 0.6 else 60
    cost = 100 if shuffle <= fact_gb + 0.6 else 70
    return _weighted_result(
        checks,
        engineering,
        anti,
        performance,
        cost,
        [
            f"Known truth-pack hot key: {pack['statistics'].get('hot_key', 'n/a')}.",
            "Adding workers does not remove a single hot-key partition; inspect distribution before scaling compute.",
            "AQE can split a skewed post-shuffle partition, but repartitioning by the same skewed key is not a fix.",
        ],
        semantic_verified=semantic_verified,
    )


def grade_retail(code: str, dataframe: DataFrame, simulation: dict[str, Any], pack: dict[str, Any], semantic_verified: bool | None = None) -> dict[str, Any]:
    grader = pack.get("grader", "retail_broadcast")
    if grader == "retail_broadcast":
        result = _grade_broadcast(code, dataframe, simulation, pack, semantic_verified)
    elif grader == "retail_skew":
        result = _grade_skew(code, dataframe, simulation, pack, semantic_verified)
    else:
        raise ValueError(f"Unknown Retail grader: {grader}")

    if semantic_verified is True:
        result["feedback"].insert(0, "Bounded reference-fixture execution matches the expected schema and rows.")
    elif semantic_verified is False:
        result["feedback"].insert(0, "Bounded reference-fixture execution does not match the expected semantic result.")
    return result


def grade_finance(code: str, dataframe: DataFrame, simulation: dict[str, Any], pack: dict[str, Any], semantic_verified: bool | None = None) -> dict[str, Any]:
    sql = dataframe.sql
    upper = sql.upper()
    checks = {
        "previous_amount_metric": 'LAG("amount"' in sql,
        "running_net_metric": 'SUM("amount")' in sql,
    }
    plan = simulation.get("plan_decision", {})
    engineering = {
        "partition_by_account": bool(plan.get("window_partitioned")),
        "order_by_transaction_ts": bool(plan.get("window_ordered")),
        "explicit_rows_frame": bool(plan.get("explicit_rows_frame")),
        "hot_key_not_fake_split": plan.get("hot_key_splittable") is False if plan.get("window_partitioned") else False,
    }
    anti = _common_anti_patterns(code, dataframe)
    if " OVER (ORDER BY" in upper or (" OVER (" in upper and "PARTITION BY" not in upper):
        anti.append("global ordered window moves the full dataset to one partition")
    for op in dataframe.ops:
        if op.kind == "repartition" and int(op.detail.get("n", 0)) == 1:
            if "repartition(1) creates a single-partition bottleneck" not in anti:
                anti.append("repartition(1) creates a single-partition bottleneck")

    fact_gb = float(pack["statistics"]["fact_bytes_gb"])
    shuffle = float(simulation.get("shuffle_gb", 0.0))
    stages = simulation.get("stages", [])
    max_partition = max((float(stage.get("max_partition_mb", 0.0)) for stage in stages), default=0.0)
    global_window = bool(plan.get("window_present")) and not bool(plan.get("window_partitioned"))
    performance = 20 if global_window else 100 if shuffle <= fact_gb + 0.3 else 65
    cost = 30 if global_window else 100 if shuffle <= fact_gb + 0.3 else 70
    result = _weighted_result(
        checks,
        engineering,
        anti,
        performance,
        cost,
        [
            "Correctness is checked on a bounded ordered-account fixture when available.",
            "The account_id window requires one shuffle plus an in-partition sort.",
            f"Known post-shuffle hot account evidence: {pack['statistics'].get('hot_key', 'n/a')} (largest modeled partition {max_partition:.0f} MB).",
            "AQE cannot split one account's ordered window across independent tasks without changing lag/running-sum semantics.",
        ],
        semantic_verified=semantic_verified,
    )
    if semantic_verified is True:
        result["feedback"].insert(0, "Bounded finance fixture matches the expected lag and running-net rows.")
    elif semantic_verified is False:
        result["feedback"].insert(0, "Bounded finance fixture does not match the expected ordered-window result.")
    return result
