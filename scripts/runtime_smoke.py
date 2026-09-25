from importlib import resources
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time

# Trusted Python must never be inherited from the environment running the smoke.
os.environ.pop("DATAPASS_TRUSTED_PYTHON", None)

from datapass_runtime.main import app, capabilities
from datapass_runtime.pipeline_compiler import compile_response
from datapass_runtime.guided_spark import compile_guard
from datapass_runtime.content import cases, content_root
from datapass_runtime.exercises import definitions
from datapass_runtime.retail_demo import run_retail_demo
from datapass_runtime.kernels import KernelManager
from datapass_runtime.native_pipeline import run_native_pipeline
from sparklab.capabilities import SUPPORT
from sparklab.physical import simulate_plan
from sparklab.runtime import load_cluster_profiles
from sparklab.safe_parser import SafeSparkParser
from sparklab.sparklab import SparkSession
from airflowlab.model import AirflowLabError
from airflowlab.parser import parse_dag
from airflowlab.simulate import Scenario, outcome_rows
from factorylab.engine import FactoryScenario, simulate_pipeline
from factorylab.model import FactoryLabError


assert app.title == "Datapass Runtime"
assert SUPPORT["schema_version"] == 1
assert (content_root() / "cases").is_dir()
assert (content_root() / "exercise-packs").is_dir()
assert any(case.get("id") == "retail-medallion" for case in cases())
assert definitions(), "Expected installed exercise definitions from content/exercise-packs."
for asset in ("profiles.json", "cluster_profiles.json", "oracle.json"):
    assert resources.files("sparklab").joinpath(asset).is_file(), asset


def modeled_exchanges(body: str) -> tuple[dict, list]:
    """Exchange facts of the SparkLab plan model at authored sizes (no data processed)."""
    spark = SparkSession({"tables": {
        "sales": {"columns": ["sale_id", "store_id", "amount"]}, "stores": {"columns": ["store_id", "region"]},
        "orders": {"columns": ["order_id", "customer_id", "order_ts", "amount"]},
    }})
    parsed = SafeSparkParser(spark).parse(
        "from pyspark.sql import functions as F\nfrom pyspark.sql.window import Window\n" + body)
    gib = 1024 ** 3
    statistics = {"sales": {"rows": 6 * 10**8, "bytes": 72 * gib, "partitions": 576},
                  "stores": {"rows": 40_000, "bytes": 48 * 1024**2, "partitions": 1},
                  "orders": {"rows": 3 * 10**8, "bytes": 24 * gib, "partitions": 192}}
    profile = load_cluster_profiles(str(resources.files("sparklab").joinpath("cluster_profiles.json")))["generic_8x8"]
    _, metrics, _ = simulate_plan(parsed.dataframe, statistics, profile, True)
    facts = metrics["plan_facts"]
    return facts, [(d["reason"], d["partitioning"], d["keys"]) for d in facts["exchange_details"]]


# Exchange placement follows Spark's rules: satisfied distributions reuse partitioning.
facts, detail = modeled_exchanges('s = spark.table("sales").join(spark.table("stores"), "store_id")\ns.groupBy("region").agg(F.sum("amount").alias("r"))')
assert facts["exchanges"] == 3 and facts["shuffle_joins"] == 1, detail  # 48 MB > 10 MB threshold: sort-merge join
facts, detail = modeled_exchanges('s = spark.table("sales").join(F.broadcast(spark.table("stores")), "store_id")\ns.groupBy("region").agg(F.sum("amount").alias("r"))')
assert (facts["exchanges"], facts["broadcast_joins"]) == (1, 1), detail
facts, detail = modeled_exchanges('spark.table("stores").join(F.broadcast(spark.table("sales")), "store_id")')
assert facts["broadcast_joins"] == 0, "Spark refuses to broadcast more than 8 GB"
facts, detail = modeled_exchanges('o = spark.table("orders")\nt = o.groupBy("customer_id").agg(F.sum("amount").alias("t"))\no.join(t, "customer_id")')
assert facts["exchanges"] == 2 and detail[1][0] == "join left side", detail  # aggregated side is reused
facts, detail = modeled_exchanges('w = Window.partitionBy("customer_id").orderBy("order_ts")\nspark.table("orders").repartition(400).withColumn("n", F.row_number().over(w))')
assert facts["exchanges"] == 2, detail  # round-robin does not cluster by customer_id
facts, detail = modeled_exchanges('w = Window.partitionBy("customer_id").orderBy("order_ts")\nspark.table("orders").repartition(400, "customer_id").withColumn("n", F.row_number().over(w))')
assert facts["exchanges"] == 1 and facts["output_partitions"] == 400, detail
facts, detail = modeled_exchanges('spark.table("orders").select("order_id", "amount").coalesce(16)')
assert (facts["exchanges"], facts["output_partitions"]) == (0, 16), detail
facts, detail = modeled_exchanges('spark.table("orders").orderBy("order_ts").groupBy("customer_id").agg(F.count("*").alias("n"))')
assert facts["exchanges"] == 1, "EliminateSorts drops a sort under an order-insensitive aggregate"
facts, detail = modeled_exchanges('spark.table("orders").withColumn("n", F.row_number().over(Window.orderBy("order_ts")))')
assert (facts["global_windows"], facts["output_partitions"]) == (1, 1), detail
facts, detail = modeled_exchanges('a = spark.table("orders").groupBy("customer_id").agg(F.count("*").alias("n"))\na.withColumnRenamed("customer_id", "c").groupBy("c").agg(F.sum("n").alias("t"))')
assert facts["exchanges"] == 2, "renaming the partitioning key loses the partitioning"

# Airflow Lab: DAG files are parsed, never executed; semantics follow Airflow 3.
AIRFLOW_HEAD = (
    "from datetime import datetime, timedelta\n"
    "from airflow.sdk import DAG\n"
    "from airflow.providers.standard.operators.empty import EmptyOperator\n"
    "from airflow.providers.standard.sensors.filesystem import FileSensor\n"
    "from airflow.timetables.interval import CronDataIntervalTimetable\n"
)


def factory_files(flavor: str) -> dict:
    """The Factory Lab sample files, keyed the way the extension sends them (see src/factoryState.ts)."""
    root = Path(__file__).resolve().parents[1] / "samples" / "factory-lab"
    files = {"pipelines": {}, "datasets": {}, "procedures": {}, "notebooks": {}}
    if flavor == "fabric":
        for folder in (root / "fabric").glob("*.DataPipeline"):
            files["pipelines"][folder.name.removesuffix(".DataPipeline")] = json.loads((folder / "pipeline-content.json").read_text())
    else:
        for path in (root / flavor / "pipeline").glob("*.json"):
            files["pipelines"][path.stem] = json.loads(path.read_text())
        for path in (root / flavor / "dataset").glob("*.json"):
            files["datasets"][path.stem] = json.loads(path.read_text())
    for path in (root / "sql" / "procedures").glob("*.sql"):
        files["procedures"][path.stem] = path.read_text()
    for folder in (root / "fabric").glob("*.Notebook"):
        files["notebooks"]["fabric:" + folder.name.removesuffix(".Notebook")] = (folder / "notebook-content.py").read_text()
    for path in (root / "databricks").rglob("*.py"):
        files["notebooks"]["databricks:/" + path.relative_to(root / "databricks").with_suffix("").as_posix()] = path.read_text()
    return files


def airflow_rows(body: str, **scenario) -> list[dict]:
    return outcome_rows(parse_dag(AIRFLOW_HEAD + body), Scenario.model_validate(scenario))


for rejected, reason in [
    ("import os\n", "Unsupported import"),
    ("with DAG('d', schedule_interval='@daily', start_date=datetime(2026, 1, 1)):\n    EmptyOperator(task_id='a')\n",
     "removed in Airflow 3"),
    ("with DAG('d', schedule='@daily', start_date=datetime.now()):\n    EmptyOperator(task_id='a')\n",
     "dynamic start_date"),
    ("with DAG('d'):\n    a = EmptyOperator(task_id='a')\n    b = EmptyOperator(task_id='b')\n    [a] >> [b]\n",
     "list cannot be linked"),
    ("with DAG('d'):\n    EmptyOperator(task_id='a', depends_on_past=True)\n", "depends_on_past"),
]:
    try:
        parse_dag(AIRFLOW_HEAD + rejected)
        raise AssertionError(f"accepted: {rejected!r}")
    except AirflowLabError as error:
        assert reason in str(error), (reason, str(error))

ONE_RUN = "with DAG('d', schedule='@daily', start_date=datetime(2026, 3, 5)):\n"  # one run at the `now` used below
DAILY = "with DAG('d', schedule={schedule}, start_date=datetime(2026, 3, 1){extra}):\n    EmptyOperator(task_id='a')\n"
# CronTriggerTimetable (Airflow 3 default for presets): logical date = tick; catchup defaults to False.
runs = airflow_rows(DAILY.format(schedule="'@daily'", extra=""), now="2026-03-05T12:00:00Z", outcome="runs")
assert [r["logical_date"] for r in runs] == ["2026-03-05T00:00:00+00:00"], runs
runs = airflow_rows(DAILY.format(schedule="'@daily'", extra=", catchup=True"), now="2026-03-05T12:00:00Z", outcome="runs")
assert len(runs) == 5, runs
# CronDataIntervalTimetable: the latest complete interval; the run starts at its end.
runs = airflow_rows(DAILY.format(schedule="CronDataIntervalTimetable('0 0 * * *', timezone='UTC')", extra=""),
                    now="2026-03-05T12:00:00Z", outcome="runs")
assert [(r["logical_date"][:10], r["run_after"][:10]) for r in runs] == [("2026-03-04", "2026-03-05")], runs

# Trigger rules as in Airflow's TriggerRuleDep: one upstream fails, the other succeeds.
RULES = ["all_success", "all_failed", "all_done", "one_success", "one_failed", "none_failed",
         "none_failed_min_one_success", "none_skipped", "always"]
body = ONE_RUN + "    ok = EmptyOperator(task_id='ok')\n    bad = EmptyOperator(task_id='bad')\n" + "".join(
    f"    [ok, bad] >> EmptyOperator(task_id='{rule}', trigger_rule='{rule}')\n" for rule in RULES)
states = {row["task_id"]: row["state"] for row in airflow_rows(
    body, now="2026-03-05T12:00:00Z", outcome="task_instances", tasks={"bad": {"fail_attempts": "all"}})}
assert states == {"ok": "success", "bad": "failed", "all_success": "upstream_failed", "all_failed": "skipped",
                  "all_done": "success", "one_success": "success", "one_failed": "success",
                  "none_failed": "upstream_failed", "none_failed_min_one_success": "upstream_failed",
                  "none_skipped": "success", "always": "success"}, states

# Retries run while try_number <= retries; a sensor times out at the first false poke past its timeout.
retry = airflow_rows(ONE_RUN + "    EmptyOperator(task_id='a', retries=2, retry_delay=timedelta(minutes=1))\n",
                     now="2026-03-05T12:00:00Z", outcome="task_instances", tasks={"a": {"fail_attempts": "all"}})
assert (retry[0]["state"], retry[0]["try_number"], retry[0]["end_s"]) == ("failed", 3, 300.0), retry
sensor = airflow_rows(ONE_RUN + "    FileSensor(task_id='s', filepath='x', poke_interval=600, timeout=7200, soft_fail=True)\n",
                      now="2026-03-05T12:00:00Z", outcome="task_instances")
assert (sensor[0]["state"], sensor[0]["end_s"]) == ("skipped", 7800.0), sensor

# Templates render without Jinja or eval; variables removed in Airflow 3 are reported.
rendered = airflow_rows(
    "with DAG('d', schedule='@daily', start_date=datetime(2026, 3, 1)):\n"
    "    FileSensor(task_id='f', filepath='{{ ds }}/{{ macros.ds_add(ds, -1) }}/{{ data_interval_start | ds_nodash }}')\n",
    now="2026-03-02T01:00:00Z", outcome="rendered")
assert [r["value"] for r in rendered] == ["2026-03-02/2026-03-01/20260302"], rendered
try:
    airflow_rows("with DAG('d', schedule='@daily', start_date=datetime(2026, 3, 1)):\n"
                 "    FileSensor(task_id='f', filepath='{{ prev_ds }}')\n",
                 now="2026-03-02T01:00:00Z", outcome="rendered")
    raise AssertionError("prev_ds must be reported as removed")
except AirflowLabError as error:
    assert "removed" in str(error), error

def databricks_files() -> dict:
    """The Databricks Lab sample files, keyed the way the extension sends them (see src/factoryState.ts)."""
    root = Path(__file__).resolve().parents[1] / "samples" / "factory-lab" / "databricks"
    files = {"notebooks": {}, "sql": {}, "compute": json.loads((root / "compute.json").read_text(encoding="utf-8")),
             "unity_catalog": json.loads((root / "unity_catalog.json").read_text(encoding="utf-8")),
             "grants": (root / "grants.sql").read_text(encoding="utf-8")}
    for path in sorted(root.rglob("*.py")):
        files["notebooks"]["databricks:/" + path.relative_to(root).with_suffix("").as_posix()] = path.read_text(encoding="utf-8")
    for path in sorted(root.rglob("*.sql")):
        if path.name != "grants.sql":
            files["sql"]["databricks:/" + path.relative_to(root).as_posix()] = path.read_text(encoding="utf-8")
    return files


def databricks_job(name: str) -> dict:
    root = Path(__file__).resolve().parents[1] / "samples" / "factory-lab" / "databricks" / "jobs"
    return json.loads((root / f"{name}.json").read_text(encoding="utf-8"))


# Factory Lab engine: Data Factory orchestration semantics, without a workspace (everything simulated).
def fx(activities, scenario=None, flavor="fabric", parameters=None, variables=None):
    document = {"properties": {"activities": activities, "parameters": parameters or {}, "variables": variables or {}}}
    return simulate_pipeline(document, "pl", flavor, FactoryScenario.model_validate(scenario or {}))


def fx_act(name, kind, after=(), **props):
    """after: activity names (Succeeded) or (name, [conditions]) pairs."""
    depends = [{"activity": d, "dependencyConditions": ["Succeeded"]} if isinstance(d, str)
               else {"activity": d[0], "dependencyConditions": d[1]} for d in after]
    return {"name": name, "type": kind, "dependsOn": depends, "typeProperties": props}


FX_COPY = {"source": {}, "sink": {}}
FX_FAIL_A = {"activities": {"A": {"fail_attempts": "all"}}}
try_catch = fx([fx_act("A", "Copy", **FX_COPY), fx_act("B", "Wait", [("A", ["Failed"])], waitTimeInSeconds=1)], FX_FAIL_A)
assert try_catch.status == "Succeeded" and try_catch.evaluated == ["B"], (try_catch.status, try_catch.evaluated)
do_if_else = fx([fx_act("A", "Copy", **FX_COPY), fx_act("B", "Wait", ["A"], waitTimeInSeconds=1),
                 fx_act("C", "Wait", [("A", ["Failed"])], waitTimeInSeconds=1)], FX_FAIL_A)
assert do_if_else.status == "Failed" and do_if_else.evaluated == ["A", "C"], (do_if_else.status, do_if_else.evaluated)
completed = fx([fx_act("A", "Copy", **FX_COPY), fx_act("B", "Wait", [("A", ["Completed"])], waitTimeInSeconds=1)], FX_FAIL_A)
assert completed.status == "Succeeded", completed.status
loop = fx([fx_act("Loop", "ForEach", items="@pipeline().parameters.tables", isSequential=True,
                  activities=[fx_act("CopyTable", "Copy", **FX_COPY)])],
          {"activities": {"CopyTable": {"fail_on_items": ["orders"]}}},
          parameters={"tables": {"type": "array", "defaultValue": ["customers", "orders", "products"]}})
assert loop.status == "Failed" and [r.status for r in loop.runs if r.name == "CopyTable"] == ["Succeeded", "Failed", "Succeeded"]
# A variable cannot reference itself (Data Factory rejects it): count through a second variable.
until = fx([fx_act("Loop", "Until", expression="@greaterOrEquals(int(variables('i')), 3)",
                   activities=[fx_act("Next", "SetVariable", variableName="next", value="@string(add(int(variables('i')), 1))"),
                               fx_act("Inc", "SetVariable", ["Next"], variableName="i", value="@variables('next')")])],
           variables={"i": {"type": "String", "defaultValue": "0"}, "next": {"type": "String"}})
assert until.status == "Succeeded" and until.variables == {"i": "3", "next": "3"}, until.variables
polled = fx([fx_act("Poll", "Until", expression="@equals(variables('state'), 'READY')",
                    activities=[fx_act("Check", "WebActivity", url="https://status.example.invalid", method="GET"),
                                fx_act("Keep", "SetVariable", ["Check"], variableName="state",
                                       value="@activity('Check').output.status")])],
            {"activities": {"Check": {"outputs": [{"status": "RUNNING"}, {"status": "RUNNING"}, {"status": "READY"}]}}},
            variables={"state": {"type": "String"}})
assert polled.status == "Succeeded" and polled.runs[0].output == {"iterations": 3}, polled.runs[0]
try:
    fx([fx_act("Inc", "SetVariable", variableName="i", value="@string(add(int(variables('i')), 1))")],
       variables={"i": {"type": "String", "defaultValue": "0"}})
    raise AssertionError("a self-referencing SetVariable must be rejected")
except FactoryLabError as error:
    assert "cannot reference itself" in str(error.issues), error.issues
typed = fx([fx_act("Set", "SetVariable", variableName="n", value="@add(1, 2)")], variables={"n": {"type": "String"}})
assert typed.status == "Failed" and "cannot be updated" in typed.runs[0].error["message"], typed.runs[0].error
retried = simulate_pipeline({"properties": {"activities": [{"name": "C", "type": "Copy", "policy": {"retry": 2, "retryIntervalInSeconds": 60},
                                                           "typeProperties": FX_COPY}]}}, "pl", "adf",
                            FactoryScenario.model_validate({"activities": {"C": {"fail_attempts": [1, 2]}}}))
