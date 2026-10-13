# Production orchestration

Cheatsheet for the Learning path *Orchestration in production*. It applies to any orchestrator (Airflow, Data
Factory and Fabric pipelines, Databricks jobs, dbt runs); the labs simulate the orchestration and run the data steps
locally.

## Every task, every time

| Property | Why |
|---|---|
| Idempotent | retries, reruns and backfills leave the same result |
| Owns a slice | a day, a partition, a batch id: it replaces exactly that |
| Bounded | an execution timeout so a hang becomes a failure |
| Retried when transient | network blips, 429, 503; not bad input |
| Observable | logs with run id and slice, row counts in and out |

## Idempotent write patterns

- Delete-then-insert the slice inside one transaction, or overwrite the partition.
- `MERGE` on the business key (upsert); add a deterministic tie-breaker when a key appears twice in a batch.
- Append-only only when the source guarantees each event once, or deduplicate on an event id downstream.

## Quality gates

1. Row rules: route failing rows to a **quarantine** table with the reason and source file.
2. Batch rules: row count within range, unique keys, quarantined share under a threshold.
3. Publish gold only if the gate passes; otherwise fail the run and alert.

## Dependencies and triggers

- Time-based schedule when the source lands at a known time; data-aware (Airflow assets, storage events) when not.
- Pools or concurrency limits protect shared resources.
- Cross-pipeline dependencies are explicit (sensors, assets, run-pipeline activities), never "it usually finishes by 3".

## Alerting

- Alert on what needs a human: a failed run after retries, a late table, a stopped quality gate.
- Every alert names the pipeline, the run, the slice and the first thing to check (runbook line).
- A failure handler that logs and succeeds can turn a run green: make sure the run still fails when it should.
