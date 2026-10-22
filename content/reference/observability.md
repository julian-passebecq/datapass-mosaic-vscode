# Observability: metrics, logs, traces, PromQL, Grafana, SLOs

Reference sheet for the concept checks (pack `infra-concepts-v1`). Datapass runs no Prometheus, Grafana, Loki or
tracing backend: the Infra Lab simulates Azure Monitor metric alerts over recorded scenarios (`lab alerts replay`),
and these cards are answered from this sheet, never executed. Checked against the Prometheus and Grafana
documentation and Google's SRE books on 2026-10-12.

## The three signals

| Signal | What it is | Good for | Watch out for |
|---|---|---|---|
| Metrics | Numbers sampled over time, one time series per name + label set | Trends, dashboards, alerts, cheap to keep for months | Every distinct label combination is a new series: no user ids, request ids or emails as labels (cardinality) |
| Logs | Timestamped events written by a program | What happened, with details, in one service | Volume and cost; free text is hard to query, so log **structured** (JSON) fields |
| Traces | One request across services, as a tree of spans (each with a start, a duration and attributes) | Where a slow or failing request spent its time | Usually sampled; needs context propagation (W3C `traceparent`) between services |

- **RED** (per service): request **R**ate, **E**rrors, **D**uration. **USE** (per resource): **U**tilization,
  **S**aturation, **E**rrors. RED says users are hurting; USE helps find which resource is why.
- OpenTelemetry is the vendor-neutral standard (APIs, SDKs, the Collector) for producing all three signals.

## Prometheus metric types

| Type | Behaviour | Example | Query it with |
|---|---|---|---|
| Counter | Only goes up; resets to 0 when the process restarts | `http_requests_total` | `rate()`, `increase()`, never the raw value |
| Gauge | Goes up and down | queue depth, memory in use | the value, `avg_over_time()`, `max_over_time()` |
| Classic histogram | Cumulative `_bucket{le="..."}` counters plus `_sum` and `_count` | `http_request_duration_seconds` | `histogram_quantile()` over `rate()` of the buckets |
| Summary | Quantiles computed in the client, plus sum and count | request latency | precomputed quantiles cannot be aggregated across instances; aggregate sum and count for an overall mean |

## PromQL basics

- `http_requests_total{code="500"}`: an **instant vector**, the latest sample of each matching series.
- `http_requests_total[5m]`: a **range vector**, every sample of each series over the last 5 minutes. It is the
  input of `rate()`, `increase()`, `avg_over_time()`; a graph cannot plot it directly.
- `rate(http_requests_total[5m])`: per-second increase, averaged over 5 minutes, with counter resets handled. Use a
  window of at least four scrape intervals.
- Aggregate **after** `rate()`: `sum by (code) (rate(http_requests_total[5m]))` gives one series per status code;
  `without (instance)` drops one label instead of keeping some.
- Error ratio: `sum(rate(http_requests_total{code=~"5.."}[5m])) / sum(rate(http_requests_total[5m]))`.
- p95 latency from a classic histogram: `histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket[5m])))`; keep `le`
  when you sum, and write the quantile as 0.95. Native histograms use the base metric without `_bucket` or `le`.
- `offset 1h` shifts a selector into the past (compare with last hour); `up == 0` lists targets Prometheus cannot
  scrape.

## Grafana dashboards

- Grafana stores dashboards, users and alert rules, **not** the data: each panel sends a query to a **data source**
  (Prometheus, Loki, Tempo, Azure Monitor, a SQL database...) when the dashboard loads or refreshes.
- **Variables** (`$service`, `$instance`) are drop-downs, filled by hand or by a query such as
  `label_values(up, service)`; panels use them in their queries, so one dashboard serves every service.
- A good service dashboard starts with RED at the top (rate, errors, latency percentiles), then saturation (USE)
  below; set units and thresholds on each panel, and link to logs and traces for the same time range.
- Dashboards are JSON: keep them in Git and provision them, rather than editing in production by hand.

## Grafana alerting

- An **alert rule** runs a query on a schedule (its evaluation interval) and compares it with a condition.
- States: **Normal** → **Pending** (condition true, waiting) → **Firing** once the condition has held for the whole
  **pending period**; a short spike goes back to Normal without notifying anyone.
- **Contact points** say how to notify (e-mail, Slack, Teams, a webhook, an on-call tool). The **notification
  policy** tree matches alert labels (for example `team=data`, `severity=page`) and routes each alert to a contact
  point, with grouping, repeat intervals and mute timings.
- Silences mute matching alerts for a time window, for example during planned maintenance.

## SLIs, SLOs and error budgets

- **SLI** (indicator): a measurement, ideally `good events / all events`, for example the share of requests answered
  successfully in under 300 ms.
- **SLO** (objective): a target for an SLI over a window, for example 99.5% over 28 days. **SLA**: a contract with
  consequences (credits) when it is missed, usually looser than the SLO.
- **Error budget** = 100% - the success target. For time-based availability of 99.9% over 30 days: 30 x 24 x 60 = 43,200 minutes, x 0.001 = **43.2 minutes**
  of full outage (4.32 minutes at 99.99%), if the entire budget remains. A request-based budget counts bad requests, not fixed outage minutes. While budget remains, ship; when it is spent, favour reliability work.
- **Burn rate**: how fast the budget is spent compared with exactly using it up over the window. Burn rate 1 spends
  it in 30 days (720 hours); burn rate 14.4 for 1 hour spends 14.4 / 720 = **2%**. The SRE workbook's multiwindow
  alerts: page at 14.4 over 1 h (2%) or 6 over 6 h (5%), open a ticket at 1 over 3 days (10%), each confirmed on a
  short window (1/12 of the long one) so the alert stops soon after the problem does.
- **Page on symptoms** users feel (errors, latency, fast SLO burn); send causes (CPU, disk, restarts) to dashboards
  and tickets.

## In the Infra Lab

The lab's `az monitor metrics alert` rules and `lab alerts replay` follow Azure Monitor's static metric alerts:
aggregation over the window (`--window-size`), evaluated every `--evaluation-frequency`, severity 0 (Critical) to 4
(Verbose), notifications through action groups, resolved after three evaluations without the condition. Missions
`alert-to-action`, `etl-vm-memory-leak` and `page-on-shir-outage` practise it on recorded scenarios.
