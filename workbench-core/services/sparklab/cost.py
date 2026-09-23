"""Transparent cost adapters for the SparkLab virtual runtime."""
from __future__ import annotations
from typing import Any
from .runtime import ClusterProfile, JobRun


def price_job(job: JobRun, profile: ClusterProfile, sparklab_eur_per_scc: float = 0.10,
              fabric_eur_per_cu_hour: float | None = None,
              databricks_usd_per_dbu: float | None = None) -> dict[str, Any]:
    # SCC is intentionally ours. It rewards reduced compute, shuffle and spill.
    scc = job.core_hours + 0.02 * job.memory_gb_hours + 0.05 * job.shuffle_gb + 0.12 * job.spill_gb
    fabric_cu_hours = job.core_hours * profile.fabric_cu_per_vcore_hour if profile.fabric_cu_per_vcore_hour is not None else None
    dbu_eq = job.node_hours * profile.dbu_equivalent_per_node_hour if profile.dbu_equivalent_per_node_hour is not None else None
    return {
        "sparklab": {
            "scc": round(scc, 3),
            "eur_per_scc": sparklab_eur_per_scc,
            "estimated_eur": round(scc * sparklab_eur_per_scc, 3),
            "label": "SparkLab training price",
        },
        "fabric_like": {
            "cu_hours": round(fabric_cu_hours, 4) if fabric_cu_hours is not None else None,
            "price_input_eur_per_cu_hour": fabric_eur_per_cu_hour,
            "estimated_eur": round(fabric_cu_hours * fabric_eur_per_cu_hour, 3) if fabric_cu_hours is not None and fabric_eur_per_cu_hour is not None else None,
            "label": "Fabric-equivalent usage estimate; not an Azure invoice",
        },
        "databricks_like": {
            "dbu_equivalent": round(dbu_eq, 4) if dbu_eq is not None else None,
            "price_input_usd_per_dbu": databricks_usd_per_dbu,
            "estimated_usd": round(dbu_eq * databricks_usd_per_dbu, 3) if dbu_eq is not None and databricks_usd_per_dbu is not None else None,
            "label": "DBU-equivalent teaching adapter; use dated vendor list price for money",
        },
    }

def credits(job, profile):
    contributors = dict(compute=job.core_hours*profile.credits_per_core_hour,
                        memory=0.02*job.memory_gb_hours, shuffle=0.05*job.shuffle_gb, spill=0.12*job.spill_gb)
    return dict(unit='Datapass Credits', fictional=True, total=round(sum(contributors.values()), 6),
                contributors={k:round(v,6) for k,v in contributors.items()},
                formula='core_hours × profile rate + 0.02 × memory_GB_hours + 0.05 × shuffle_GB + 0.12 × spill_GB',
                explanation='Allocated worker slots and driver include idle time; startup charges driver only. No currency, payment or vendor bill.')
