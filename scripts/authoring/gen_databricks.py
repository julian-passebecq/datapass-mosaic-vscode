"""Generate content/exercise-packs/databricks-v1 from authored specs.

Expected rows come from running each reference through the Databricks grader
(`datapass_runtime.databricks_grading.run_fixture`); review them by hand. Starters
and mutants must run and fail. Run from the repository root with PYTHONPATH=runtime.
"""
from __future__ import annotations

import copy
import json
import textwrap
from pathlib import Path

from pack_quality import write_mutants

ROOT = Path.cwd()
PACK = ROOT / "content" / "exercise-packs" / "databricks-v1"
EXERCISES: list[dict] = []
LANG = {"job": "databricks-job", "notebook": "databricks-notebook", "grants": "databricks-grants"}


def code(text: str) -> str:
    return textwrap.dedent(text).strip("\n") + "\n"


def nb(body: str) -> str:
    return "# Databricks notebook source\n" + code(body)


def job_json(data: dict) -> str:
    return json.dumps(data, indent=2) + "\n"


def exercise(**spec):
    EXERCISES.append(spec)


# -- shared lab files --------------------------------------------------------------------------------
NB_INGEST = nb("""
    from pyspark.sql import functions as F

    raw = spark.table("main.bronze.orders_raw")
    orders = raw.filter(F.col("net_amount") > 0)
    orders.write.mode("overwrite").saveAsTable("main.silver.orders")
    dbutils.jobs.taskValues.set(key="new_rows", value=orders.count())
""")
NB_SEGMENTS = nb("""
    segments = spark.table("main.source.dim_customer_segment")
    segments.write.mode("overwrite").saveAsTable("main.silver.dim_segment")
""")
NB_GOLD = nb("""
    from pyspark.sql import functions as F

    orders = spark.table("main.silver.orders")
    segments = spark.table("main.silver.dim_segment")
    gold = (orders.join(segments, "segment_id")
            .groupBy("segment_name")
            .agg(F.count("order_id").alias("orders"), F.sum("net_amount").alias("revenue")))
    gold.write.mode("overwrite").saveAsTable("main.gold.revenue_by_segment")
""")
NB_ALERT = nb("""
    dbutils.jobs.taskValues.set(key="alert", value="the retail job failed")
""")
NB_DAILY = nb("""
    from pyspark.sql import functions as F

    run_date = dbutils.widgets.get("run_date")
    orders = spark.table("main.silver.orders")
    daily = orders.groupBy("segment_id").agg(F.count("order_id").alias("orders")).withColumn("load_date", F.lit(run_date))
    daily.write.mode("overwrite").saveAsTable("main.gold.daily_orders")
""")
NB_SEGMENT_REPORT = nb("""
    from pyspark.sql import functions as F

    segment_id = int(dbutils.widgets.get("segment_id"))
    orders = spark.table("main.silver.orders").filter(F.col("segment_id") == segment_id)
    report = orders.groupBy("segment_id").agg(F.count("order_id").alias("orders"), F.sum("net_amount").alias("revenue"))
    report.write.mode("overwrite").saveAsTable("main.gold.segment_report_" + str(segment_id))
""")
NOTEBOOKS = {"databricks:/Shared/nb_ingest_orders": NB_INGEST, "databricks:/Shared/nb_load_segments": NB_SEGMENTS,
             "databricks:/Shared/nb_gold_revenue": NB_GOLD, "databricks:/Shared/nb_alert": NB_ALERT,
             "databricks:/Shared/nb_daily_orders": NB_DAILY, "databricks:/Shared/nb_segment_report": NB_SEGMENT_REPORT}
ORDERS_RAW = [{"order_id": f"O-{i:03d}", "customer_id": f"C{i % 5:03d}", "segment_id": i % 4 + 1,
               "net_amount": float((i * 37) % 250 - 20)} for i in range(1, 25)]
ORDER_TYPES = {"order_id": "VARCHAR", "customer_id": "VARCHAR", "segment_id": "INTEGER", "net_amount": "DOUBLE"}


def raw_orders(rows=ORDERS_RAW):
    return {"name": "bronze.orders_raw", "rows": rows, "columns": list(ORDER_TYPES), "types": ORDER_TYPES}


SILVER_ORDERS = {"name": "silver.orders", "rows": [r for r in ORDERS_RAW if r["net_amount"] > 0],
                 "columns": list(ORDER_TYPES), "types": ORDER_TYPES}


def task(key, notebook=None, deps=(), **extra):
    item = {"task_key": key}
    if deps:
        item["depends_on"] = [{"task_key": d} if isinstance(d, str) else {"task_key": d[0], "outcome": d[1]} for d in deps]
    if notebook:
        item["notebook_task"] = {"notebook_path": f"/Workspace/Shared/{notebook}"}
    item.update(extra)
    return item


def scenario(**kw):
    base = {"files": {"notebooks": dict(NOTEBOOKS)}, "tables": [raw_orders()]}
    files = kw.pop("files", None)
    if files:
        base["files"].update(files)
    base.update(kw)
    return base


def pack_job(name, tasks, **settings):
    return {"name": name, "tasks": tasks, **settings}


# 1 -------------------------------------------------------------------------------------------------
STAR_TASKS = [task("ingest_orders", "nb_ingest_orders"), task("load_segments", "nb_load_segments"),
              task("gold_revenue", "nb_gold_revenue", ["ingest_orders", "load_segments"])]
exercise(
    id="dbx-fan-in-dependencies", title="Tasks that wait for each other", difficulty="easy", language="job",
    topics=["jobs", "task-dependencies"],
    prompt=("Write the job retail_star (Jobs API JSON). Three notebook tasks on serverless compute: ingest_orders "
            "(/Workspace/Shared/nb_ingest_orders) and load_segments (/Workspace/Shared/nb_load_segments) have no "
            "dependency and run in parallel; gold_revenue (/Workspace/Shared/nb_gold_revenue) joins their outputs, so it "
            "must wait for both."),
    sections=[("Graded", "When each task starts and ends, and its state, including a run where load_segments is slow.")],
    starter=job_json(pack_job("retail_star", [task("ingest_orders", "nb_ingest_orders"), task("load_segments", "nb_load_segments"),
                                              task("gold_revenue", "nb_gold_revenue")])),
    solution=job_json(pack_job("retail_star", STAR_TASKS)),
    fixtures=[
        ("parallel", "visible", scenario(columns=["task", "state", "start_s", "end_s"])),
        ("slow-segments", "hidden", scenario(tasks={"load_segments": {"duration_seconds": 300}},
                                             columns=["task", "state", "start_s", "end_s"])),
        ("gold-table", "edge", scenario(outcome="table", table="gold.revenue_by_segment")),
    ],
    mutants=[job_json(pack_job("retail_star", STAR_TASKS[:2] + [task("gold_revenue", "nb_gold_revenue", ["ingest_orders"])])),
             job_json(pack_job("retail_star", [STAR_TASKS[0], task("load_segments", "nb_load_segments", ["ingest_orders"]),
                                               STAR_TASKS[2]]))],
    hints=["A task without depends_on starts as soon as the job starts.",
           "depends_on takes a list: [{\"task_key\": \"ingest_orders\"}, {\"task_key\": \"load_segments\"}]."],
    explanation=("gold_revenue lists both tasks in depends_on, so it starts when the slower one ends; ingest_orders and "
                 "load_segments have no dependency and run side by side. Chaining load_segments after ingest_orders "
                 "would also be correct data-wise, but it wastes time: they don't need each other."),
    follow_ups=["What would happen to gold_revenue if load_segments failed?"],
)