assert retried.status == "Succeeded" and (retried.runs[0].attempts, retried.runs[0].end_s) == (3, 210.0), retried.runs[0]
assert retried.runs[0].error is None and retried.runs[0].note.startswith("Succeeded on attempt 3 after 2 retries"), retried.runs[0]
message = fx([fx_act("L", "Lookup", source={}),
              fx_act("Set", "SetVariable", ["L"], variableName="msg",
                     value="Load @{pipeline().parameters.env} on @{formatDateTime(pipeline().TriggerTime, 'yyyy-MM-dd')} "
                           "max=@{activity('L').output.firstRow.maxdate} by @{pipeline().Pipeline}")],
             {"activities": {"L": {"output": {"firstRow": {"maxdate": "2026-03-04"}}}}},
             parameters={"env": {"type": "String", "defaultValue": "dev"}}, variables={"msg": {"type": "String"}})
assert message.variables["msg"] == "Load dev on 2026-03-05 max=2026-03-04 by pl", message.variables
for bad, flavor, expected in [
    ([fx_act("A", "Wait", waitTimeInSeconds=1), fx_act("Set", "SetVariable", variableName="v", value="@activity('A').output")], "fabric", "not an ancestor"),
    ([fx_act("N", "TridentNotebook", notebookId="nb")], "adf", "DatabricksNotebook"),
    ([fx_act("Ap", "AppendVariable", variableName="v", value="x")], "fabric", "needs an Array variable"),
    ([fx_act("L", "ForEach", items="@createArray(1)", activities=[fx_act("L2", "ForEach", items="@createArray(1)", activities=[])])],
     "fabric", "cannot be nested"),
]:
    try:
        fx(bad, flavor=flavor, variables={"v": {"type": "String"}})
        raise AssertionError(f"expected a validation error: {expected}")
    except FactoryLabError as error:
        assert expected in str(error.issues), (expected, error.issues)

# Pipeline notebooks on SparkLab: parameters cell, widgets, save modes, spark.sql, exit values.
with TemporaryDirectory(prefix="datapass-factory-notebook-smoke-") as temp:
    from datapass_runtime.catalog import Catalog
    from datapass_runtime.factory_workspace import FactoryWorkspace
    from sparklab.safe_parser import SafeSparkParser, SparkLabSyntaxError
    from sparklab.sparklab import SparkSession

    nb_catalog = Catalog(Path(temp), "duckdb")
    nb_catalog.execute("CREATE TABLE bronze.orders AS SELECT * FROM source.orders", "smoke")
    FABRIC_NB = (
        "# PARAMETERS CELL ********************\n\nrun_date = '2026-01-01'\nmin_amount = 0\n\n"
        "# CELL ********************\n\nfrom pyspark.sql import functions as F\n"
        "df = spark.table('bronze.orders').filter(F.col('net_amount') > min_amount).withColumn('d', F.lit(run_date))\n"
        "df.write.mode('overwrite').saveAsTable('silver.nb_orders')\n"
        "notebookutils.notebook.exit(f'{df.count()} rows for {run_date}')\n")
    nb = FactoryWorkspace(nb_catalog, {"notebooks": {"fabric:nb": FABRIC_NB, "fabric:flat": FABRIC_NB.replace("# PARAMETERS CELL", "# CELL")}})
    ran = nb.run_notebook("fabric", "nb", {"run_date": "2026-03-05", "min_amount": 100})
    assert ran["status"] == "success" and ran["exit_value"] == "4 rows for 2026-03-05", ran
    flat = nb.run_notebook("fabric", "flat", {"run_date": "2026-03-05", "min_amount": 100})
    assert flat["exit_value"] == "10 rows for 2026-01-01" and any("reassigned" in note for note in flat["notes"]), flat
    DBX_NB = ("dbutils.widgets.text('layer', 'silver')\nlayer = dbutils.widgets.get('layer')\n"
              "spark.table('bronze.orders').write.saveAsTable(layer + '.dbx_orders')\n"
              "spark.sql(\"DELETE FROM silver.dbx_orders WHERE net_amount <= 0\")\n"
              "dbutils.notebook.exit(spark.sql('SELECT * FROM silver.dbx_orders').count())\n")
    dbx = FactoryWorkspace(nb_catalog, {"notebooks": {"databricks:/Shared/dbx": DBX_NB, "databricks:/Shared/nowidget": "x = dbutils.widgets.get('missing')\n"}})
    first = dbx.run_notebook("databricks", "/Shared/dbx", {})
    assert first["status"] == "success" and first["exit_value"] == "10" and first["tables_written"] == ["silver.dbx_orders"], first
    second = dbx.run_notebook("databricks", "/Shared/dbx", {})  # Spark's default save mode is errorifexists
    assert second["status"] == "error" and "TABLE_OR_VIEW_ALREADY_EXISTS" in second["error"], second
    assert "InputWidgetNotDefined" in dbx.run_notebook("databricks", "/Shared/nowidget", {})["error"]
    assert "not found" in dbx.run_notebook("databricks", "/Shared/missing", {})["error"]
    # Ordinary SparkLab cells keep the bounded API: no writes, SQL strings or actions outside pipeline notebooks.
    for cell in ("df = spark.table('source.orders')\ndf.write.saveAsTable('silver.x')\n",
                 "df = spark.sql('SELECT 1')\n", "print('x')\ndf = spark.table('source.orders')\n",
                 "n = spark.table('source.orders').count()\n"):
        try:
            SafeSparkParser(SparkSession({"tables": {}})).parse(cell)
            raise AssertionError(f"SparkLab cell mode must reject: {cell!r}")
        except SparkLabSyntaxError:
            pass
    nb_catalog.close()

# SQL pool Lab: T-SQL translated to DuckDB runs for real; designs, distributions, partitions and plans are modelled.
with TemporaryDirectory(prefix="datapass-sqlpool-smoke-") as temp:
    from datapass_runtime.catalog import Catalog
    from datapass_runtime.sqlpool_database import CatalogDatabase
    from sqlpoollab.engine import SqlPool
    from sqlpoollab.model import Metadata, TableDesign
    from sqlpoollab.physical import distribution_stats

    pool_catalog = Catalog(Path(temp), "duckdb")
    pool_db = CatalogDatabase(pool_catalog)
    pool_meta = Metadata(Path(temp) / "sqlpool.json")

    def pool_run(script, flavor="synapse"):
        return SqlPool(pool_db, pool_meta, flavor, scale=1_000_000).run(script)

    def moves(result):
        return [(s["operation"], s["columns"]) for s in result.plan["steps"] if s["operation"] != "ReturnOperation"]

    built = pool_run(
        "CREATE TABLE dbo.dim_segment WITH (DISTRIBUTION = REPLICATE, CLUSTERED INDEX (segment_id)) AS\n"
        "SELECT segment_id, segment_name FROM source.dim_customer_segment;\n"
        "CREATE TABLE [dbo].[fact_orders] WITH (DISTRIBUTION = HASH([customer_id]), CLUSTERED COLUMNSTORE INDEX,\n"
        "    PARTITION (order_date RANGE RIGHT FOR VALUES ('2026-09-17', '2026-09-18'))) AS\n"
        "SELECT order_id, customer_id, segment_id, net_amount, CAST(LEFT(loaded_at, 10) AS DATE) AS order_date\n"
        "FROM source.orders OPTION (LABEL = 'CTAS : fact_orders');\n"
        "CREATE TABLE dbo.fact_rr WITH (DISTRIBUTION = ROUND_ROBIN) AS SELECT * FROM dbo.fact_orders;\n"
        "SELECT TOP 3 s.segment_name, SUM(f.net_amount) AS revenue FROM dbo.fact_orders AS f\n"
        "JOIN dbo.dim_segment AS s ON f.segment_id = s.segment_id\n"
        "WHERE f.order_date >= '2026-09-17' AND ISNULL(f.net_amount, 0) > 0 GROUP BY s.segment_name ORDER BY revenue DESC;\n"
        "EXPLAIN SELECT r.customer_id, COUNT(*) AS n FROM fact_rr r JOIN fact_orders o ON r.order_id = o.order_id\n"
        "GROUP BY r.customer_id;\n")
    assert [r.status for r in built] == ["ok"] * 5, [(r.kind, r.message) for r in built]
    assert moves(built[1]) == [("ShuffleMoveOperation", ["customer_id"])], built[1].plan
    report = built[3]
    assert report.rows == [{"segment_name": "Corporate", "revenue": 4500.0}, {"segment_name": "Small Business", "revenue": 325.0},
                           {"segment_name": "Consumer", "revenue": 150.0}], report.rows
    assert moves(report) == [("ShuffleMoveOperation", ["segment_name"])], report.plan  # the replicated join is local
    assert [(x["partitions_scanned"], x["partitions_total"]) for x in report.plan["scans"]] == [(2, 3)], report.plan
    explained = built[4]
    assert explained.kind == "EXPLAIN" and explained.rows == [], explained
    assert moves(explained) == [("ShuffleMoveOperation", ["order_id"])] * 2 + [("ShuffleMoveOperation", ["customer_id"])], explained.plan
    saved = json.loads((Path(temp) / "sqlpool.json").read_text(encoding="utf-8"))["tables"]["warehouse.fact_orders"]
    assert saved["distribution"] == "HASH" and saved["partition"]["boundaries"] == ["2026-09-17", "2026-09-18"], saved
    skew = distribution_stats(pool_db, pool_meta.tables["warehouse.fact_orders"], 12, 1_000_000)
    assert skew.skew_pct >= 10 and skew.heavy_values[0] == ("CORPORATE_ACCOUNT_01", 0.25), skew
    # A key seen once stands for many distinct values at scale: a unique key spreads evenly.
    unique = distribution_stats(pool_db, TableDesign("warehouse.fact_orders", "HASH", ["order_id"]), 12, 1_000_000)
    assert unique.skew_pct == 0 and unique.heavy_values == [] and unique.empty_distributions == 0, unique

    # Joins on hash columns: local only when the data types match; otherwise the smaller side moves.
    typed = pool_run(
        "CREATE TABLE dbo.k_int WITH (DISTRIBUTION = HASH(k)) AS SELECT CAST(1 AS INT) AS k;\n"
        "CREATE TABLE dbo.k_int2 WITH (DISTRIBUTION = HASH(k)) AS SELECT CAST(1 AS INT) AS k;\n"
        "CREATE TABLE dbo.k_big WITH (DISTRIBUTION = HASH(k)) AS SELECT CAST(1 AS BIGINT) AS k;\n"
        "EXPLAIN SELECT a.k, COUNT(*) AS n FROM dbo.k_int AS a JOIN dbo.k_int2 AS b ON a.k = b.k GROUP BY a.k;\n"
        "EXPLAIN SELECT a.k, COUNT(*) AS n FROM dbo.k_int AS a JOIN dbo.k_big AS b ON a.k = b.k GROUP BY a.k;\n")
    assert [r.status for r in typed] == ["ok"] * 5, [(r.kind, r.message) for r in typed]
    assert moves(typed[3]) == [], typed[3].plan
    assert moves(typed[4]) == [("ShuffleMoveOperation", ["k"])], typed[4].plan
    assert any("data types must match" in note for note in typed[4].plan["notes"]), typed[4].plan

    # Stored procedures: parameters with defaults, SQL Server style argument errors, nesting in one session.
    proc = pool_run(
        "CREATE PROCEDURE dbo.usp_daily @day DATE, @min_amount DECIMAL(10,2) = 0\nAS\nBEGIN\n"
        "    IF OBJECT_ID('dbo.daily_revenue') IS NOT NULL DROP TABLE dbo.daily_revenue;\n"
        "    CREATE TABLE dbo.daily_revenue WITH (DISTRIBUTION = ROUND_ROBIN, HEAP)\n"
        "    AS SELECT order_date, COUNT_BIG(*) AS orders FROM dbo.fact_orders\n"
        "       WHERE order_date = @day AND net_amount >= @min_amount GROUP BY order_date;\nEND\nGO\n"
        "EXEC dbo.usp_daily @day = '2026-09-17';\nSELECT orders FROM daily_revenue;\n"
        "EXEC dbo.usp_daily '2026-09-17', 100;\nSELECT orders FROM daily_revenue;\n"
        "DECLARE @n INT = (SELECT COUNT(*) FROM dbo.fact_orders);\nSELECT @n AS n;\n"
        "RENAME OBJECT dbo.daily_revenue TO daily_revenue_v1;\n")
    assert [r.status for r in proc] == ["ok"] * 8, [(r.kind, r.message) for r in proc]
    assert [c.kind for c in proc[1].children] == ["DROP TABLE", "CTAS"], proc[1].children
    assert proc[2].rows == [{"orders": 11}] and proc[4].rows[0]["orders"] < 11 and proc[6].rows == [{"n": 12}], proc
    assert "warehouse.daily_revenue_v1" in pool_meta.tables and "warehouse.daily_revenue" not in pool_meta.tables
    missing = pool_run("EXEC dbo.usp_daily;")[-1]
    assert missing.status == "error" and "expects parameter '@day'" in missing.message, missing

    # T-SQL idioms: TOP in a subquery, string dates in date functions, PRINT of an expression.
    idioms = pool_run(
        "DECLARE @best VARCHAR(40) = (SELECT TOP 1 segment_name FROM dbo.dim_segment ORDER BY segment_id DESC);\n"
        "PRINT CONCAT('Best: ', @best);\n"
        "SELECT DATEADD(day, 30, '2026-01-01') AS d, EOMONTH('2026-02-10') AS e, DATEDIFF(day, '2026-01-01', '2026-03-01') AS n;\n")
    assert [r.status for r in idioms] == ["ok"] * 3 and idioms[1].message == "Best: Public Sector", idioms
    assert idioms[2].rows == [{"d": "2026-01-31T00:00:00", "e": "2026-02-28", "n": 59}], idioms[2].rows

    # Partition switching moves a whole partition; TRUNCATE_TARGET replaces what the target partition held.
    switched = pool_run(
        "CREATE TABLE dbo.p_fact (id INT, d DATE) WITH (DISTRIBUTION = HASH(id), PARTITION (d RANGE RIGHT FOR VALUES ('2026-02-01')));\n"
        "CREATE TABLE dbo.p_stage (id INT, d DATE) WITH (DISTRIBUTION = HASH(id), PARTITION (d RANGE RIGHT FOR VALUES ('2026-02-01')));\n"
        "INSERT INTO dbo.p_fact VALUES (1, '2026-02-03');\n"
        "INSERT INTO dbo.p_stage VALUES (2, '2026-02-04'), (3, '2026-02-05');\n"
        "ALTER TABLE dbo.p_stage SWITCH PARTITION 2 TO dbo.p_fact PARTITION 2 WITH (TRUNCATE_TARGET = ON);\n"
        "SELECT COUNT(*) AS n, MIN(id) AS first_id FROM dbo.p_fact;\nSELECT COUNT(*) AS staged FROM dbo.p_stage;\n")
    assert [r.status for r in switched] == ["ok"] * 7, [(r.kind, r.message) for r in switched]
    assert switched[5].rows == [{"n": 2, "first_id": 2}] and switched[6].rows == [{"staged": 0}], switched
    refill = pool_run("INSERT INTO dbo.p_stage VALUES (4, '2026-02-06');\n"
                      "ALTER TABLE dbo.p_stage SWITCH PARTITION 2 TO dbo.p_fact PARTITION 2;\n")
    assert refill[-1].status == "error", refill[-1]

    # Platform rules are enforced with the platform's messages; learner SQL still goes through catalog validation.
    for flavor, script, expected in [
        ("synapse", "CREATE TABLE dbo.q AS SELECT * FROM source.orders;", "requires a DISTRIBUTION option"),
        ("synapse", "SELECT * INTO dbo.t2 FROM source.orders;", "use CREATE TABLE AS SELECT"),
        ("synapse", "CREATE TABLE dbo.p (d DATE) WITH (PARTITION (d RANGE RIGHT FOR VALUES ('2026-02-01', '2026-01-01')));",
         "ascending order"),
        ("synapse", "ALTER TABLE dbo.fact_orders SPLIT RANGE ('2026-09-17 12:00');", "Only empty partitions can be split"),
        ("synapse", "CREATE TABLE dbo.fk (a INT, CONSTRAINT f FOREIGN KEY (a) REFERENCES dbo.k_int (k) NOT ENFORCED);",
         "FOREIGN KEY constraints are not supported"),
        ("synapse", "CREATE SCHEMA staging;", "schemas are fixed"),
        ("synapse", "GRANT SELECT ON dbo.fact_orders TO analyst;", "not simulated"),
        ("synapse", "SELECT * FROM read_csv('secrets.csv');", "not filesystem or network table functions"),
        ("fabric", "CREATE TABLE dbo.fx (a INT) WITH (DISTRIBUTION = HASH(a));", "takes no DISTRIBUTION option"),
        ("fabric", "CREATE TABLE dbo.fy (a NVARCHAR(10));", "use varchar"),
        ("fabric", "CREATE TABLE dbo.fw (a INT PRIMARY KEY);", "NOT ENFORCED"),
        ("fabric", "RENAME OBJECT dbo.fact_rr TO fact_rr2;", "Synapse flavor only"),
    ]:
        refused = pool_run(script, flavor)[-1]
        assert refused.status == "error" and expected in refused.message, (script, refused)
    fabric = pool_run("CREATE TABLE dbo.fz WITH (CLUSTER BY (order_id)) AS SELECT order_id, net_amount FROM source.orders;",
                      "fabric")[-1]
    assert fabric.status == "ok" and "managed layout (Fabric), CLUSTER BY (order_id)" in fabric.message, fabric
    pool_catalog.close()

# BI Lab: warehouse scripts run on DuckDB; lineage is a static analysis of their SQL; star model checks are queries.
BI_SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "bi-lab"


def bi_scripts() -> list[dict]:
    return [{"path": f"bi/warehouse/{f.name}", "text": f.read_text(encoding="utf-8")}
            for f in sorted((BI_SAMPLE / "warehouse").glob("*.sql"))]


