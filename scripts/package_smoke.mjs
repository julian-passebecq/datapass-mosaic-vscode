import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";

const required = [
  "dist/extension.js",
  "dist/webview.js",
  "dist/webview.css",
  "media/datapass.svg",
  "content/modules.json",
  "content/cases/retail-medallion.json",
  "runtime/pyproject.toml",
  "runtime/datapass_runtime/main.py",
  "runtime/datapass_runtime/execution.py",
  "runtime/sparklab/profiles.json",
  "runtime/airflowlab/parser.py",
  "runtime/factorylab/engine.py",
  "runtime/factorylab/README.md",
  "runtime/sqlpoollab/engine.py",
  "runtime/sqlpoollab/README.md",
  "runtime/databrickslab/engine.py",
  "runtime/databrickslab/README.md",
  "runtime/bilab/lineage.py",
  "runtime/bilab/README.md",
  "runtime/dbtlab/engine.py",
  "runtime/dbtlab/README.md",
  "runtime/snowflakesql/translate.py",
  "runtime/snowflakesql/README.md",
  "content/exercise-packs/dbt-v1/grading.server.json",
  "content/exercise-packs/dwh-v1/grading.server.json",
  "content/exercise-packs/sqlpool-v1/grading.server.json",
  "content/exercise-packs/airflow-lab-v1/grading.server.json",
  "samples/dbt/retail-dbt/dbt_project.yml",
  "samples/factory-lab/fabric/pl_retail_daily.DataPipeline/pipeline-content.json",
  "samples/factory-lab/sql/procedures/warehouse.usp_load_gold_revenue.sql",
  "samples/factory-lab/sql/pool/01_star_schema.sql",
  "samples/factory-lab/databricks/jobs/retail_daily_dbx.json",
  "samples/bi-lab/model.json",
  "samples/bi-lab/warehouse/05_fct_sales.sql",
  "samples/bi-lab/dbt/dbt_project.yml",
  "samples/bi-lab/dbt/models/marts/fct_sales.sql"
];

for (const path of required) {
  await access(path);
}

const ignore = await readFile(".vscodeignore", "utf8");
for (const forbidden of [
  "legacy-donors/**",
  "migration-sources/**",
  "workbench-core/**",
  "runtime/build/**",
  "runtime/**/*.egg-info/**",
  "**/*.map"
]) {
  assert.ok(ignore.includes(forbidden), `VSIX ignore is missing ${forbidden}`);
}

console.log("VSIX package boundary smoke passed.");