# 2 -------------------------------------------------------------------------------------------------
ALERT_SOLUTION = STAR_TASKS + [task("notify_on_failure", "nb_alert", ["ingest_orders", "load_segments", "gold_revenue"],
                                    run_if="AT_LEAST_ONE_FAILED")]
exercise(
    id="dbx-failure-alert", title="An alert task that runs only on failure", difficulty="easy", language="job",
    topics=["jobs", "run-if", "failure-handling"],
    prompt=("The retail_star job is given. Add a task notify_on_failure (/Workspace/Shared/nb_alert) that runs only when "
            "ingest_orders, load_segments or gold_revenue fails, and is skipped otherwise."),
    sections=[("Graded", "The state of every task in a normal run and when gold_revenue fails, and the run status and "
                         "leaf tasks when ingest_orders fails."),
              ("Run if", "ALL_SUCCESS (default), AT_LEAST_ONE_SUCCESS, NONE_FAILED, ALL_DONE, AT_LEAST_ONE_FAILED, "
               "ALL_FAILED. An unmet failure condition makes the task Excluded; Upstream failed counts as failed.")],
    starter=job_json(pack_job("retail_star", STAR_TASKS)), solution=job_json(pack_job("retail_star", ALERT_SOLUTION)),
    fixtures=[
        ("normal-run", "visible", scenario(columns=["task", "state"])),
        ("gold-fails", "hidden", scenario(tasks={"gold_revenue": {"fail_attempts": "all"}}, columns=["task", "state"])),
        ("ingest-fails-status", "edge", scenario(tasks={"ingest_orders": {"fail_attempts": "all"}}, outcome="run",
                                                 columns=["result_state", "leaves"])),
    ],
    mutants=[job_json(pack_job("retail_star", STAR_TASKS + [task("notify_on_failure", "nb_alert",
                                                                 ["ingest_orders", "load_segments", "gold_revenue"], run_if="ALL_DONE")])),
             job_json(pack_job("retail_star", STAR_TASKS + [task("notify_on_failure", "nb_alert",
                                                                 ["ingest_orders", "load_segments", "gold_revenue"], run_if="ALL_FAILED")]))],
    hints=["run_if decides whether a task runs from the states of its dependencies.",
           "When gold_revenue fails, ingest_orders and load_segments still succeeded."],
    explanation=("AT_LEAST_ONE_FAILED runs the alert as soon as any dependency failed (Upstream failed counts as failed), "
                 "and marks it Excluded otherwise, which counts as success. ALL_DONE would alert on every run; "
                 "ALL_FAILED only when all three failed. Note the run status: the alert is now the only leaf task, so "
                 "when it runs and succeeds the run ends Succeeded with failures, not Failed. Databricks decides the "
                 "status from the leaf tasks."),
    follow_ups=["How would you keep the run Failed while still sending the alert?"],
)

# 3 -------------------------------------------------------------------------------------------------
IF_TASKS = [task("load_segments", "nb_load_segments"), task("ingest_orders", "nb_ingest_orders", ["load_segments"]),
            {"task_key": "has_new_rows", "depends_on": [{"task_key": "ingest_orders"}],
             "condition_task": {"op": "GREATER_THAN", "left": "{{tasks.ingest_orders.values.new_rows}}", "right": "0"}},
            task("gold_revenue", "nb_gold_revenue", [("has_new_rows", "true")])]


def if_tasks(condition):
    return IF_TASKS[:2] + [{"task_key": "has_new_rows", "depends_on": [{"task_key": "ingest_orders"}],
                            "condition_task": condition}, IF_TASKS[3]]


EMPTY_RAW = raw_orders([])
exercise(
    id="dbx-if-new-rows", title="Skip the gold task when nothing new arrived", difficulty="medium", language="job",
    topics=["jobs", "if-else", "task-values"],
    prompt=("ingest_orders sets the task value new_rows (the number of rows it loaded). Add an If/else condition task "
            "has_new_rows that checks new_rows > 0, and run gold_revenue only on its true branch. Keep load_segments "
            "and ingest_orders as they are."),
    sections=[("Graded", "Every task's state and the condition's outcome, with new orders and with an empty load."),
              ("If/else", "condition_task {op, left, right}: == and != compare text, the other operators compare "
               "numbers. Downstream tasks depend on {\"task_key\": \"has_new_rows\", \"outcome\": \"true\"}.")],
    starter=job_json(pack_job("retail_if", IF_TASKS[:2] + [task("gold_revenue", "nb_gold_revenue", ["ingest_orders"])])),
    solution=job_json(pack_job("retail_if", IF_TASKS)),
    fixtures=[
        ("new-rows", "visible", scenario(columns=["task", "state", "outcome"])),
        ("empty-load", "hidden", scenario(tables=[EMPTY_RAW], columns=["task", "state", "outcome"])),
        ("empty-status", "edge", scenario(tables=[EMPTY_RAW], outcome="run", columns=["result_state"])),
    ],
    mutants=[job_json(pack_job("retail_if", if_tasks({"op": "GREATER_THAN", "left": "0",
                                                      "right": "{{tasks.ingest_orders.values.new_rows}}"}))),
             job_json(pack_job("retail_if", if_tasks({"op": "NOT_EQUAL", "left": "{{tasks.ingest_orders.values.new_rows}}",
                                                      "right": "0.0"})))],
    hints=["The operand {{tasks.ingest_orders.values.new_rows}} reads the task value.",
           "The task on the false branch of an If/else is Excluded, and an excluded task counts as successful."],
    explanation=("GREATER_THAN compares the operands as numbers, so 12 > 0 is true and 0 > 0 is false: gold_revenue "
                 "runs only when rows arrived, and the run still Succeeds when it is excluded. NOT_EQUAL compares text: "
                 "'0' != '0.0' is true, so the empty load would still run gold."),
    follow_ups=["Which run_if would make a task run on both branches once the condition is evaluated?"],
)

