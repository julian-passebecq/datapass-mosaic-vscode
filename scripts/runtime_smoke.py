from importlib import resources
import json
import os
from pathlib import Path
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
