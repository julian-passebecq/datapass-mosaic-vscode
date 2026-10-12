# Linux and VMs

Cheatsheet for the Learning path *Infrastructure and DevOps for data*. The Terminal Lab runs your own commands in a
real VS Code terminal (Datapass runs none of them); VM metrics and alerts in the Infra Lab are recorded scenarios
replayed with Azure Monitor semantics.

## Shell essentials

| Task | Command |
|---|---|
| Free space per filesystem | `df -h` |
| Size of folders | `du -sh /data/* \| sort -h` |
| Memory | `free -m` |
| Processes, load | `top`, `htop`, `uptime`, `ps aux --sort=-%mem \| head` |
| Find text | `grep -rn "ERROR" logs/` |
| Follow a log | `tail -f app.log`, `journalctl -u etl.service -f` |
| Permissions | `chmod 750 run.sh` (owner rwx, group r-x, others none), `chown etl:data dir` |
| Who listens on a port | `ss -ltnp` |

Permission digits: read 4 + write 2 + execute 1, for owner, group, others.

## Scripts that fail properly

```bash
#!/usr/bin/env bash
set -euo pipefail         # stop on error, on unset variables, and on any failing pipe stage
[ -s "$file" ] || { echo "missing or empty: $file" >&2; exit 1; }
```

`$?` holds the last exit status: 0 is success. Schedulers judge a job by it.

## Cron

`m h dom mon dow`: `30 6 * * 1-5` is 06:30 on weekdays. Cron uses the machine's time zone; log in UTC.

## Reading a VM

- **Load average** counts runnable tasks plus tasks in uninterruptible I/O wait; compare it with the vCPU count.
- High CPU with low I/O wait: compute bound. Low CPU with high I/O wait: disk bound.
- Available memory falling steadily until a restart: a leak.

## Azure Monitor metric alerts

| Setting | Meaning |
|---|---|
| Aggregation | average, minimum, maximum, total, count over the window |
| Window size | how much data is aggregated (for example 5 or 15 minutes) |
| Evaluation frequency | how often the rule is checked |
| Action group | who is notified and how |

A 30-second spike barely moves a 5-minute average. Choose the aggregation for the symptom.