# 4 -------------------------------------------------------------------------------------------------
TV_JOB = pack_job("retail_if", IF_TASKS)


def tv_notebook(count_expr="orders.count()", setter=True):
    body = f"""
        from pyspark.sql import functions as F

        raw = spark.table("main.bronze.orders_raw")
        orders = raw.filter(F.col("net_amount") > 0)
        orders.write.mode("overwrite").saveAsTable("main.silver.orders")
    """
    body += (f'    dbutils.jobs.taskValues.set(key="new_rows", value={count_expr})\n' if setter
             else f'    dbutils.notebook.exit(str({count_expr}))\n')
    return nb(body)


def tv_scenario(**kw):
    return scenario(files={"jobs": {"retail_if": TV_JOB}}, job="retail_if", notebook="databricks:/Shared/nb_ingest_orders", **kw)


exercise(
    id="dbx-task-value-notebook", title="Pass a row count to the next task", difficulty="medium", language="notebook",
    topics=["notebooks", "task-values", "dbutils"],
    prompt=("Write the ingest notebook of the retail_if job: load the orders of main.bronze.orders_raw with a positive "
            "net_amount into main.silver.orders (overwrite), and set the task value new_rows to the number of rows you "
            "wrote. The job's If/else task reads {{tasks.ingest_orders.values.new_rows}}."),
    sections=[("Graded", "The task values of ingest_orders, the silver table, and the downstream states on an empty load."),
              ("Task values", "dbutils.jobs.taskValues.set(key=..., value=...) stores a JSON value for later tasks. The "
               "notebook exit value (dbutils.notebook.exit) is not readable by other tasks.")],
    starter=tv_notebook(setter=False), solution=tv_notebook(),
    fixtures=[
        ("values", "visible", tv_scenario(outcome="values", only=["ingest_orders"], columns=["task", "key", "value"])),
        ("silver", "hidden", tv_scenario(outcome="table", table="silver.orders")),
        ("empty-load", "edge", tv_scenario(tables=[EMPTY_RAW], columns=["task", "state", "outcome"])),
    ],
    mutants=[tv_notebook("raw.count()")],
    hints=["df.count() is an action: it returns a number you can store.",
           "dbutils.jobs.taskValues.set(key=\"new_rows\", value=...)."],
    explanation=("Task values are how Databricks tasks hand data to each other: the If/else task compares "
                 "{{tasks.ingest_orders.values.new_rows}}. The exit value of dbutils.notebook.exit is shown in the run "
                 "output but no dynamic value reference reads it, so the condition fails. Counting the raw table instead "
                 "of what you wrote would overstate new_rows."),
    follow_ups=["How would you pass the list of loaded dates instead of a count?"],
)

# 5 -------------------------------------------------------------------------------------------------
DAILY_TASK = task("daily_orders", "nb_daily_orders")


def daily_job(default=None, base=None):
    t = copy.deepcopy(DAILY_TASK)
    if base:
        t["notebook_task"]["base_parameters"] = base
    settings = {"parameters": [{"name": "run_date", "default": default}]} if default else {}
    return job_json(pack_job("daily_orders", [t], **settings))


def daily_scenario(**kw):
    return scenario(tables=[SILVER_ORDERS], outcome="table", table="gold.daily_orders", **kw)


exercise(
    id="dbx-job-parameters", title="A run date that follows the run", difficulty="medium", language="job",
    topics=["jobs", "job-parameters", "dynamic-value-references"],
    prompt=("The notebook /Workspace/Shared/nb_daily_orders reads the widget run_date and stamps it on "
            "main.gold.daily_orders. Write the job daily_orders so that run_date is a job parameter whose default is "
            "the date the run starts, and that can be overridden with Run now with different parameters."),
    sections=[("Graded", "The gold table for runs starting on different days, and for a run with run_date overridden."),
              ("Parameters", "Job parameters are pushed down to notebook tasks as widgets. Dynamic value references such "
               "as {{job.start_time.iso_date}} are resolved when the run starts.")],
    starter=daily_job(base={"run_date": "2026-03-05"}), solution=daily_job("{{job.start_time.iso_date}}"),
    fixtures=[
        ("march-5", "visible", daily_scenario()),
        ("april-10", "hidden", daily_scenario(now="2026-04-10T06:00:00Z")),
        ("override", "edge", daily_scenario(job_parameters={"run_date": "2026-03-01"})),
    ],
    mutants=[daily_job("{{job.start_time.iso_datetime}}"), daily_job("2026-03-05")],
    hints=["A job parameter is {\"name\": \"run_date\", \"default\": \"...\"} in the job's parameters list.",
           "{{job.start_time.iso_date}} gives the run's start date as YYYY-MM-DD."],
    explanation=("A job parameter with the default {{job.start_time.iso_date}} gives every run its own date and can be "
                 "overridden per run; it reaches the notebook as the run_date widget. A literal date in "
                 "base_parameters is frozen, and iso_datetime adds the time of day."),
    follow_ups=["How would you backfill three past days with the same job?"],
)

# 6 -------------------------------------------------------------------------------------------------
def retry_job(**extra):
    return job_json(pack_job("flaky_ingest", [task("ingest_orders", "nb_ingest_orders", **extra)]))


RETRY_SOLUTION = dict(max_retries=2, min_retry_interval_millis=60000, timeout_seconds=600)
exercise(
    id="dbx-retries-timeout", title="Retry transient failures, not slow runs", difficulty="medium", language="job",
    topics=["jobs", "retries", "timeouts"],
    prompt=("The source of ingest_orders sometimes drops the connection. Make the task retry up to 2 times, waiting 1 "
            "minute between attempts, and stop any attempt that runs longer than 10 minutes, without retrying it."),
    sections=[("Graded", "The task's state, number of attempts and timing when it fails once, fails twice, and when "
                         "it is too slow.")],
    starter=retry_job(), solution=retry_job(**RETRY_SOLUTION),
    fixtures=[
        ("fails-once", "visible", scenario(tasks={"ingest_orders": {"fail_attempts": [1]}},
                                           columns=["task", "state", "attempts", "start_s", "end_s"])),
        ("fails-twice", "hidden", scenario(tasks={"ingest_orders": {"fail_attempts": [1, 2]}},
                                           columns=["task", "state", "attempts", "start_s", "end_s"])),
        ("too-slow", "edge", scenario(tasks={"ingest_orders": {"duration_seconds": 900}},
                                      columns=["task", "state", "attempts", "end_s"])),
    ],
    mutants=[retry_job(**RETRY_SOLUTION, retry_on_timeout=True), retry_job(max_retries=2, timeout_seconds=600),
             retry_job(max_retries=1, min_retry_interval_millis=60000, timeout_seconds=600)],
    hints=["max_retries, min_retry_interval_millis and timeout_seconds are task settings.",
           "A timed-out attempt is retried only with retry_on_timeout: true."],
    explanation=("max_retries 2 with a 60,000 ms interval rides over transient failures; timeout_seconds 600 cuts a stuck "
                 "attempt, and since retry_on_timeout is false by default a timeout ends the task instead of tripling "
                 "the wait."),
    follow_ups=["When would retrying on timeout be the right choice?"],
)