with TemporaryDirectory(prefix="datapass-bi-smoke-") as temp:
    from datapass_runtime.catalog import Catalog
    from bilab.lab import lab_view
    from bilab.lineage import Lineage
    from bilab.model import StarModel, check_model
    from bilab.script import run_script, split_script

    assert resources.files("bilab").joinpath("README.md").is_file()
    parts = split_script("-- header\nSELECT 1;\n\n/* note; */\nSELECT ';' AS x;\nSELECT 3")
    assert [(s.index, s.line, s.kind) for s in parts] == [(1, 2, "SELECT"), (2, 5, "SELECT"), (3, 6, "SELECT")], parts
    bi_catalog = Catalog(Path(temp), "duckdb")
    stopped = run_script(bi_catalog, "CREATE TABLE silver.t AS SELECT 1 AS a;\nCOPY silver.t TO 'x.csv';\nSELECT 2;", "smoke")
    assert [r.status for r in stopped] == ["success", "error"] and "outside the local SQL teaching contract" in stopped[1].message
    view = lab_view(bi_catalog, bi_scripts(), json.loads((BI_SAMPLE / "model.json").read_text(encoding="utf-8")), True)
    assert view["status"] == "ok" and all(s["status"] == "success" for s in view["statements"]), view["stopped"]
    tables = {t["name"]: t for t in view["tables"]}
    assert tables["gold.fct_sales"]["rows"] == 16 and tables["gold.dim_customer"]["rows"] == 9, tables["gold.fct_sales"]
    columns = {(c["table"], c["column"]): c for c in view["lineage"]["columns"]}
    net = columns[("gold.fct_sales", "net_amount")]
    assert net["transform"] == "expression" and net["sources"] == [
        "source.shop_order_lines.discount_amount", "source.shop_order_lines.quantity", "source.shop_order_lines.unit_price"], net
    assert columns[("gold.dim_customer", "valid_from")]["transform"] == "rename"
    assert columns[("gold.dim_customer", "valid_to")]["transform"] == "window"  # LEAD() OVER, not an aggregate
    assert columns[("gold.dim_date", "fiscal_year")]["transform"] == "generated"
    assert columns[("gold.fct_returns", "customer_key")]["origins"] == [
        "source.crm_customer_history.customer_id", "source.crm_customer_history.effective_date"], columns[("gold.fct_returns", "customer_key")]
    impact = {(i["table"], i["column"], i["effect"]) for i in view["lineage"]["impact"]["source.shop_orders.order_date"]}
    assert ("gold.fct_sales", "*", "rows") in impact and ("gold.fct_returns", "*", "rows") in impact, impact  # point-in-time join
    assert view["lineage"]["impact"]["source.crm_customers.email"] == [
        {"table": "gold.dim_customer", "column": "email", "effect": "value"}], view["lineage"]["impact"]["source.crm_customers.email"]
    checks = view["model"]["checks"]
    assert checks and all(c["status"] == "pass" for c in checks), [c for c in checks if c["status"] != "pass"]
    assert {c["check"] for c in checks} >= {"grain_unique", "scd2_no_overlap", "scd2_no_gap", "one_side_unique", "single_active_path"}
    bad_model = json.loads((BI_SAMPLE / "model.json").read_text(encoding="utf-8"))
    bad_model["relationships"][1]["active"] = True  # two active paths to dim_date
    bad_model["relationships"][2] = {"from": "gold.fct_sales.order_id", "to": "gold.dim_customer.customer_id"}
    failed = {(c["check"], c["status"]) for c in check_model(bi_catalog, StarModel.model_validate(bad_model))["checks"]}
    assert ("single_active_path", "fail") in failed and ("one_side_unique", "fail") in failed, failed
    assert lab_view(bi_catalog, [], {"tables": [{"name": "gold.x", "role": "dimension"}]}, False)["model"]["error"]
    # DML lineage: UPDATE ... FROM and MERGE feed the target's columns; conditions only decide rows.
    dml = Lineage({"gold.dim": ["id", "city", "valid_to"], "silver.chg": ["id", "city", "day"]})
    dml.add_script("scd.sql", "UPDATE gold.dim AS d SET valid_to = c.day FROM silver.chg AS c WHERE d.id = c.id;\n"
                              "MERGE INTO gold.dim AS d USING silver.chg AS s ON d.id = s.id\n"
                              "WHEN MATCHED THEN UPDATE SET city = s.city WHEN NOT MATCHED THEN INSERT (id, city) VALUES (s.id, s.city);")
    dml_view = dml.view()
    dml_columns = {c["column"]: c for c in dml_view["columns"] if c["table"] == "gold.dim"}
    assert dml_columns["valid_to"]["sources"] == ["silver.chg.day"] and dml_columns["city"]["transform"] == "copy", dml_columns
    assert {(i["source"], i["role"]) for i in dml_view["influence"]} >= {("silver.chg.id", "filter"), ("silver.chg.id", "merge")}
    assert not dml_view["issues"], dml_view["issues"]
    bi_catalog.close()

# dbt emulation: sandboxed Jinja, real DuckDB SQL, dbt Core semantics (scripts/dbt_oracle_smoke.py compares them
# with dbt Core when it is installed).
def bi_dbt_files() -> dict:
    folder = BI_SAMPLE / "dbt"
    return {f.relative_to(folder).as_posix(): f.read_text(encoding="utf-8") for f in folder.rglob("*") if f.is_file()}


with TemporaryDirectory(prefix="datapass-dbt-smoke-") as temp:
    from datapass_runtime.catalog import Catalog
    from bilab.script import run_script
    from dbtlab.lab import dbt_view

    assert resources.files("dbtlab").joinpath("README.md").is_file()
    dbt_catalog = Catalog(Path(temp), "duckdb")
    parsed = dbt_view(dbt_catalog, bi_dbt_files(), "parse", None, None, False, None)
    assert parsed["status"] == "parsed" and len(parsed["nodes"]) == 32 and not parsed["project"]["issues"], parsed["project"]
    missing = dbt_view(dbt_catalog, bi_dbt_files(), "build", ["stg_shop__orders"], None, False, None)
    assert missing["run"]["results"][0]["status"] == "error" and "does not exist" in missing["run"]["results"][0]["message"]
    run_script(dbt_catalog, (BI_SAMPLE / "warehouse" / "00_sources.sql").read_text(encoding="utf-8"), "smoke")
    built = dbt_view(dbt_catalog, bi_dbt_files(), "build", None, None, False, None)
    assert built["status"] == "success" and built["run"]["counts"]["success"] == 12 and built["run"]["counts"]["pass"] == 19, built["run"]["counts"]
    assert "not dbt Core" in built["truth"]
    dbt_columns = {(c["table"], c["column"]): c for c in built["lineage"]["columns"]}
    assert dbt_columns[("warehouse.fct_sales", "net_amount")]["origins"] == [
        "source.shop_order_lines.discount_amount", "source.shop_order_lines.quantity", "source.shop_order_lines.unit_price"]
    incremental = dbt_view(dbt_catalog, bi_dbt_files(), "run", ["fct_sales"], None, False, None)
    assert "{%" not in incremental["run"]["results"][0]["compiled"] and "where o.order_date >=" in incremental["run"]["results"][0]["compiled"]
    # A ref reached only in incremental runs is refused, as dbt Core does, until the depends_on hint declares it.
    without_hint = bi_dbt_files()
    without_hint["models/marts/fct_sales.sql"] = without_hint["models/marts/fct_sales.sql"].replace("-- depends_on: {{ ref('dim_date') }}", "")
    refused = dbt_view(dbt_catalog, without_hint, "run", ["fct_sales"], None, False, None)["run"]["results"][0]
    assert refused["status"] == "error" and "depends_on: {{ ref('dim_date') }}" in refused["message"], refused["message"]
    # The Jinja sandbox, packages and schemas outside the catalog layers.
    base = {"dbt_project.yml": "name: p\nversion: '1.0.0'\nconfig-version: 2\nprofile: p\n"}
    for sql, expected in [("select '{{ ''.__class__ }}' as x", "unsafe"), ("select {{ dbt_utils.star('x') }}", "Packages are not installed"),
                          ("select {{ env_var('HOME') }}", "env_var"), ("{{ config(schema='gold') }} select 1 as x", "generate_schema_name")]:
        outcome = dbt_view(dbt_catalog, {**base, "models/m.sql": sql}, "run", None, None, False, None)["run"]["results"][0]
        assert outcome["status"] == "error" and expected in outcome["message"], (sql, outcome["message"])
    assert dbt_view(dbt_catalog, {"models/m.sql": "select 1"}, "run", None, None, False, None)["status"] == "invalid"
    dbt_catalog.close()

# Databricks Lab: jobs orchestrated on a logical clock; notebook and SQL tasks run on the catalog under Unity Catalog.
from databrickslab.compute import load_compute
from databrickslab.engine import JobScenario, simulate_job
from databrickslab.model import DatabricksLabError


def dbx_task(key, deps=(), **extra):
    task = {"task_key": key, "notebook_task": {"notebook_path": f"/Shared/{key}"}}
    if deps:
        task["depends_on"] = [{"task_key": d} if isinstance(d, str) else {"task_key": d[0], "outcome": d[1]} for d in deps]
    task.update(extra)
    return task


def dbx_dry(tasks, scenario=None, **job):
    _, result = simulate_job({"name": "smoke", "tasks": tasks, **job}, load_compute(None),
                             JobScenario.model_validate(scenario or {}), None)
    return result, {t["key"]: t["state"] for t in result["tasks"]}


# run_if, exclusion through the unmet If/else branch, and the leaf rule for the run status.
result, states = dbx_dry([
    dbx_task("a"),
    {"task_key": "check", "depends_on": [{"task_key": "a"}],
     "condition_task": {"op": "GREATER_THAN", "left": "{{tasks.a.values.n}}", "right": "0"}},
    dbx_task("yes", [("check", "true")]), dbx_task("no", [("check", "false")]),
    dbx_task("after_no", ["no"]), dbx_task("cleanup", ["yes", "after_no"], run_if="ALL_DONE"),
], {"tasks": {"a": {"values": {"n": 3}}}})
assert states == {"a": "success", "check": "success", "yes": "success", "no": "excluded", "after_no": "excluded",
                  "cleanup": "success"}, states
assert result["result_state"] == "SUCCESS", result
result, states = dbx_dry([dbx_task("a"), dbx_task("b", ["a"]), dbx_task("handler", ["a"], run_if="AT_LEAST_ONE_FAILED")],
                         {"tasks": {"a": {"fail_attempts": "all"}}})
assert states == {"a": "failed", "b": "upstream_failed", "handler": "success"}, states
assert result["result_state"] == "FAILED", result  # b is a leaf and is upstream failed
result, states = dbx_dry([dbx_task("a"), dbx_task("b", ["a"]), dbx_task("handler", ["a"], run_if="AT_LEAST_ONE_FAILED")])
assert states["handler"] == "excluded" and result["result_state"] == "SUCCESS", states
result, states = dbx_dry([dbx_task("a"), dbx_task("b"), dbx_task("c", ["a", "b"], run_if="AT_LEAST_ONE_SUCCESS")],
                         {"tasks": {"a": {"fail_attempts": "all"}}})
assert states["c"] == "success" and result["result_state"] == "SUCCESS_WITH_FAILURES", result
# Retries and timeouts.
result, states = dbx_dry([dbx_task("a", max_retries=2, min_retry_interval_millis=30000)],
                         {"tasks": {"a": {"fail_attempts": [1, 2], "duration_seconds": 60}}})
attempts = result["tasks"][0]["attempts"]
assert states["a"] == "success" and [x["status"] for x in attempts] == ["failed", "failed", "success"], attempts
assert attempts[1]["start_s"] - attempts[0]["end_s"] == 30, attempts
result, states = dbx_dry([dbx_task("a", timeout_seconds=30, max_retries=1)], {"tasks": {"a": {"duration_seconds": 60}}})
assert states["a"] == "timedout" and len(result["tasks"][0]["attempts"]) == 1, result  # retry_on_timeout is false
# If/else: == compares text, > compares numbers; job parameters are pushed down and win over task parameters.
for op, left, right, outcome in [("EQUAL_TO", "12.0", "12", "false"), ("GREATER_THAN_OR_EQUAL", "12.0", "12", "true")]:
    result, _ = dbx_dry([{"task_key": "c", "condition_task": {"op": op, "left": left, "right": right}}])
    assert result["tasks"][0]["outcome"] == outcome, (op, result["tasks"][0])
result, _ = dbx_dry([dbx_task("a", notebook_task={"notebook_path": "/Shared/a", "base_parameters": {
    "day": "x", "run": "{{job.run_id}}", "lit": "{{unknown.ref}}"}})],
    {"job_parameters": {"day": "2026-03-09"}, "run_id": 42}, parameters=[{"name": "day", "default": "{{job.start_time.iso_date}}"}])
assert result["tasks"][0]["parameters"] == {"day": "2026-03-09", "run": "42", "lit": "{{unknown.ref}}"}, result["tasks"][0]
result, states = dbx_dry([dbx_task("a", notebook_task={"notebook_path": "/Shared/a", "base_parameters": {"x": "{{job.nope}}"}})])
assert states["a"] == "failed" and "Invalid dynamic value reference" in result["tasks"][0]["error"], result
# For each: iterations with concurrency; compute and cost: a job cluster starts once and terminates after its last task.
result, _ = dbx_dry([{"task_key": "loop", "for_each_task": {"inputs": "[1, 2, 3]", "concurrency": 2,
                                                           "task": dbx_task("inner", notebook_task={"notebook_path": "/Shared/i", "base_parameters": {"n": "{{input}}"}})}}])
assert [i["parameters"]["n"] for i in result["tasks"][0]["iterations"]] == ["1", "2", "3"], result
result, _ = dbx_dry([dbx_task("a", job_cluster_key="c"), dbx_task("b", ["a"], job_cluster_key="c")],
                    job_clusters=[{"job_cluster_key": "c", "new_cluster": {"spark_version": "15.4.x-scala2.12",
                                                                            "node_type_id": "Standard_DS3_v2", "num_workers": 2}}])
[usage] = result["compute"]
assert (usage["startup_s"], usage["billed_s"], usage["tasks"]) == (300, 540, ["a", "b"]), usage
for bad, expected in [
    ([dbx_task("a"), dbx_task("b", ["missing"])], "not a task of this job"),
    ([dbx_task("a", ["b"]), dbx_task("b", ["a"])], "cycle"),
    ([{"task_key": "p", "spark_python_task": {"python_file": "x.py"}}], "does not simulate"),
    ([dbx_task("a", job_cluster_key="none")], "not in job_clusters"),
    ([dbx_task("a", existing_cluster_id="nope")], "does not exist"),
    ([dbx_task("a"), {"task_key": "c", "depends_on": [{"task_key": "a"}], "condition_task": {"op": "EQUAL_TO", "left": "1", "right": "1"}},
      dbx_task("d", ["c"])], 'set outcome to "true" or "false"'),
]:
    try:
        dbx_dry(bad)
        raise AssertionError(f"expected an invalid job: {expected}")
    except DatabricksLabError as error:
        assert any(expected in issue["message"] for issue in error.issues), (expected, error.issues)

with TemporaryDirectory(prefix="datapass-databricks-smoke-") as temp:
    from datapass_runtime.catalog import Catalog, statements
    from datapass_runtime.databricks_workspace import bind_parameters, map_names

    # Files with Windows line endings split cleanly; comments and literals keep their text.
    assert statements("SELECT 1;\r\nSELECT 2;\r\n") == ["SELECT 1;", "SELECT 2;"]
    assert bind_parameters("-- :x\r\nSELECT ':x', :x", {"x": "a'b"}) == "-- :x\r\nSELECT ':x', 'a''b'"
    assert map_names("SELECT * FROM main.gold.t -- main.silver.u") == "SELECT * FROM gold.t -- main.silver.u"
    from datapass_runtime.databricks_workspace import explore as dbx_explore, run as dbx_run

    dbx_catalog = Catalog(Path(temp), "duckdb")
    dbx_files = databricks_files()

    def dbx_local(name, files=None, scenario=None):
        return dbx_run(dbx_catalog, {"name": name, "document": databricks_job(name), "files": files or dbx_files,
                                     "scenario": scenario or {}, "data_plane": "local"})

    retail = dbx_local("retail_daily_dbx")
    assert retail["status"] == "simulated" and retail["run"]["result_state"] == "SUCCESS", retail["run"]
    tasks = {t["key"]: t for t in retail["run"]["tasks"]}
    assert tasks["ingest_orders"]["values"] == {"new_rows": 12} and tasks["has_new_rows"]["outcome"] == "true", tasks
    assert tasks["gold_checks"]["rows"] == [{"segments": 4, "revenue": 4985.0, "enough_segments": True}], tasks["gold_checks"]
    assert tasks["alert_on_failure"]["state"] == "excluded", tasks["alert_on_failure"]
    assert {t["name"] for t in retail["tables_changed"]} == {"bronze.orders", "silver.orders", "gold.revenue_by_segment"}
    assert [u["kind"] for u in retail["run"]["compute"]] == ["job_cluster", "warehouse"], retail["run"]["compute"]

    # The ML job runs as a service principal: least privileges, a registered model, an alias and batch scoring.
    power = dbx_local("power_model_training")
    assert power["run"]["result_state"] == "SUCCESS", [(t["key"], t["error"]) for t in power["run"]["tasks"]]
    train = power["run"]["tasks"][0]
    assert train["values"] == {"rmse": 0.0, "model_version": 1}, train  # power = 2 * wind_speed + 4 exactly
    [model] = power["mlflow"]["models"]
    assert model["name"] == "main.ml.power_model" and model["aliases"] == {"champion": 1}, model
    assert model["owner"] == "sp-ml-training" and model["versions"][0]["signature"]["inputs"] == ["wind_speed"], model
    scored = dbx_catalog.query("SELECT MAX(ABS(prediction - actual_power)) AS err FROM gold.turbine_power_scored")["rows"]
    assert scored == [{"err": 0.0}], scored
    again = dbx_local("power_model_training")
    assert again["mlflow"]["models"][0]["aliases"] == {"champion": 2}, again["mlflow"]
    denied_files = dict(dbx_files, grants=dbx_files["grants"].replace(
        "GRANT SELECT ON TABLE main.source.turbine_readings TO `sp-ml-training`;", ""))
    denied = dbx_local("power_model_training", denied_files)
    train = denied["run"]["tasks"][0]
    assert train["state"] == "failed" and train["error_code"] == "UnauthorizedError", train
    assert "does not have SELECT on Table 'main.source.turbine_readings'" in train["error"], train
    state = dbx_explore(dbx_catalog, {"files": dbx_files})
    owners = state["unity"]["owners"]
    assert owners == {"main.ml.power_model": "sp-ml-training", "main.gold.turbine_power_scored": "sp-ml-training"}, owners
    assert any(g["principal"] == "analysts" and g["privilege"] == "SELECT" for g in state["unity"]["grants"])
    assert state["mlflow"]["experiments"][0]["name"] == "/Shared/power-forecast", state["mlflow"]

    # Notebooks stay bounded: no eval/exec, no arbitrary imports, even with MLflow available.
    from sparklab.safe_parser import SafeSparkParser, SparkLabSyntaxError
    from sparklab.sparklab import SparkSession
    for unsafe in ("import os\n", "import mlflow\nmlflow.log_artifact('/etc/passwd')\n",
                   "from pyspark.ml.feature import StringIndexer\n", "x = __import__('os')\n",
                   "with open('x') as f:\n    pass\n"):
        session = SparkSession({"tables": {}})
        session.notebook_runtime = object()
        try:
            SafeSparkParser(session).run_notebook(unsafe, {}, "databricks", None, None)
            raise AssertionError(f"must reject: {unsafe!r}")
        except SparkLabSyntaxError:
            pass
    dbx_catalog.close()

