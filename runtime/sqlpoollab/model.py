"""Table designs of the simulated SQL pool and the metadata the lab keeps about them."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

DISTRIBUTIONS = 60  # a dedicated SQL pool always stores a distributed table in 60 distributions
ROWGROUP_TARGET = 1_000_000  # "a minimum of 1 million rows per distribution and partition" for columnstore
FLAVORS = ('synapse', 'fabric')
FLAVOR_LABELS = {'synapse': 'Azure Synapse dedicated SQL pool', 'fabric': 'Microsoft Fabric Data Warehouse'}


class PoolError(Exception):
    """A statement the pool rejects, with the product's reason."""

    def __init__(self, message: str, statement: int | None = None, line: int | None = None):
        super().__init__(message)
        self.message = message
        self.statement = statement
        self.line = line


@dataclass
class Partitioning:
    column: str
    range: str  # LEFT (default) or RIGHT
    boundaries: list[Any]

    @property
    def count(self) -> int:
        return len(self.boundaries) + 1


@dataclass
class TableDesign:
    name: str  # schema.table, lower case
    distribution: str = 'ROUND_ROBIN'  # HASH | ROUND_ROBIN | REPLICATE (Synapse); AUTO (Fabric)
    hash_columns: list[str] = field(default_factory=list)
    index: str = 'CLUSTERED COLUMNSTORE INDEX'  # | HEAP | CLUSTERED INDEX | AUTO (Fabric)
    index_columns: list[str] = field(default_factory=list)  # CLUSTERED INDEX keys, or CCI ORDER columns
    partition: Partitioning | None = None
    cluster_by: list[str] = field(default_factory=list)  # Fabric data clustering
    nonclustered_indexes: dict[str, list[str]] = field(default_factory=dict)
    statistics: dict[str, list[str]] = field(default_factory=dict)
    constraints: list[dict[str, Any]] = field(default_factory=list)
    identity: str | None = None
    # How many real rows one lab row stands for (inherited through CTAS / INSERT ... SELECT).
    scale_factor: float | None = None
    created_by: str = 'CREATE TABLE'

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data['partition'] = asdict(self.partition) if self.partition else None
        return data

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> 'TableDesign':
        data = dict(data)
        partition = data.pop('partition', None)
        design = cls(**data)
        design.partition = Partitioning(**partition) if partition else None
        return design

    def label(self) -> str:
        if self.distribution == 'AUTO':
            clustering = f", CLUSTER BY ({', '.join(self.cluster_by)})" if self.cluster_by else ''
            return f"managed layout (Fabric){clustering}"
        parts = [f"HASH({', '.join(self.hash_columns)})" if self.distribution == 'HASH' else self.distribution]
        if self.index == 'CLUSTERED INDEX':
            parts.append(f"CLUSTERED INDEX ({', '.join(self.index_columns)})")
        elif self.index == 'CLUSTERED COLUMNSTORE INDEX' and self.index_columns:
            parts.append(f"CLUSTERED COLUMNSTORE INDEX ORDER ({', '.join(self.index_columns)})")
        else:
            parts.append(self.index)
        if self.partition:
            parts.append(f"PARTITION ({self.partition.column} RANGE {self.partition.range}, "
                         f"{self.partition.count} partitions)")
        if self.cluster_by:
            parts.append(f"CLUSTER BY ({', '.join(self.cluster_by)})")
        return ', '.join(parts)


@dataclass
class Procedure:
    name: str
    parameters: list[tuple[str, str, str | None]]  # (name without @, T-SQL type, default literal)
    body: str
    line: int = 1


class Metadata:
    """Designs and procedures, persisted next to the catalog (sqlpool.json)."""

    def __init__(self, path: Path | None):
        self.path = path
        self.tables: dict[str, TableDesign] = {}
        self.procedures: dict[str, Procedure] = {}
        self.flavor_of: dict[str, str] = {}
        if path is not None and path.exists():
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
                self.tables = {k: TableDesign.from_json(v) for k, v in data.get('tables', {}).items()}
                self.procedures = {k: Procedure(v['name'], [tuple(p) for p in v['parameters']], v['body'], v.get('line', 1))
                                   for k, v in data.get('procedures', {}).items()}
            except (ValueError, KeyError, TypeError):
                self.tables, self.procedures = {}, {}

    def save(self) -> None:
        if self.path is None:
            return
        data = {'schema_version': 1,
                'tables': {k: v.to_json() for k, v in sorted(self.tables.items())},
                'procedures': {k: {'name': p.name, 'parameters': [list(x) for x in p.parameters], 'body': p.body,
                                   'line': p.line} for k, p in sorted(self.procedures.items())}}
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, indent=2), encoding='utf-8')
        tmp.replace(self.path)
