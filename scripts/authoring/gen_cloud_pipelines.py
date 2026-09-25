"""Generate content/exercise-packs/cloud-pipelines-v1 from authored specs.

Expected rows are computed by running each reference through the Cloud Lab grader
(`datapass_runtime.factory_grading.run_fixture`) with the fixture scenario; review
them by hand. The generator also checks that starters and mutants run and fail.
Run from the repository root with PYTHONPATH=runtime.
"""
from __future__ import annotations

import copy
import json
import textwrap
from pathlib import Path

from pack_quality import write_mutants

ROOT = Path.cwd()
PACK = ROOT / "content" / "exercise-packs" / "cloud-pipelines-v1"
EXERCISES: list[dict] = []
ZERO = "00000000-0000-0000-0000-000000000000"
PRODUCT = {"fabric": "Microsoft Fabric Data Factory", "adf": "Azure Data Factory", "synapse": "Azure Synapse pipelines"}


def code(text: str) -> str:
    return textwrap.dedent(text).strip("\n") + "\n"


def exercise(**spec):
    spec.setdefault("language", "factory")
    spec.setdefault("local", False)
    EXERCISES.append(spec)


# -- pipeline JSON builders ----------------------------------------------------------------------
def dep(item):
    if isinstance(item, str):
        return {"activity": item, "dependencyConditions": ["Succeeded"]}
    return {"activity": item[0], "dependencyConditions": list(item[1])}


def policy(timeout="0.12:00:00", retry=0, interval=30):
    return {"timeout": timeout, "retry": retry, "retryIntervalInSeconds": interval,
            "secureOutput": False, "secureInput": False}


def act(name, kind, after=(), props=None, pol=None, **extra):
    activity = {"name": name, "type": kind, "dependsOn": [dep(d) for d in after]}
    if pol is not None:
        activity["policy"] = pol
    activity.update(extra)
    activity["typeProperties"] = props if props is not None else {}
    return activity


def expr(value):
    return {"value": value, "type": "Expression"}


def pipeline(activities, parameters=None, variables=None, name=None, description=None):
    properties = {}
    if description:
        properties["description"] = description
    properties["activities"] = activities
    if parameters:
        properties["parameters"] = parameters
    if variables:
        properties["variables"] = variables
    properties["annotations"] = []
    document = {"name": name, "properties": properties} if name else {"properties": properties}
    return json.dumps(document, indent=2) + "\n"


def lakehouse(schema, table):
    return {"annotations": [], "type": "LakehouseTable", "schema": [],
            "typeProperties": {"schema": schema, "table": table},
            "linkedService": {"name": "lh_retail", "properties": {
                "annotations": [], "type": "Lakehouse",
                "typeProperties": {"workspaceId": ZERO, "artifactId": "00000000-0000-0000-0000-00000000001a",
                                   "rootFolder": "Tables"}}}}


def fabric_copy(name, source, sink, after=(), pol=None):
    return act(name, "Copy", after, {
        "source": {"type": "LakehouseTableSource", "datasetSettings": lakehouse(*source)},
        "sink": {"type": "LakehouseTableSink", "tableActionOption": "Overwrite", "datasetSettings": lakehouse(*sink)},
        "enableStaging": False}, pol or policy())


def outlook(name, after, subject, body):
    return act(name, "Office365Outlook", after, {"inputs": {"body": {
        "To": "data-team@example.com", "Subject": subject, "Body": body}}})


def teams(name, after, message):
    return act(name, "Teams", after, {"inputs": {"body": {"messageBody": message}}})


def notebook(name, after=(), notebook_id="nb_silver_orders", parameters=None, pol=None):
    props = {"notebookId": notebook_id, "workspaceId": ZERO}
    if parameters:
        props["parameters"] = parameters
    return act(name, "TridentNotebook", after, props, pol or policy())


def fabric_param(expression, kind="string"):
    return {"value": expr(expression), "type": kind}


def dataset(name, schema, table, kind="AzureSqlTable", linked="ls_lab_sql"):
    return {"name": name, "properties": {
        "linkedServiceName": {"referenceName": linked, "type": "LinkedServiceReference"},
        "annotations": [], "type": kind, "schema": [], "typeProperties": {"schema": schema, "table": table}}}


def ref(name, kind="DatasetReference"):
    return {"referenceName": name, "type": kind}


def sql_copy(name, query, sink_dataset, after=(), write="insert", keys=None, pol=None, pre=None):
    sink = {"type": "AzureSqlSink", "writeBehavior": write, "sqlWriterUseTableLock": False, "tableOption": "autoCreate"}
    if keys:
        sink["upsertSettings"] = {"useTempDB": True, "keys": keys}
    if pre:
        sink["preCopyScript"] = pre
    return act(name, "Copy", after, {
        "source": {"type": "AzureSqlSource", "sqlReaderQuery": query, "queryTimeout": "02:00:00", "partitionOption": "None"},
        "sink": sink, "enableStaging": False}, pol or policy(), outputs=[ref(sink_dataset)])


def script(name, after, text, linked="ls_lab_sql"):
    return act(name, "Script", after, {"scripts": [{"type": "NonQuery", "text": text}],
                                       "scriptBlockExecutionTimeout": "02:00:00"},
               policy(), linkedServiceName=ref(linked, "LinkedServiceReference"))


def web(name, after, url, method="GET", pol=None, body=None):
    props = {"url": url, "method": method}
    if body is not None:
        props["body"] = body
    return act(name, "WebActivity", after, props, pol or policy())


def set_variable(name, after, variable, value):
    return act(name, "SetVariable", after, {"variableName": variable, "value": value})


def rows_note(columns):
    return ", ".join(columns)


# 1 ------------------------------------------------------------------------------------------------
def alert_pipeline(condition):
    return pipeline([
        fabric_copy("Copy orders", ("source", "orders"), ("bronze", "orders")),
        outlook("Email data team", [("Copy orders", [condition])], "Daily orders copy failed",
                "@concat('Run ', pipeline().RunId, ' failed: ', activity('Copy orders').error.message)"),
    ], description="Copy the day's orders to bronze and warn the data team when the copy fails.")


ALERT_BASE = {"flavor": "fabric", "pipeline": "pl_orders_copy", "outcome": "activity_runs", "columns": ["name", "status"]}
FAIL_COPY = {"Copy orders": {"fail_attempts": "all", "error_message": "Lakehouse unavailable"}}
exercise(
    id="cp-alert-on-failure", title="Email the team only when the copy fails", difficulty="easy", flavor="fabric",
    topics=["dependency-conditions", "error-handling"],
    prompt=("pl_orders_copy copies the day's orders to bronze, and the Email data team activity should warn the team "
            "when the copy fails. Today the email goes out after every successful copy instead. Fix the dependency "
            "so the email is sent only when Copy orders fails."),
    sections=[("Graded", "The status of each activity when the copy fails and when it succeeds, and the run status "
                         "when the copy fails.")],
    starter=alert_pipeline("Succeeded"), solution=alert_pipeline("Failed"),
    fixtures=[
        ("copy-fails", "visible", {**ALERT_BASE, "activities": FAIL_COPY}),
        ("copy-succeeds", "hidden", dict(ALERT_BASE)),
        ("run-status-when-handled", "edge", {**ALERT_BASE, "activities": FAIL_COPY, "outcome": "run", "columns": ["status"]}),
    ],
    mutants=[alert_pipeline("Completed"), alert_pipeline("Skipped")],
    hints=["dependencyConditions lists the outcomes of the upstream activity that let this activity run.",
           "Completed means Succeeded or Failed: the email would also go out on good days."],
    explanation=("With dependencyConditions [\"Failed\"], the email runs only when the copy fails and is Skipped "
                 "otherwise. The run then ends Succeeded even though the copy failed: the run status is decided by the "
                 "leaf activities, and here the only leaf is the email, which succeeded. This is the try/catch "
                 "pattern: the failure counts as handled."),
    follow_ups=["Add a Fail activity after the email so the run is still reported as failed once the team is warned."],
)

# 2 ------------------------------------------------------------------------------------------------
def cleanup_pipeline(conditions):
    return pipeline([
        sql_copy("Load staging", "SELECT * FROM source.orders", "ds_staging_orders"),
        script("Merge into target", ["Load staging"],
               "MERGE INTO silver.orders AS t USING staging.orders AS s ON t.order_id = s.order_id "
               "WHEN MATCHED THEN UPDATE SET net_amount = s.net_amount "
               "WHEN NOT MATCHED THEN INSERT (order_id, net_amount) VALUES (s.order_id, s.net_amount);"),
        script("Drop staging", [("Merge into target", conditions)], "DROP TABLE IF EXISTS staging.orders;"),
    ], name="pl_stage_and_merge", description="Load a staging table, merge it into silver, then drop the staging table.")