# 7 -------------------------------------------------------------------------------------------------
CLUSTER = {"job_cluster_key": "etl", "new_cluster": {"spark_version": "15.4.x-scala2.12", "node_type_id": "Standard_DS3_v2",
                                                    "num_workers": 2}}


def cluster_job(where):
    tasks = copy.deepcopy(STAR_TASKS)
    clusters = []
    for index, t in enumerate(tasks):
        if where == "all-purpose":
            t["existing_cluster_id"] = "analytics-shared"
        elif where == "shared":
            t["job_cluster_key"] = "etl"
            clusters = [CLUSTER]
        elif where == "per-task":
            key = f"etl_{index}"
            t["job_cluster_key"] = key
            clusters.append({**copy.deepcopy(CLUSTER), "job_cluster_key": key})
        elif where == "big":
            t["job_cluster_key"] = "etl"
            clusters = [{"job_cluster_key": "etl", "new_cluster": {**CLUSTER["new_cluster"], "num_workers": 8}}]
    settings = {"job_clusters": clusters} if clusters else {}
    return job_json(pack_job("retail_star", tasks, **settings))


COMPUTE = {"clusters": [{"cluster_id": "analytics-shared", "cluster_name": "Shared analytics", "node_type_id": "Standard_DS3_v2",
                         "num_workers": 2, "autotermination_minutes": 60, "state": "TERMINATED"}],
           "warehouses": [{"id": "serverless-sql", "name": "Serverless Starter Warehouse", "cluster_size": "2X-Small"}]}
exercise(
    id="dbx-shared-job-cluster", title="Run a scheduled job on a job cluster", difficulty="medium", language="job",
    topics=["compute", "job-clusters", "cost"],
    prompt=("retail_star runs its three tasks on the all-purpose cluster analytics-shared, which bills more per DBU and "
            "stays up idle for an hour after the run. Move the three tasks to one job cluster named etl "
            "(spark_version 15.4.x-scala2.12, node Standard_DS3_v2, 2 workers) that they share."),
    sections=[("Graded", "The compute the run uses: kind, tasks, start-up, billed time and DBUs."),
              ("The lab's compute model", "A job cluster starts when its first task is ready (300 s), bills at the jobs "
               "compute rate and terminates after its last task. Rates and times are teaching values; their order is real.")],
    starter=cluster_job("all-purpose"), solution=cluster_job("shared"),
    fixtures=[
        ("compute", "visible", scenario(files={"compute": COMPUTE}, outcome="compute",
                                        columns=["kind", "key", "tasks", "startup_s", "billed_s", "dbu"])),
        ("duration", "hidden", scenario(files={"compute": COMPUTE}, outcome="run", columns=["result_state", "duration_s"])),
        ("idle-cost", "edge", scenario(files={"compute": COMPUTE}, outcome="compute", columns=["kind", "idle_cost"])),
    ],
    mutants=[cluster_job("per-task"), cluster_job("big")],
    hints=["Declare the cluster once in job_clusters, then set job_cluster_key on each task.",
           "A job cluster per task starts three clusters, and gold_revenue waits for its own start-up."],
    explanation=("One shared job cluster starts once, runs the three tasks at the jobs compute rate and terminates "
                 "after gold_revenue: no idle hour, no second start-up. A cluster per task pays three start-ups and "
                 "delays gold_revenue; a bigger cluster bills more DBUs for work that doesn't need it."),
    follow_ups=["When is serverless compute a better choice than a job cluster?"],
)

# 8 -------------------------------------------------------------------------------------------------
NB_NIGHTLY_SILVER = nb("""
    from pyspark.sql import functions as F

    orders = spark.table("main.source.orders").filter(F.col("net_amount") > 0)
    orders.write.mode("overwrite").saveAsTable("main.silver.orders")
""")
NB_NIGHTLY_GOLD = nb("""
    from pyspark.sql import functions as F

    orders = spark.table("main.silver.orders")
    segments = spark.table("main.source.dim_customer_segment")
    daily = orders.join(segments, "segment_id").groupBy("segment_name").agg(F.sum("net_amount").alias("revenue"))
    daily.write.mode("overwrite").saveAsTable("main.gold.revenue_daily")
""")
NIGHTLY = pack_job("nightly_revenue", [task("silver_orders", "nb_nightly_silver"),
                                       task("gold_revenue", "nb_nightly_gold", ["silver_orders"])],
                   run_as={"service_principal_name": "sp-etl"})
GRANT_FILES = {"notebooks": {**NOTEBOOKS, "databricks:/Shared/nb_nightly_silver": NB_NIGHTLY_SILVER,
                             "databricks:/Shared/nb_nightly_gold": NB_NIGHTLY_GOLD},
               "jobs": {"nightly_revenue": NIGHTLY}, "unity_catalog": {"groups": {"analysts": ["bob@contoso.com"]}}}
GOLD_OTHER = {"name": "gold.customer_ltv", "rows": [{"customer_id": "C001", "ltv": 120.0}]}


def grants_scenario(**kw):
    return {"files": copy.deepcopy(GRANT_FILES), "tables": [SILVER_ORDERS, GOLD_OTHER], "job": "nightly_revenue", **kw}


LEAST = code("""
    GRANT USE SCHEMA ON SCHEMA main.source TO `sp-etl`;
    GRANT SELECT ON TABLE main.source.orders TO `sp-etl`;
    GRANT SELECT ON TABLE main.source.dim_customer_segment TO `sp-etl`;
    GRANT USE SCHEMA ON SCHEMA main.silver TO `sp-etl`;
    GRANT SELECT, MODIFY ON TABLE main.silver.orders TO `sp-etl`;
    GRANT USE SCHEMA, CREATE TABLE ON SCHEMA main.gold TO `sp-etl`;
""")
PROBES = [{"principal": "sp-etl", "action": "read", "object": "main.source.turbine_readings"},
          {"principal": "sp-etl", "action": "read", "object": "main.gold.customer_ltv"},
          {"principal": "sp-etl", "action": "create", "object": "main.silver.orders_copy"},
          {"principal": "sp-etl", "action": "read", "object": "main.gold.revenue_daily"}]
