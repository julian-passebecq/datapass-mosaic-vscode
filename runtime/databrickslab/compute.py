"""The compute the lab models: job clusters, all-purpose clusters, serverless and SQL warehouses.

Nothing is provisioned. Start times and DBU figures are teaching values: the node
DBU rates follow the published sizes of common Azure VMs, and the cost per DBU is
in *lab units* whose only real property is their order: all-purpose compute costs
more per DBU than jobs compute, and a cluster bills from its start until it
terminates, idle time included. The Azure VM bill (spot or on-demand) is not
counted. Photon is recorded, not modelled.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# node type -> (cores, memory GB, DBU per hour)
NODE_TYPES: dict[str, tuple[int, int, float]] = {
    'Standard_DS3_v2': (4, 14, 0.75),
    'Standard_DS4_v2': (8, 28, 1.5),
    'Standard_DS5_v2': (16, 56, 3.0),
    'Standard_E8ds_v4': (8, 64, 2.0),
    'Standard_F4s_v2': (4, 8, 0.5),
}
RATE = {'jobs': 0.30, 'all_purpose': 0.55, 'serverless': 0.45, 'sql_serverless': 0.70}  # lab units per DBU
CLASSIC_START_S = 300
POOL_START_S = 60
SERVERLESS_START_S = 10
WAREHOUSE_START_S = 5
SERVERLESS_DBU_PER_HOUR = 2.0
WAREHOUSE_SIZES = {'2X-Small': 4, 'X-Small': 6, 'Small': 12, 'Medium': 24, 'Large': 40}

DEFAULT_COMPUTE: dict[str, Any] = {
    'clusters': [{'cluster_id': 'analytics-shared', 'cluster_name': 'Shared analytics (all-purpose)',
                  'node_type_id': 'Standard_DS3_v2', 'num_workers': 2, 'autotermination_minutes': 60,
                  'state': 'RUNNING'}],
    'warehouses': [{'id': 'serverless-sql', 'name': 'Serverless Starter Warehouse', 'cluster_size': '2X-Small',
                    'enable_serverless_compute': True}],
}


@dataclass
class AllPurposeCluster:
    cluster_id: str
    name: str
    node_type: str
    workers: int
    autotermination_minutes: int
    running: bool


@dataclass
class Warehouse:
    warehouse_id: str
    name: str
    size: str
    serverless: bool


@dataclass
class ComputeCatalog:
    clusters: dict[str, AllPurposeCluster]
    warehouses: dict[str, Warehouse]
    warnings: list[str] = field(default_factory=list)


def load_compute(raw: Any) -> ComputeCatalog:
    """factory/databricks/compute.json: all-purpose clusters and SQL warehouses of the lab workspace."""
    data = raw if isinstance(raw, dict) else DEFAULT_COMPUTE
    catalog = ComputeCatalog({}, {})
    for item in data.get('clusters') or []:
        if not isinstance(item, dict) or not isinstance(item.get('cluster_id'), str):
            catalog.warnings.append('compute.json: every cluster needs a cluster_id')
            continue
        node = item.get('node_type_id') if item.get('node_type_id') in NODE_TYPES else 'Standard_DS3_v2'
        if item.get('node_type_id') not in NODE_TYPES:
            catalog.warnings.append(f"compute.json: {item['cluster_id']} uses an unknown node type; the lab uses {node}")
        workers = item.get('num_workers', 1)
        catalog.clusters[item['cluster_id']] = AllPurposeCluster(
            item['cluster_id'], str(item.get('cluster_name', item['cluster_id'])), node,
            workers if type(workers) is int and workers >= 0 else 1,
            int(item.get('autotermination_minutes', 120) or 0), str(item.get('state', 'TERMINATED')).upper() == 'RUNNING')
    for item in data.get('warehouses') or []:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str):
            catalog.warnings.append('compute.json: every warehouse needs an id')
            continue
        size = item.get('cluster_size') if item.get('cluster_size') in WAREHOUSE_SIZES else '2X-Small'
        catalog.warehouses[item['id']] = Warehouse(item['id'], str(item.get('name', item['id'])), size,
                                                   item.get('enable_serverless_compute', True) is not False)
    return catalog


@dataclass
class Usage:
    """One compute resource used by a run: when it was up and what it billed."""
    key: str
    kind: str  # job_cluster | all_purpose | serverless | warehouse
    label: str
    requested_s: float
    ready_s: float
    end_s: float = 0.0
    nodes: float = 0.0
    dbu_per_hour: float = 0.0
    rate: float = 0.0
    tasks: list[str] = field(default_factory=list)
    idle_after_s: float = 0.0
    notes: list[str] = field(default_factory=list)
    busy_s: float = 0.0

    def billed_seconds(self) -> float:
        if self.kind == 'serverless':
            return self.busy_s
        return max(0.0, self.end_s - self.requested_s)

    def dbu(self) -> float:
        return self.dbu_per_hour * self.billed_seconds() / 3600

    def idle_dbu(self) -> float:
        return self.dbu_per_hour * self.idle_after_s / 3600

    def to_json(self) -> dict[str, Any]:
        return {'key': self.key, 'kind': self.kind, 'label': self.label, 'requested_s': round(self.requested_s, 1),
                'ready_s': round(self.ready_s, 1), 'end_s': round(self.end_s, 1),
                'startup_s': round(self.ready_s - self.requested_s, 1), 'billed_s': round(self.billed_seconds(), 1),
                'nodes': self.nodes, 'dbu_per_hour': round(self.dbu_per_hour, 3), 'dbu': round(self.dbu(), 4),
                'rate': self.rate, 'cost': round(self.dbu() * self.rate, 4), 'tasks': self.tasks,
                'idle_after_s': round(self.idle_after_s, 1), 'idle_dbu': round(self.idle_dbu(), 4),
                'idle_cost': round(self.idle_dbu() * self.rate, 4), 'notes': self.notes}


def job_cluster_usage(spec: Any, requested_s: float) -> Usage:
    per_node = NODE_TYPES[spec.node_type][2]
    driver = NODE_TYPES.get(spec.driver_node_type, NODE_TYPES[spec.node_type])[2]
    startup = POOL_START_S if spec.pool else CLASSIC_START_S
    usage = Usage(spec.key, 'job_cluster', f"Job cluster {spec.key}: {spec.label()}", requested_s,
                  requested_s + startup, nodes=1 + spec.billed_workers,
                  dbu_per_hour=driver + per_node * spec.billed_workers, rate=RATE['jobs'])
    usage.notes.append(f"Starts when its first task is ready ({startup} s{' from the pool' if spec.pool else ''}) and "
                       "terminates after its last task.")
    if spec.autoscale:
        usage.notes.append(f"Autoscaling {spec.autoscale[0]}-{spec.autoscale[1]} workers: the lab bills the average.")
    if spec.photon:
        usage.notes.append('Photon: recorded; its speed and DBU rate are not modelled.')
    if spec.availability.startswith('SPOT'):
        usage.notes.append('Spot instances lower the Azure VM bill, which the lab does not count (DBUs only).')
    return usage


def all_purpose_usage(cluster: AllPurposeCluster, requested_s: float) -> Usage:
    per_node = NODE_TYPES[cluster.node_type][2]
    startup = 0 if cluster.running else CLASSIC_START_S
    usage = Usage(cluster.cluster_id, 'all_purpose', f"All-purpose cluster {cluster.name}", requested_s,
                  requested_s + startup, nodes=1 + cluster.workers, dbu_per_hour=per_node * (1 + cluster.workers),
                  rate=RATE['all_purpose'])
    usage.notes.append('Already running: no start time.' if cluster.running else
                       f"Terminated: the run starts it ({CLASSIC_START_S} s).")
    usage.notes.append('All-purpose compute bills more per DBU than jobs compute.')
    if cluster.autotermination_minutes:
        usage.idle_after_s = cluster.autotermination_minutes * 60
        usage.notes.append(f"After the last task it stays up idle until auto-termination "
                           f"({cluster.autotermination_minutes} min).")
    else:
        usage.notes.append('No auto-termination: it keeps running (and billing) after the run.')
    return usage


def serverless_usage(environment: str, requested_s: float) -> Usage:
    usage = Usage(f"serverless:{environment}", 'serverless', 'Serverless compute for jobs', requested_s,
                  requested_s + SERVERLESS_START_S, nodes=0, dbu_per_hour=SERVERLESS_DBU_PER_HOUR,
                  rate=RATE['serverless'])
    usage.notes.append(f"Starts in seconds ({SERVERLESS_START_S} s in the lab) and bills only while tasks run.")
    return usage


def warehouse_usage(warehouse: Warehouse, requested_s: float) -> Usage:
    usage = Usage(warehouse.warehouse_id, 'warehouse', f"SQL warehouse {warehouse.name} ({warehouse.size}"
                  f"{', serverless' if warehouse.serverless else ', pro'})", requested_s,
                  requested_s + (WAREHOUSE_START_S if warehouse.serverless else CLASSIC_START_S),
                  nodes=0, dbu_per_hour=float(WAREHOUSE_SIZES[warehouse.size]), rate=RATE['sql_serverless'])
    usage.notes.append('SQL tasks run on a SQL warehouse, not on a Spark cluster.')
    return usage
