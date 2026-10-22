"""Generate content/exercise-packs/infra-concepts-v1: observability concept checks (Practice language `quiz`).

Questions about what the Infra Lab does not simulate: the three signals (metrics, logs, traces), Prometheus metric
types and PromQL basics, Grafana dashboards and Grafana alerting, and SLIs, SLOs and error budgets. Nothing runs and
there is no Prometheus or Grafana simulation: each card has a public question (exercises.json) and a private answer
with its explanation (grading.server.json), compared by the runtime as for `concepts-v1`. The reference sheet
content/reference/observability.md backs every card. Facts checked against the Prometheus and Grafana documentation
and Google's SRE books on 2026-10-12.

    python scripts/authoring/gen_infra_concepts.py
"""
import json
from pathlib import Path

PACK = Path(__file__).resolve().parents[2] / "content" / "exercise-packs" / "infra-concepts-v1"
REFERENCE = ("reference/observability.md", "Observability: metrics, logs, traces, PromQL, Grafana, SLOs")
PREFIX = "infra-concept-"

# (id, topic, difficulty, title, question, choices {letter: text} or None, correct letters or accepted texts, why, hint)
CARDS = [
    ("signals-traces", "signals", "easy", "Which signal shows where a request spent its time",
     "A checkout request took 4 seconds. It crossed the API gateway, the orders service and the payment service. Which signal tells you which of them added the delay?",
     {"a": "A metric of the gateway's average latency", "b": "A distributed trace of that request",
      "c": "The CPU usage of each service", "d": "The gateway's access log"}, ["b"],
     "A trace records one request as a tree of spans, one per service or operation, each with its start and duration, so it shows where the time went. Metrics aggregate many requests; logs describe events one service at a time.",
     "You want the path of one request, hop by hop."),
    ("signals-cardinality", "signals", "medium", "Labels and cardinality",
     "Why should you not add a `user_id` label to a Prometheus request counter?",
     {"a": "Labels cannot hold numbers", "b": "Every distinct label value creates a new time series, so millions of users mean millions of series",
      "c": "Prometheus drops labels longer than 8 characters", "d": "Counters cannot have labels"}, ["b"],
     "Each unique combination of label values is its own time series, stored and indexed separately. Unbounded values (user ids, request ids, emails) explode memory and query time. Put such details in logs or traces instead.",
     "Count the time series the label would create."),
    ("signals-structured-logs", "signals", "easy", "Structured logs",
     "What do you gain by writing logs as JSON objects (`{\"level\": \"error\", \"order_id\": 42, ...}`) instead of free text?",
     {"a": "Smaller files", "b": "Fields you can filter and aggregate on without fragile text parsing",
      "c": "Logs no longer need timestamps", "d": "Nothing: log tools only read text"}, ["b"],
     "Structured logs keep each value in a named field, so a log backend can filter (`level = error`), group and join on them reliably. Free text needs regular expressions that break when the message changes.",
     "Think about querying the logs later."),
    ("promql-metric-types", "promql", "easy", "Counter or gauge",
     "A metric reports how many messages are waiting in a queue right now; it goes up and down. Which Prometheus metric type is it? (one word)",
     None, ["gauge", "a gauge"],
     "A gauge is a value that can go up and down (queue depth, memory in use, temperature). A counter only goes up (or resets to zero on restart), like a total number of requests.",
     "It is not a counter, because it can go down."),
    ("promql-rate", "promql", "easy", "Requests per second from a counter",
     "`http_requests_total` is a counter. Which query gives the requests per second, averaged over the last 5 minutes?",
     {"a": "http_requests_total", "b": "rate(http_requests_total[5m])",
      "c": "sum(http_requests_total)", "d": "avg_over_time(http_requests_total[5m])"}, ["b"],
     "`rate()` takes a range vector of a counter and returns its per-second increase, handling counter resets. The raw counter only grows since the process started, and averaging it means nothing.",
     "A counter's value matters less than how fast it grows."),
    ("promql-range-vector", "promql", "medium", "What [5m] returns",
     "What does `http_requests_total[5m]` return on its own?",
     {"a": "A range vector: every sample of each series over the last 5 minutes", "b": "The value 5 minutes ago",
      "c": "The average of the last 5 minutes", "d": "An error: [5m] needs offset"}, ["a"],
     "A range selector returns, for each series, all its samples in the window. Functions like rate(), increase() or avg_over_time() turn it into one value per series (an instant vector), which is what a graph plots. `offset 5m` is what shifts a query into the past.",
     "It is the input that rate() expects."),
    ("promql-sum-by", "promql", "medium", "One line per status code",
     "Your counter `http_requests_total` has the labels `instance`, `method` and `code`. Which query gives one line per status code, all instances and methods together?",
     {"a": "rate(http_requests_total[5m]) by (code)", "b": "sum by (code) (rate(http_requests_total[5m]))",
      "c": "sum(rate(http_requests_total{code}[5m]))", "d": "count by (code) (http_requests_total)"}, ["b"],
     "Aggregate after rate(): `sum by (code) (...)` adds the per-second rates of every series that shares a code and keeps only that label. Summing raw counters before rate() would hide counter resets; count counts series, not requests.",
     "rate() first, then aggregate."),
    ("promql-histogram-quantile", "promql", "hard", "p95 latency from a classic histogram",
     "Request durations are recorded in the classic histogram `http_request_duration_seconds`. Which query gives the 95th percentile latency over all instances, over the last 5 minutes?",
     {"a": "quantile(0.95, http_request_duration_seconds_sum)",
      "b": "histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket[5m])))",
      "c": "avg(http_request_duration_seconds_bucket) * 0.95",
      "d": "histogram_quantile(95, http_request_duration_seconds_count)"}, ["b"],
     "A classic Prometheus histogram exposes cumulative `_bucket` counters labelled `le` (less than or equal). Take their rate, sum them keeping `le`, then histogram_quantile(0.95, ...) estimates the 95th percentile from the buckets. The quantile is written as 0.95, not 95.",
     "Classic histogram buckets carry the le label; keep it when you sum."),
    ("grafana-datasources", "grafana", "easy", "Where Grafana's data lives",
     "Where are the numbers a Grafana dashboard shows stored?",
     {"a": "In Grafana's own database, copied at every refresh", "b": "In the data sources Grafana queries (Prometheus, Loki, a SQL database, Azure Monitor...)",
      "c": "In the browser", "d": "In the dashboard's JSON file"}, ["b"],
     "Grafana is a visualization and alerting layer: each panel sends a query to a data source when the dashboard loads or refreshes. Its own database keeps dashboards, users and alert rules, not the time series.",
     "Each panel has a query and a data source."),
    ("grafana-variables", "grafana", "medium", "One dashboard for every service",
     "You want one dashboard where the viewer picks the service in a drop-down and every panel follows. What do you use?",
     {"a": "A copy of the dashboard per service", "b": "A dashboard variable (for example `$service`) used in the panels' queries",
      "c": "An annotation", "d": "A transformation"}, ["b"],
     "Dashboard (template) variables are drop-downs whose values can come from a query (for example `label_values(up, service)`); panels refer to them as `$service`, so one dashboard serves every service.",
     "It shows up as a drop-down at the top of the dashboard."),
    ("grafana-pending-period", "grafana", "medium", "The pending period of an alert rule",
     "A Grafana alert rule checks `error ratio > 5%` every minute, with a pending period of 5 minutes. The ratio goes above 5% for 3 minutes, then drops. What happens?",
     {"a": "It fires after the first minute", "b": "It goes to Pending and back to Normal without firing",
      "c": "It fires after 5 minutes anyway", "d": "It fires and resolves at once"}, ["b"],
     "When the condition becomes true the rule enters Pending; it fires only if the condition stays true for the whole pending period. Short spikes therefore never notify anyone.",
     "Pending means not yet firing."),
    ("grafana-notification-policies", "grafana", "medium", "Routing alerts to the right team",
     "In Grafana alerting, what decides that alerts labelled `team=data` go to the data team's Slack channel and the others to e-mail?",
     {"a": "The panel's thresholds", "b": "Notification policies, which match alert labels and route to contact points",
      "c": "The data source", "d": "Each alert rule's title"}, ["b"],
     "Contact points say how to notify (Slack, e-mail, a webhook, an on-call tool); the notification policy tree matches alert labels and routes each alert to a contact point, with grouping, timing and muting.",
     "Labels are matched by a tree of policies."),
    ("slo-sli", "slo", "easy", "SLI or SLO",
     "Which sentence is a service level objective (SLO), not an indicator (SLI)?",
     {"a": "The share of requests answered in under 300 ms", "b": "99.5% of requests answered in under 300 ms over 28 days",
      "c": "The number of HTTP 500 responses per minute", "d": "The p99 latency of the API"}, ["b"],
     "An SLI is a measurement, usually a ratio of good events to all events. An SLO is a target for an SLI over a window: a percentage and a period. An SLA is a contract with consequences when the SLO is missed.",
     "An objective has a target and a period."),
    ("slo-error-budget", "slo", "medium", "The error budget of 99.9%",
     "An API has a 99.9% availability SLO over 30 days. How many minutes of full outage does its error budget allow over those 30 days? (a number)",
     None, ["43.2", "43.2 minutes", "43.2 min", "43", "43 minutes"],
     "The error budget is 100% - 99.9% = 0.1% of the window: 30 days x 24 h x 60 min = 43,200 minutes, and 0.1% of it is 43.2 minutes. At 99.99% it would be 4.32 minutes.",
     "Multiply the minutes in 30 days by 0.001."),
    ("slo-burn-rate", "slo", "hard", "What a burn rate of 14.4 means",
     "A 30-day SLO has an alert on a burn rate of 14.4 sustained over 1 hour. When it fires, how much of the 30-day error budget has that hour consumed?",
     {"a": "0.2%", "b": "2%", "c": "14.4%", "d": "50%"}, ["b"],
     "A burn rate of 1 spends the budget exactly over the 30 days (720 hours). At 14.4, one hour spends 14.4 / 720 = 2% of the budget. Google's recommended examples use 14.4 over one hour and 6 over six hours for pages, and 1 over three days for tickets; teams can adapt notification severity.",
     "At burn rate 1, the budget lasts 720 hours."),
    ("alert-symptoms", "slo", "medium", "What should wake someone up",
     "Which alert should page the on-call engineer at night?",
     {"a": "CPU above 80% on one VM for 5 minutes", "b": "The checkout error budget burning fast enough to be gone within days",
      "c": "A disk 60% full", "d": "One pod restarted"}, ["b"],
     "Page on symptoms users feel (errors, latency, SLO burn) and send causes (CPU, disk, restarts) to dashboards or tickets: a busy CPU that hurts nobody is not an emergency, and user-facing pain is one even when no cause alert fired.",
     "Ask whether a user would notice."),
    ("red-use", "signals", "medium", "RED and USE",
     "The RED method gives three signals to watch for every request-driven service. Which are they?",
     {"a": "Rate, Errors, Duration", "b": "Reads, Exceptions, Disk", "c": "Requests, Endpoints, Deployments",
      "d": "Utilization, Saturation, Errors"}, ["a"],
     "RED (Tom Wilkie): request Rate, Errors and Duration, per service. USE (Brendan Gregg): Utilization, Saturation and Errors, per resource (CPU, memory, disk, network). RED tells you users are hurting; USE helps find which resource is why.",
     "The letters describe requests, not machines."),
]


