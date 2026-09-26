# Databricks compute

Reference sheet for the concept checks (pack `concepts-v1`). The Cloud Lab's Databricks tab simulates jobs and compute
costs with lab figures; it does not connect to Databricks. Checked against the Databricks documentation on 2026-09-26.

## Kinds of compute

| Compute | For | Billing |
|---|---|---|
| **All-purpose** cluster | interactive notebooks, several people exploring | higher DBU rate; runs until stopped or auto-terminated |
| **Job** compute | a scheduled job; created for the run, removed after it | lower DBU rate than all-purpose |
| **SQL warehouse** (classic, pro, serverless) | SQL queries, BI tools (Power BI, dashboards) | DBUs per warehouse size; serverless starts in seconds |
| **Serverless** notebooks and jobs | no cluster to configure | managed by Databricks |

For classic compute, the cloud provider bills the VMs on top of the DBUs.

## Access modes (Unity Catalog)

- **Standard** (formerly *shared*): several users on one cluster, isolated from each other, each with their own Unity
  Catalog permissions.
- **Dedicated** (formerly *single user*): the cluster belongs to one user or group.
- **No isolation shared** is legacy and does not support Unity Catalog.

## Saving time and money

- **Instance pools** keep VMs ready, so clusters start and scale faster. Idle pool instances cost no DBUs, but the cloud
  provider still bills the VMs.
- **Autoscaling** adds and removes workers with the load; **auto-termination** stops idle all-purpose clusters.
- **Spot** instances for workers are cheaper and can be taken back by the cloud provider.