CLEAN_FILES = {"datasets": {"ds_staging_orders": dataset("ds_staging_orders", "staging", "orders")}}
CLEAN_BASE = {"flavor": "adf", "pipeline": "pl_stage_and_merge", "files": CLEAN_FILES, "columns": ["name", "status"]}
exercise(
    id="cp-cleanup-always", title="Drop the staging table in every case", difficulty="easy", flavor="adf",
    topics=["dependency-conditions", "cleanup"],
    prompt=("pl_stage_and_merge loads a staging table, merges it into silver, then drops the staging table. The drop "
            "must run in every case once the merge step is over: when the merge succeeds, when it fails, and when "
            "the merge never ran because the load failed."),
    sections=[("Graded", "The status of each activity when the merge fails, when the load fails, and on a normal day.")],
    starter=cleanup_pipeline(["Succeeded"]), solution=cleanup_pipeline(["Completed", "Skipped"]),
    fixtures=[
        ("merge-fails", "visible", {**CLEAN_BASE, "activities": {"Merge into target": {"fail_attempts": "all"}}}),
        ("load-fails", "hidden", {**CLEAN_BASE, "activities": {"Load staging": {"fail_attempts": "all"}}}),
        ("normal-day", "edge", dict(CLEAN_BASE)),
    ],
    mutants=[cleanup_pipeline(["Completed"]), cleanup_pipeline(["Succeeded", "Failed"]), cleanup_pipeline(["Failed"])],
    hints=["When Load staging fails, Merge into target does not fail: it is Skipped.",
           "Several conditions on the same dependency are alternatives: any one of them is enough."],
    explanation=("Completed covers Succeeded and Failed, but not Skipped. When the load fails, the merge is Skipped, "
                 "so a drop that waits for Completed is Skipped too and the staging table stays behind. Listing "
                 "[\"Completed\", \"Skipped\"] on the same dependency means \"once the merge step is over, whatever "
                 "happened\"."),
    follow_ups=["Why would a separate dependency on Load staging (with Failed) run the drop twice in some cases, and never in others?"],
)

# 3 ------------------------------------------------------------------------------------------------
def retry_pipeline(retry, interval):
    return pipeline([
        web("Call rates API", [], "https://rates.example.invalid/v1/daily", pol=policy("0.00:10:00", retry, interval)),
        act("Load rates", "Copy", ["Call rates API"], {
            "source": {"type": "RestSource", "httpRequestTimeout": "00:01:40"},
            "sink": {"type": "AzureSqlSink", "writeBehavior": "insert"}, "enableStaging": False}, policy()),
    ], name="pl_exchange_rates", description="Fetch today's exchange rates from a partner API, then load them.")


RETRY_BASE = {"flavor": "adf", "pipeline": "pl_exchange_rates", "columns": ["name", "status", "attempts", "end_s"]}
exercise(
    id="cp-retry-flaky-api", title="Retry a flaky API call", difficulty="easy", flavor="adf",
    topics=["retry-policy", "activity-policy"],
    prompt=("Call rates API sometimes fails for a minute or two. Give it 2 retries, 60 seconds apart, so a short "
            "outage does not fail the pipeline. Load rates runs after it."),
    sections=[("Graded", "Status, attempts and end time (seconds after the run starts) of each activity when the "
                         "API fails twice then answers, when it never recovers, and on a normal day. In these checks "
                         "a call takes 10 seconds and the copy 30 seconds.")],
    starter=retry_pipeline(0, 30), solution=retry_pipeline(2, 60),
    fixtures=[
        ("fails-twice", "visible", {**RETRY_BASE, "activities": {"Call rates API": {"fail_attempts": [1, 2], "duration_seconds": 10}}}),
        ("never-recovers", "hidden", {**RETRY_BASE, "activities": {"Call rates API": {"fail_attempts": "all", "duration_seconds": 10}}}),
        ("normal-day", "edge", {**RETRY_BASE, "activities": {"Call rates API": {"duration_seconds": 10}}}),
    ],
    mutants=[retry_pipeline(3, 60), retry_pipeline(2, 30), retry_pipeline(1, 60)],
    hints=["policy.retry counts retries, not attempts: 2 retries means up to 3 attempts.",
           "policy.retryIntervalInSeconds is the pause between attempts (30 to 86400 seconds)."],
    explanation=("With retry 2 and retryIntervalInSeconds 60, the third attempt starts at 10 + 60 + 10 + 60 = 140 s "
                 "and ends at 150 s. When the API never recovers, the activity fails after its third attempt and "
                 "Load rates is Skipped."),
    follow_ups=["Why not set retry to 10 just in case? Think about a partner API that is down for the whole morning."],
)

# 4 ------------------------------------------------------------------------------------------------
def timeout_pipeline(timeout, retry=0):
    return pipeline([
        notebook("Silver orders", pol=policy(timeout, retry)),
        act("Gold revenue", "SqlServerStoredProcedure", ["Silver orders"],
            {"storedProcedureName": "[warehouse].[usp_load_gold_revenue]"}, policy("0.00:30:00")),
        teams("Alert on-call", [("Silver orders", ["Failed"])],
              "@concat('Silver orders failed: ', activity('Silver orders').error.message)"),
    ], description="Clean orders in a notebook, build gold with a stored procedure, alert on notebook failure.")


TIMEOUT_BASE = {"flavor": "fabric", "pipeline": "pl_morning_load", "columns": ["name", "status", "end_s"]}
exercise(
    id="cp-timeout-stuck-notebook", title="Stop waiting for a stuck notebook", difficulty="medium", flavor="fabric",
    topics=["activity-policy", "timeout"],
    prompt=("The Silver orders notebook normally takes 20 minutes, but sometimes hangs for hours and blocks the "
            "morning load: the default activity timeout is 12 hours. Make it give up after 1 hour, without retrying, "
            "so the Teams alert (it already runs on failure) fires early."),
    sections=[("Graded", "Status and end time of each activity when the notebook hangs for 5 hours, on a normal "
                         "20-minute day, and on a slow day that still finishes within the hour.")],
    starter=timeout_pipeline("0.12:00:00"), solution=timeout_pipeline("0.01:00:00"),
    fixtures=[
        ("notebook-hangs", "visible", {**TIMEOUT_BASE, "activities": {"Silver orders": {"duration_seconds": 18000}}}),
        ("normal-day", "hidden", {**TIMEOUT_BASE, "activities": {"Silver orders": {"duration_seconds": 1200}}}),
        ("slow-but-in-time", "edge", {**TIMEOUT_BASE, "activities": {"Silver orders": {"duration_seconds": 3500}}}),
    ],
    mutants=[timeout_pipeline("0.00:30:00"), timeout_pipeline("0.02:00:00"), timeout_pipeline("0.01:00:00", retry=1)],
    hints=["policy.timeout is a timespan: d.hh:mm:ss, so 12 hours is 0.12:00:00.",
           "A timeout counts as a failure: the activities that run on Failed start right after it."],
    explanation=("With timeout 0.01:00:00 the notebook fails at 3600 s instead of running for 5 hours; Gold revenue is "
                 "Skipped and Alert on-call runs at once. A slow but healthy run of 58 minutes is not cut."),
    follow_ups=["What would a retry add here, and what would it cost on a day the notebook really hangs?"],
)

# 5 ------------------------------------------------------------------------------------------------
def foreach_pipeline(items, sequential, batch=None):
    loop = {"items": expr(items), "isSequential": sequential,
            "activities": [act("Copy table", "Copy", [], {
                "source": {"type": "AzureSqlSource", "sqlReaderQuery": expr("@concat('SELECT * FROM source.', item())")},
                "sink": {"type": "ParquetSink"}, "enableStaging": False}, policy(),
                outputs=[{"referenceName": "ds_bronze_table", "type": "DatasetReference",
                          "parameters": {"table": expr("@item()")}}])]}
    if batch is not None:
        loop["batchCount"] = batch
    return pipeline([act("Copy each table", "ForEach", [], loop)],
                    parameters={"tables": {"type": "array", "defaultValue": ["customers", "orders", "products", "stores"]}},
                    name="pl_copy_tables", description="Copy every table named in the tables parameter to bronze.")