source = """pipeline("ci")
a = sql("a", "SELECT 1")
b = quality("b", "SELECT 1 WHERE FALSE")
a >> b
"""
compiled = compile_response(source)
assert compiled["valid"], compiled
assert compiled["ir"] is not None
assert len(compiled["ir"]["tasks"]) == 2
assert len(compiled["ir"]["edges"]) == 1
assert compiled["ir"]["edges"][0] == {"source": "a", "target": "b"}

canonical, plan = compile_guard(
    'df = spark.table("orders")\n'
    'df = df.filter("net_amount > 0")\n'
    'df = df.select("order_id", "customer_id", "net_amount")'
)
assert canonical.startswith('df = spark.table("orders")')
assert plan["source_table"] == "orders"
assert [operation["op"] for operation in plan["operations"]] == ["filter", "select"]


with TemporaryDirectory(prefix="datapass-retail-smoke-") as temp:
    workspace = Path(temp)
    datasets = workspace / "datasets"
    datasets.mkdir()
    (datasets / "retail_orders.csv").write_text(
        "\n".join([
            "order_id,customer_id,order_date,amount,status",
            "1,C001,2026-09-01,100.0,completed",
            "2,C001,2026-09-02,50.0,completed",
            "3,C002,2026-09-02,-5.0,refund",
            "4,C002,2026-09-03,200.0,completed",
            "5,C003,2026-09-03,0.0,cancelled",
            "",
        ]),
        encoding="utf-8",
    )
    previous_workspace = os.environ.get("DATAPASS_WORKSPACE_ROOT")
    os.environ["DATAPASS_WORKSPACE_ROOT"] = str(workspace)
    try:
        retail = run_retail_demo("datasets/retail_orders.csv")
    finally:
        if previous_workspace is None:
            os.environ.pop("DATAPASS_WORKSPACE_ROOT", None)
        else:
            os.environ["DATAPASS_WORKSPACE_ROOT"] = previous_workspace

    assert retail["status"] == "success"
    assert retail["database_path"] == ".datapass/data/workspace.duckdb"
    assert [stage["rows"] for stage in retail["stages"]] == [5, 5, 3, 2]
    assert retail["polars_quality"] == {"rows": 3, "customers": 2, "revenue": 350.0}
    assert retail["preview"]["rows"][0]["customer_id"] == "C002"
    assert retail["preview"]["rows"][0]["revenue"] == 200.0
    assert (workspace / ".datapass" / "data" / "workspace.duckdb").is_file()


with TemporaryDirectory(prefix="datapass-kernel-smoke-") as temp:
    manager = KernelManager(mode="duckdb", trusted=False, timeout=8.0, max_workers=1)
    try:
        capability = manager.call("smoke", Path(temp), {"op": "capabilities"})
        assert capability["storage"] == "duckdb"
        assert any(kernel["id"] == "sql" and kernel["available"] for kernel in capability["kernels"])
        catalog = manager.call("smoke", Path(temp), {"op": "catalog"})
        assert any(item["name"] == "source.orders" for item in catalog)

        grading = manager.call(
            "smoke",
            Path(temp),
            {
                "op": "exercise",
                "exercise_id": "demo-sum",
                "exercise_version": "1",
                "language": "sql",
                "code": "SELECT COALESCE(SUM(value), 0) AS total FROM input",
                "mode": "submit",
                "notebook_id": "exercise-demo-sum-1",
                "cell_id": "solution",
                "source_revision": 1,
                "profile": "generic_8x8",
                "aqe": True,
            },
        )
        assert grading["status"] == "passed", grading
        assert len(grading["checks"]) == 3
        assert all(check["passed"] for check in grading["checks"])

        # Trailing comments and semicolons must not break the grading wrapper.
        for suffix in (" -- done", ";", "; -- done", "\n-- keep every row\n", " /* note */;"):
            wrapped = manager.call("smoke", Path(temp), {
                "op": "exercise", "exercise_id": "demo-sum", "exercise_version": "1", "language": "sql",
                "code": "SELECT COALESCE(SUM(value), 0) AS total FROM input" + suffix, "mode": "submit",
                "notebook_id": "exercise-demo-sum-1", "cell_id": "solution", "source_revision": 2,
                "profile": "generic_8x8", "aqe": True,
            })
            assert wrapped["status"] == "passed", (suffix, wrapped["checks"])

        pipeline_source = """pipeline("smoke_pipeline")
extract = sql("extract", "CREATE OR REPLACE TABLE bronze.pipeline_smoke AS SELECT order_id FROM source.orders WHERE net_amount > 0")
check = quality("check", "SELECT * FROM bronze.pipeline_smoke WHERE order_id IS NULL")
publish = sql("publish", "SELECT COUNT(*) AS rows FROM bronze.pipeline_smoke")
extract >> check >> publish
"""
        pipeline_run = run_native_pipeline(
            pipeline_source,
            lambda request: manager.call("smoke", Path(temp), request),
        )
        assert pipeline_run["status"] == "success", pipeline_run
        assert [task["status"] for task in pipeline_run["tasks"]] == ["success", "success", "success"]
        catalog = manager.call("smoke", Path(temp), {"op": "catalog"})
        assert any(item["name"] == "bronze.pipeline_smoke" and item["fresh"] for item in catalog)

        # dbt is declared by the compiler but not wired: it must fail fast and
        # honestly (no retries burned, no success), and block its downstream.
        dbt_source = """pipeline("dbt_smoke")
models = dbt("models", project="retail-dbt", retries=3, retry_delay=5)
after = sql("after", "SELECT 1 AS ok")
models >> after
"""
        started = time.perf_counter()
        dbt_run = run_native_pipeline(dbt_source, lambda request: manager.call("smoke", Path(temp), request))
        assert time.perf_counter() - started < 3, "dbt activity must not sleep through retries"
        assert dbt_run["status"] == "failed", dbt_run
        dbt_task, after_task = dbt_run["tasks"]
        assert dbt_task["status"] == "failed" and dbt_task["attempts"] == 1, dbt_task
        assert "not wired" in dbt_task["error"] and "Nothing was run" in dbt_task["error"], dbt_task
        assert after_task["status"] == "skipped", after_task
    finally:
        manager.close()