exercise(
    id="uc-least-privilege-job", title="Least privileges for a job's service principal", difficulty="hard",
    language="grants", topics=["unity-catalog", "privileges", "service-principals"],
    prompt=("The nightly_revenue job runs as the service principal sp-etl. Its first task reads main.source.orders and "
            "overwrites the existing main.silver.orders (owned by you); the second reads main.silver.orders and "
            "main.source.dim_customer_segment and creates main.gold.revenue_daily. Write the grants that let the job "
            "run, and nothing more: sp-etl must not read other source or gold tables, nor create silver tables."),
    sections=[("Graded", "The job's task states when it runs as sp-etl twice, and access checks for sp-etl afterwards."),
              ("Unity Catalog", "Reading a table needs USE CATALOG (all users have it on main), USE SCHEMA and SELECT; "
               "writing needs MODIFY and SELECT; creating needs CREATE TABLE on the schema, and the creator owns the "
               "new table. Privileges on a schema apply to all its tables. Grants to a table need the table to exist.")],
    starter=code("""
        -- Grants for the nightly_revenue job (runs as `sp-etl`).
    """), solution=LEAST,
    fixtures=[
        ("job-runs", "visible", grants_scenario(runs=2, columns=["task", "state", "error_code"])),
        ("nothing-more", "hidden", grants_scenario(outcome="access", access=PROBES)),
        ("owner-reads-its-table", "edge", grants_scenario(outcome="access", access=PROBES[3:])),
    ],
    mutants=[code("""
        GRANT ALL PRIVILEGES ON CATALOG main TO `sp-etl`;
    """), LEAST.replace("GRANT SELECT ON TABLE main.source.orders TO `sp-etl`;\nGRANT SELECT ON TABLE main.source.dim_customer_segment TO `sp-etl`;\n",
                        "GRANT SELECT ON SCHEMA main.source TO `sp-etl`;\n"),
             LEAST.replace("GRANT SELECT, MODIFY ON TABLE main.silver.orders", "GRANT MODIFY ON TABLE main.silver.orders")],
    hints=["Start from the error of the failing task: it names the missing privilege and the object.",
           "MODIFY alone is not enough to overwrite a table: the principal also needs SELECT on it."],
    explanation=("Table-level SELECT on the two source tables, SELECT and MODIFY on silver.orders, and CREATE TABLE on "
                 "the gold schema (with USE SCHEMA on each schema) are exactly what the job does. sp-etl then owns "
                 "gold.revenue_daily, so it can read and overwrite it on the next run without another grant. ALL "
                 "PRIVILEGES on the catalog, or SELECT on the whole source schema, would open tables the job never uses."),
    follow_ups=["Why is granting to a group better than granting to individual users?"],
)

# 9 -------------------------------------------------------------------------------------------------
NB_NEW_GOLD = nb("""
    spark.table("main.gold.revenue").write.mode("overwrite").saveAsTable("main.gold.revenue_copy")
""")
ANALYST_JOB = pack_job("publish_gold", [task("publish", "nb_publish_gold")])
ANALYST_FILES = {"notebooks": {"databricks:/Shared/nb_publish_gold": NB_NEW_GOLD}, "jobs": {"publish_gold": ANALYST_JOB},
                 "unity_catalog": {"groups": {"analysts": ["bob@contoso.com", "chen@contoso.com"]}}}
GOLD_REVENUE = {"name": "gold.revenue", "rows": [{"segment": "Consumer", "revenue": 150.0}]}


def analyst_scenario(probes):
    return {"files": copy.deepcopy(ANALYST_FILES), "tables": [GOLD_REVENUE, SILVER_ORDERS], "job": "publish_gold",
            "outcome": "access", "access": probes}


ANALYST = code("""
    GRANT USE SCHEMA, SELECT ON SCHEMA main.gold TO `analysts`;
""")
exercise(
    id="uc-analysts-read-gold", title="Analysts read every gold table, even new ones", difficulty="medium",
    language="grants", topics=["unity-catalog", "privileges", "inheritance"],
    prompt=("Members of the analysts group must be able to read every table of main.gold, including tables created "
            "after your grant, and nothing in main.silver. They must not change gold tables. Write the grants."),
    sections=[("Graded", "Access checks for members of analysts after a job creates a new gold table.")],
    starter=code("""
        GRANT SELECT ON TABLE main.gold.revenue TO `analysts`;
    """), solution=ANALYST,
    fixtures=[
        ("existing-table", "visible", analyst_scenario([{"principal": "bob@contoso.com", "action": "read", "object": "main.gold.revenue"},
                                                        {"principal": "bob@contoso.com", "action": "read", "object": "main.silver.orders"}])),
        ("new-table", "hidden", analyst_scenario([{"principal": "chen@contoso.com", "action": "read", "object": "main.gold.revenue_copy"}])),
        ("read-only", "edge", analyst_scenario([{"principal": "bob@contoso.com", "action": "write", "object": "main.gold.revenue"},
                                                {"principal": "dana@contoso.com", "action": "read", "object": "main.gold.revenue"}])),
    ],
    mutants=[code("""
        GRANT USE SCHEMA, SELECT ON SCHEMA main.gold TO `bob@contoso.com`;
    """), code("""
        GRANT USE SCHEMA ON SCHEMA main.gold TO `analysts`;
        GRANT SELECT ON TABLE main.gold.revenue TO `analysts`;
    """), code("""
        GRANT USE SCHEMA, SELECT ON CATALOG main TO `analysts`;
    """)],
    hints=["SELECT granted on a schema is inherited by every table in it, current and future.",
           "Grant to the group: its members get the privileges, people who join later too."],
    explanation=("USE SCHEMA and SELECT on the schema main.gold, granted to the group, cover every gold table including "
                 "the ones created later, for every member. A table-level grant misses new tables, a grant to one user "
                 "misses the rest of the group, and a grant on the catalog opens silver too."),
    follow_ups=["How would you let analysts discover silver tables without reading their data?"],
)

# 10 ------------------------------------------------------------------------------------------------
TURBINES = [{"sample_id": i, "wind_speed": round(3 + (i % 20) * 0.5, 2), "air_density": round(1.15 + (i % 7) * 0.01, 3),
             "power": round(20 * (3 + (i % 20) * 0.5) + 300 * (1.15 + (i % 7) * 0.01) + ((i * 37) % 11 - 5) * 0.8, 3)}
            for i in range(1, 61)]
