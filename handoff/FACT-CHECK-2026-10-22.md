# Selected vendor fact checks — 2026-10-22

**E-FACTS-P2: PARTIAL.** This is a selected review, not verification of all 89 exercises in the two packs.
All corrected cards retain their existing graded answers. Their authoring generators and generated content
are kept in sync. Pack provenance is not promoted to a blanket vendor-verification claim.

| Exercise | Correction | Primary source |
| --- | --- | --- |
| `infra-concept-slo-burn-rate` | Google's recommended examples page at 14.4 over one hour and 6 over six hours; the 1 over three days example opens a ticket. Teams can adapt notification severity. The answer remains 2% of the 30-day budget. | [Google SRE workbook, Tables 5-6 and 5-8](https://sre.google/workbook/alerting-on-slos/) |
| `infra-concept-promql-histogram-quantile` | Scope the question, title, hint and explanation to a classic histogram. Native histograms use the base metric without `_bucket` or `le`. | [Prometheus histogram_quantile](https://prometheus.io/docs/prometheus/latest/querying/functions/#histogram_quantile) |
| `lc-airflow-xcom` | Scope database storage to the default BaseXCom backend. Object-storage and custom backends exist; passing small metadata remains the recommendation. | [Airflow XCom backends](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/xcoms.html) |

Selected unchanged checks:

- `lc-spark-shuffle-partitions`, `lc-spark-broadcast-threshold`, `lc-spark-aqe-skew`: defaults of 200 partitions and
  10 MB, plus AQE skew splitting, remain documented in [Spark performance tuning](https://spark.apache.org/docs/latest/sql-performance-tuning.html).
- `lc-airflow-catchup-default`: `catchup_by_default=False` remains documented in
  [Airflow configuration](https://airflow.apache.org/docs/apache-airflow/stable/configurations-ref.html#catchup-by-default).
- `lc-dbx-liquid-clustering`: changing clustering keys alone does not rewrite existing data, per
  [Databricks clustering](https://docs.databricks.com/aws/en/tables/clustering).
- `infra-concept-grafana-pending-period`: a three-minute breach with a five-minute pending period returns to Normal
  without firing, per [Grafana alert rules](https://grafana.com/docs/grafana/latest/alerting/alerting-rules/create-grafana-managed-rule/).
- `infra-concept-promql-rate`, `infra-concept-promql-sum-by`: counter reset handling and rate before aggregation
  remain correct, per [Prometheus rate](https://prometheus.io/docs/prometheus/latest/querying/functions/#rate).

These are documentation checks, not execution of Spark, Databricks, Airflow, Prometheus or Grafana. No provider
credentials, external services or real infrastructure were used for this review.

## Resumed review

The independent review covered all 17 Infra concept cards and selected Git/Bash learning text. The complete
72-card learning-check pack and every version of every documented platform remain outside this claim.

| Scope | Correction | Primary source |
| --- | --- | --- |
| Structured logs | Reliable queries require consistent field names, types and meanings; JSON syntax alone does not ensure this. | [OpenTelemetry log structure](https://opentelemetry.io/docs/concepts/signals/logs/#structured-unstructured-and-semistructured-logs) |
| SLI/SLO and outage budget | An objective can target a value/range; 43.2 minutes assumes time-based availability with the entire budget available. Request-based budgets count requests. | [Google SRE objectives](https://sre.google/sre-book/service-level-objectives/), [Embracing Risk](https://sre.google/sre-book/embracing-risk/), [availability table](https://sre.google/sre-book/availability-table/) |
| Prometheus summaries | Precomputed quantiles cannot generally be aggregated; sum and count can produce a combined mean. | [Prometheus histograms and summaries](https://prometheus.io/docs/practices/histograms/#count-and-sum-of-observations) |
| Bash `set -e` | It has documented conditional/command-list exceptions. Handle expected failures explicitly. The lesson now checks all inputs before moving them. | [GNU Bash set builtin](https://www.gnu.org/software/bash/manual/html_node/The-Set-Builtin.html) |
| Git merge | Preserving commit history does not imply conflict-free operation. Start clean, review and test the result. | [git-merge](https://git-scm.com/docs/git-merge#_description) |

Authoring generators and generated card explanations remain synchronized. These documentation checks do not
execute Prometheus/Grafana or constitute a full curriculum audit. The Bash documentation was available as
official indexed text; its direct fetch timed out during review.