with TemporaryDirectory(prefix="datapass-csv-import-smoke-") as temp:
    from fastapi.testclient import TestClient

    previous_workspace = os.environ.get("DATAPASS_WORKSPACE_ROOT")
    os.environ["DATAPASS_WORKSPACE_ROOT"] = temp
    try:
        with TestClient(app) as client:
            csv_text = "﻿city,visits\nLyon,3\nParis,\n"
            imported = client.post("/api/local/import-csv", json={"asset": "bronze.city_visits", "text": csv_text})
            assert imported.status_code == 200, imported.text
            body = imported.json()
            assert body["asset"] == "bronze.city_visits" and body["rows_imported"] == 2, body
            assert [column["type"] for column in body["schema"]] == ["VARCHAR", "VARCHAR"], body["schema"]
            assert body["result"]["rows"] == [{"city": "Lyon", "visits": "3"}, {"city": "Paris", "visits": ""}], body["result"]
            assert "text" in body["truth"], body["truth"]
            catalog = client.get("/api/local/catalog").json()
            assert any(item["name"] == "bronze.city_visits" and item["row_count"] == 2 for item in catalog), catalog

            # Catalog tree: every schema, with columns, types, kinds and row counts; a broken view keeps its error.
            client.post("/api/local/execute", json={"language": "sql", "code": "CREATE VIEW silver.visits_v AS SELECT city FROM bronze.city_visits"})
            schema = client.get("/api/local/catalog/schema").json()
            assert schema["engine"] == "duckdb" and schema["layers"][0] == "source" and not schema["truncated"], schema
            by_name = {f'{t["schema"]}.{t["name"]}': t for t in schema["tables"]}
            visits = by_name["bronze.city_visits"]
            assert visits["kind"] == "table" and visits["row_count"] == 2 and visits["layer"] is True, visits
            assert visits["columns"] == [{"name": "city", "type": "VARCHAR"}, {"name": "visits", "type": "VARCHAR"}], visits
            assert by_name["silver.visits_v"]["kind"] == "view" and by_name["silver.visits_v"]["row_count"] == 2, by_name["silver.visits_v"]
            assert by_name["source.orders"]["row_count"] == 12 and by_name["source.orders"]["fresh"] is True, by_name["source.orders"]

            # Catalog handoff: releasing closes the worker's connection, so another process can write the file
            # (as dbt Core does); catalog requests are refused until reattached; a held file blocks the reattach.
            assert client.get("/api/local/catalog/lease").json() == {"attached": True, "holder": None, "since": None}
            released = client.post("/api/local/catalog/release", json={"holder": "dbt build --select tag:daily"})
            assert released.status_code == 200 and released.json()["holder"] == "dbt build --select tag:daily", released.text
            refused = client.get("/api/local/catalog")
            assert refused.status_code == 409 and "lent to" in refused.json()["detail"], refused.text
            assert client.post("/api/local/exercise", json={
                "exercise_id": "x", "exercise_version": "1", "language": "sql", "code": "SELECT 1", "mode": "run",
                "notebook_id": "n", "cell_id": "c", "source_revision": 0}).status_code == 409
            db_file = str(Path(temp) / ".datapass" / "data" / "workspace.duckdb")
            holder_code = ("import duckdb, sys, time; c = duckdb.connect(sys.argv[1]); "
                           "c.execute('CREATE OR REPLACE TABLE silver.from_dbt AS SELECT 42 AS answer'); "
                           "print('ready', flush=True); sys.stdin.readline(); c.close()")
            external = subprocess.Popen([sys.executable, "-c", holder_code, db_file], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, text=True)
            try:
                assert external.stdout.readline().strip() == "ready", "an external writer can open the released file"
                blocked = client.post("/api/local/catalog/reattach")
                assert blocked.status_code == 409 and "still held" in blocked.json()["detail"], blocked.text
                assert client.get("/api/local/catalog/lease").json()["attached"] is False
            finally:
                external.communicate("done\n", timeout=30)
            reattached = client.post("/api/local/catalog/reattach")
            assert reattached.status_code == 200 and reattached.json()["attached"] is True, reattached.text
            answer = client.post("/api/local/query", json={"query": "SELECT answer FROM silver.from_dbt"}).json()
            assert answer["result"]["rows"] == [{"answer": 42}], answer
            assert client.post("/api/local/catalog/release", json={"holder": "two\nlines"}).status_code == 422

            # Missions: every shipped mission validates and every fixture batch loads; the checker judges an
            # untouched mission without dbt (no artifacts yet) with messages, and never claims a pass.
            from missionlab.model import load_missions
            missions = load_missions()
            assert len(missions) == 5, [m.id for m, _ in missions]
            for mission, _pack in missions:
                for batch in mission.batches:
                    loaded = client.post("/api/local/missions/setup", json={"mission_id": mission.id, "batch_id": batch.id})
                    assert loaded.status_code == 200 and loaded.json()["statements"] > 0, (mission.id, batch.id, loaded.text)
                checked = client.post("/api/local/missions/check", json={"mission_id": mission.id})
                assert checked.status_code == 200, (mission.id, checked.text)
                verdict = checked.json()
                assert verdict["status"] == "not-yet" and verdict["truth"].startswith("Checked for real"), verdict
                assert any(not c["passed"] for c in verdict["criteria"]), verdict
            raw_orders = client.post("/api/local/query", json={"query": "SELECT count(*) AS n FROM incr_raw.shop_orders"}).json()
            assert raw_orders["result"]["rows"] == [{"n": 11}], raw_orders  # day-2 replaced the landing table
            fresh = client.post("/api/local/query", json={"query": "SELECT count(*) AS n FROM fresh_raw.erp_products WHERE loaded_at < now() - INTERVAL 19 DAY"}).json()
            assert fresh["result"]["rows"] == [{"n": 8}], fresh
            incremental = client.post("/api/local/missions/check", json={"mission_id": "incremental-order-lines"}).json()
            node = next(c for c in incremental["criteria"] if c["id"] == "incremental")
            assert "No target/manifest.json yet" in node["checks"][0]["detail"], node
            client.post("/api/local/missions/setup", json={"mission_id": "incremental-order-lines", "batch_id": "day-1"})
            restarted = client.post("/api/local/missions/check", json={"mission_id": "incremental-order-lines"}).json()
            assert restarted["requires"] and "Load next batch" in restarted["requires"][0], restarted
            assert client.post("/api/local/missions/setup", json={"mission_id": "nope", "batch_id": "x"}).status_code == 404
            assert client.post("/api/local/missions/setup", json={"mission_id": "../x", "batch_id": "x"}).status_code == 422
            assert client.post("/api/local/missions/setup", json={"mission_id": "sales-board", "batch_id": "day-9"}).status_code == 400

            # Imports never overwrite, and only create bronze tables.
            again = client.post("/api/local/import-csv", json={"asset": "bronze.city_visits", "text": "city\nNice\n"})
            assert again.status_code == 400 and "already exists" in again.json()["detail"], again.text
            for asset in ("source.orders", "silver.city_visits", "bronze.1bad", "bronze.x; DROP TABLE y"):
                refused = client.post("/api/local/import-csv", json={"asset": asset, "text": "a\n1\n"})
                assert refused.status_code == 422, (asset, refused.text)
            for bad_csv in ("a,a\n1,2\n", "a,b\n1\n", "1col\nx\n", "a\n" + "x\n" * 5001):
                refused = client.post("/api/local/import-csv", json={"asset": "bronze.bad_csv", "text": bad_csv})
                assert refused.status_code == 400, (bad_csv[:20], refused.text)
            extra = client.post("/api/local/import-csv", json={"asset": "bronze.x", "text": "a\n1\n", "path": "/etc/passwd"})
            assert extra.status_code == 422, extra.text
            queried = client.post("/api/local/query", json={"query": "SELECT CAST(visits AS INTEGER) AS v FROM bronze.city_visits WHERE visits <> ''"})
            assert queried.json()["result"]["rows"] == [{"v": 3}], queried.text

            # Mosaic data tools: typed Parquet/JSON import (content, never a path), SUMMARIZE, EXPLAIN ANALYZE.
            import base64
            import duckdb as _duckdb
            parquet_path = Path(temp) / "made.parquet"
            _duckdb.connect().execute(
                "COPY (SELECT i AS order_id, i * 1.5 AS amount, DATE '2026-01-01' + CAST(i AS INTEGER) AS order_date FROM range(1, 6) t(i)) "
                f"TO '{parquet_path.as_posix()}' (FORMAT PARQUET)")
            encoded = base64.b64encode(parquet_path.read_bytes()).decode()
            typed = client.post("/api/local/import-file", json={"asset": "bronze.orders_pq", "format": "parquet", "data": encoded})
            assert typed.status_code == 200, typed.text
            typed = typed.json()
            assert typed["rows_imported"] == 5 and typed["format"] == "parquet", typed
            assert {c["name"]: c["type"] for c in typed["schema"]} == {"order_id": "BIGINT", "amount": "DECIMAL(22,1)", "order_date": "DATE"} or \
                {c["name"] for c in typed["schema"]} == {"order_id", "amount", "order_date"}, typed["schema"]
            assert "types come from the Parquet file" in typed["truth"]
            json_text = '[{"sku": "A1", "qty": 2, "tags": ["x"]}, {"sku": "B2", "qty": 5, "tags": []}]'
            from_json = client.post("/api/local/import-file", json={"asset": "bronze.skus", "format": "json",
                                                                    "data": base64.b64encode(json_text.encode()).decode()})
            assert from_json.status_code == 200 and from_json.json()["rows_imported"] == 2, from_json.text
            qty = {c["name"]: c["type"] for c in from_json.json()["schema"]}["qty"]
            assert qty in {"BIGINT", "INTEGER"}, qty
            for bad in (
                {"asset": "bronze.orders_pq", "format": "parquet", "data": encoded},              # never overwrites
                {"asset": "bronze.fake", "format": "parquet", "data": base64.b64encode(b"not parquet").decode()},
                {"asset": "bronze.badjson", "format": "json", "data": base64.b64encode(b"{not json").decode()},
                {"asset": "bronze.b64", "format": "json", "data": "!!!!"},
                {"asset": "bronze.cols", "format": "json", "data": base64.b64encode(b'[{"bad name": 1}]').decode()},
            ):
                refused = client.post("/api/local/import-file", json=bad)
                assert refused.status_code == 400, (bad["asset"], refused.text)
            for bad in ({"asset": "silver.x", "format": "json", "data": "e30="}, {"asset": "bronze.x", "format": "csv", "data": "e30="},
                        {"asset": "bronze.x", "format": "json", "data": "e30=", "path": "/etc/passwd"}):
                assert client.post("/api/local/import-file", json=bad).status_code == 422, bad
            assert not list(Path(temp, ".datapass", "data", "imports").glob("*")), "temporary import copies are removed"
            # Only the staging folder is readable, and cell SQL still cannot reach it or anything else.
            for escape in ("SELECT * FROM 'C:/Windows/win.ini'", "SELECT * FROM '/etc/passwd'",
                           f"SELECT * FROM '{(Path(temp) / 'made.parquet').as_posix()}'"):
                blocked = client.post("/api/local/execute", json={"language": "sql", "code": escape, "notebook_id": "n", "cell_id": "c"}).json()
                assert blocked["status"] == "error", (escape, blocked)

            profile = client.post("/api/local/profile", json={"asset": "bronze.orders_pq"})
            assert profile.status_code == 200, profile.text
            by_column = {row["column_name"]: row for row in profile.json()["result"]["rows"]}
            assert by_column["order_id"]["min"] == "1" and by_column["order_id"]["max"] == "5", by_column["order_id"]
            assert float(by_column["amount"]["null_percentage"]) == 0.0
            assert client.post("/api/local/profile", json={"asset": "bronze.missing"}).status_code == 400
            assert client.post("/api/local/profile", json={"asset": "bronze.x; DROP TABLE y"}).status_code == 422

            plan = client.post("/api/local/explain", json={"query": "SELECT order_date, SUM(amount) AS total FROM bronze.orders_pq GROUP BY 1 -- by day"})
            assert plan.status_code == 200, plan.text
            assert "HASH_GROUP_BY" in plan.json()["plan"] and "Total Time" in plan.json()["plan"], plan.json()["plan"][:400]
            for refused_sql in ("DROP TABLE bronze.orders_pq", "SELECT 1; SELECT 2", "SELECT * FROM read_parquet('x.parquet')"):
                refused = client.post("/api/local/explain", json={"query": refused_sql})
                assert refused.status_code == 400, (refused_sql, refused.text)
            still = client.post("/api/local/query", json={"query": "SELECT COUNT(*) AS n FROM bronze.orders_pq"}).json()
            assert still["result"]["rows"] == [{"n": 5}], still

            # Mosaic's `-- dialect:` files: translated to DuckDB (runtime/sqldialects) with the catalog's types, run for real.
            tsql = client.post("/api/local/execute", json={"language": "sql", "dialect": "tsql", "notebook_id": "vscode-sql", "cell_id": "active-sql", "code": (
                "-- dialect: tsql\nCREATE TABLE silver.orders_tsql AS\nSELECT TOP 3 [order_id], order_id / 2 AS pair, "
                "CAST(order_id AS VARCHAR(10)) + '#' AS tag FROM bronze.orders_pq ORDER BY order_id;\n"
                "SELECT COUNT_BIG(*) AS n, SUM(pair) AS pairs, MAX(tag) AS last_tag FROM silver.orders_tsql;")}).json()
            assert tsql["status"] == "success", tsql
            assert tsql["result"]["rows"] == [{"n": 3, "pairs": 2, "last_tag": "3#"}], tsql["result"]  # 1/2 + 2/2 + 3/2 as integers
            assert tsql["dialect"]["source"] == "tsql" and tsql["dialect"]["label"] == "T-SQL dialect translated to DuckDB, not SQL Server"
            assert "order_id // 2" in tsql["dialect"]["sql"] and "LIMIT 3" in tsql["dialect"]["sql"], tsql["dialect"]["sql"]
            assert any("Integer / integer" in r for r in tsql["dialect"]["rewrites"]), tsql["dialect"]["rewrites"]
            assert "silver.orders_tsql" in {a["name"] for a in tsql["catalog"]}
            refused_tsql = client.post("/api/local/execute", json={"language": "sql", "dialect": "tsql", "code": "SELECT GETDATE() AS now"}).json()
            assert refused_tsql["status"] == "error" and refused_tsql["error"]["type"] == "TsqlDialectError", refused_tsql
            assert "not SQL Server" in refused_tsql["error"]["message"], refused_tsql
            escape_dialect = client.post("/api/local/execute", json={"language": "sql", "dialect": "postgres",
                                                                     "code": "SELECT * FROM read_csv('secrets.csv')"}).json()
            assert escape_dialect["status"] == "error" and "table functions" in escape_dialect["error"]["message"], escape_dialect
            bq_plan = client.post("/api/local/explain", json={"dialect": "bigquery", "query":
                "SELECT order_date, COUNTIF(amount > 1) AS big FROM `bronze.orders_pq` GROUP BY order_date QUALIFY ROW_NUMBER() OVER (ORDER BY order_date) = 1"})
            assert bq_plan.status_code == 200, bq_plan.text
            assert bq_plan.json()["dialect"]["source"] == "bigquery" and "COUNT_IF" in bq_plan.json()["query"], bq_plan.json()
            assert "not BigQuery" in bq_plan.json()["truth"], bq_plan.json()["truth"]
            assert client.post("/api/local/explain", json={"dialect": "bigquery", "query": "SELECT CURRENT_DATE()"}).status_code == 400
            for bad in ({"language": "python", "code": "x = 1", "dialect": "tsql"}, {"language": "sql", "code": "SELECT 1", "dialect": "mysql"},
                        {"language": "sql", "code": "SELECT 1", "dialect": "tsql", "output_asset": "silver.x"}):
                assert client.post("/api/local/execute", json=bad).status_code == 422, bad
            assert [d["id"] for d in capabilities()["mosaic"]["sql_dialects"]] == ["tsql", "snowflake", "bigquery", "spark", "postgres"]

            # Airflow Lab: the DAG text is parsed and simulated, never executed.
            lab_dag = AIRFLOW_HEAD + (
                "from airflow.providers.standard.operators.python import BranchPythonOperator\n"
                "def pick(**context):\n    return 'b'\n"
                "with DAG('lab', schedule='@daily', start_date=datetime(2026, 3, 1), catchup=True):\n"
                "    s = FileSensor(task_id='s', filepath='/in/{{ ds }}.csv', poke_interval=60, timeout=600, soft_fail=True)\n"
                "    choose = BranchPythonOperator(task_id='choose', python_callable=pick)\n"
                "    s >> choose >> [EmptyOperator(task_id='a'), EmptyOperator(task_id='b')]\n")
            lab = client.post("/api/local/airflow/simulate", json={"source": lab_dag, "scenario": {"now": "2026-03-03T12:00:00Z"}}).json()
            assert lab["status"] == "simulated" and lab["total_runs"] == 3, lab
            final = {i["task_id"]: i["state"] for i in lab["runs"][-1]["instances"]}
            assert final == {"s": "success", "choose": "success", "a": "skipped", "b": "success"}, final  # Lab default: file present
            assert lab["runs"][-1]["rendered"] == [{"task_id": "s", "field": "filepath", "value": "/in/2026-03-03.csv"}], lab["runs"][-1]
            assert all({"t", "task_id", "state", "try_number", "message"} <= set(e) for e in lab["runs"][-1]["events"])
            never = client.post("/api/local/airflow/simulate", json={"source": lab_dag, "scenario": {
                "now": "2026-03-03T12:00:00Z", "latest_run_only": True, "tasks": {"s": {"sensor_true_after_seconds": None}}}}).json()
            assert [i["state"] for i in never["runs"][0]["instances"]] == ["skipped"] * 4, never
            manual = client.post("/api/local/airflow/simulate", json={"source": lab_dag.replace("schedule='@daily'", "schedule=None"),
                                 "scenario": {"now": "2026-03-03T12:00:00Z", "manual_runs": ["2026-03-03T09:15:00Z"]}}).json()
            assert [(r["run_type"], r["logical_date"]) for r in manual["runs"]] == [("manual", "2026-03-03T09:15:00+00:00")], manual
            broken = client.post("/api/local/airflow/simulate", json={"source": "from airflow.sdk import DAG\nimport os\n"}).json()
            assert broken["status"] == "invalid" and broken["error"]["line"] == 2 and broken["dag"] is None, broken
            unknown_branch = client.post("/api/local/airflow/simulate", json={"source": lab_dag.replace("return 'b'", "return context['x']"),
                                         "scenario": {"now": "2026-03-01T12:00:00Z"}}).json()
            assert unknown_branch["status"] == "simulation_error" and unknown_branch["dag"]["dag_id"] == "lab", unknown_branch
            assert "scenario must say" in unknown_branch["error"]["message"], unknown_branch
            too_long = client.post("/api/local/airflow/simulate", json={"source": "x" * 60001})
            assert too_long.status_code == 422, too_long.status_code

            # Factory Lab: pipelines are simulated; Copy, Lookup, Script, procedures and notebooks run locally.
            def factory(flavor, name, scenario=None, data_plane="local", document=None):
                files = factory_files(flavor)
                body = {"flavor": flavor, "name": name, "document": document or files["pipelines"][name],
                        "files": files, "scenario": scenario or {}, "data_plane": data_plane}
                response = client.post("/api/local/factory/simulate", json=body)
                assert response.status_code == 200, response.text
                return response.json()

            def runs_by_name(view):
                return {run["name"]: run for run in view["run"]["activity_runs"]}

            fabric = factory("fabric", "pl_retail_daily", {"parameters": {"run_date": "2026-03-06"}})
            assert fabric["status"] == "simulated" and fabric["run"]["status"] == "Succeeded", fabric
            assert fabric["data_plane"] == "local" and fabric["flavor_label"] == "Microsoft Fabric Data Factory", fabric
            steps = runs_by_name(fabric)
            assert steps["Copy orders to bronze"]["truth"] == "local", steps
            assert "injected after the parameters cell" in steps["Silver orders"]["note"], steps["Silver orders"]
            assert steps["Silver orders"]["output"]["result"]["exitValue"] == "10", steps["Silver orders"]
            assert steps["Email on notebook failure"]["status"] == "Skipped", steps
            assert steps["Post to Teams"]["truth"] == "simulated" and steps["Has gold rows"]["output"] == {"branch": "True"}
            assert {t["name"] for t in fabric["tables_changed"]} == {"bronze.orders", "silver.orders", "gold.revenue_by_segment"}
            gold = client.post("/api/local/query", json={"query": "SELECT COUNT(*) AS n, MIN(load_date) AS d FROM gold.revenue_by_segment"}).json()
            assert gold["result"]["rows"] == [{"n": 4, "d": "2026-03-06"}], gold

            adf = factory("adf", "pl_retail_daily_adf")
            assert adf["run"]["status"] == "Succeeded", adf
            steps = runs_by_name(adf)
            assert "(upsert)" in steps["Copy orders to bronze"]["note"] and steps["Silver orders"]["output"]["runOutput"] == "10", steps
            assert steps["Notify webhook"]["truth"] == "simulated" and '"silver_rows":"10"' in steps["Notify webhook"]["input"]["body"], steps
            factory("adf", "pl_retail_daily_adf")  # upsert on order_id: running twice keeps one row per order
            assert client.post("/api/local/query", json={"query": "SELECT COUNT(*) AS n FROM bronze.orders"}).json()["result"]["rows"] == [{"n": 12}]

            synapse = factory("synapse", "pl_sqlpool_daily")
            assert synapse["run"]["status"] == "Succeeded", synapse
            check = runs_by_name(synapse)["Check gold"]["output"]
            assert check["count"] == 3 and check["value"][0]["segment_name"] == "Corporate", check  # min_orders Int32 "2"

            failing = factory("fabric", "pl_retail_daily", {"activities": {"Silver orders": {"fail_attempts": "all", "error_message": "Spark job aborted"}}})
            steps = runs_by_name(failing)
            assert failing["run"]["status"] == "Failed" and steps["Email on notebook failure"]["status"] == "Succeeded", failing
            assert set(failing["run"]["evaluated"]) == {"Silver orders", "Email on notebook failure"}, failing["run"]["evaluated"]

            dry = factory("fabric", "pl_retail_daily", data_plane="simulated")
            assert dry["data_plane"] == "simulated" and dry["tables_changed"] == [], dry
            assert dry["run"]["status"] == "Failed" and dry["hints"] and "scenario" in dry["hints"][0], dry
            dry_ok = factory("fabric", "pl_retail_daily", {"activities": {"Count gold rows": {"output": {"firstRow": {"segments": 2}}}}},
                             data_plane="simulated")
            assert dry_ok["run"]["status"] == "Succeeded" and all(r["truth"] == "simulated" for r in dry_ok["run"]["activity_runs"]), dry_ok

            wrong = factory("adf", "pl_retail_daily", document=factory_files("fabric")["pipelines"]["pl_retail_daily"])
            assert wrong["status"] == "invalid" and wrong["run"] is None, wrong
            assert any("TridentNotebook" in i["message"] and "DatabricksNotebook" in i["message"] for i in wrong["issues"]), wrong["issues"]
            oversized = client.post("/api/local/factory/simulate", json={
                "flavor": "fabric", "name": "p", "document": {"properties": {"activities": []}},
                "files": {"notebooks": {"fabric:big": "x" * 40001}}})
            assert oversized.status_code == 422, oversized.status_code
            # SQL pool Lab: the route runs T-SQL on the workspace catalog and describes the pool's tables.
            pool = client.post("/api/local/sqlpool/run", json={"flavor": "synapse", "scale": 1000000, "script": (
                "CREATE TABLE dbo.dim_segment WITH (DISTRIBUTION = REPLICATE) AS\n"
                "SELECT segment_id, segment_name FROM source.dim_customer_segment;\n"
                "CREATE TABLE dbo.fact_orders WITH (DISTRIBUTION = HASH(customer_id)) AS SELECT * FROM source.orders;\n"
                "SELECT s.segment_name, COUNT(*) AS orders FROM dbo.fact_orders AS o\n"
                "JOIN dbo.dim_segment AS s ON o.segment_id = s.segment_id GROUP BY s.segment_name;\n")})
            assert pool.status_code == 200, pool.text
            pool = pool.json()
            assert pool["status"] == "ok" and pool["distributions"] == 60 and "Simulated SQL pool" in pool["truth"], pool
            assert [s["kind"] for s in pool["statements"]] == ["CTAS", "CTAS", "SELECT"], pool["statements"]
            tables = {t["name"]: t for t in pool["tables"]}
            assert tables["dbo.dim_segment"]["distribution"] == "REPLICATE", tables
            fact = tables["dbo.fact_orders"]
            assert fact["rows"] == 12 and len(fact["distribution_stats"]["shares"]) == 60, fact
            assert fact["columnstore_ok"] is False, fact  # 12 million rows at scale: 200,000 per distribution
            assert [s["operation"] for s in pool["plan"]["steps"]] == ["ShuffleMoveOperation", "ReturnOperation"], pool["plan"]
            again = client.post("/api/local/sqlpool/run", json={"flavor": "synapse", "script": ""}).json()
            assert {t["name"] for t in again["tables"]} >= {"dbo.dim_segment", "dbo.fact_orders"}, again  # designs persist
            failed = client.post("/api/local/sqlpool/run", json={"flavor": "fabric", "script": (
                "CREATE TABLE dbo.f1 (a INT);\nCREATE TABLE dbo.f2 (a INT) WITH (DISTRIBUTION = ROUND_ROBIN);\n"
                "CREATE TABLE dbo.f3 (a INT);\n")}).json()
            assert failed["status"] == "error" and [s["status"] for s in failed["statements"]] == ["ok", "error"], failed
            for bad in ({"flavor": "oracle", "script": "SELECT 1;"}, {"script": "x" * 60001}, {"script": "SELECT 1;", "scale": 0},
                        {"script": "SELECT 1;", "path": "/etc/passwd"}):
                assert client.post("/api/local/sqlpool/run", json=bad).status_code == 422, bad
            assert capabilities()["sqlpool_lab"]["cloud_connection"] is False
            # BI Lab: the route runs the warehouse scripts on the workspace catalog, then reports lineage and checks.
            bi = client.post("/api/local/bi/lab", json={"scripts": bi_scripts(), "run": True,
                                                        "model": json.loads((BI_SAMPLE / "model.json").read_text(encoding="utf-8"))})
            assert bi.status_code == 200, bi.text
            bi = bi.json()
            assert bi["status"] == "ok" and bi["ran"] and len(bi["statements"]) == 14, (bi["status"], len(bi["statements"]))
            assert all(c["status"] == "pass" for c in bi["model"]["checks"]) and "sqlglot" in bi["lineage"]["truth"]
            analyzed = client.post("/api/local/bi/lab", json={"scripts": bi_scripts()[-1:], "run": False}).json()
            assert analyzed["statements"] == [] and analyzed["model"] is None and analyzed["lineage"]["columns"], analyzed["status"]
            broken = client.post("/api/local/bi/lab", json={"scripts": [{"path": "bi/x.sql", "text": "SELECT * FROM gold.nope;"}]}).json()
            assert broken["status"] == "error" and broken["stopped"]["line"] == 1, broken["stopped"]
            for bad in ({"scripts": [{"path": "../evil.sql", "text": "SELECT 1;"}]}, {"scripts": [{"path": "a.sql", "text": "x" * 60001}]},
                        {"scripts": [], "run": "yes"}, {"scripts": [], "extra": 1}):
                assert client.post("/api/local/bi/lab", json=bad).status_code == 422, bad
            assert capabilities()["bi_lab"]["power_bi"] is False
            # BI Lab dbt tab: the emulation runs on the workspace catalog (the warehouse sources were built above).
            dbt_run = client.post("/api/local/bi/dbt", json={"files": bi_dbt_files(), "command": "build", "select": ["+fct_sales"]})
            assert dbt_run.status_code == 200, dbt_run.text
            dbt_run = dbt_run.json()
            assert dbt_run["status"] == "success" and dbt_run["run"]["counts"]["error"] == 0, dbt_run["run"]["counts"]
            for bad in ({"files": {"../x.sql": "select 1"}}, {"files": {}, "select": ["--vars"]}, {"files": {}, "command": "deps"},
                        {"files": {}, "extra": True}):
                assert client.post("/api/local/bi/dbt", json=bad).status_code == 422, bad
            assert "not dbt Core" in capabilities()["bi_lab"]["dbt"]
            # Databricks Lab: the route runs a job on the workspace catalog; the state route shows UC and MLflow.
            dbx = client.post("/api/local/databricks/run", json={"name": "retail_daily_dbx", "document": databricks_job("retail_daily_dbx"),
                                                                 "files": databricks_files(), "data_plane": "local"})
            assert dbx.status_code == 200, dbx.text
            dbx = dbx.json()
            assert dbx["status"] == "simulated" and dbx["run"]["status_label"] == "Succeeded", dbx.get("run")
            assert "Nothing connects to Azure Databricks" in dbx["truth"] and dbx["job"]["tasks"][1]["kind"] == "condition"
            dry = client.post("/api/local/databricks/run", json={"name": "retail_daily_dbx", "document": databricks_job("retail_daily_dbx"),
                                                                 "files": databricks_files(), "data_plane": "simulated",
                                                                 "scenario": {"tasks": {"ingest_orders": {"values": {"new_rows": 0}}}}}).json()
            assert dry["run"]["tasks"][1]["outcome"] == "false" and dry["tables_changed"] == [], dry["run"]["tasks"][1]
            explored = client.post("/api/local/databricks/state", json={"files": databricks_files()}).json()
            assert explored["unity"]["catalog"] == "main" and explored["compute_catalog"]["warehouses"][0]["id"] == "serverless-sql"
            for bad in ({"name": "x", "document": {}, "files": {"notebooks": {"../evil": "x"}}},
                        {"name": "x", "document": {}, "files": {"notebooks": {"databricks:/x": "x" * 40001}}},
                        {"name": "bad name!", "document": {}}, {"name": "x", "document": {}, "data_plane": "cloud"}):
                assert client.post("/api/local/databricks/run", json=bad).status_code == 422, bad
            invalid = client.post("/api/local/databricks/run", json={"name": "x", "document": {"name": "x"}}).json()
            assert invalid["status"] == "invalid" and invalid["run"] is None, invalid
            assert capabilities()["databricks_lab"]["cloud_connection"] is False
    finally:
        if previous_workspace is None:
            os.environ.pop("DATAPASS_WORKSPACE_ROOT", None)
        else:
            os.environ["DATAPASS_WORKSPACE_ROOT"] = previous_workspace

