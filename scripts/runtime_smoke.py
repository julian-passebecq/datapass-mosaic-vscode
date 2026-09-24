from importlib import resources
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from datapass_runtime.main import app
from datapass_runtime.pipeline_compiler import compile_response
from datapass_runtime.guided_spark import compile_guard
from datapass_runtime.content import cases, content_root
from datapass_runtime.exercises import definitions
from datapass_runtime.retail_demo import run_retail_demo
from sparklab.capabilities import SUPPORT


assert app.title == "Datapass Runtime"
assert SUPPORT["schema_version"] == 1
assert (content_root() / "cases").is_dir()
assert (content_root() / "exercise-packs").is_dir()
assert any(case.get("id") == "retail-medallion" for case in cases())
assert definitions(), "Expected installed exercise definitions from content/exercise-packs."
for asset in ("profiles.json", "cluster_profiles.json", "oracle.json"):
    assert resources.files("sparklab").joinpath(asset).is_file(), asset

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
    assert retail["database_path"] == ".datapass/data/datapass.duckdb"
    assert [stage["rows"] for stage in retail["stages"]] == [5, 5, 3, 2]
    assert retail["polars_quality"] == {"rows": 3, "customers": 2, "revenue": 350.0}
    assert retail["preview"]["rows"][0]["customer_id"] == "C002"
    assert retail["preview"]["rows"][0]["revenue"] == 200.0
    assert (workspace / ".datapass" / "data" / "datapass.duckdb").is_file()

print("Datapass runtime smoke passed.")