TURBINE_TABLE = {"name": "bronze.turbine_training", "rows": TURBINES,
                 "types": {"sample_id": "INTEGER", "wind_speed": "DOUBLE", "air_density": "DOUBLE", "power": "DOUBLE"}}
TRAIN_HEAD = """
    import mlflow
    from pyspark.ml.feature import VectorAssembler
    from pyspark.ml.regression import LinearRegression
    from pyspark.ml.evaluation import RegressionEvaluator

    readings = spark.table("main.bronze.turbine_training")
    train, test = readings.randomSplit([0.8, 0.2], seed=7)
    assembler = VectorAssembler(inputCols=["wind_speed", "air_density"], outputCol="features")
    lr = LinearRegression(featuresCol="features", labelCol="power")
    evaluator = RegressionEvaluator(labelCol="power", predictionCol="prediction", metricName="rmse")
"""


def tracking_notebook(experiment=True, on="test"):
    body = TRAIN_HEAD + ('    mlflow.set_experiment("/Shared/power-forecast")\n' if experiment else '') + f"""
    with mlflow.start_run(run_name="linear-wind-density"):
        model = lr.fit(assembler.transform(train))
        rmse = evaluator.evaluate(model.transform(assembler.transform({on})))
        mlflow.log_param("features", "wind_speed,air_density")
        mlflow.log_metric("rmse", rmse)

    dbutils.jobs.taskValues.set(key="rmse", value=round(rmse, 3))
"""
    return nb(body)


TRAIN_JOB = pack_job("power_training", [task("train", "ml/nb_train")])


def train_scenario(**kw):
    return {"files": {"jobs": {"power_training": TRAIN_JOB}}, "tables": [TURBINE_TABLE], "job": "power_training",
            "notebook": "databricks:/Shared/ml/nb_train", **kw}


exercise(
    id="dbx-mlflow-tracking", title="Track a training run with MLflow", difficulty="medium", language="notebook",
    topics=["mlflow", "machine-learning", "spark-ml"],
    prompt=("The notebook trains a linear regression of power on wind_speed and air_density (80/20 split, seed 7). "
            "Track it with MLflow: in the experiment /Shared/power-forecast, a run named linear-wind-density that logs "
            "the parameter features = \"wind_speed,air_density\" and the metric rmse measured on the test split. Also "
            "set the task value rmse, rounded to 3 decimals."),
    sections=[("Graded", "The MLflow runs (experiment, run name, parameters, metrics) and the task value."),
              ("Lab ML", "pyspark.ml is a bounded subset: VectorAssembler, LinearRegression (least squares on the lab "
               "rows), RegressionEvaluator. randomSplit is stable per seed in the lab, not Spark's exact split.")],
    starter=nb(TRAIN_HEAD + """
    model = lr.fit(assembler.transform(train))
    rmse = evaluator.evaluate(model.transform(assembler.transform(test)))
"""), solution=tracking_notebook(),
    fixtures=[
        ("runs", "visible", train_scenario(outcome="mlflow_runs", columns=["experiment", "run_name", "params", "metrics"])),
        ("task-value", "hidden", train_scenario(outcome="values", columns=["key", "value"])),
        ("two-runs", "edge", train_scenario(runs=2, outcome="mlflow_runs", columns=["experiment", "run_name", "status"])),
    ],
    mutants=[tracking_notebook(on="train"), tracking_notebook(experiment=False)],
    hints=["with mlflow.start_run(run_name=...) as run: groups what you log into one run.",
           "Evaluate the model on test, not on the rows it was fitted on."],
    explanation=("set_experiment chooses where runs go (without it, a notebook's runs land in the notebook's own "
                 "experiment); start_run opens the run, log_param and log_metric record it, and each job run adds a new "
                 "MLflow run. The RMSE on the training rows is optimistic: measure it on the held-out test split."),
    follow_ups=["What else would you log to compare two feature sets fairly?"],
)

# 11 ------------------------------------------------------------------------------------------------
def register_notebook(example=True, name="main.ml.power_model", alias="info.registered_model_version"):
    example_arg = ', input_example=test.select("wind_speed", "air_density")' if example else ''
    body = TRAIN_HEAD + f"""    mlflow.set_registry_uri("databricks-uc")
    mlflow.set_experiment("/Shared/power-forecast")

    with mlflow.start_run(run_name="linear-wind-density"):
        model = lr.fit(assembler.transform(train))
        mlflow.log_metric("rmse", evaluator.evaluate(model.transform(assembler.transform(test))))
        info = mlflow.spark.log_model(model, "model"{example_arg}, registered_model_name="{name}")

    from mlflow import MlflowClient
    MlflowClient().set_registered_model_alias("{name}", "champion", {alias})
"""
    return nb(body)


ML_GRANTS = code("""
    GRANT USE SCHEMA, SELECT ON SCHEMA main.bronze TO `sp-ml`;
    GRANT USE SCHEMA, CREATE MODEL ON SCHEMA main.ml TO `sp-ml`;
""")
SP_TRAIN_JOB = pack_job("power_training", [task("train", "ml/nb_train")], run_as={"service_principal_name": "sp-ml"})


def register_scenario(**kw):
    return {"files": {"jobs": {"power_training": SP_TRAIN_JOB}, "grants": ML_GRANTS}, "tables": [TURBINE_TABLE],
            "job": "power_training", "notebook": "databricks:/Shared/ml/nb_train", **kw}


exercise(
    id="dbx-register-champion", title="Register a model and promote it with an alias", difficulty="hard",
    language="notebook", topics=["mlflow", "unity-catalog", "model-registry"],
    prompt=("Extend the training notebook (run by a job as the service principal sp-ml): log the fitted model with "
            "mlflow.spark.log_model, register it in Unity Catalog as main.ml.power_model, and point the alias champion "
            "at the version you just registered."),
    sections=[("Graded", "The versions of main.ml.power_model after one and two job runs: aliases, owner and signature."),
              ("Models in Unity Catalog", "Three-level names, a signature is required (pass input_example= or "
               "signature=), and aliases replace the old stages. The registering principal owns a new model.")],
    starter=nb(TRAIN_HEAD + """    mlflow.set_registry_uri("databricks-uc")
    mlflow.set_experiment("/Shared/power-forecast")

    with mlflow.start_run(run_name="linear-wind-density"):
        model = lr.fit(assembler.transform(train))
        mlflow.log_metric("rmse", evaluator.evaluate(model.transform(assembler.transform(test))))
"""), solution=register_notebook(),
    fixtures=[
        ("first-version", "visible", register_scenario(outcome="models", columns=["name", "version", "aliases", "owner"])),
        ("second-run", "hidden", register_scenario(runs=2, outcome="models", columns=["name", "version", "aliases"])),
        ("signature", "edge", register_scenario(outcome="models", columns=["version", "inputs"])),
    ],
    mutants=[register_notebook(example=False), register_notebook(alias="1")],
    hints=["log_model(..., registered_model_name=\"main.ml.power_model\") logs and registers in one call and returns "
           "the new version in registered_model_version.",
           "MlflowClient().set_registered_model_alias(name, \"champion\", version)."],
    explanation=("Registering with a three-level name creates the model in Unity Catalog (sp-ml owns it), an input "
                 "example gives the signature Unity Catalog requires, and moving the champion alias to the version you "
                 "just registered lets scoring jobs load models:/main.ml.power_model@champion without code changes. A "
                 "hard-coded version 1 leaves champion behind on the next run."),
    follow_ups=["How would you promote only when the new RMSE beats the champion's?"],
)