FOREACH_BASE = {"flavor": "adf", "pipeline": "pl_copy_tables", "outcome": "run", "columns": ["status", "duration_s"]}
HARD_CODED = "@createArray('customers', 'orders', 'products', 'stores')"
exercise(
    id="cp-foreach-batch", title="Copy tables two at a time", difficulty="medium", flavor="adf",
    topics=["foreach", "parallelism", "parameters"],
    prompt=("pl_copy_tables copies every table in a hard-coded list, one after the other. Read the list from the "
            "tables pipeline parameter instead, and copy the tables in parallel, at most 2 at the same time: the "
            "source database accepts 2 connections."),
    sections=[("Graded", "Run status and duration (each copy takes 30 seconds) with the default tables, with five "
                         "tables passed as a parameter, and when one table fails.")],
    starter=foreach_pipeline(HARD_CODED, True), solution=foreach_pipeline("@pipeline().parameters.tables", False, 2),
    fixtures=[
        ("default-tables", "visible", dict(FOREACH_BASE)),
        ("five-tables", "hidden", {**FOREACH_BASE, "parameters": {"tables": ["customers", "orders", "products", "stores", "returns"]}}),
        ("one-table-fails", "edge", {**FOREACH_BASE, "activities": {"Copy table": {"fail_on_items": ["orders"]}}}),
    ],
    mutants=[foreach_pipeline("@pipeline().parameters.tables", False, 4),
             foreach_pipeline("@pipeline().parameters.tables", True, 2),
             foreach_pipeline(HARD_CODED, False, 2)],
    hints=["ForEach runs its iterations in parallel unless isSequential is true; batchCount caps how many run at once.",
           "item() is the current element; the list itself comes from items."],
    explanation=("With isSequential false and batchCount 2, four 30-second copies take 60 seconds and five take 90. "
                 "When one iteration fails, the others still run, and the ForEach, and so the run, ends Failed."),
    follow_ups=["What changes if one table takes 10 minutes and the others 30 seconds?"],
)

# 6 ------------------------------------------------------------------------------------------------
def if_pipeline(expression):
    return pipeline([
        act("Count new orders", "Lookup", [], {
            "source": {"type": "DataWarehouseSource",
                       "sqlReaderQuery": "SELECT COUNT(*) AS new_orders FROM bronze.orders_increment",
                       "partitionOption": "None", "queryTimeout": "02:00:00"},
            "firstRowOnly": True}, policy("0.00:10:00")),
        act("Any new orders", "IfCondition", ["Count new orders"], {
            "expression": expr(expression),
            "ifTrueActivities": [act("Refresh gold", "SqlServerStoredProcedure", [],
                                     {"storedProcedureName": "[gold].[usp_refresh_daily_sales]"}, policy("0.00:30:00"))],
            "ifFalseActivities": []}),
    ], description="Refresh gold only when new orders arrived.")


IF_BASE = {"flavor": "fabric", "pipeline": "pl_refresh_gold", "columns": ["name", "status"]}
exercise(
    id="cp-if-new-rows", title="Refresh gold only when new rows arrived", difficulty="medium", flavor="fabric",
    topics=["if-condition", "lookup", "expressions"],
    prompt=("Count new orders returns one row with a new_orders column. Make Any new orders run Refresh gold only when "
            "at least one new order arrived; when nothing is new, the pipeline just skips the refresh."),
    sections=[("Graded", "The status of each activity when the Lookup counts 3 new orders, none, and exactly one. "
                         "In the checks the Lookup output comes from the scenario.")],
    starter=if_pipeline("@activity('Count new orders').output.firstRow.new_orders"),
    solution=if_pipeline("@greater(activity('Count new orders').output.firstRow.new_orders, 0)"),
    fixtures=[
        ("three-new", "visible", {**IF_BASE, "activities": {"Count new orders": {"output": {"firstRow": {"new_orders": 3}}}}}),
        ("none-new", "hidden", {**IF_BASE, "activities": {"Count new orders": {"output": {"firstRow": {"new_orders": 0}}}}}),
        ("exactly-one", "edge", {**IF_BASE, "activities": {"Count new orders": {"output": {"firstRow": {"new_orders": 1}}}}}),
    ],
    mutants=[if_pipeline("@greaterOrEquals(activity('Count new orders').output.firstRow.new_orders, 0)"),
             if_pipeline("@greater(activity('Count new orders').output.firstRow.new_orders, 1)")],
    hints=["An If Condition needs a Boolean: a number is not true or false.",
           "A Lookup with firstRowOnly exposes its row as output.firstRow."],
    explanation=("@greater(activity('Count new orders').output.firstRow.new_orders, 0) is true from one new order. "
                 "Activities of the branch that does not run do not appear in the run at all, and the If Condition "
                 "itself succeeds."),
    follow_ups=["How would you also refresh gold on the first day of the month, whatever the count?"],
)

# 7 ------------------------------------------------------------------------------------------------
def exit_pipeline(value, check="@equals(variables('silver_rows'), '0')"):
    return pipeline([
        notebook("Silver orders", parameters={"run_date": fabric_param("@pipeline().parameters.run_date")}),
        set_variable("Keep silver rows", ["Silver orders"], "silver_rows", value),
        act("No silver rows", "IfCondition", ["Keep silver rows"], {
            "expression": expr(check),
            "ifTrueActivities": [act("Stop empty load", "Fail", [], {
                "message": "The silver notebook wrote no rows", "errorCode": "SILVER_EMPTY"})],
            "ifFalseActivities": []}),
    ], parameters={"run_date": {"type": "string", "defaultValue": "2026-03-05"}},
        variables={"silver_rows": {"type": "String"}},
        description="Run the silver notebook, keep its row count, and stop when it wrote nothing.")


def nb_out(value):
    return {"Silver orders": {"output": {"result": {"exitValue": value}}}}


EXIT_BASE = {"flavor": "fabric", "pipeline": "pl_silver_check"}
exercise(
    id="cp-notebook-exit-value", title="Use the notebook's exit value", difficulty="medium", flavor="fabric",
    topics=["notebook-activity", "variables", "expressions"],
    prompt=("The Silver orders notebook ends with notebookutils.notebook.exit(str(row_count)). Keep that value in the "
            "silver_rows variable (String) right after the notebook. The If Condition after it must stop the run "
            "with the Fail activity when the notebook wrote no rows. The Set variable was copied from an Azure Data "
            "Factory pipeline; fix it for Fabric."),
    sections=[("Graded", "The variables after a run where the notebook returns \"42\", and the run status when it "
                         "returns \"0\" and \"7\". The notebook's exit value comes from the scenario.")],
    starter=exit_pipeline("@activity('Silver orders').output.runOutput"),
    solution=exit_pipeline("@activity('Silver orders').output.result.exitValue"),
    fixtures=[
        ("rows-written", "visible", {**EXIT_BASE, "activities": nb_out("42"), "outcome": "variables"}),
        ("no-rows", "hidden", {**EXIT_BASE, "activities": nb_out("0"), "outcome": "run", "columns": ["status"]}),
        ("some-rows", "edge", {**EXIT_BASE, "activities": nb_out("7"), "outcome": "run", "columns": ["status"]}),
    ],
    mutants=[exit_pipeline("@activity('Silver orders').output.result"),
             exit_pipeline("@activity('Silver orders').output.result.exitValue", "@equals(variables('silver_rows'), 0)")],
    hints=["A Fabric Notebook activity returns the exit value as output.result.exitValue; runOutput is the Azure "
           "Databricks activity's field.",
           "The exit value is text: \"0\" is not the number 0 for equals()."],
    explanation=("In Fabric the value passed to notebookutils.notebook.exit reaches the pipeline as "
                 "activity('Silver orders').output.result.exitValue, always as text. equals(variables('silver_rows'), "
                 "'0') compares text with text; comparing it with the number 0 is always false, so the empty-load "
                 "guard would never fire."),
    follow_ups=["Return JSON from the notebook and read one of its fields with json(...) in the pipeline."],
)

# 8 ------------------------------------------------------------------------------------------------
def folder_pipeline(value):
    return pipeline([
        set_variable("Set target folder", [], "target_folder", value),
        act("Copy orders to raw", "Copy", ["Set target folder"], {
            "source": {"type": "AzureSqlSource", "sqlReaderQuery": "SELECT * FROM source.orders"},
            "sink": {"type": "ParquetSink"}, "enableStaging": False}, policy(),
            outputs=[{"referenceName": "ds_raw_folder", "type": "DatasetReference",
                      "parameters": {"folder": expr("@variables('target_folder')")}}]),
    ], variables={"target_folder": {"type": "String"}}, name="pl_orders_to_raw",
        description="Copy the orders to a date-partitioned folder of the raw zone.")


