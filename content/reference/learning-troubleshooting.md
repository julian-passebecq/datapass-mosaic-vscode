# Troubleshooting pipelines

Cheatsheet for all four curriculum paths. A method first, then the usual suspects.

## Method

1. **Scope**: what failed (run, task, slice), since when, what changed (code, data, config, platform).
2. **First error**: read the first failure in the log and its innermost `Caused by`; later errors are consequences.
3. **Reproduce small**: the same task, the same slice, locally or in a lab, with the same inputs.
4. **One change at a time**; rerun; compare row counts and checksums with a known good run.
5. **Write it down**: cause, fix, and the check that would have caught it earlier.

## Wrong results

| Symptom | Usual cause | Check |
|---|---|---|
| Totals too high after a join | duplicate keys on the "one" side, type 2 joined on business key | `count(*)` vs `count(DISTINCT key)` per side |
| Rows missing after a LEFT JOIN | a filter on the right side in `WHERE` instead of `ON` | move the filter into `ON` |
| `NOT IN` returns nothing | a NULL in the subquery | use `NOT EXISTS` |
| Duplicated day after a rerun | append-only load | make it idempotent (replace slice, MERGE) |
| Yesterday's data loaded twice, today's missing | wall-clock date in the task | use the run's logical date or data interval |

## Failures

| Symptom | Usual cause |
|---|---|
| `ModuleNotFoundError` only on workers | package missing from the worker environment or image |
| One task slow, then out of memory | skew on a key (often NULL or a default) |
| Task never ends, retries never start | no timeout on a hung call |
| 401 / 403 after a deploy | expired secret, wrong identity, missing grant |
| 429 storms | parallel tasks share a rate limit: pool or lower concurrency |
| `CrashLoopBackOff`, `OOMKilled` | see the Kubernetes cheatsheet |
| Disk full on a VM | `df -h`, then `du -sh` on the biggest filesystem; rotate logs |

## Slow

Compare with the last normal run: input size, number of files, plan, skew. See the performance cheatsheet.

## Prevent the next one

Row count and freshness checks, a quality gate before publishing, alerts with a runbook line, and a test with the
input that broke it.