runtime_caps = capabilities()["runtime"]
assert runtime_caps["trusted_local_python"] is False, runtime_caps
assert runtime_caps["python_sandboxed"] is False, runtime_caps


# --- SQL dialects translated to DuckDB (runtime/sqldialects): Snowflake --------------------------------------------
# Each expected value is Snowflake's documented result, so a sqlglot change that alters a translation fails here.
import datetime as _dt

import duckdb as _duckdb
from sqldialects import SnowflakeDialectError, translate

_sf = _duckdb.connect()
_sf.execute("""CREATE TABLE t AS SELECT * FROM (VALUES
    (1, 'Ann', 'a1b22', DATE '2024-01-31', TIMESTAMP '2024-01-31 10:15:00', 10.0::DOUBLE, NULL::VARCHAR, 'x'),
    (2, 'bob', 'xyz', DATE '2024-02-29', TIMESTAMP '2024-02-29 23:30:00', 0.0::DOUBLE, 'k', 'x'),
    (3, 'Cy', NULL, DATE '2024-03-10', TIMESTAMP '2024-03-10 00:00:00', 2.0::DOUBLE, 'm', 'y')
) AS v(id, name, code, d, ts, amount, note, grp)""")
_D = _dt.date
SNOWFLAKE_SEMANTICS = [
    # Regular expressions: replace every match, full-string REGEXP_LIKE/RLIKE, NULL when REGEXP_SUBSTR finds nothing.
    ("SELECT REGEXP_REPLACE('a1b2', '[0-9]', '#') AS r", [("a#b#",)]),
    ("SELECT REGEXP_REPLACE('a1b2', '[0-9]') AS r", [("ab",)]),
    ("SELECT REGEXP_LIKE('abc', 'b') AS p, REGEXP_LIKE('abc', 'a.c') AS f, 'abc' RLIKE 'ab' AS r", [(False, True, False)]),
    ("SELECT REGEXP_SUBSTR('abc', '[0-9]+') AS n, REGEXP_SUBSTR('ab12c34', '[0-9]+') AS m", [(None, "12")]),
    ("SELECT REGEXP_SUBSTR(description, '\\\\d+') AS age FROM (SELECT 'aged 42 years' AS description)", [("42",)]),
    # NULL propagation where DuckDB's own functions would skip NULLs.
    ("SELECT CONCAT('a', NULL) AS c, CONCAT_WS('-', 'a', NULL) AS w, 'a' || NULL AS p, CONCAT('a', 'b', 'c') AS ok", [(None, None, None, "abc")]),
    ("SELECT GREATEST(1, NULL, 3) AS g, LEAST(1, NULL) AS l, GREATEST(1, 5, 3) AS g2", [(None, None, 5)]),
    # NULL ordering (NULLs are the largest value) and window defaults.
    ("SELECT note FROM t ORDER BY note DESC", [(None,), ("m",), ("k",)]),
    ("SELECT note FROM t ORDER BY note", [("k",), ("m",), (None,)]),
    ("SELECT id, ROW_NUMBER() OVER (ORDER BY note DESC) AS rn FROM t ORDER BY id", [(1, 1), (2, 3), (3, 2)]),
    ("SELECT id, LAST_VALUE(id) OVER (PARTITION BY grp ORDER BY id) AS lv, FIRST_VALUE(id) OVER (ORDER BY id DESC) AS fv FROM t ORDER BY id", [(1, 2, 3), (2, 2, 3), (3, 3, 3)]),
    ("SELECT x, SUM(x) OVER (ORDER BY x) AS s FROM (SELECT 1 AS x UNION ALL SELECT 1 UNION ALL SELECT 2) ORDER BY x, s", [(1, 2), (1, 2), (2, 4)]),
    ("SELECT id, RANK() OVER (ORDER BY grp) AS r, DENSE_RANK() OVER (ORDER BY grp) AS dr, NTILE(2) OVER (ORDER BY id) AS nt, LAG(id) OVER (ORDER BY id) AS lg, LEAD(id, 1, 0) OVER (ORDER BY id) AS ld FROM t ORDER BY id",
     [(1, 1, 1, 1, None, 2), (2, 1, 1, 1, 1, 3), (3, 3, 2, 2, 2, 0)]),
    # Division.
    ("SELECT 7 / 2 AS a, DIV0(5, 0) AS b, DIV0(6, 3) AS c", [(3.5, 0, 2.0)]),
    ("SELECT id, amount / NULLIF(amount, 0) AS r FROM t ORDER BY id", [(1, 1.0), (2, None), (3, 1.0)]),
    ("SELECT id % 2 AS m, MOD(-7, 3) AS n FROM t WHERE id = 1", [(1, -1)]),
    # Dates keep their type; week and day-of-week follow Snowflake's defaults.
    ("SELECT DATEADD(month, 1, TO_DATE('2024-01-31')) AS m, DATEADD(day, 1, d::DATE) AS n, DATEADD(year, 1, ts::TIMESTAMP) AS y FROM t WHERE id = 1",
     [(_D(2024, 2, 29), _D(2024, 2, 1), _dt.datetime(2025, 1, 31, 10, 15))]),
    ("SELECT DATE_TRUNC('month', d::DATE) AS m, TRUNC(d::DATE, 'year') AS y, LAST_DAY(d::DATE) AS l FROM t WHERE id = 2", [(_D(2024, 2, 1), _D(2024, 1, 1), _D(2024, 2, 29))]),
    ("SELECT DATEDIFF(day, TO_DATE('2024-01-01'), TO_DATE('2024-03-01')) AS d, DATEDIFF(month, TO_DATE('2024-01-31'), TO_DATE('2024-02-01')) AS m, "
     "DATEDIFF(year, TO_DATE('2023-12-31'), TO_DATE('2024-01-01')) AS y, DATEDIFF(week, TO_DATE('2024-01-07'), TO_DATE('2024-01-08')) AS w, "
     "DATEDIFF(week, TO_DATE('2024-01-08'), TO_DATE('2024-01-14')) AS w0, TIMESTAMPDIFF(hour, '2024-01-01 10:59:00'::TIMESTAMP, '2024-01-01 11:01:00'::TIMESTAMP) AS h",
     [(60, 1, 1, 1, 0, 1)]),
    ("SELECT DAYOFWEEK(d) AS w, DAYOFWEEKISO(d) AS wi, YEAR(d) AS y, QUARTER(d) AS q, MONTH(d) AS m, DAY(d) AS dd, DATE_PART(dayofweek, d) AS dp FROM t WHERE id = 3",
     [(0, 7, 2024, 1, 3, 10, 0)]),
    ("SELECT TO_DATE('03/15/2024', 'MM/DD/YYYY') AS a, TO_DATE('2024-03-15') AS b, TRY_TO_DATE('2024-13-01') AS c, TRY_CAST('x' AS INT) AS e", [(_D(2024, 3, 15), _D(2024, 3, 15), None, None)]),
    ("SELECT TO_CHAR(d::DATE, 'MON DD, YYYY') AS a, TO_VARCHAR(ts::TIMESTAMP, 'YYYY-MM-DD HH24:MI') AS b, TO_CHAR(TO_DATE('2024-03-10'), 'DY') AS c FROM t WHERE id = 1", [("Jan 31, 2024", "2024-01-31 10:15", "Sun")]),
    # Strings.
    ("SELECT SPLIT_PART('a,b,c', ',', 2) AS a, SPLIT_PART('a,b,c', ',', -1) AS b, SPLIT_PART('a,b,c', ',', 0) AS c", [("b", "c", "a")]),
    ("SELECT SUBSTR('abcdef', 2, 3) AS a, SUBSTR('abcdef', 0, 2) AS b, LEFT('abc', 2) AS l, RIGHT('abc', 2) AS r, LENGTH('abc') AS n, LEN('ab') AS m", [("bcd", "ab", "ab", "bc", 3, 2)]),
    ("SELECT UPPER('a') AS u, LOWER('B') AS l, TRIM('  a ') AS t, LTRIM('xxa', 'x') AS lt, RTRIM('ayy', 'y') AS rt, REPLACE('aaa', 'a', 'b') AS r, REVERSE('ab') AS v", [("A", "b", "a", "a", "a", "bbb", "ba")]),
    ("SELECT LPAD('7', 3, '0') AS l, RPAD('7', 3, '-') AS r, CHARINDEX('b', 'abc') AS c, POSITION('c' IN 'abc') AS p, CONTAINS('abc', 'b') AS h, STARTSWITH('abc', 'a') AS s, ENDSWITH('abc', 'b') AS e",
     [("007", "7--", 2, 3, True, True, False)]),
    # Conditional functions.
    ("SELECT IFF(1 > 2, 'y', 'n') AS i, NVL(NULL, 2) AS n, IFNULL(NULL, 3) AS f, NVL2(NULL, 1, 2) AS n2, NULLIF(1, 1) AS ni, ZEROIFNULL(NULL) AS z, NULLIFZERO(0) AS nz, "
     "DECODE(2, 1, 'one', 2, 'two', 'other') AS de, EQUAL_NULL(NULL, NULL) AS eq, COALESCE(NULL, NULL, 4) AS co", [("n", 2, 3, 2, None, 0, None, "two", True, 4)]),
    # Aggregates.
    ("SELECT grp, COUNT(*) AS n, COUNT(note) AS nn, COUNT(DISTINCT name) AS dn, COUNT_IF(amount > 1) AS ci, SUM(amount) AS s, AVG(amount) AS a, MIN(id) AS mi, MAX(id) AS ma, "
     "LISTAGG(name, ',') WITHIN GROUP (ORDER BY name DESC) AS l FROM t GROUP BY grp ORDER BY grp", [("x", 2, 1, 2, 1, 10.0, 5.0, 1, 2, "bob,Ann"), ("y", 1, 1, 1, 1, 2.0, 2.0, 3, 3, "Cy")]),
    ("SELECT MEDIAN(x) AS m, VARIANCE(x) AS v, VAR_POP(x) AS vp, ROUND(STDDEV(x), 6) AS s, ROUND(STDDEV_POP(x), 6) AS sp FROM (SELECT 1 AS x UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4)",
     [(2.5, 1.6666666666666667, 1.25, 1.290994, 1.118034)]),
    # Numbers and casts.
    ("SELECT ABS(-2) AS a, ROUND(2.5) AS r, ROUND(-2.5) AS rn, ROUND(2.345, 2) AS r2, CEIL(1.2) AS c, FLOOR(-1.2) AS f, TRUNC(12.345, 1) AS t, SQRT(16) AS q, POWER(2, 3) AS p, SIGN(-3) AS s",
     [(2, 3, -3, 2.35, 2, -2, 12.3, 4.0, 8.0, -1)]),
    ("SELECT CAST('12' AS INT) AS i, '7'::NUMBER(10, 2) AS n, 3::VARCHAR AS v, 'true'::BOOLEAN AS b, '2024-01-02'::DATE AS d, '1.5'::FLOAT AS f", [(12, 7, "3", True, _D(2024, 1, 2), 1.5)]),
    # Query syntax and identifiers.
    ("SELECT ID, UPPER(Name) AS Upper_Name FROM T WHERE Name ILIKE 'a%' OR code LIKE ANY ('x%', 'z%') ORDER BY 1", [(1, "ANN"), (2, "BOB")]),
    ("SELECT TOP 2 id FROM t ORDER BY id DESC", [(3,), (2,)]),
    ("SELECT grp, COUNT(*) AS n FROM t GROUP BY ALL HAVING COUNT(*) > 1", [("x", 2)]),
    ("SELECT id FROM t QUALIFY ROW_NUMBER() OVER (PARTITION BY grp ORDER BY id DESC) = 1 ORDER BY id", [(2,), (3,)]),
    ("WITH a AS (SELECT id FROM t WHERE id < 3) SELECT id FROM a MINUS SELECT 1 UNION ALL SELECT 9 ORDER BY id", [(2,), (9,)]),
    ("SELECT a.id, b.id AS other FROM t AS a LEFT JOIN t AS b ON a.id = b.id + 1 WHERE a.id IN (1, 2) AND EXISTS (SELECT 1 FROM t AS c WHERE c.id = a.id) ORDER BY a.id", [(1, None), (2, 1)]),
    ("SELECT id FROM t NATURAL JOIN (SELECT 2 AS id) AS x", [(2,)]),
    ("SELECT id FROM t JOIN (SELECT 3 AS id) USING (id)", [(3,)]),
    ("SELECT id FROM t WHERE note IS DISTINCT FROM 'k' AND id BETWEEN 1 AND 3 ORDER BY id", [(1,), (3,)]),
    ("SELECT $$it's$$ AS a, 'it''s' AS b, 'a\\\\b' AS c", [("it's", "it's", "a\\b")]),
]
for source, expected in SNOWFLAKE_SEMANTICS:
    translated = translate(source).sql
    actual = [tuple(float(v) if type(v).__name__ == "Decimal" else v for v in row) for row in _sf.execute(translated).fetchall()]
    assert actual == expected, (source, translated, actual, expected)
_names = _sf.execute(translate("SELECT ID, UPPER(Name) AS Upper_Name, id AS \"Kept Case\" FROM T").sql).description
assert [d[0] for d in _names] == ["id", "upper_name", "Kept Case"], _names
try:
    _sf.execute(translate("SELECT 10 / amount AS r FROM t").sql).fetchall()
    raise AssertionError("Snowflake raises on division by zero")
except _duckdb.Error as error:
    assert "Division by zero" in str(error), error
assert "REGEXP_SUBSTR returns NULL when nothing matches" in translate("SELECT REGEXP_SUBSTR(code, 'b') FROM t").rewrites

SNOWFLAKE_REFUSED = {
    "SELECT HASH(name) FROM t": "HASH is not in the supported Snowflake subset",
    "SELECT REGEXP_INSTR(code, '1') FROM t": "REGEXP_INSTR is not in the supported Snowflake subset",
    "SELECT REGEXP_LIKE(code, 'A', 'i') FROM t": "parameter arguments",
    "SELECT REGEXP_SUBSTR(code, '[0-9]', 1, 2) FROM t": "position, occurrence",
    "SELECT CURRENT_DATE() AS d": "not in the supported Snowflake subset",
    "SELECT RANDOM() AS r": "RANDOM is not in the supported Snowflake subset",
    "SELECT * FROM t, LATERAL FLATTEN(input => ARRAY_CONSTRUCT(1, 2)) f": "not in the supported Snowflake subset",
    "SELECT PARSE_JSON(note):a FROM t": "not in the supported Snowflake subset",
    "SELECT id FROM t SAMPLE (50)": "SAMPLE is not in the supported Snowflake subset",
    "SELECT COUNT(DISTINCT id, name) FROM t": "COUNT(DISTINCT a, b)",
    "SELECT CAST(ts AS TIMESTAMP_TZ) FROM t": "Type",
    "SELECT DATEADD(day, 1, d) FROM t": "needs an argument whose type is explicit",
    "SELECT DATE_TRUNC('month', d) FROM t": "needs an argument whose type is explicit",
    "SELECT TO_CHAR(d, 'YYYY-MM') FROM t": "TO_CHAR is not in the supported Snowflake subset",
    "SELECT TO_CHAR(d::DATE, 'YYYY \"Q\"Q') FROM t": "format",
    "SELECT WEEK(d::DATE) FROM t": "not in the supported Snowflake subset",
    "SELECT id % amount FROM t": "MOD and % need a non-zero number literal",
    "SELECT d + INTERVAL '1 day' FROM t": "INTERVAL",
    "SELECT $1 FROM t": "$ column references",
    "DELETE FROM t": "Only a SELECT query is supported",
    "CREATE TABLE x AS SELECT 1 AS a": "Only a SELECT query is supported",
    "SELECT 1; SELECT 2": "exactly one query",
    "SELECT id FROM t WHERE id = ANY (SELECT 1)": "ANY",
    "SELECT FROM WHERE": "could not be parsed",
}
for source, fragment in SNOWFLAKE_REFUSED.items():
    try:
        translate(source)
        raise AssertionError(f"Snowflake subset should refuse: {source}")
    except SnowflakeDialectError as error:
        assert fragment in str(error), (source, str(error))
        assert "could not be parsed" in str(error) or "not Snowflake" in str(error), str(error)
_sf.close()