FOLDER_BASE = {"flavor": "adf", "pipeline": "pl_orders_to_raw", "outcome": "variables"}
exercise(
    id="cp-date-folder-path", title="Build a date-partitioned folder path", difficulty="medium", flavor="adf",
    topics=["expressions", "dates", "variables"],
    prompt=("Set the target_folder variable to the folder of the run's day, for example raw/orders/2026/03/05 for a "
            "run triggered on 5 March 2026. Use the trigger time of the run (UTC)."),
    sections=[("Graded", "The variables for runs triggered at different times, including a month change and a year "
                         "change.")],
    starter=folder_pipeline("raw/orders/"),
    solution=folder_pipeline("@concat('raw/orders/', formatDateTime(pipeline().TriggerTime, 'yyyy/MM/dd'))"),
    fixtures=[
        ("march-fifth", "visible", {**FOLDER_BASE, "now": "2026-03-05T12:00:00Z"}),
        ("late-evening", "hidden", {**FOLDER_BASE, "now": "2026-11-23T23:59:00Z", "trigger_type": "ScheduleTrigger"}),
        ("new-year", "edge", {**FOLDER_BASE, "now": "2027-01-01T00:30:00Z", "trigger_type": "ScheduleTrigger"}),
    ],
    mutants=[folder_pipeline("@concat('raw/orders/', formatDateTime(pipeline().TriggerTime, 'yyyy/mm/dd'))"),
             folder_pipeline("@concat('raw/orders/', formatDateTime(pipeline().TriggerTime, 'yyyy/M/d'))"),
             folder_pipeline("@concat('raw/orders/', formatDateTime(pipeline().TriggerTime, 'YYYY/MM/DD'))")],
    hints=["formatDateTime uses .NET format strings: MM is the month, mm the minutes.",
           "String interpolation also works: raw/orders/@{formatDateTime(...)}."],
    explanation=("formatDateTime(pipeline().TriggerTime, 'yyyy/MM/dd') gives 2026/03/05. In .NET formats mm means "
                 "minutes, M drops the leading zero, and YYYY or DD are not format letters at all: they are copied "
                 "as they are."),
    follow_ups=["Use a pipeline parameter to reload an older day, and fall back to the trigger time when it is empty."],
)

# 9 ------------------------------------------------------------------------------------------------
def until_pipeline(inner_wait):
    inner = [web("Check export", [], "https://partner.example.invalid/exports/daily/status", pol=policy("0.00:05:00")),
             set_variable("Keep status", ["Check export"], "export_status", "@activity('Check export').output.status")]
    inner += inner_wait
    return pipeline([
        web("Request export", [], "https://partner.example.invalid/exports/daily", method="POST", body="{}",
            pol=policy("0.00:05:00")),
        act("Wait for export", "Until", ["Request export"], {
            "expression": expr("@equals(variables('export_status'), 'READY')"),
            "timeout": "0.02:00:00", "activities": inner}),
        act("Load export", "Copy", ["Wait for export"], {
            "source": {"type": "RestSource"}, "sink": {"type": "SqlPoolSink"}, "enableStaging": False}, policy()),
    ], variables={"export_status": {"type": "String", "defaultValue": "PENDING"}}, name="pl_partner_export",
        description="Ask a partner for an export, poll until it is ready, then load it.")


WAIT = act("Wait a minute", "Wait", ["Keep status"], {"waitTimeInSeconds": 60})
WAIT_IF_NOT_READY = act("Not ready yet", "IfCondition", ["Keep status"], {
    "expression": expr("@not(equals(variables('export_status'), 'READY'))"),
    "ifTrueActivities": [act("Wait a minute", "Wait", [], {"waitTimeInSeconds": 60})],
    "ifFalseActivities": []})
WAIT_IF_READY = act("Not ready yet", "IfCondition", ["Keep status"], {
    "expression": expr("@not(equals(variables('export_status'), 'READY'))"),
    "ifTrueActivities": [], "ifFalseActivities": [act("Wait a minute", "Wait", [], {"waitTimeInSeconds": 60})]})
UNTIL_BASE = {"flavor": "synapse", "pipeline": "pl_partner_export", "only": ["Check export", "Wait a minute"],
              "columns": ["name", "status", "iteration"]}


def statuses(*values):
    return {"Check export": {"outputs": [{"status": value} for value in values]}}


exercise(
    id="cp-until-export-ready", title="Poll until the export is ready", difficulty="hard", flavor="synapse",
    topics=["until", "if-condition", "variables"],
    prompt=("Check export answers {\"status\": \"RUNNING\"} until the partner's export is ready, then "
            "{\"status\": \"READY\"}. The Until loop checks, keeps the status in a variable and waits a minute. Change "
            "it so it waits only when the export is not ready yet: after the READY answer the pipeline must go on at "
            "once."),
    sections=[("Graded", "Every Check export and Wait a minute run, with its loop iteration, when the export is ready "
                         "at the third check, at the fifth, and at once. Check export's answers come from the "
                         "scenario."),
              ("Loop rules", "Until evaluates its expression after each iteration. A Set variable cannot reference "
                             "the variable it sets, and ForEach or Until cannot be nested in ForEach or Until, but an "
                             "If Condition can run inside an Until.")],
    starter=until_pipeline([WAIT]), solution=until_pipeline([WAIT_IF_NOT_READY]),
    fixtures=[
        ("ready-on-third-check", "visible", {**UNTIL_BASE, "activities": statuses("RUNNING", "RUNNING", "READY")}),
        ("ready-on-fifth-check", "hidden", {**UNTIL_BASE, "activities": statuses("RUNNING", "RUNNING", "RUNNING", "RUNNING", "READY")}),
        ("ready-at-once", "edge", {**UNTIL_BASE, "activities": statuses("READY")}),
    ],
    mutants=[until_pipeline([WAIT_IF_READY]),
             until_pipeline([act("Wait a minute", "Wait", ["Keep status"], {"waitTimeInSeconds": 60}),
                             act("Not ready yet", "IfCondition", ["Keep status"], {
                                 "expression": expr("@not(equals(variables('export_status'), 'READY'))"),
                                 "ifTrueActivities": [], "ifFalseActivities": []})])],
    hints=["Put the Wait inside an If Condition that tests the status you just kept.",
           "Activities of the branch that does not run do not appear in the run."],
    explanation=("Checking, keeping the status, then waiting only when it is not READY makes the loop end right after "
                 "the READY answer: three checks and two waits when the export is ready at the third check. The Until "
                 "timeout (here 2 hours) is the safety net if the partner never finishes."),
    follow_ups=["Count the checks in a second variable and fail the pipeline after 10 checks."],
)

# 10 -----------------------------------------------------------------------------------------------
def proceed_pipeline(log_condition, done_conditions):
    activities = [
        fabric_copy("Copy orders", ("source", "orders"), ("bronze", "orders")),
        notebook("Transform", ["Copy orders"]),
        act("Log failure", "Script", [("Copy orders", [log_condition])], {
            "scripts": [{"type": "NonQuery", "text": expr(
                "@concat('INSERT INTO warehouse.load_errors VALUES (''', pipeline().RunId, ''', ''Copy orders'')')")}]},
            policy()),
    ]
    if done_conditions:
        activities.append(act("Done", "Wait", [("Transform", done_conditions)], {"waitTimeInSeconds": 1}))
    return pipeline(activities, description="Copy and transform the orders; log a failed copy without failing the run.")


PROCEED_BASE = {"flavor": "fabric", "pipeline": "pl_orders_guarded"}
COPY_FAILS = {"Copy orders": {"fail_attempts": "all"}}
exercise(
    id="cp-try-catch-proceed", title="Handle a failed copy without failing the run", difficulty="hard", flavor="fabric",
    topics=["run-status", "dependency-conditions", "error-handling"],
    prompt=("When Copy orders fails, Log failure records it, and the run must end Succeeded so the pipelines scheduled "
            "after it are not blocked. Transform must still run only after a successful copy, and a real failure of "
            "Transform must still fail the run. Today a failed copy fails the whole run. Add what is needed."),
    sections=[("Graded", "The run status when the copy fails and when Transform fails, and the status of Copy orders, "
                         "Log failure and Transform when the copy fails and on a normal day."),
              ("Run status", "A run is evaluated from its leaf activities (those nothing depends on). A skipped leaf is "
                             "replaced by its parents. The run succeeds only if every evaluated activity succeeded.")],
    starter=proceed_pipeline("Failed", None), solution=proceed_pipeline("Failed", ["Succeeded", "Skipped"]),
    fixtures=[
        ("copy-fails", "visible", {**PROCEED_BASE, "activities": COPY_FAILS, "outcome": "run", "columns": ["status"]}),
        ("transform-fails", "hidden", {**PROCEED_BASE, "activities": {"Transform": {"fail_attempts": "all"}},
                                       "outcome": "run", "columns": ["status"]}),
        ("normal-day-steps", "hidden", {**PROCEED_BASE, "only": ["Copy orders", "Log failure", "Transform"],
                                        "columns": ["name", "status"]}),
        ("copy-fails-steps", "edge", {**PROCEED_BASE, "activities": COPY_FAILS,
                                      "only": ["Copy orders", "Log failure", "Transform"], "columns": ["name", "status"]}),
    ],
    mutants=[proceed_pipeline("Failed", ["Completed"]), proceed_pipeline("Failed", ["Succeeded", "Skipped", "Failed"]),
             proceed_pipeline("Completed", ["Succeeded", "Skipped"])],
    hints=["When the copy fails, Transform is a skipped leaf: it is replaced by Copy orders, which failed.",
           "Give Transform a successor that runs when Transform succeeded or was skipped, but not when it failed."],
    explanation=("Adding an activity after Transform with the conditions Succeeded or Skipped changes the leaves. When "
                 "the copy fails, Transform is Skipped, the new activity runs, and the evaluated leaves (it and Log "
                 "failure) both succeeded: the run is Succeeded. When Transform fails, the new activity is Skipped, so "
                 "Transform is evaluated and the run fails."),
    follow_ups=["Why does moving Log failure to Completed not help, and what does it change on a normal day?"],
)