def starter(card):
    _, _, _, _, question, choices, _, _, _ = card
    lines = ["Concept check (no execution): nothing runs; the runtime checks your answer when you Submit.", "", question, ""]
    if choices:
        lines += [f"  {letter}) {text}" for letter, text in choices.items()]
        lines += ["", "Write the letter of your choice after \"answer:\" (several letters separated by commas if several are right), save, then Submit."]
    else:
        lines += ["Write your short answer after \"answer:\", save, then Submit."]
    return "\n".join(lines + ["answer:", ""])


def main():
    exercises, grading, mutants = [], {}, {}
    ref_path, ref_title = REFERENCE
    for card in CARDS:
        cid, topic, difficulty, title, question, choices, correct, why, hint = card
        kind = "choice" if choices else "text"
        eid = PREFIX + cid
        exercises.append({
            "schema_version": 1, "id": eid, "version": "1", "title": title, "difficulty": difficulty,
            "topics": ["observability", topic], "tags": ["concept-check", "observability", topic], "origin": "authored",
            "language": "quiz", "runtime": "datapass-quiz-v1", "prompt": question,
            "sections": [{"title": "Concept check (no execution)",
                          "body": "Nothing runs here: the Infra Lab simulates Azure Monitor alerts but no Prometheus, Grafana or tracing backend. Answer in the file, save, and Submit; the runtime compares your answer with the pack's answer and explains it once you are right. The reference sheet (" + ref_title + ") covers the topic."}],
            "starter_source": starter(card),
            "fixtures": [{"id": eid + "-fixtures", "version": "1"}],
            "visible_checks": [{"id": "format", "description": "Your answer is well formed (Run checks only this)."}],
            "hidden_check_refs": ["answer"], "edge_check_refs": [],
            "hints": [hint, "Open the reference sheet: " + ref_title + "."],
            "solution": {"available": True, "reveal": "explicit"},
            "explanation": "The explanation comes with a correct submission, from the runtime.",
            "follow_ups": [], "canonical_placement": {"domain": "concepts", "topic": "observability"},
            "related_associations": ["practice/concepts", "lab/infra"], "validator_version": "quiz-v1",
            "runtime_requirements": [], "provenance": {"source": "Authored for Datapass Workbench; checked against the Prometheus and Grafana documentation and Google's SRE books on 2026-10-12"},
            "constraints": {"truth": "Concept check: no execution; the answer is compared by the runtime. No Prometheus or Grafana is simulated."},
            "context_refs": [ref_path], "truth": "concept-check",
        })
        base = {"kind": kind, "choices": list(choices) if choices else []}
        answer = {"check": "answer", **base, "why": why, **({"correct": correct} if choices else {"accepted": correct})}
        grading[eid] = {
            "solution": "answer: " + (", ".join(correct) if choices else correct[0]) + "\n",
            "fixtures": [
                {"id": "format", "visibility": "visible", "input_rows": [], "expected": [], "scenario": {"check": "format", **base}},
                {"id": "answer", "visibility": "hidden", "input_rows": [], "expected": [], "scenario": answer},
            ],
        }
        wrong = [c for c in (choices or {}) if c not in correct][:2] if choices else ["I don't know"]
        mutants[eid] = ["answer: " + w + "\n" for w in wrong]
    mutants[PREFIX + "promql-metric-types"].append("answer: counter\n")
    mutants[PREFIX + "slo-error-budget"].append("answer: 4.32\n")
    PACK.mkdir(parents=True, exist_ok=True)
    dump = lambda name, data: (PACK / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    dump("manifest.json", {"schema_version": 1, "id": "infra-concepts-v1", "version": "1",
                           "title": "Concept checks: observability, PromQL, Grafana, SLOs and error budgets (no execution)",
                           "enabled": True, "provenance": {"source": "Authored for Datapass Workbench"}})
    dump("exercises.json", exercises)
    dump("grading.server.json", grading)
    dump("quality.json", {"flags": {"runnable_starters": True}, "mutants": mutants})
    print(f"infra-concepts-v1: {len(exercises)} cards")


if __name__ == "__main__":
    main()