# The kernel runs the translation on exercise fixtures (typed CTEs), like the sql language.
with TemporaryDirectory(prefix="datapass-snowflake-smoke-") as temp:
    from datapass_runtime.execution import Engine
    engine = Engine(Path(temp), "duckdb")
    assert next(k for k in engine.capabilities()["kernels"] if k["id"] == "snowflake")["available"]
    orders = "\"orders\" AS (SELECT CAST(1 AS INTEGER) AS \"order_id\", CAST('2024-01-31' AS DATE) AS \"order_date\", CAST(NULL AS VARCHAR) AS \"note\" " \
             "UNION ALL SELECT CAST(2 AS INTEGER), CAST('2024-02-01' AS DATE), CAST('gift' AS VARCHAR))"
    run = engine.execute({"language": "snowflake", "cell_id": "c", "notebook_id": "n", "_exercise_fixture_ctes": orders,
                          "code": "SELECT ORDER_ID, DATEADD(month, 1, order_date::DATE) AS due, CONCAT('#', note) AS tag FROM ORDERS ORDER BY order_id;"})
    assert run["status"] == "success", run
    assert run["result"]["columns"] == ["order_id", "due", "tag"], run["result"]
    assert run["result"]["rows"] == [{"order_id": 1, "due": "2024-02-29", "tag": None}, {"order_id": 2, "due": "2024-03-01", "tag": "#gift"}], run["result"]
    assert run["dialect"]["source"] == "snowflake" and run["dialect"]["target"] == "duckdb", run["dialect"]
    assert run["dialect"]["rewrites"] == ["DATEADD of a DATE stays a DATE"], run["dialect"]
    assert run["dialect"]["label"] == "Snowflake SQL dialect translated to DuckDB, not Snowflake", run["dialect"]
    refused = engine.execute({"language": "snowflake", "cell_id": "c", "notebook_id": "n", "_exercise_fixture_ctes": orders,
                              "code": "SELECT REGEXP_INSTR(note, 'g') AS i FROM orders"})
    assert refused["status"] == "error" and refused["error"]["type"] == "SnowflakeDialectError", refused
    assert "REGEXP_INSTR" in refused["error"]["message"], refused
    engine.catalog.close()


# --- SQL dialects translated to DuckDB: T-SQL, BigQuery, Spark SQL (ANSI), PostgreSQL ---------------------------------
# Each expected value is the engine's documented result; types come from a schema, as the catalog gives them.
from decimal import Decimal as _Decimal

from sqldialects import DialectError, translate_expression

_T = _dt.datetime

DIALECT_TABLE = """CREATE TABLE t AS SELECT * FROM (VALUES
    (1, 'Ann', 'a1b22', DATE '2024-01-31', TIMESTAMP '2024-01-31 10:15:00', 10.0::DOUBLE, NULL::VARCHAR, 'x', 7, 2.50::DECIMAL(10,2)),
    (2, 'bob', 'xyz', DATE '2024-02-29', TIMESTAMP '2024-02-29 23:30:00', 0.0::DOUBLE, 'k', 'x', -7, 3.75::DECIMAL(10,2)),
    (3, 'Cy', NULL, DATE '2024-03-10', TIMESTAMP '2024-03-10 00:00:00', 2.5::DOUBLE, 'm', 'y', 2, 1.00::DECIMAL(10,2))
) AS v(id, name, code, d, ts, amount, note, grp, qty, price)"""
DIALECT_SCHEMA = {'t': {'id': 'INTEGER', 'name': 'VARCHAR', 'code': 'VARCHAR', 'd': 'DATE', 'ts': 'TIMESTAMP', 'amount': 'DOUBLE',
                'note': 'VARCHAR', 'grp': 'VARCHAR', 'qty': 'INTEGER', 'price': 'DECIMAL(10,2)'}}

DIALECT_SEMANTICS = {
    'tsql': [
        ("SELECT 7 / 2 AS a, -7 / 2 AS b, 7 / 2.0 AS c, 7 % 3 AS m, -7 % 3 AS n", [(3, -3, 3.5, 1, -1)]),
        ("SELECT qty / 2 AS h FROM t ORDER BY id", [(3,), (-3,), (1,)]),
        ("SELECT SUM(qty) / COUNT(*) AS s, AVG(qty + 10) AS a, ROUND(AVG(price), 2) AS p FROM t", [(0, 10, 2.42)]),
        ("SELECT id, AVG(id) OVER (ORDER BY id ROWS BETWEEN 1 PRECEDING AND CURRENT ROW) AS w FROM t ORDER BY id", [(1, 1), (2, 1), (3, 2)]),
        ("SELECT note FROM t ORDER BY note", [(None,), ("k",), ("m",)]),
        ("SELECT note FROM t ORDER BY note DESC", [("m",), ("k",), (None,)]),
        ("SELECT name + '-' + grp AS c, 'a' + note AS n FROM t ORDER BY id", [("Ann-x", None), ("bob-x", "ak"), ("Cy-y", "am")]),
        ("SELECT CONCAT('a', note, 'b') AS c, CONCAT_WS('-', 'a', note, 'b') AS w FROM t WHERE id = 1", [("ab", "a-b")]),
        ("SELECT LEN('ab  ') AS l, LEN('  ab') AS m, LEN(name) AS n FROM t WHERE id = 1", [(2, 4, 3)]),
        ("SELECT CAST(2.5 AS INT) AS a, CAST(-2.5 AS INT) AS b, CAST(amount AS INT) AS c, CAST(price AS INT) AS p FROM t WHERE id = 3", [(2, -2, 2, 1)]),
        ("SELECT CAST('42' AS INT) AS a, TRY_CAST('2.5' AS INT) AS b, TRY_CAST(' 7 ' AS INT) AS c, TRY_CONVERT(INT, 'x') AS e", [(42, None, 7, None)]),
        ("SELECT CAST('abcdef' AS VARCHAR(3)) AS a, CAST(123 AS VARCHAR(2)) AS b, CAST('ab' AS CHAR(4)) + '|' AS c, CAST(REPLICATE('x', 40) AS VARCHAR) AS d",
         [("abc", "*", "ab  |", "x" * 30)]),
        ("SELECT DATEADD(month, 1, d) AS m, DATEADD(day, 1, d) AS n, DATEADD(hour, 2, ts) AS h, DATEADD(quarter, 1, d) AS q FROM t WHERE id = 1",
         [(_D(2024, 2, 29), _D(2024, 2, 1), _T(2024, 1, 31, 12, 15), _D(2024, 4, 30))]),
        ("SELECT DATEADD(day, 30, '2026-01-01') AS d", [(_T(2026, 1, 31),)]),
        ("SELECT DATEDIFF(day, '2024-01-01', '2024-03-01') AS d, DATEDIFF(month, '2024-01-31', '2024-02-01') AS m, "
         "DATEDIFF(year, '2023-12-31', '2024-01-01') AS y, DATEDIFF(week, '2024-01-06', '2024-01-07') AS w, "
         "DATEDIFF(week, '2024-01-07', '2024-01-13') AS w0, DATEDIFF(hour, '2024-01-01 10:59', '2024-01-01 11:01') AS h, "
         "DATEDIFF(day, d, ts) AS dd FROM t WHERE id = 2", [(60, 1, 1, 1, 0, 1, 0)]),
        ("SELECT DATEPART(weekday, d) AS w, DATEPART(dayofyear, d) AS y, DATEPART(iso_week, d) AS i, DATEPART(quarter, d) AS q, "
         "YEAR(d) AS yy, MONTH(d) AS mm, DAY(d) AS dd, DATEPART(hour, ts) AS hh FROM t WHERE id = 3", [(1, 70, 10, 1, 2024, 3, 10, 0)]),
        ("SELECT DATENAME(month, d) AS m, DATENAME(weekday, d) AS w FROM t WHERE id = 1", [("January", "Wednesday")]),
        ("SELECT EOMONTH(d) AS e, EOMONTH(d, 1) AS n, DATEFROMPARTS(2024, 2, 29) AS p FROM t WHERE id = 1", [(_D(2024, 1, 31), _D(2024, 2, 29), _D(2024, 2, 29))]),
        ("SELECT CONVERT(VARCHAR(10), d, 103) AS a, CONVERT(VARCHAR(8), d, 112) AS b, CONVERT(VARCHAR(19), ts, 120) AS c, "
         "CONVERT(VARCHAR(10), ts, 120) AS c10, CONVERT(DATE, '31/01/2024', 103) AS p, CONVERT(INT, '12') AS i FROM t WHERE id = 1",
         [("31/01/2024", "20240131", "2024-01-31 10:15:00", "2024-01-31", _D(2024, 1, 31), 12)]),
        ("SELECT TOP 2 id FROM t ORDER BY id DESC", [(3,), (2,)]),
        ("SELECT id FROM t ORDER BY id OFFSET 1 ROWS FETCH NEXT 1 ROWS ONLY", [(2,)]),
        ("SELECT * FROM (SELECT TOP 1 name FROM t ORDER BY id DESC) AS x", [("Cy",)]),
        ("SELECT IIF(1 > 2, 'y', 'n') AS i, ISNULL(NULL, 2) AS n, NULLIF(1, 1) AS ni, COALESCE(NULL, NULL, 4) AS c, GREATEST(1, NULL, 3) AS g",
         [("n", 2, None, 4, 3)]),
        ("SELECT LEFT('abc', 2) AS l, RIGHT('abc', 2) AS r, SUBSTRING('abcdef', 2, 3) AS s, SUBSTRING('abcdef', 0, 2) AS s0, "
         "SUBSTRING('abcdef', -1, 3) AS sn, CHARINDEX('c', 'abcabc') AS c, CHARINDEX('c', 'abcabc', 4) AS c2, REPLICATE('x', 3) AS rep, "
         "STUFF('abcdef', 2, 3, 'X') AS st, REVERSE('ab') AS rv, UPPER('a') AS u, LTRIM('  a') AS lt, RTRIM('a  ') AS rt, TRIM('  a  ') AS tr",
         [("ab", "bc", "bcd", "a", "a", 3, 6, "xxx", "aXef", "ba", "A", "a", "a", "a")]),
        ("SELECT grp, STRING_AGG(name, ',') WITHIN GROUP (ORDER BY name DESC) AS l FROM t GROUP BY grp ORDER BY grp", [("x", "bob,Ann"), ("y", "Cy")]),
        ("SELECT id, ROW_NUMBER() OVER (ORDER BY note) AS rn, LAG(id) OVER (ORDER BY id) AS lg, LEAD(id, 1, 0) OVER (ORDER BY id) AS ld FROM t ORDER BY id",
         [(1, 1, None, 2), (2, 2, 1, 3), (3, 3, 2, 0)]),
        ("SELECT ROUND(2.5, 0) AS r, ROUND(-2.5, 0) AS rn, ROUND(2.345, 2) AS r2, CEILING(1.2) AS c, FLOOR(-1.2) AS f, ABS(-2) AS a, "
         "POWER(2, 3) AS p, POWER(2, 0.5) AS p2, SQRT(16.0) AS q, SIGN(-3) AS s", [(3, -3, 2.35, 2, -2, 2, 8, 1, 4.0, -1)]),
        ("SELECT CAST('12' AS BIGINT) AS i, CAST('7.5' AS DECIMAL(10, 2)) AS n, CAST(7.6 AS DECIMAL) AS n0, CAST('2024-01-02' AS DATE) AS d, "
         "CAST(1 AS BIT) AS b, CAST('1.5' AS FLOAT) AS f", [(12, 7.5, 8, _D(2024, 1, 2), True, 1.5)]),
        ("WITH a AS (SELECT id FROM t WHERE id < 3) SELECT a.id FROM a WHERE EXISTS (SELECT 1 FROM t AS c WHERE c.id = a.id) ORDER BY a.id", [(1,), (2,)]),
        ("SELECT [id], N'x' AS [s] FROM [t] WHERE [id] = 1 OPTION (LABEL = 'report')", [(1, "x")]),
        ("SELECT COUNT_BIG(*) AS n, STDEVP(id) AS sp, VARP(id) AS vp FROM t", [(3, 0.816496580927726, 0.6666666666666666)]),
    ],
    'bigquery': [
        ("SELECT 7 / 2 AS a, DIV(7, 2) AS b, DIV(-7, 2) AS c, MOD(-7, 3) AS m, SAFE_DIVIDE(1, 0) AS s", [(3.5, 3, -3, -1, None)]),
        ("SELECT note FROM t ORDER BY note", [(None,), ("k",), ("m",)]),
        ("SELECT note FROM t ORDER BY note DESC", [("m",), ("k",), (None,)]),
        ("SELECT CONCAT('a', NULL) AS c, CONCAT('a', 'b') AS d, 'a' || 'b' AS e", [(None, "ab", "ab")]),
        ("SELECT GREATEST(1, NULL, 3) AS g, LEAST(2, 5) AS l", [(None, 2)]),
        ("SELECT DATE_ADD(d, INTERVAL 1 MONTH) AS m, DATE_SUB(d, INTERVAL 1 DAY) AS s, DATE_ADD(d, INTERVAL 1 QUARTER) AS q FROM t WHERE id = 1",
         [(_D(2024, 2, 29), _D(2024, 1, 30), _D(2024, 4, 30))]),
        ("SELECT DATE_DIFF(DATE '2024-03-01', DATE '2024-01-01', DAY) AS d, DATE_DIFF(DATE '2024-02-01', DATE '2024-01-31', MONTH) AS m, "
         "DATE_DIFF(DATE '2024-01-07', DATE '2024-01-06', WEEK) AS w, DATE_DIFF(DATE '2024-01-13', DATE '2024-01-07', WEEK) AS w0, "
         "DATE_DIFF(DATE '2024-01-08', DATE '2024-01-07', ISOWEEK) AS iw", [(60, 1, 1, 0, 1)]),
        ("SELECT DATE_TRUNC(d, MONTH) AS m, DATE_TRUNC(d, WEEK) AS w, DATE_TRUNC(d, ISOWEEK) AS iw, DATE_TRUNC(d, YEAR) AS y FROM t WHERE id = 1",
         [(_D(2024, 1, 1), _D(2024, 1, 28), _D(2024, 1, 29), _D(2024, 1, 1))]),
        ("SELECT EXTRACT(DAYOFWEEK FROM d) AS w, EXTRACT(DAYOFYEAR FROM d) AS y, EXTRACT(ISOWEEK FROM d) AS iw, EXTRACT(QUARTER FROM d) AS q FROM t WHERE id = 3",
         [(1, 70, 10, 1)]),
        ("SELECT FORMAT_DATE('%Y-%m', d) AS f, FORMAT_DATE('%d %b %Y', d) AS g, PARSE_DATE('%d/%m/%Y', '31/01/2024') AS p FROM t WHERE id = 1",
         [("2024-01", "31 Jan 2024", _D(2024, 1, 31))]),
        ("SELECT DATE(2024, 2, 29) AS d, LAST_DAY(DATE '2024-02-10') AS l, DATE(ts) AS dt FROM t WHERE id = 1", [(_D(2024, 2, 29), _D(2024, 2, 29), _D(2024, 1, 31))]),
        ("SELECT REGEXP_CONTAINS('abc', r'b') AS c, REGEXP_EXTRACT('ab12c34', r'[0-9]+') AS e, REGEXP_EXTRACT('abc', r'[0-9]+') AS n, "
         "REGEXP_EXTRACT('ab12', r'b([0-9])') AS g, REGEXP_REPLACE('a1b2', r'[0-9]', '#') AS r", [(True, "12", None, "1", "a#b#")]),
        ("SELECT CAST(2.5 AS INT64) AS a, CAST(-2.5 AS INT64) AS b, CAST(amount AS INT64) AS c, CAST('42' AS INT64) AS d, SAFE_CAST('2.5' AS INT64) AS e, "
         "CAST('7.123456789' AS NUMERIC) AS n, CAST(1.5 AS STRING) AS s FROM t WHERE id = 3", [(3, -3, 3, 42, None, 7.123456789, "1.5")]),
        ("SELECT SUBSTR('abcdef', 2, 3) AS a, SUBSTR('abcdef', 0, 2) AS b, SUBSTR('abcdef', -2) AS c, STRPOS('abc', 'c') AS p, LENGTH('abc') AS l, "
         "STARTS_WITH('abc', 'a') AS s, LPAD('7', 3, '0') AS lp", [("bcd", "ab", "ef", 3, 3, True, "007")]),
        ("SELECT grp, COUNT(*) AS n, COUNTIF(amount > 1) AS c, STRING_AGG(name, ',' ORDER BY name DESC) AS l, LOGICAL_AND(id > 0) AS a, AVG(id) AS av "
         "FROM t GROUP BY grp ORDER BY grp", [("x", 2, 1, "bob,Ann", True, 1.5), ("y", 1, 1, "Cy", True, 3.0)]),
        ("SELECT id FROM t WHERE TRUE QUALIFY ROW_NUMBER() OVER (PARTITION BY grp ORDER BY id DESC) = 1 ORDER BY id", [(2,), (3,)]),
        ("SELECT * EXCEPT (name, code, d, ts, amount, note, qty, price) FROM t ORDER BY id", [(1, "x"), (2, "x"), (3, "y")]),
        ("SELECT IF(1 > 2, 'y', 'n') AS i, IFNULL(NULL, 2) AS n, COALESCE(NULL, 3) AS c", [("n", 2, 3)]),
        ("SELECT `id` FROM `t` WHERE `id` = 1", [(1,)]),
        ("SELECT ROUND(2.5) AS a, ROUND(-2.5) AS b, ROUND(amount) AS c, TRUNC(2.7) AS t FROM t WHERE id = 3", [(3, -3, 3.0, 2)]),
    ],
    'spark': [
        ("SELECT 7 / 2 AS a, 7 DIV 2 AS b, -7 DIV 2 AS c, -7 % 3 AS m", [(3.5, 3, -3, -1)]),
        ("SELECT note FROM t ORDER BY note", [(None,), ("k",), ("m",)]),
        ("SELECT note FROM t ORDER BY note DESC", [("m",), ("k",), (None,)]),
        ("SELECT CONCAT('a', NULL) AS c, CONCAT_WS('-', 'a', NULL, 'b') AS w, GREATEST(1, NULL, 3) AS g", [(None, "a-b", 3)]),
        ("SELECT DATE_ADD(d, 1) AS a, DATE_SUB(d, 1) AS s, ADD_MONTHS(d, 1) AS m, DATEDIFF(d, DATE '2024-01-01') AS dd, TRUNC(d, 'MM') AS tm, "
         "DATE_TRUNC('MONTH', d) AS dm, LAST_DAY(d) AS l FROM t WHERE id = 1",
         [(_D(2024, 2, 1), _D(2024, 1, 30), _D(2024, 2, 29), 30, _D(2024, 1, 1), _T(2024, 1, 1), _D(2024, 1, 31))]),
        ("SELECT DAYOFWEEK(d) AS w, EXTRACT(DAYOFWEEK FROM d) AS e, DAYOFYEAR(d) AS y, QUARTER(d) AS q, YEAR(d) AS yy FROM t WHERE id = 3", [(1, 1, 70, 1, 2024)]),
        ("SELECT DATE_FORMAT(d, 'yyyy-MM') AS f, DATE_FORMAT(ts, 'yyyy-MM-dd HH:mm') AS g, TO_DATE('31/01/2024', 'dd/MM/yyyy') AS p, TO_DATE('2024-01-02') AS q "
         "FROM t WHERE id = 1", [("2024-01", "2024-01-31 10:15", _D(2024, 1, 31), _D(2024, 1, 2))]),
        ("SELECT 'abc' RLIKE 'b' AS r, REGEXP_EXTRACT('ab12', '([0-9]+)') AS e, REGEXP_EXTRACT('abc', '([0-9]+)', 1) AS n, REGEXP_REPLACE('a1b2', '[0-9]', '#') AS rr",
         [(True, "12", "", "a#b#")]),
        ("SELECT CAST(2.5 AS INT) AS a, CAST(-2.5 AS INT) AS b, CAST(amount AS INT) AS c, CAST('42' AS INT) AS d, TRY_CAST('2.5' AS INT) AS e, "
         "CAST('7.5' AS DECIMAL(10, 1)) AS n, CAST(7.6 AS DECIMAL) AS n0 FROM t WHERE id = 3", [(2, -2, 2, 42, None, 7.5, 8)]),
        ("SELECT SUBSTRING('abcdef', 0, 2) AS a, SUBSTR('abcdef', -2) AS b, INSTR('abc', 'c') AS i, LOCATE('c', 'abc') AS l, SPLIT_PART('a,b,c', ',', -1) AS sp, "
         "LENGTH('ab ') AS n", [("ab", "ef", 3, 3, "c", 3)]),
        ("SELECT grp, COUNT_IF(amount > 1) AS c, MEDIAN(id) AS m, BOOL_AND(id > 0) AS b FROM t GROUP BY grp ORDER BY grp", [("x", 1, 1.5, True), ("y", 1, 3.0, True)]),
        ("SELECT IF(1 > 2, 'y', 'n') AS i, NVL(NULL, 2) AS n, NVL2(NULL, 1, 2) AS n2, COALESCE(NULL, 3) AS c", [("n", 2, 2, 3)]),
        ("SELECT ROUND(2.5) AS a, ROUND(-2.5) AS b, ROUND(amount) AS c FROM t WHERE id = 3", [(3, -3, 3.0)]),
        ("SELECT `id` FROM `t` WHERE `id` = 1", [(1,)]),
        ("SELECT id FROM t QUALIFY ROW_NUMBER() OVER (PARTITION BY grp ORDER BY id DESC) = 1 ORDER BY id", [(2,), (3,)]),
    ],
    'postgres': [
        ("SELECT 7 / 2 AS a, -7 / 2 AS b, 7.0 / 2 AS c, 7 % 3 AS m, -7 % 3 AS n, DIV(7, 2) AS d", [(3, -3, 3.5, 1, -1, 3)]),
        ("SELECT qty / 2 AS h FROM t ORDER BY id", [(3,), (-3,), (1,)]),
        ("SELECT note FROM t ORDER BY note", [("k",), ("m",), (None,)]),
        ("SELECT note FROM t ORDER BY note DESC", [(None,), ("m",), ("k",)]),
        ("SELECT CONCAT('a', NULL, 'b') AS c, 'a' || NULL AS p, CONCAT_WS('-', 'a', NULL, 'b') AS w", [("ab", None, "a-b")]),
        ("SELECT CAST(2.5 AS INT) AS a, CAST(-2.5 AS INT) AS b, 2.5::float8::int AS c, 3.5::float8::int AS c2, '42'::int AS d, "
         "'abcdef'::varchar(3) AS v, 1.5::numeric AS n", [(3, -3, 2, 4, 42, "abc", 1.5)]),
        ("SELECT ROUND(2.5) AS a, ROUND(-2.5) AS b, ROUND(2.5::float8) AS c, ROUND(3.5::float8) AS d, ROUND(2.345, 2) AS e, TRUNC(2.99) AS t, "
         "ROUND(AVG(qty)::numeric, 2) AS av FROM t", [(3, -3, 2.0, 4.0, 2.35, 2, 0.67)]),
        ("SELECT d + 1 AS a, d - DATE '2024-01-01' AS b, d + INTERVAL '1 month' AS c, DATE_TRUNC('month', d) AS m, EXTRACT(DOW FROM d) AS w, "
         "EXTRACT(ISODOW FROM d) AS iw, EXTRACT(DOY FROM d) AS y FROM t WHERE id = 3", [(_D(2024, 3, 11), 69, _T(2024, 4, 10), _T(2024, 3, 1), 0, 7, 70)]),
        ("SELECT TO_CHAR(d, 'YYYY-MM-DD') AS a, TO_CHAR(ts, 'HH24:MI') AS b, TO_DATE('31/01/2024', 'DD/MM/YYYY') AS c FROM t WHERE id = 1",
         [("2024-01-31", "10:15", _D(2024, 1, 31))]),
        ("SELECT SUBSTRING('abcdef', 2, 3) AS a, SUBSTRING('abcdef' FROM 2 FOR 3) AS b, SUBSTRING('abcdef', 0, 2) AS c, SUBSTRING('abcdef', -1, 3) AS d, "
         "POSITION('c' IN 'abc') AS p, LEFT('abcdef', -2) AS l, SPLIT_PART('a,b,c', ',', -1) AS sp, 'abc' ~ 'b' AS rx, 'ABC' ~* 'b' AS rxi, "
         "REGEXP_REPLACE('a1b2', '[0-9]', '#') AS r1, REGEXP_REPLACE('a1b2', '[0-9]', '#', 'g') AS rg",
         [("bcd", "bcd", "a", "a", 3, "abcd", "c", True, True, "a#b2", "a#b#")]),
        ("SELECT grp, STRING_AGG(name, ',' ORDER BY name DESC) AS l, COUNT(*) FILTER (WHERE amount > 1) AS c, BOOL_AND(id > 0) AS b, AVG(id) AS a "
         "FROM t GROUP BY grp ORDER BY grp", [("x", "bob,Ann", 1, True, 1.5), ("y", "Cy", 1, True, 3.0)]),
        ("SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY id) AS m FROM t", [(2.0,)]),
        ("SELECT DISTINCT ON (grp) grp, id FROM t ORDER BY grp, id DESC", [("x", 2), ("y", 3)]),
        ("SELECT GREATEST(1, NULL, 3) AS g, LEAST(2, NULL) AS l", [(3, 2)]),
        ("SELECT id FROM t ORDER BY id LIMIT 1 OFFSET 1", [(2,)]),
        ("SELECT ID, Name AS FullName FROM T WHERE id = 1", [(1, "Ann")]),
    ],
}
DIALECT_COLUMNS = {('postgres', "SELECT ID, Name AS FullName FROM T WHERE id = 1"): ['id', 'fullname']}
DIALECT_DIVISION = {'tsql': 'Divide by zero', 'bigquery': 'division by zero', 'spark': 'DIVIDE_BY_ZERO', 'postgres': 'division by zero'}
DIALECT_REFUSED = {
    'tsql': {
        "SELECT GETDATE() AS g": "the clock", "SELECT NEWID() AS u": "the clock", "SELECT * FROM #tmp": "Temporary tables",
        "SELECT @x AS v": "Variables", "SELECT @@ROWCOUNT AS r": "System variable", "SELECT id INTO t2 FROM t": "SELECT ... INTO",
        "SELECT TOP 10 PERCENT id FROM t": "PERCENT", "SELECT FORMAT(d, 'yyyy-MM') FROM t": "FORMAT and DATENAME",
        "SELECT CAST(ts AS VARCHAR(20)) FROM t": "style 0", "SELECT CAST(amount AS VARCHAR(10)) FROM t": "scientific",
        "SELECT DATEPART(week, d) FROM t": "iso_week", "SELECT CONVERT(VARCHAR(10), d, 107) FROM t": "CONVERT style 107",
        "SELECT CHOOSE(1, 'a', 'b')": "CHOOSE is not in the supported T-SQL subset", "SELECT PATINDEX('%a%', name) FROM t": "PATINDEX",
        "SELECT name FROM t WHERE name LIKE '[A-C]%'": "character classes", "SELECT d + 1 FROM t": "use DATEADD",
        "SELECT ROUND(amount) FROM t": "ROUND needs its length", "SELECT DATEADD(hour, 1, d) FROM t": "of a DATE is an error",
        "SELECT * FROM t CROSS APPLY (SELECT 1 AS x) AS a": "APPLY", "DELETE FROM t": "Only a SELECT query",
        "SELECT FROM WHERE": "could not be parsed", "SELECT * FROM read_csv('x.csv')": "table functions",
        "SELECT CAST(x AS DATETIMEOFFSET) FROM t": "Type", "SELECT 1; SELECT 2": "exactly one query",
    },
    'bigquery': {
        "SELECT x FROM UNNEST([1, 2]) AS x": "UNNEST", "SELECT ARRAY_AGG(id) FROM t": "ARRAY_AGG", "SELECT CURRENT_DATE()": "the clock",
        "SELECT EXTRACT(WEEK FROM d) FROM t": "ISOWEEK", "SELECT REGEXP_EXTRACT(name, r'(a)(b)') FROM t": "more than one capturing group",
        "SELECT FORMAT_DATE('%E4Y', d) FROM t": "format", "SELECT id FROM myproject.silver.t": "project.dataset.table",
        "SELECT CAST(id AS BIGNUMERIC) FROM t": "Type", "SELECT APPROX_COUNT_DISTINCT(id) FROM t": "APPROX_COUNT_DISTINCT",
        "SELECT STRUCT(1 AS a) AS s": "STRUCT", "SELECT TIMESTAMP_ADD(ts, INTERVAL 1 HOUR) FROM t": "TIMESTAMP_ADD",
    },
    'spark': {
        "SELECT EXPLODE(ARRAY(1, 2))": "EXPLODE", "SELECT COLLECT_LIST(id) FROM t": "COLLECT_LIST", "SELECT SPLIT(name, ',') FROM t": "SPLIT",
        "SELECT CURRENT_DATE()": "the clock", "SELECT MONTHS_BETWEEN(d, d) FROM t": "MONTHS_BETWEEN", "SELECT FIRST(id) FROM t": "FIRST",
        "SELECT DATE_FORMAT(d, 'Q') FROM t": "pattern", "SELECT BROUND(amount) FROM t": "BROUND",
    },
    'postgres': {
        "SELECT NOW()": "the clock", "SELECT GENERATE_SERIES(1, 3)": "GENERATE_SERIES", "SELECT ARRAY[1, 2]": "Array is not in the supported",
        "SELECT AGE(d, d) FROM t": "AGE", "SELECT ts::timestamptz FROM t": "Type", "SELECT ROUND(amount, 1) FROM t": "does not exist",
        "SELECT EXTRACT(EPOCH FROM ts) FROM t": "EPOCH", "SELECT SUBSTRING(name FROM 'a.') FROM t": "FROM pattern",
        "SELECT name::char(3) FROM t": "Type", "SELECT REGEXP_REPLACE(name, 'a', 'b', 'i') FROM t": "flags",
        "SELECT ts - ts FROM t": "INTERVAL",
    },
}

