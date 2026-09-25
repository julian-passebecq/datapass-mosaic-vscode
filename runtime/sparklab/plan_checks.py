"""Grade a submission's modeled Spark plan against an exercise's declared limits.

Facts come from physical.simulate_plan: exchange placement and join strategy
follow Spark's planning rules over authored input sizes. They are teaching
evidence from the SparkLab model, never Apache Spark measurements.
"""
from __future__ import annotations

from typing import Any

# rule -> (plan fact, comparison, singular noun)
RULES = {
    'max_exchanges': ('exchanges', 'at most', 'shuffle exchange'),
    'min_broadcast_joins': ('broadcast_joins', 'at least', 'broadcast join'),
    'max_shuffle_joins': ('shuffle_joins', 'at most', 'shuffle join'),
    'max_global_windows': ('global_windows', 'at most', 'window without partitionBy'),
    'max_output_partitions': ('output_partitions', 'at most', 'output partition'),
}


def _count(value: int, noun: str) -> str:
    return f"{value} {noun}" + ("" if value == 1 or noun.endswith("partitionBy") else "s")


def _exchange(detail: dict[str, Any]) -> str:
    keys = f"({', '.join(detail['keys'])})" if detail.get('keys') else ''
    return f"{detail['partitioning']}{keys} for {detail['reason']}"


def evaluate(checks: list[dict[str, Any]], facts: dict[str, Any]) -> list[dict[str, Any]]:
    results = []
    for check in checks:
        fact, bound, noun = RULES[check['rule']]
        actual = int(facts[fact])
        passed = actual <= check['value'] if bound == 'at most' else actual >= check['value']
        message = (f"SparkLab model, not Apache Spark: {_count(actual, noun)}; "
                   f"required {bound} {check['value']}.")
        details = facts.get('exchange_details') or []
        if fact == 'exchanges' and details:
            message += " Exchanges: " + "; ".join(_exchange(d) for d in details) + "."
        refused = facts.get('refused_broadcasts') or []
        if fact == 'broadcast_joins' and refused:
            sizes = ", ".join(f"{r['modeled_gb']:g} GB" for r in refused)
            message += (f" A broadcast hint on a {sizes} input was not applied: real Spark fails a broadcast "
                        "above 8 GB, so broadcast the small side.")
        results.append({'id': check['id'], 'passed': passed, 'message': message})
    return results