# 11 -----------------------------------------------------------------------------------------------
PORT_PARAMS = {"run_date": {"type": "string", "defaultValue": "2026-03-05"}}
PORT_VARS = {"silver_rows": {"type": "String"}}
PORT_STARTER = pipeline([
    act("Silver orders", "DatabricksNotebook", [], {
        "notebookPath": "/Shared/nb_silver_orders_dbx",
        "baseParameters": {"run_date": expr("@pipeline().parameters.run_date")}}, policy(),
        linkedServiceName=ref("ls_lab_databricks", "LinkedServiceReference")),
    set_variable("Keep silver rows", ["Silver orders"], "silver_rows", "@activity('Silver orders').output.runOutput"),
    web("Notify team", ["Keep silver rows"], "https://hooks.example.invalid/retail", method="POST",
        body=expr("@concat('Silver rows: ', variables('silver_rows'))")),
], parameters=PORT_PARAMS, variables=PORT_VARS, name="pl_daily_orders",
    description="Ported from Azure Data Factory: clean orders in a notebook, keep its row count, notify the team.")


def port_pipeline(notebook_parameters, value, notify="teams"):
    last = (teams("Notify team", ["Keep silver rows"], "@concat('Silver rows: ', variables('silver_rows'))")
            if notify == "teams" else
            web("Notify team", ["Keep silver rows"], "https://hooks.example.invalid/retail", method="POST",
                body=expr("@concat('Silver rows: ', variables('silver_rows'))")))
    return pipeline([
        notebook("Silver orders", parameters=notebook_parameters),
        set_variable("Keep silver rows", ["Silver orders"], "silver_rows", value),
        last,
    ], parameters=PORT_PARAMS, variables=PORT_VARS, description="Clean orders in a notebook, keep its row count, notify the team.")


PORT_OK_PARAMS = {"run_date": fabric_param("@pipeline().parameters.run_date")}
PORT_BASE = {"flavor": "fabric", "pipeline": "pl_daily_orders",
             "activities": {"Silver orders": {"output": {"result": {"exitValue": "12"}}}}}
exercise(
    id="cp-port-adf-to-fabric", title="Port an Azure Data Factory pipeline to Fabric", difficulty="hard", flavor="fabric",
    topics=["fabric-vs-adf", "notebook-activity", "migration"],
    prompt=("The starter is pl_daily_orders from Azure Data Factory. Port it to Fabric Data Factory: the Databricks "
            "notebook becomes the Fabric notebook nb_silver_orders (Notebook activity, parameters in Fabric's "
            "format), the silver_rows variable must receive the notebook's exit value the Fabric way, and the webhook "
            "becomes a Teams activity. Keep the activity names."),
    sections=[("Graded", "The type and status of each activity, the variables after the run, and the parameters the "
                         "Notebook activity passes (for a run with another run_date). The notebook's exit value comes "
                         "from the scenario."),
              ("Fabric vs Azure Data Factory", "Notebook: TridentNotebook with notebookId and parameters "
               "{name: {value, type}}, result in output.result.exitValue. Azure Databricks: DatabricksNotebook with "
               "notebookPath and baseParameters {name: value}, result in output.runOutput. Notifications: Teams and "
               "Office365Outlook activities in Fabric, a Web activity to a webhook or Logic App in Azure Data Factory.")],
    starter=PORT_STARTER,
    solution=port_pipeline(PORT_OK_PARAMS, "@activity('Silver orders').output.result.exitValue"),
    fixtures=[
        ("activity-types", "visible", {**PORT_BASE, "columns": ["name", "type", "status"]}),
        ("exit-value", "hidden", {**PORT_BASE, "outcome": "variables"}),
        ("notebook-parameters", "edge", {**PORT_BASE, "parameters": {"run_date": "2026-03-07"}, "outcome": "inputs",
                                         "only": ["Silver orders"], "fields": ["parameters.run_date.value"],
                                         "columns": ["name", "field", "value"]}),
    ],
    mutants=[port_pipeline(PORT_OK_PARAMS, "@activity('Silver orders').output.runOutput"),
             port_pipeline({"run_date": "@pipeline().parameters.run_date"}, "@activity('Silver orders').output.result.exitValue"),
             port_pipeline(PORT_OK_PARAMS, "@activity('Silver orders').output.result.exitValue", notify="web")],
    hints=["Fabric's Notebook activity type is TridentNotebook; its parameters are objects with a value and a type.",
           "The exit value moves from output.runOutput to output.result.exitValue."],
    explanation=("The orchestration model is the same in both products; what changes is the activities and their "
                 "settings. Fabric runs its own notebooks with TridentNotebook (notebookId, parameters as "
                 "{\"value\": ..., \"type\": \"string\"}) and returns the exit value in output.result.exitValue; "
                 "Teams and Outlook activities replace webhook calls."),
    follow_ups=["Port the Copy activity too: Azure Data Factory datasets become Fabric connections and inline dataset settings."],
)

# 12 -----------------------------------------------------------------------------------------------
def watermark_pipeline(query, update=True):
    activities = [
        act("Get watermark", "Lookup", [], {
            "source": {"type": "AzureSqlSource",
                       "sqlReaderQuery": "SELECT watermark FROM warehouse.watermarks WHERE table_name = 'orders'"},
            "dataset": ref("ds_watermarks"), "firstRowOnly": True}, policy("0.00:10:00")),
        sql_copy("Copy new orders", query, "ds_bronze_orders", ["Get watermark"]),
    ]
    if update:
        activities.append(script("Update watermark", ["Copy new orders"],
                                 "UPDATE warehouse.watermarks SET watermark = (SELECT MAX(updated_at) FROM bronze.orders) "
                                 "WHERE table_name = 'orders'"))
    return pipeline(activities, name="pl_orders_incremental",
                    description="Copy only the orders changed since the last load, then move the watermark.")


WM_QUERY = "SELECT * FROM source.orders WHERE updated_at {op} '@{{activity('Get watermark').output.firstRow.watermark}}'"
WM_FILES = {"datasets": {"ds_bronze_orders": dataset("ds_bronze_orders", "bronze", "orders"),
                         "ds_watermarks": dataset("ds_watermarks", "warehouse", "watermarks")}}


def orders(*rows):
    return [{"order_id": o, "amount": a, "updated_at": u} for o, a, u in rows]


OLD = [("O1", 10.0, "2026-03-04 09:00:00"), ("O2", 20.0, "2026-03-04 18:00:00")]
NEW = [("O3", 30.0, "2026-03-05 08:00:00"), ("O4", 40.0, "2026-03-05 10:00:00"), ("O5", 50.0, "2026-03-05 11:30:00")]


def wm_scenario(source, bronze, watermark):
    return {"flavor": "adf", "pipeline": "pl_orders_incremental", "data_plane": "local", "files": WM_FILES, "runs": 2,
            "tables": [{"name": "source.orders", "rows": orders(*source)},
                       {"name": "bronze.orders", "rows": orders(*bronze),
                        "columns": ["order_id", "amount", "updated_at"],
                        "types": {"order_id": "VARCHAR", "amount": "DOUBLE", "updated_at": "VARCHAR"}},
                       {"name": "warehouse.watermarks", "rows": [{"table_name": "orders", "watermark": watermark}]}],
            "outcome": "table", "table": "bronze.orders", "columns": ["order_id", "amount"]}


