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
