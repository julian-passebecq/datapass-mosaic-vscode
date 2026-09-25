"""Physical model of a table: rows per distribution, partitions and columnstore rowgroups, from the lab data.

- HASH: every key value that repeats in the lab rows and holds at least 1% of them
  is placed on one of the 60 distributions by a stable hash of its text (sha256,
  mod 60), as a hash distribution places each value; NULL keys all share one
  distribution. Values seen once, and rarer values, are assumed to spread evenly:
  at scale each stands for many distinct values.
  This reproduces the causes of skew named by the Synapse guidance: few distinct
  values, NULLs, and heavy hitters. Placement is the lab's, not Synapse's internal
  hash; the pattern is what matters.
- ROUND_ROBIN spreads rows evenly; REPLICATE keeps a full copy on every compute node.
- Rows at scale are the lab rows times the table's scale factor.
- Partitions: rows per partition from the data (NULLs go to partition 1), then rows
  per distribution and partition at scale, compared with the columnstore guidance
  of at least 1,000,000 rows per distribution and partition.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Protocol

from .model import DISTRIBUTIONS, ROWGROUP_TARGET, Partitioning, TableDesign

HEAVY_SHARE = 0.01


class Reader(Protocol):
    def fetch(self, sql: str) -> list[tuple[Any, ...]]: ...
    def columns(self, name: str) -> list[tuple[str, str]]: ...


def placement(text: str | None) -> int:
    key = '\x00NULL' if text is None else text
    return int(hashlib.sha256(key.encode('utf-8')).hexdigest(), 16) % DISTRIBUTIONS


def _key_sql(columns: list[str]) -> str:
    quoted = [f'"{c}"' for c in columns]
    if len(quoted) == 1:
        return f"CAST({quoted[0]} AS VARCHAR)"
    null_all = ' AND '.join(f"{q} IS NULL" for q in quoted)
    joined = ", ".join(f"COALESCE(CAST({q} AS VARCHAR), '<NULL>')" for q in quoted)
    return f"CASE WHEN {null_all} THEN NULL ELSE concat_ws('|', {joined}) END"


@dataclass
class DistributionStats:
    table: str
    distribution: str
    rows: int
    rows_at_scale: float
    shares: list[float]  # share of the rows on each of the 60 distributions (empty for REPLICATE)
    distinct_keys: int | None
    null_share: float
    heavy_values: list[tuple[str, float]]

    @property
    def max_share(self) -> float:
        return max(self.shares) if self.shares else 0.0

    @property
    def min_share(self) -> float:
        return min(self.shares) if self.shares else 0.0

    @property
    def skew_pct(self) -> float:
        """(max - min) / max rows per distribution, the check the Synapse guidance uses (10% is the alert)."""
        if not self.shares or self.max_share == 0:
            return 0.0
        return round((self.max_share - self.min_share) / self.max_share * 100, 1)

    @property
    def empty_distributions(self) -> int:
        return sum(1 for s in self.shares if s <= 0)


def distribution_stats(reader: Reader, design: TableDesign, rows: int, scale: float) -> DistributionStats:
    name = design.name
    if design.distribution == 'REPLICATE':
        return DistributionStats(name, 'REPLICATE', rows, rows * scale, [], None, 0.0, [])
    if design.distribution != 'HASH' or rows == 0:
        shares = [1 / DISTRIBUTIONS] * DISTRIBUTIONS if rows else [0.0] * DISTRIBUTIONS
        return DistributionStats(name, design.distribution, rows, rows * scale, shares, None, 0.0, [])
    key = _key_sql(design.hash_columns)
    total, distinct, nulls = reader.fetch(
        f"SELECT COUNT(*), COUNT(DISTINCT k), COUNT(*) - COUNT(k) FROM (SELECT {key} AS k FROM {name}) AS keys")[0]
    heavy = reader.fetch(
        f"SELECT k, COUNT(*) AS n FROM (SELECT {key} AS k FROM {name}) AS keys WHERE k IS NOT NULL "
        f"GROUP BY k HAVING COUNT(*) >= 2 AND COUNT(*) >= {HEAVY_SHARE} * {int(total)} ORDER BY n DESC, k LIMIT 101")
    shares = [0.0] * DISTRIBUTIONS
    heavy_values = [(str(value), count / total) for value, count in heavy]
    for value, share in heavy_values:
        shares[placement(value)] += share
    null_share = nulls / total
    if null_share:
        shares[placement(None)] += null_share
    tail = max(0.0, 1.0 - sum(s for _, s in heavy_values) - null_share)
    shares = [s + tail / DISTRIBUTIONS for s in shares]
    return DistributionStats(name, 'HASH', rows, rows * scale, shares, int(distinct), null_share, heavy_values)


@dataclass
class PartitionStats:
    number: int
    lower: Any
    upper: Any
    rows: int
    rows_at_scale: float
    rows_per_distribution: float | None
    columnstore_ok: bool | None


def boundary_sql(value: Any, column_type: str) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return repr(value)
    text = "'" + str(value).replace("'", "''") + "'"
    return f"CAST({text} AS {column_type})"


def partition_range(partition: Partitioning, number: int) -> tuple[Any, Any]:
    """(lower, upper) boundary values of a partition (None = unbounded). RIGHT: lower <= v < upper; LEFT: lower < v <= upper."""
    lower = partition.boundaries[number - 2] if number >= 2 else None
    upper = partition.boundaries[number - 1] if number <= len(partition.boundaries) else None
    return lower, upper


def partition_number_sql(partition: Partitioning, column_type: str) -> str:
    """SQL expression giving each row's partition number (NULLs in partition 1, as in SQL Server)."""
    if not partition.boundaries:
        return '1'
    compare = '>=' if partition.range == 'RIGHT' else '>'
    terms = ' + '.join(f"COALESCE(CAST(\"{partition.column}\" {compare} {boundary_sql(v, column_type)} AS INTEGER), 0)"
                       for v in partition.boundaries)
    return f"(1 + {terms})"


def partition_stats(reader: Reader, design: TableDesign, rows: int, scale: float) -> list[PartitionStats]:
    partition = design.partition
    if partition is None:
        return []
    types = {name.lower(): kind for name, kind in reader.columns(design.name)}
    column_type = types.get(partition.column.lower(), 'VARCHAR')
    counts = {int(p): int(n) for p, n in reader.fetch(
        f"SELECT {partition_number_sql(partition, column_type)} AS p, COUNT(*) FROM {design.name} GROUP BY 1")}
    stats = []
    distributed = design.distribution != 'REPLICATE'
    for number in range(1, partition.count + 1):
        lower, upper = partition_range(partition, number)
        count = counts.get(number, 0)
        at_scale = count * scale
        per_distribution = at_scale / DISTRIBUTIONS if distributed else at_scale
        columnstore_ok = None
        if design.index == 'CLUSTERED COLUMNSTORE INDEX' and count:
            columnstore_ok = per_distribution >= ROWGROUP_TARGET
        stats.append(PartitionStats(number, lower, upper, count, at_scale, per_distribution, columnstore_ok))
    return stats


def table_rowgroup_check(design: TableDesign, rows: int, scale: float) -> bool | None:
    """Columnstore rows per distribution for an unpartitioned table (None when not columnstore or empty)."""
    if design.index != 'CLUSTERED COLUMNSTORE INDEX' or rows == 0 or design.partition is not None:
        return None
    per_distribution = rows * scale / (DISTRIBUTIONS if design.distribution != 'REPLICATE' else 1)
    return per_distribution >= ROWGROUP_TARGET