# 12 ------------------------------------------------------------------------------------------------
def version_notebook(features, alias_version="info.registered_model_version"):
    cols = ', '.join(f'"{f}"' for f in features)
    return nb(f"""
        import mlflow
        from pyspark.ml.feature import VectorAssembler
        from pyspark.ml.regression import LinearRegression

        readings = spark.table("main.bronze.turbine_training")
        model = LinearRegression(featuresCol="features", labelCol="power").fit(
            VectorAssembler(inputCols=[{cols}], outputCol="features").transform(readings))
        with mlflow.start_run(run_name="v"):
            info = mlflow.spark.log_model(model, "model", input_example=readings.select({cols}),
                                          registered_model_name="main.ml.power_model")

        from mlflow import MlflowClient
        MlflowClient().set_registered_model_alias("main.ml.power_model", "champion", {alias_version})
    """)


SCORING_FILES = {"notebooks": {"databricks:/Shared/ml/nb_v1": version_notebook(["wind_speed"]),
                               "databricks:/Shared/ml/nb_v2": version_notebook(["wind_speed", "air_density"]),
                               "databricks:/Shared/ml/nb_rollback": nb("""
                                   from mlflow import MlflowClient
                                   MlflowClient().set_registered_model_alias("main.ml.power_model", "champion", 1)
                               """)},
                 "jobs": {"train_v1": pack_job("train_v1", [task("train", "ml/nb_v1")]),
                          "train_v2": pack_job("train_v2", [task("train", "ml/nb_v2")]),
                          "rollback": pack_job("rollback", [task("alias", "ml/nb_rollback")]),
                          "score_power": pack_job("score_power", [task("score", "ml/nb_score")])}}


def scoring_scenario(setup, **kw):
    return {"files": copy.deepcopy(SCORING_FILES), "tables": [TURBINE_TABLE], "setup_jobs": setup, "job": "score_power",
            "notebook": "databricks:/Shared/ml/nb_score", "outcome": "table", "table": "gold.power_scored", **kw}


def scoring_notebook(uri):
    return nb(f"""
        import mlflow

        model = mlflow.spark.load_model("{uri}")
        readings = spark.table("main.bronze.turbine_training")
        scored = model.transform(readings).select("sample_id", "power", "prediction")
        scored.write.mode("overwrite").saveAsTable("main.gold.power_scored")
    """)


exercise(
    id="dbx-batch-score-champion", title="Batch scoring with whatever version is champion", difficulty="medium",
    language="notebook", topics=["mlflow", "model-registry", "batch-inference"],
    prompt=("main.ml.power_model has several versions and the alias champion marks the one to use. Write the scoring "
            "notebook: load the champion model, score main.bronze.turbine_training, and write sample_id, power and "
            "prediction to main.gold.power_scored (overwrite)."),
    sections=[("Graded", "The scored table after the model was retrained, and after champion was rolled back to an "
                         "older version.")],
    starter=scoring_notebook("models:/main.ml.power_model/1"), solution=scoring_notebook("models:/main.ml.power_model@champion"),
    fixtures=[
        ("retrained", "visible", scoring_scenario(["train_v1", "train_v2"])),
        ("rolled-back", "hidden", scoring_scenario(["train_v1", "train_v2", "rollback"])),
        ("only-v1", "edge", scoring_scenario(["train_v1"])),
    ],
    mutants=[scoring_notebook("models:/main.ml.power_model/2")],
    hints=["A model URI can name a version (models:/<name>/2) or an alias (models:/<name>@champion).",
           "mlflow.spark.load_model returns a model with transform()."],
    explanation=("Loading models:/main.ml.power_model@champion resolves the alias at every run, so promoting or rolling "
                 "back a version changes what the job scores with, without touching the notebook. A version number "
                 "is frozen: it keeps scoring with the old model after a promotion, or with the new one after a rollback."),
    follow_ups=["Which privileges does a scoring job's principal need on the model?"],
)

# 13 ------------------------------------------------------------------------------------------------
def loop_job(inputs="{{job.parameters.segments}}", concurrency=2, segment="{{input}}", default="[1, 2, 3, 4]"):
    inner = task("segment_report", "nb_segment_report")
    inner["notebook_task"]["base_parameters"] = {"segment_id": segment}
    loop = {"task_key": "report_each_segment", "for_each_task": {"inputs": inputs, "task": inner}}
    if concurrency:
        loop["for_each_task"]["concurrency"] = concurrency
    return job_json(pack_job("segment_reports", [loop], parameters=[{"name": "segments", "default": default}]))


def loop_scenario(**kw):
    return scenario(tables=[SILVER_ORDERS], **kw)


exercise(
    id="dbx-for-each-segments", title="One report per segment with a for-each task", difficulty="medium",
    language="job", topics=["jobs", "for-each", "parameters"],
    prompt=("Write the job segment_reports: a for-each task report_each_segment that runs "
            "/Workspace/Shared/nb_segment_report once per segment id of the job parameter segments (a JSON array, "
            "default [1, 2, 3, 4]), passing each id as the notebook parameter segment_id, two iterations at a time."),
    sections=[("Graded", "The for-each task's state and end time, and the reports written, including a run with "
                         "segments [2, 4].")],
    starter=loop_job(concurrency=None), solution=loop_job(),
    fixtures=[
        ("timing", "visible", loop_scenario(columns=["task", "state", "end_s"])),
        ("report-3", "hidden", loop_scenario(outcome="table", table="gold.segment_report_3")),
        ("two-segments", "edge", loop_scenario(job_parameters={"segments": "[2, 4]"}, columns=["task", "state", "end_s"])),
    ],
    mutants=[loop_job(inputs="[1, 2, 3, 4]"), loop_job(segment="1"), loop_job(concurrency=4)],
    hints=["for_each_task takes inputs (a JSON array or a reference such as {{job.parameters.segments}}), concurrency "
           "and the task to repeat.",
           "{{input}} is the current item inside the nested task."],
    explanation=("The for-each task reads its inputs from the job parameter, so a run with other segments needs no "
                 "change, and {{input}} hands each id to the notebook. Concurrency 2 runs two notebooks at a time: four "
                 "segments take two rounds."),
    follow_ups=["What changes if one segment's notebook fails?"],
)