exercise(
    id="cp-incremental-watermark", title="Load only new rows with a watermark", difficulty="hard", flavor="adf",
    local=True, topics=["incremental-load", "lookup", "expressions"],
    prompt=("pl_orders_incremental must copy only the orders changed since the last load. Get watermark reads the last "
            "loaded updated_at from warehouse.watermarks. Make Copy new orders copy only the newer rows, and add a "
            "Script activity after the copy that moves the watermark to the newest updated_at now in bronze.orders. "
            "The pipeline runs twice in a row in every check: the second run must not duplicate anything."),
    sections=[("Tables", "source.orders and bronze.orders: order_id VARCHAR, amount DOUBLE, updated_at VARCHAR "
                         "('YYYY-MM-DD HH:MM:SS'). warehouse.watermarks: table_name VARCHAR, watermark VARCHAR. The copy "
                         "appends to bronze.orders (writeBehavior insert)."),
              ("Graded", "The rows of bronze.orders (order_id, amount) after two runs: with new orders, with an order "
                         "whose updated_at equals the watermark, and with nothing new.")],
    starter=watermark_pipeline("SELECT * FROM source.orders", update=False),
    solution=watermark_pipeline(expr(WM_QUERY.format(op=">"))),
    fixtures=[
        ("two-runs", "visible", wm_scenario(OLD + NEW, OLD, "2026-03-04 18:00:00")),
        ("boundary-row", "hidden", wm_scenario(OLD + [("O6", 60.0, "2026-03-06 07:00:00")], OLD, "2026-03-04 18:00:00")),
        ("nothing-new", "edge", wm_scenario(OLD, OLD, "2026-03-04 18:00:00")),
    ],
    mutants=[watermark_pipeline(expr(WM_QUERY.format(op=">=")), update=True),
             watermark_pipeline(expr(WM_QUERY.format(op=">")), update=False)],
    hints=["Put the watermark into the query with string interpolation: '@{activity('Get watermark').output.firstRow.watermark}'.",
           "Strictly newer (>) rows only: the row at the watermark was loaded last time."],
    explanation=("The copy reads only rows newer than the stored watermark, and the Script moves the watermark to the "
                 "newest loaded row. The second run then finds nothing new. With >= the row at the watermark is "
                 "copied again on every run; without the update the new rows come back on the next run."),
    follow_ups=["What happens if two orders share the same updated_at and only one of them was there during the last load?"],
)

# 13 -----------------------------------------------------------------------------------------------
def upsert_pipeline(write, keys=None, pre=None):
    return pipeline([sql_copy("Upsert customers", "SELECT customer_id, name, city FROM source.customers",
                              "ds_bronze_customers", write=write, keys=keys, pre=pre)],
                    name="pl_customers_upsert", description="Keep bronze.customers in line with the source, rerun-safe.")


UP_FILES = {"datasets": {"ds_bronze_customers": dataset("ds_bronze_customers", "bronze", "customers")}}
CUSTOMERS = [{"customer_id": "C1", "name": "Ada", "city": "Paris"},
             {"customer_id": "C2", "name": "Ben", "city": "Lyon"},
             {"customer_id": "C3", "name": "Chloe", "city": "Paris"}]


def up_scenario(bronze):
    return {"flavor": "adf", "pipeline": "pl_customers_upsert", "data_plane": "local", "files": UP_FILES, "runs": 2,
            "tables": [{"name": "source.customers", "rows": CUSTOMERS},
                       {"name": "bronze.customers", "rows": bronze, "columns": ["customer_id", "name", "city"]}],
            "outcome": "table", "table": "bronze.customers"}


exercise(
    id="cp-upsert-idempotent", title="Make the customer load safe to rerun", difficulty="medium", flavor="adf",
    local=True, topics=["copy-activity", "upsert", "idempotence"],
    prompt=("Upsert customers inserts every source row into bronze.customers, so a rerun duplicates customers. Make the "
            "copy update existing customers and insert new ones, matching on customer_id. Customers already in bronze "
            "but no longer in the source must be kept."),
    sections=[("Tables", "source.customers and bronze.customers: customer_id, name, city (text)."),
              ("Graded", "The rows of bronze.customers after two runs: starting empty, with a customer whose city "
                         "changed, and with an old customer that is no longer in the source.")],
    starter=upsert_pipeline("insert"), solution=upsert_pipeline("upsert", ["customer_id"]),
    fixtures=[
        ("rerun-no-duplicates", "visible", up_scenario([])),
        ("city-changed", "hidden", up_scenario([{"customer_id": "C2", "name": "Ben", "city": "Nice"}])),
        ("keeps-old-customers", "edge", up_scenario([{"customer_id": "C9", "name": "Zoe", "city": "Lille"}])),
    ],
    mutants=[upsert_pipeline("upsert", ["city"]), upsert_pipeline("insert", pre="DELETE FROM bronze.customers")],
    hints=["An Azure SQL sink has writeBehavior insert or upsert; upsertSettings.keys names the matching columns.",
           "Deleting the table before inserting also avoids duplicates, but it loses the customers the source no longer has."],
    explanation=("writeBehavior upsert with upsertSettings.keys [\"customer_id\"] updates a customer that is already "
                 "there and inserts the others, so running the pipeline twice gives the same table. Unlike a full "
                 "overwrite, it keeps target rows that the source no longer sends."),
    follow_ups=["How would you also mark customers that disappeared from the source as inactive?"],
)

# 14 -----------------------------------------------------------------------------------------------
PROC = code("""
-- Rebuilds one day of gold.daily_revenue: rerunning a day replaces it.
CREATE PROCEDURE warehouse.usp_load_daily_revenue
    @load_date VARCHAR(10),
    @min_amount DECIMAL(10, 2)
AS
BEGIN
    DELETE FROM gold.daily_revenue WHERE load_date = @load_date;
    INSERT INTO gold.daily_revenue
    SELECT @load_date AS load_date, COUNT(*) AS orders, SUM(net_amount) AS revenue
    FROM silver.orders
    WHERE order_date = @load_date AND net_amount >= @min_amount;
END
""")


def proc_pipeline(parameters):
    return pipeline([act("Load daily revenue", "SqlPoolStoredProcedure", [], {
        "storedProcedureName": "[warehouse].[usp_load_daily_revenue]", "storedProcedureParameters": parameters},
        policy("0.00:30:00"), sqlPool=ref("sqlpool01", "SqlPoolReference"))],
        parameters={"run_date": {"type": "string", "defaultValue": "2026-03-05"},
                    "min_amount": {"type": "float", "defaultValue": 0}},
        name="pl_daily_revenue", description="Rebuild one day of gold revenue in the dedicated SQL pool.")


PROC_OK = {"load_date": {"value": expr("@pipeline().parameters.run_date"), "type": "String"},
           "min_amount": {"value": expr("@pipeline().parameters.min_amount"), "type": "Decimal"}}
SILVER = [{"order_id": o, "order_date": d, "net_amount": a} for o, d, a in [
    ("O1", "2026-03-05", 25.0), ("O2", "2026-03-05", 150.0), ("O3", "2026-03-05", 80.0), ("O4", "2026-03-06", 120.0),
    ("O5", "2026-03-06", 60.0), ("O6", "2026-03-06", 300.0), ("O7", "2026-03-04", 40.0)]]
GOLD_TYPES = {"load_date": "VARCHAR", "orders": "BIGINT", "revenue": "DOUBLE"}


def proc_scenario(parameters, gold):
    return {"flavor": "synapse", "pipeline": "pl_daily_revenue", "data_plane": "local", "parameters": parameters,
            "files": {"procedures": {"warehouse.usp_load_daily_revenue": PROC}},
            "tables": [{"name": "silver.orders", "rows": SILVER},
                       {"name": "gold.daily_revenue", "rows": gold, "columns": ["load_date", "orders", "revenue"],
                        "types": GOLD_TYPES}],
            "outcome": "table", "table": "gold.daily_revenue"}


exercise(
    id="cp-sqlpool-proc-params", title="Call a SQL pool procedure with typed parameters", difficulty="medium",
    flavor="synapse", local=True, topics=["stored-procedure", "parameters", "sql-pool"],
    prompt=("warehouse.usp_load_daily_revenue rebuilds one day of gold.daily_revenue. Its header declares "
            "@load_date VARCHAR(10) and @min_amount DECIMAL(10, 2). Make Load daily revenue pass the pipeline's run_date "
            "and min_amount parameters to it, with the right types. Today it passes a fixed date and forgets "
            "min_amount."),
    sections=[("The procedure", "```sql\n" + PROC + "```"),
              ("Tables", "silver.orders: order_id, order_date ('YYYY-MM-DD'), net_amount DOUBLE. gold.daily_revenue: "
                         "load_date VARCHAR, orders BIGINT, revenue DOUBLE."),
              ("Graded", "The rows of gold.daily_revenue after a run: for the default parameters, when the day already "
                         "has a stale row, and for another day with a minimum amount.")],
    starter=proc_pipeline({"load_date": {"value": "2026-03-05", "type": "String"}}),
    solution=proc_pipeline(PROC_OK),
    fixtures=[
        ("default-day", "visible", proc_scenario({}, [])),
        ("stale-day-replaced", "hidden", proc_scenario({"run_date": "2026-03-05"}, [
            {"load_date": "2026-03-04", "orders": 1, "revenue": 40.0},
            {"load_date": "2026-03-05", "orders": 9, "revenue": 999.0}])),
        ("other-day-min-amount", "edge", proc_scenario({"run_date": "2026-03-06", "min_amount": 100}, [])),
    ],
    mutants=[proc_pipeline({"load_date": {"value": expr("@pipeline().parameters.run_date"), "type": "String"},
                            "min_amount": {"value": "0", "type": "Decimal"}}),
             proc_pipeline({"load_date": {"value": "2026-03-05", "type": "String"},
                            "min_amount": {"value": expr("@pipeline().parameters.min_amount"), "type": "Decimal"}})],
    hints=["storedProcedureParameters is keyed by the parameter name without @; each entry has a value and a type.",
           "A value can be dynamic content: {\"value\": \"@pipeline().parameters.run_date\", \"type\": \"Expression\"}."],
    explanation=("Each procedure parameter is passed by name with a type (String, Decimal, Int32, ...), and its value "
                 "can come from a pipeline parameter. The procedure deletes the day before inserting it, so rerunning a "
                 "day replaces its row instead of adding a second one."),
    follow_ups=["What error do you get when the pipeline passes a parameter the procedure does not declare?"],
)