_dx = _duckdb.connect()
_dx.execute(DIALECT_TABLE)
for _dialect, _cases in DIALECT_SEMANTICS.items():
    for source, expected in _cases:
        translated = translate(source, _dialect, schema=DIALECT_SCHEMA).sql
        cursor = _dx.execute(translated)
        actual = [tuple(float(v) if isinstance(v, _Decimal) else v for v in row) for row in cursor.fetchall()]
        assert actual == expected, (_dialect, source, translated, actual, expected)
        if (_dialect, source) in DIALECT_COLUMNS:
            assert [d[0] for d in cursor.description] == DIALECT_COLUMNS[(_dialect, source)], cursor.description
    try:
        _dx.execute(translate("SELECT 10 / amount AS r FROM t", _dialect, schema=DIALECT_SCHEMA).sql).fetchall()
        raise AssertionError(f"{_dialect} raises on division by zero")
    except _duckdb.Error as error:
        assert DIALECT_DIVISION[_dialect] in str(error), (_dialect, error)
    for source, fragment in DIALECT_REFUSED[_dialect].items():
        try:
            translate(source, _dialect, schema=DIALECT_SCHEMA)
            raise AssertionError(f"{_dialect} subset should refuse: {source}")
        except DialectError as error:
            assert fragment in str(error), (_dialect, source, str(error))
            assert "could not be parsed" in str(error) or "dialect translated to DuckDB, not" in str(error), str(error)
# Without a schema, a rule that needs a type refuses instead of guessing.
for _dialect, source in (("tsql", "SELECT qty / 2 FROM t"), ("postgres", "SELECT qty / 2 FROM t"), ("tsql", "SELECT AVG(qty) FROM t"),
                         ("tsql", "SELECT CAST(amount AS INT) FROM t"), ("postgres", "SELECT ROUND(amount) FROM t")):
    try:
        translate(source, _dialect)
        raise AssertionError(f"{_dialect}: {source} needs a known type")
    except DialectError as error:
        assert "known here" in str(error), (source, str(error))
# Scripts (Mosaic): CREATE TABLE/VIEW AS, INSERT, DROP; other statements are refused with the supported list.
_catalog_types = {"main": {"t": DIALECT_SCHEMA["t"]}}  # {schema: {table: columns}}, as the catalog gives them
script = translate("CREATE TABLE silver.x AS SELECT TOP 2 id, qty / 2 AS h FROM main.t ORDER BY id;\nINSERT INTO silver.x SELECT 9, 9 / 2;\n"
                   "CREATE OR REPLACE VIEW silver.v AS SELECT * FROM silver.x;\nSELECT SUM(h) AS s FROM silver.v;\nDROP VIEW IF EXISTS silver.v;",
                   "tsql", mode="script", schema=_catalog_types)
assert len(script.statements) == 5 and script.sql.endswith(";"), script.sql
_dx.execute("CREATE SCHEMA silver")
for statement in script.statements:
    _dx.execute(statement)
assert _dx.execute("SELECT SUM(h) FROM silver.x").fetchall() == [(3 - 3 + 4,)]  # 7 / 2, -7 / 2 and 9 / 2 as integers
for source, fragment in {"UPDATE t SET id = 1": "UPDATE statements are not translated", "CREATE TABLE silver.y (a INT)": "column definitions",
                         "SELECT id INTO silver.z FROM t": "SELECT ... INTO", "MERGE INTO t USING t AS s ON t.id = s.id WHEN MATCHED THEN DELETE": "MERGE"}.items():
    try:
        translate(source, "tsql", mode="script", schema=_catalog_types)
        raise AssertionError(source)
    except DialectError as error:
        assert fragment in str(error), (source, str(error))
assert translate_expression("CONCAT('a', ISNULL(NULL, 'b'))", "tsql").sql == "CONCAT('a', COALESCE(NULL, 'b'))"
_dx.close()


# Mirrors the SparkLab scratch starter written by the extension (src/scaffold/starters.ts).
SPARKLAB_SCRATCH = """from pyspark.sql import functions as F

orders = spark.table("source.orders")
revenue = orders.filter(F.col("net_amount") > 0).groupBy("customer_id").agg(F.sum("net_amount").alias("revenue"))
"""


def execute(manager, kernel_id, workspace, language, code, **extra):
    return manager.call(
        kernel_id,
        workspace / ".datapass" / "data",
        {"op": "execute", "language": language, "code": code, "notebook_id": "smoke",
         "cell_id": "cell", "output_asset": None, **extra},
        cwd=workspace,
    )


with TemporaryDirectory(prefix="datapass-trust-smoke-") as temp:
    workspace = Path(temp)
    (workspace / "datasets").mkdir()
    (workspace / "datasets" / "tiny.csv").write_text("id,amount\n1,10\n2,20\n", encoding="utf-8")

    untrusted = KernelManager(mode="duckdb", trusted=False, timeout=15.0, max_workers=1)
    try:
        blocked = execute(untrusted, "untrusted", workspace, "python", "1 + 1")
        assert blocked["status"] == "error", blocked
        assert "Trusted local Python is disabled" in blocked["error"]["message"], blocked
        kernels = untrusted.call("untrusted", workspace / ".datapass" / "data", {"op": "capabilities"}, cwd=workspace)["kernels"]
        assert not next(kernel for kernel in kernels if kernel["id"] == "python")["available"]
        assert next(kernel for kernel in kernels if kernel["id"] == "sparklab")["available"]

        # SparkLab needs no trust: the source is parsed by a whitelist, never executed.
        spark = execute(untrusted, "untrusted", workspace, "sparklab", SPARKLAB_SCRATCH, profile="generic_8x8", aqe=True)
        assert spark["status"] == "success", spark
        assert spark["result"]["columns"] == ["customer_id", "revenue"], spark["result"]
        assert spark["result"]["rows"], spark["result"]
        assert spark["compiled_sql"].upper().startswith("SELECT")
        assert spark["simulation"]["status"] == "modeled", spark["simulation"]
        assert "simulated" in spark["simulation"]["truth"].lower()
        assert spark["simulation"]["datapass_credits"]["fictional"] is True
        assert [node["operation"] for node in spark["simulation"]["logical_plan"]] == ["scan", "filter", "aggregate"]
        assert spark["simulation"]["metrics"]["plan_facts"]["exchanges"] == 1, spark["simulation"]["metrics"]["plan_facts"]

        for unsafe in ("import os\nos.system('echo unsafe')", "open('x.txt', 'w').write('x')"):
            rejected = execute(untrusted, "untrusted", workspace, "sparklab", unsafe)
            assert rejected["status"] == "error", rejected
            assert rejected["error"]["type"] == "SparkLabSyntaxError", rejected
        assert not (workspace / ".datapass" / "data" / "x.txt").exists()
        assert not (workspace / "x.txt").exists()
    finally:
        untrusted.close()

    trusted = KernelManager(mode="duckdb", trusted=True, timeout=30.0, max_workers=1)
    try:
        # Relative paths resolve from the workspace root, like `python file.py`.
        run = execute(
            trusted, "trusted", workspace, "python",
            "import polars as pl\nframe = pl.read_csv('datasets/tiny.csv')\nprint(frame.height)\nframe",
        )
        assert run["status"] == "success", run
        assert run["stdout"].strip() == "2", run["stdout"]
        assert run["result"]["columns"] == ["id", "amount"], run["result"]
        assert run["result"]["rows"] == [{"id": 1, "amount": 10}, {"id": 2, "amount": 20}], run["result"]
    finally:
        trusted.close()

print("Datapass runtime smoke passed.")