# -- pack assembly ---------------------------------------------------------------------------------
SIM = ("Your {what} runs on the lab's simulated Azure Databricks: job orchestration, compute and Unity Catalog follow "
       "Databricks' rules, and notebook and SQL tasks really run on an isolated local catalog built for each check "
       "(SparkLab, DuckDB). Nothing connects to Azure Databricks.")
WHAT = {"job": "job (Jobs API JSON)", "notebook": "notebook", "grants": "grants (Unity Catalog SQL)"}


def definition(spec: dict, rank: int) -> dict:
    by_visibility = {"visible": [], "hidden": [], "edge": []}
    for fid, visibility, _ in spec["fixtures"]:
        by_visibility[visibility].append(fid)
    sections = [{"title": "Simulator", "body": SIM.format(what=WHAT[spec["language"]])}]
    sections += [{"title": title, "body": body} for title, body in spec["sections"]]
    projections = {json.dumps(sc.get("columns")) for _, _, sc in spec["fixtures"]}
    exact = json.loads(projections.pop()) if len(projections) == 1 else None
    return {
        "schema_version": 1, "id": spec["id"], "version": "1", "title": spec["title"], "difficulty": spec["difficulty"],
        "topics": spec["topics"], "tags": ["cloud-lab", "databricks", "simulated"], "origin": "authored",
        "language": LANG[spec["language"]], "runtime": "datapass-databricks-sim-v1", "prompt": spec["prompt"],
        "sections": sections, "starter_source": spec["starter"],
        "fixtures": [{"id": f"{spec['id']}-fixtures", "version": "1"}],
        "visible_checks": [{"id": fid, "description": "Simulated Databricks outcome for the public scenario."}
                           for fid in by_visibility["visible"]],
        "hidden_check_refs": by_visibility["hidden"], "edge_check_refs": by_visibility["edge"],
        "hints": spec["hints"], "solution": {"available": True, "reveal": "explicit"},
        "explanation": spec["explanation"], "follow_ups": spec["follow_ups"],
        "canonical_placement": {"domain": "cloud-databricks", "topic": spec["topics"][0]},
        "related_associations": ["cloud-lab/databricks"],
        "recommendation": {"rank": rank, "reason": "Cloud Lab Databricks progression"},
        "validator_version": "rows-v2",
        "validation": {"kind": "rows", "ordered": False, "duplicate_sensitive": True, "relative_tolerance": 1e-09,
                       "absolute_tolerance": 1e-06, "required_columns": exact or [], "exact_schema": exact,
                       "forbidden_extra_columns": True, "null_semantics": "equal"},
        "runtime_requirements": ["databricks-simulator"],
        "provenance": {"source": "Authored for Datapass Workbench: Azure Databricks jobs, Unity Catalog and MLflow rules "
                                 "(Microsoft Learn)",
                       "fixtures": "Authored scenarios; expected rows computed by running the reference and reviewed"},
        "constraints": {"truth": "Simulated Azure Databricks: notebook and SQL tasks run on an isolated local catalog; "
                                 "orchestration, compute and Unity Catalog are simulated."},
        "truth": "simulated",
    }


def outcome(language, source, scenario):
    from databrickslab.exercise import DbxScenario, graded_columns, project
    from datapass_runtime.databricks_grading import JobRejected, run_fixture
    parsed = DbxScenario.model_validate(scenario)
    try:
        rows = run_fixture(LANG[language], source, parsed)
    except JobRejected as exc:
        return None, str(exc)
    return project(rows, graded_columns(parsed, rows)), None


def main() -> None:
    from datapass_runtime.exercise_contracts import RowValidation
    from datapass_runtime.exercise_packs import PackRegistry
    from datapass_runtime.exercise_validation import validate_result
    ids = [spec["id"] for spec in EXERCISES]
    assert len(ids) == len(set(ids))
    definitions, grading, problems = [], {}, []
    for rank, spec in enumerate(EXERCISES, start=1):
        public = definition(spec, rank)
        definitions.append(public)
        validation = RowValidation.model_validate(public["validation"])
        fixtures = []
        for fid, visibility, sc in spec["fixtures"]:
            rows, error = outcome(spec["language"], spec["solution"], copy.deepcopy(sc))
            if error:
                problems.append(f"{spec['id']}/{fid}: reference rejected: {error}")
                rows = []
            fixtures.append({"id": fid, "visibility": visibility, "input_rows": [], "scenario": sc, "expected": rows})
        grading[spec["id"]] = {"solution": spec["solution"], "fixtures": fixtures}
        for label, source in [("starter", spec["starter"])] + [(f"mutant {i}", m) for i, m in enumerate(spec["mutants"])]:
            failed = False
            for fixture in fixtures:
                rows, error = outcome(spec["language"], source, copy.deepcopy(fixture["scenario"]))
                if error:
                    problems.append(f"{spec['id']}: {label} does not run: {error}")
                    failed = True
                    break
                columns = list(rows[0]) if rows else list((fixture["expected"] or [{}])[0])
                if not validate_result({"rows": rows, "columns": columns, "truncated": False}, fixture["expected"], validation):
                    failed = True
            if not failed:
                problems.append(f"{spec['id']}: {label} passes every check")
    manifest = {"schema_version": 1, "id": "databricks-v1", "version": "1",
                "title": "Cloud Lab: Azure Databricks jobs, Unity Catalog and MLflow (simulated)", "enabled": True,
                "provenance": {"source": "Authored for Datapass Workbench"}}
    PackRegistry().register(manifest, definitions, grading)
    PACK.mkdir(parents=True, exist_ok=True)
    for name, data in (("manifest.json", manifest), ("exercises.json", definitions), ("grading.server.json", grading)):
        (PACK / name).write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8",
                                 newline="\n")
    write_mutants(PACK, {spec["id"]: spec["mutants"] for spec in EXERCISES})
    for spec in EXERCISES:
        print(f"== {spec['id']}")
        for fixture in grading[spec["id"]]["fixtures"]:
            print(f"   {fixture['id']:22s}", json.dumps(fixture["expected"], default=str)[:420])
    if problems:
        print("\nPROBLEMS:\n  " + "\n  ".join(problems))


if __name__ == "__main__":
    main()