# 15 -----------------------------------------------------------------------------------------------
NB_PIPELINE = json.loads(pipeline([
    notebook("Silver orders", parameters={"run_date": fabric_param("@pipeline().parameters.run_date"),
                                          "min_amount": fabric_param("@pipeline().parameters.min_amount", "int")}),
    set_variable("Keep silver rows", ["Silver orders"], "silver_rows", "@activity('Silver orders').output.result.exitValue"),
], parameters={"run_date": {"type": "string", "defaultValue": "2026-03-05"},
               "min_amount": {"type": "int", "defaultValue": 0}},
    variables={"silver_rows": {"type": "String"}}))
NB_HEAD = """
# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   }
# META }

"""
NB_BODY = """
run_date = "2026-01-01"
min_amount = 0

# CELL ********************

from pyspark.sql import functions as F

orders = spark.table("bronze.orders")
silver = orders.filter(F.col("net_amount") > min_amount).withColumn("load_date", F.lit(run_date))
silver.write.mode("overwrite").saveAsTable("silver.orders")
notebookutils.notebook.exit(str(silver.count()))
"""
BRONZE = [{"order_id": o, "net_amount": a} for o, a in [("O1", 10.0), ("O2", 150.0), ("O3", 0.0), ("O4", 45.0),
                                                         ("O5", 220.0), ("O6", -5.0)]]


def nb_scenario(parameters):
    return {"flavor": "fabric", "pipeline": "pl_silver_orders", "notebook": "fabric:nb_silver_orders",
            "data_plane": "local", "parameters": parameters, "files": {"pipelines": {"pl_silver_orders": NB_PIPELINE}},
            "tables": [{"name": "bronze.orders", "rows": BRONZE}],
            "outcome": "table", "table": "silver.orders", "columns": ["order_id", "load_date"]}


exercise(
    id="nb-fabric-parameters-cell", title="Let the pipeline set the notebook's parameters", difficulty="easy",
    flavor="fabric", language="factory-notebook", local=True, topics=["notebook-parameters", "notebook-activity"],
    prompt=("The pipeline pl_silver_orders runs this notebook with run_date and min_amount, but the notebook always "
            "uses its own values (2026-01-01 and 0). Make it take the values the pipeline passes, and keep its own "
            "values as defaults for interactive runs."),
    sections=[("The pipeline", "The Notebook activity passes run_date = @pipeline().parameters.run_date and min_amount "
                               "= @pipeline().parameters.min_amount (int), then keeps the exit value in silver_rows."),
              ("Tables", "bronze.orders: order_id VARCHAR, net_amount DOUBLE."),
              ("Graded", "The rows of silver.orders (order_id, load_date) after pipeline runs with different run_date "
                         "and min_amount values. The notebook runs on SparkLab, statement by statement, on an isolated "
                         "local catalog; it is never executed as Python.")],
    starter=code(NB_HEAD + "# CELL ********************\n" + NB_BODY),
    solution=code(NB_HEAD + "# PARAMETERS CELL ********************\n" + NB_BODY),
    fixtures=[
        ("run-date-passed", "visible", nb_scenario({"run_date": "2026-03-05", "min_amount": 0})),
        ("min-amount-passed", "hidden", nb_scenario({"run_date": "2026-03-06", "min_amount": 100})),
        ("both-changed", "edge", nb_scenario({"run_date": "2026-12-31", "min_amount": 20})),
    ],
    mutants=[code(NB_HEAD + "# CELL ********************\n" + NB_BODY.replace(
                 "# CELL ********************", "# PARAMETERS CELL ********************")),
             code(NB_HEAD + "# PARAMETERS CELL ********************\n" + NB_BODY.replace(
                 'orders = spark.table("bronze.orders")', 'min_amount = 0\norders = spark.table("bronze.orders")'))],
    hints=["Fabric injects the pipeline's parameters right after the cell marked as the parameters cell.",
           "In the notebook source, a cell marker reads # CELL ********************; the parameters cell uses "
           "# PARAMETERS CELL ********************."],
    explanation=("Without a parameters cell, Fabric injects the pipeline's values at the top of the notebook, and the "
                 "notebook's own assignments then overwrite them. Marking the first cell as the parameters cell makes "
                 "the injected values come after it: the pipeline wins, and the cell keeps the defaults for "
                 "interactive runs."),
    follow_ups=["Which parameter types can a Fabric Notebook activity pass, and what does the notebook receive?"],
)

# 16 -----------------------------------------------------------------------------------------------
DBX_PIPELINE = json.loads(pipeline([
    act("Top customers", "DatabricksNotebook", [], {
        "notebookPath": "/Shared/nb_top_customers",
        "baseParameters": {"min_orders": expr("@string(pipeline().parameters.min_orders)"),
                           "target_table": "gold.top_customers"}}, policy(),
        linkedServiceName=ref("ls_lab_databricks", "LinkedServiceReference")),
    set_variable("Keep top count", ["Top customers"], "top_count", "@activity('Top customers').output.runOutput"),
], parameters={"min_orders": {"type": "int", "defaultValue": 2}}, variables={"top_count": {"type": "String"}},
    name="pl_top_customers"))
DBX_STARTER = code('''
# Databricks notebook source
from pyspark.sql import functions as F

min_orders = 2
target_table = "gold.top_customers"

orders = spark.table("silver.orders")
top = (
    orders.groupBy("customer_id")
    .agg(F.count("order_id").alias("orders"), F.sum("net_amount").alias("revenue"))
    .filter(F.col("orders") >= min_orders)
)
top.write.saveAsTable(target_table)
''')


def dbx_notebook(mode=True, widget_min=True):
    reads = ('min_orders = int(dbutils.widgets.get("min_orders"))' if widget_min else "min_orders = 2")
    write = 'top.write.mode("overwrite").saveAsTable(target_table)' if mode else "top.write.saveAsTable(target_table)"
    return code(f'''
# Databricks notebook source
dbutils.widgets.text("min_orders", "2")
dbutils.widgets.text("target_table", "gold.top_customers")

# COMMAND ----------

from pyspark.sql import functions as F

{reads}
target_table = dbutils.widgets.get("target_table")

orders = spark.table("silver.orders")
top = (
    orders.groupBy("customer_id")
    .agg(F.count("order_id").alias("orders"), F.sum("net_amount").alias("revenue"))
    .filter(F.col("orders") >= min_orders)
)
{write}

# COMMAND ----------

dbutils.notebook.exit(str(top.count()))
''')


SILVER_CUSTOMERS = [{"order_id": o, "customer_id": c, "net_amount": a} for o, c, a in [
    ("O1", "C1", 10.0), ("O2", "C1", 20.0), ("O3", "C2", 5.0), ("O4", "C3", 7.0), ("O5", "C3", 8.0), ("O6", "C3", 9.0),
    ("O7", "C4", 30.0), ("O8", "C4", 1.0)]]


def dbx_scenario(parameters, outcome):
    scenario = {"flavor": "adf", "pipeline": "pl_top_customers", "notebook": "databricks:/Shared/nb_top_customers",
                "data_plane": "local", "parameters": parameters, "runs": 2,
                "files": {"pipelines": {"pl_top_customers": DBX_PIPELINE}},
                "tables": [{"name": "silver.orders", "rows": SILVER_CUSTOMERS}]}
    if outcome == "table":
        scenario.update(outcome="table", table="gold.top_customers", columns=["customer_id", "orders"])
    else:
        scenario.update(outcome="variables")
    return scenario


