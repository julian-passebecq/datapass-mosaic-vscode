"""SQL pool Lab panel view: run a script, then describe every pool table and the last query plan."""
from __future__ import annotations

import re
from dataclasses import asdict
from datetime import datetime
from typing import Any

from .engine import Database, SqlPool, StatementResult
from .model import DISTRIBUTIONS, FLAVOR_LABELS, ROWGROUP_TARGET, Metadata
from .physical import distribution_stats, partition_stats, table_rowgroup_check

TRUTH = ("Simulated SQL pool: T-SQL is translated to DuckDB for a documented subset and the data statements really run "
         "on the local catalog. Distributions, partitions, columnstore rowgroups and distributed plans are modelled for "
         "teaching, not measured by a real dedicated SQL pool; nothing connects to Azure or Fabric.")


_WAREHOUSE = re.compile(r'\bwarehouse\.(?=[A-Za-z_"])')


def display_name(name: str) -> str:
    """The pool's dbo schema is the lab's warehouse layer."""
    return 'dbo.' + name.split('.', 1)[1] if name.startswith('warehouse.') else name


def display_text(text: str) -> str:
    """Messages name the warehouse tables as the learner writes them: dbo.<table>."""
    return _WAREHOUSE.sub('dbo.', text)


def plan_view(plan: dict[str, Any] | None) -> dict[str, Any] | None:
    if not plan:
        return plan
    return {**plan,
            'steps': [{**s, 'tables': [display_name(t) for t in s['tables']], 'reason': display_text(s['reason'])}
                      for s in plan['steps']],
            'scans': [{**s, 'table': display_name(s['table']), 'reason': display_text(s['reason'])}
                      for s in plan['scans']],
            'notes': [display_text(n) for n in plan['notes']]}


def statement_view(result: StatementResult) -> dict[str, Any]:
    data = asdict(result)
    data['target'] = display_name(result.target) if result.target else None
    data['message'] = display_text(result.message)
    data['notes'] = [display_text(n) for n in result.notes]
    data['plan'] = plan_view(result.plan)
    data['children'] = [statement_view(child) for child in result.children]
    return data


def table_view(pool: SqlPool, name: str) -> dict[str, Any]:
    db = pool.db
    design = pool.design_of(name)
    rows = db.count(name)
    factor = design.scale_factor or pool.scale
    view: dict[str, Any] = {
        'name': display_name(name), 'table': name, 'label': design.label(), 'distribution': design.distribution,
        'hash_columns': design.hash_columns, 'index': design.index, 'index_columns': design.index_columns,
        'partition': None, 'cluster_by': design.cluster_by, 'nonclustered_indexes': design.nonclustered_indexes,
        'statistics': design.statistics, 'constraints': design.constraints, 'identity': design.identity,
        'rows': rows, 'scale_factor': factor, 'rows_at_scale': rows * factor, 'created_by': design.created_by,
        'distribution_stats': None, 'partitions': [], 'columnstore_ok': None,
    }
    if pool.flavor == 'fabric':
        return view
    stats = distribution_stats(db, design, rows, factor)
    view['distribution_stats'] = {
        'shares': [round(s, 6) for s in stats.shares], 'skew_pct': stats.skew_pct,
        'max_share_pct': round(stats.max_share * 100, 2), 'min_share_pct': round(stats.min_share * 100, 2),
        'empty_distributions': stats.empty_distributions, 'distinct_keys': stats.distinct_keys,
        'null_share_pct': round(stats.null_share * 100, 2),
        'heavy_values': [{'value': v, 'share_pct': round(s * 100, 2)} for v, s in stats.heavy_values[:8]],
    }
    if design.partition:
        view['partition'] = {'column': design.partition.column, 'range': design.partition.range,
                             'boundaries': [str(b) for b in design.partition.boundaries],
                             'count': design.partition.count}
        view['partitions'] = [{'number': p.number, 'lower': None if p.lower is None else str(p.lower),
                               'upper': None if p.upper is None else str(p.upper), 'rows': p.rows,
                               'rows_at_scale': p.rows_at_scale, 'rows_per_distribution': p.rows_per_distribution,
                               'columnstore_ok': p.columnstore_ok}
                              for p in partition_stats(db, design, rows, factor)]
    else:
        view['columnstore_ok'] = table_rowgroup_check(design, rows, factor)
    return view


def pool_tables(pool: SqlPool, extra: list[str]) -> list[str]:
    names = {n for n in pool.metadata.tables if pool.db.exists(n)} | {n for n in extra if pool.db.exists(n)}
    for gone in [n for n in pool.metadata.tables if not pool.db.exists(n)]:
        pool.metadata.tables.pop(gone, None)
    return sorted(names)


def pool_view(db: Database, metadata: Metadata, script: str, flavor: str, scale: float,
              warehouse_tables: list[str], now: datetime | None = None) -> dict[str, Any]:
    pool = SqlPool(db, metadata, flavor, now, scale)
    results = pool.run(script) if script.strip() else []
    names = pool_tables(pool, warehouse_tables)
    metadata.save()
    failed = next((r for r in results if r.status == 'error'), None)
    return {
        'status': 'error' if failed else 'ok',
        'flavor': flavor, 'flavor_label': FLAVOR_LABELS[flavor], 'truth': TRUTH, 'scale': scale,
        'distributions': DISTRIBUTIONS, 'rowgroup_target': ROWGROUP_TARGET,
        'statements': [statement_view(r) for r in results],
        'tables': [table_view(pool, name) for name in names],
        'plan': plan_view(pool.last_plan),
    }