exercise(
    id="nb-databricks-widgets", title="Parameterize a Databricks notebook run by Data Factory", difficulty="medium",
    flavor="adf", language="factory-notebook", local=True, topics=["notebook-parameters", "databricks", "save-modes"],
    prompt=("The Azure Data Factory pipeline pl_top_customers runs this Azure Databricks notebook every day with the "
            "baseParameters min_orders and target_table, and keeps the notebook's runOutput in top_count. Read both "
            "parameters with widgets (defaults 2 and gold.top_customers), replace the table on every run, and return "
            "the number of top customers with dbutils.notebook.exit."),
    sections=[("The pipeline", "The Azure Databricks notebook activity passes baseParameters min_orders = "
                               "@string(pipeline().parameters.min_orders) and target_table = gold.top_customers, then "
                               "Set variable keeps @activity('Top customers').output.runOutput in top_count."),
              ("Tables", "silver.orders: order_id VARCHAR, customer_id VARCHAR, net_amount DOUBLE."),
              ("Graded", "top_count after the second of two daily runs, for two min_orders values, and the rows of the "
                         "target table (customer_id, orders). The notebook runs on SparkLab on an isolated local "
                         "catalog; it is never executed as Python.")],
    starter=DBX_STARTER, solution=dbx_notebook(),
    fixtures=[
        ("count-returned", "visible", dbx_scenario({"min_orders": 2}, "variables")),
        ("min-orders-three", "hidden", dbx_scenario({"min_orders": 3}, "variables")),
        ("table-after-two-runs", "edge", dbx_scenario({"min_orders": 2}, "table")),
    ],
    mutants=[dbx_notebook(mode=False), dbx_notebook(widget_min=False)],
    hints=["dbutils.widgets.get returns text: convert min_orders with int(...) before comparing.",
           "Spark's default save mode is errorifexists: the second daily run fails unless you choose a mode."],
    explanation=("Data Factory passes baseParameters as widget values, always as text, so the notebook declares them "
                 "with dbutils.widgets.text (the defaults serve interactive runs) and reads them with "
                 "dbutils.widgets.get. mode(\"overwrite\") makes the daily run replace the table instead of failing "
                 "with TABLE_OR_VIEW_ALREADY_EXISTS, and dbutils.notebook.exit sends the count back as runOutput."),
    follow_ups=["Return a JSON string with the count and the total revenue, and read both in the pipeline."],
)


# -- pack assembly ---------------------------------------------------------------------------------
SIMULATOR = ("Your pipeline JSON is validated with the design rules of {product} and simulated by the Cloud Lab "
             "engine: dependency conditions, run status from the leaf activities, retries and timeouts, containers "
             "and the expression language. Nothing connects to Microsoft Fabric or Azure. Each check runs the "
             "pipeline in its own scenario (activity failures, durations, outputs, parameters, trigger time).")
NOTEBOOK_SIMULATOR = ("Your notebook runs inside a given {product} pipeline. The pipeline is simulated by the Cloud Lab "
                      "engine and the notebook runs on SparkLab, the bounded fake Spark, statement by statement: it is "
                      "never executed as Python. Each check is its own pipeline run.")
LOCAL_DATA = ("Copy, Lookup, Script, stored procedures and notebooks really run, on an isolated DuckDB catalog built "
              "for each check from the tables below. Your workspace lakehouse is never read or written.")


def definition(spec: dict, rank: int) -> dict:
    by_visibility = {"visible": [], "hidden": [], "edge": []}
    for fid, visibility, _ in spec["fixtures"]:
        by_visibility[visibility].append(fid)
    product = PRODUCT[spec["flavor"]]
    intro = (NOTEBOOK_SIMULATOR if spec["language"] == "factory-notebook" else SIMULATOR).format(product=product)
    sections = [{"title": "Simulator", "body": intro}]
    if spec["local"]:
        sections.append({"title": "Local data", "body": LOCAL_DATA})
    sections += [{"title": title, "body": body} for title, body in spec["sections"]]
    projections = {json.dumps(scenario.get("columns")) for _, _, scenario in spec["fixtures"]}
    exact = json.loads(projections.pop()) if len(projections) == 1 else None
    validation = {
        "kind": "rows", "ordered": False, "duplicate_sensitive": True,
        "relative_tolerance": 1e-09, "absolute_tolerance": 1e-06,
        "required_columns": exact or [], "exact_schema": exact,
        "forbidden_extra_columns": True, "null_semantics": "equal",
    }
    tags = ["cloud-lab", "data-factory", spec["flavor"], "simulated"] + (["local-data"] if spec["local"] else [])
    return {
        "schema_version": 1,
        "id": spec["id"],
        "version": "1",
        "title": spec["title"],
        "difficulty": spec["difficulty"],
        "topics": spec["topics"],
        "tags": tags,
        "origin": "authored",
        "language": spec["language"],
        "runtime": "datapass-factory-sim-v1",
        "prompt": spec["prompt"],
        "sections": sections,
        "starter_source": spec["starter"],
        "fixtures": [{"id": f"{spec['id']}-fixtures", "version": "1"}],
        "visible_checks": [{"id": fid, "description": "Simulated pipeline outcome for the public scenario."}
                           for fid in by_visibility["visible"]],
        "hidden_check_refs": by_visibility["hidden"],
        "edge_check_refs": by_visibility["edge"],
        "hints": spec["hints"],
        "solution": {"available": True, "reveal": "explicit"},
        "explanation": spec["explanation"],
        "follow_ups": spec["follow_ups"],
        "canonical_placement": {"domain": "cloud-pipelines", "topic": spec["topics"][0]},
        "related_associations": ["cloud-lab/pipelines"],
        "recommendation": {"rank": rank, "reason": "Cloud Lab pipeline progression"},
        "validator_version": "rows-v2",
        "validation": validation,
        "runtime_requirements": ["factory-simulator"],
        "provenance": {
            "source": "Authored for Datapass Workbench: Data Factory orchestration on the Cloud Lab simulator",
            "fixtures": "Authored scenarios; expected rows computed by running the reference and reviewed",
        },
        "constraints": {
            "truth": ("Simulated orchestration for " + product + "; "
                      + ("Copy, Lookup, Script, stored procedures and notebooks run on an isolated local DuckDB catalog."
                         if spec["local"] else "every activity follows the check's scenario.")),
        },
        "truth": "simulated",
    }


def outcome(language, source, scenario):
    from datapass_runtime.factory_grading import run_fixture
    from factorylab.exercise import ExerciseScenario
    from factorylab.model import FactoryLabError
    try:
        return run_fixture(language, source, ExerciseScenario.model_validate(scenario)), None
    except FactoryLabError as exc:
        return None, "; ".join(f"{i.path}: {i.message}" for i in exc.issues)


def main() -> None:
    from datapass_runtime.exercise_packs import PackRegistry
    from datapass_runtime.exercise_validation import validate_result
    from datapass_runtime.exercise_contracts import RowValidation
    ids = [spec["id"] for spec in EXERCISES]
    assert len(ids) == len(set(ids))
    definitions, grading, problems = [], {}, []
    for rank, spec in enumerate(EXERCISES, start=1):
        public = definition(spec, rank)
        definitions.append(public)
        validation = RowValidation.model_validate(public["validation"])
        fixtures = []
        for fid, visibility, scenario in spec["fixtures"]:
            rows, error = outcome(spec["language"], spec["solution"], copy.deepcopy(scenario))
            if error:
                problems.append(f"{spec['id']}/{fid}: reference rejected: {error}")
                rows = []
            fixtures.append({"id": fid, "visibility": visibility, "input_rows": [], "scenario": scenario, "expected": rows})
        grading[spec["id"]] = {"solution": spec["solution"], "fixtures": fixtures}
        for label, source in [("starter", spec["starter"])] + [(f"mutant {i}", m) for i, m in enumerate(spec["mutants"])]:
            failed = False
            for fixture in fixtures:
                rows, error = outcome(spec["language"], source, copy.deepcopy(fixture["scenario"]))
                if error:
                    problems.append(f"{spec['id']}: {label} does not run: {error}")
                    failed = True
                    break
                columns = fixture["scenario"].get("columns") or (list(rows[0]) if rows else [])
                if not validate_result({"rows": rows, "columns": columns, "truncated": False}, fixture["expected"], validation):
                    failed = True
            if not failed:
                problems.append(f"{spec['id']}: {label} passes every check")
    manifest = {
        "schema_version": 1, "id": "cloud-pipelines-v1", "version": "1",
        "title": "Cloud Lab: Data Factory pipelines for Fabric, Azure Data Factory and Synapse (simulated)",
        "enabled": True,
        "provenance": {"source": "Authored for Datapass Workbench"},
    }
    PackRegistry().register(manifest, definitions, grading)
    PACK.mkdir(parents=True, exist_ok=True)
    for name, data in (("manifest.json", manifest), ("exercises.json", definitions), ("grading.server.json", grading)):
        (PACK / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_mutants(PACK, {spec["id"]: spec["mutants"] for spec in EXERCISES})
    for spec in EXERCISES:
        print(f"== {spec['id']}")
        for fixture in grading[spec["id"]]["fixtures"]:
            print(f"   {fixture['id']:24s}", json.dumps(fixture["expected"]))
    if problems:
        print("\nPROBLEMS:\n  " + "\n  ".join(problems))


if __name__ == "__main__":
    main()
