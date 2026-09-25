# Datapass Workbench harvest audit

Date: 2026-09-23

This file is the compact source-of-truth for reuse from older Julian Passebecq repositories.

## Rule

Harvest **capabilities, contracts, content and proven UI mechanics**. Do not merge entire historical applications into the VS Code extension.

VS Code owns code editing, Explorer, terminals, Git, Jupyter and extension lifecycle. Datapass owns learning content, local data runtimes, simulation semantics and specialist visual surfaces.

## Primary donor: ducklabms_code

`julian-passebecq/ducklabms_code` is the consolidated donor and supersedes re-copying most older Datapass experiments.

Already retained in this repository:

- `workbench-core/`: preserved integrated Workbench source/reference.
- `packages/notebook-core/`: Mosaic notebook document/layout contracts, ipynb import/export and project serialization.
- `packages/contracts/`: shared case/workbench/foundation contracts.
- `runtime/sparklab/`: bounded SparkLab/ZilaCode training runtime.
- `content/cases/`: connected DE cases.
- `content/exercise-packs/`: Spark, pipeline and unified case exercises/grading.
- `migration-sources/fabric/`: Fabric-style notebook/pipeline/graph donors.
- `migration-sources/airflow-dbt/`: Airflow/dbt UX and domain donors.
- `migration-sources/workbench-ui/`: previous Workbench/Mosaic UI donor.
- real local dbt sample project under `workbench-core/examples/analytics-m2/retail-dbt/`.

Useful mechanics already identified there:

- draggable/resizable Mosaic notebook geometry;
- shared React Flow graph mechanics for pipeline, DAG, lineage and data-model surfaces;
- pipeline palette/canvas/properties split and dependency validation;
- FastAPI + local data-engine boundary;
- DuckDB/DuckLake local lakehouse model;
- explicit simulated-vs-real capability labeling.

Do not duplicate these from older source repos.

## DataPass VS Code donor

Source: `julian-passebecq/datapass-vscode`.

Keep/adapt:

- DataPass Activity Bar and extension-host patterns;
- CSP + nonce protected webviews;
- extension/tool detection;
- safe command dispatch;
- portable `.datapass/project.json` workspace manifest;
- status/capability model.

Already represented in `src/platform/`:

- catalog;
- commands;
- detection;
- status;
- VS Code extension detection.

Added in this harvest pass:

- `src/project/`: lightweight local project manifest contract;
- `src/webview/security.ts`: reusable CSP/nonce helpers.

Do **not** migrate its cloud control-plane identity into the teaching workbench. Fabric/Databricks/vendor extensions may be detected as optional companions, but Fabric Lab remains a local simulator.

## LeetCode / interview donor

Source: `julian-passebecq/leetcodedataeng`.

Preserved under `legacy-donors/leetcodedataeng/`:

- curriculum;
- SQL challenges;
- multi-engine challenge concepts;
- cheat sheets;
- engine-selection material;
- progress backup logic.

Use the **content**, not its web shell or Monaco editor. Practice in the extension should open native VS Code files and use Datapass tests/results/hints.

The historical app contains broad DE coverage including Python, SQL, PySpark, storage/formats, dbt, Airflow, troubleshooting, modeling and engine comparisons. Promote exercises progressively into versioned `content/exercise-packs/`.

## ZillaCode problems (through CodeDELeet)

Source: CodeDELeet's normalized import of the 52 ZillaCode problems (`public/packs/v3-zilla.json`, its provenance ledger `docs/v3/ZILLA_IMPORT_PROVENANCE.json` and `licenses/ZillaCode-Apache-2.0.txt`). ZillaCode is Apache-2.0 (https://github.com/davidzajac1/zillacode). The user's private ZillaCode archive was not used and the reference application was never run.

**Promoted (2026-09-25)** as the Practice pack `zilla-v1` (52 scenarios, 278 variants), built our way:

- one semantic scenario per problem, graded on our engines: DuckDB SQL, Snowflake SQL translated to DuckDB (`runtime/sqldialects`), pandas and Polars (trusted Python), SparkLab where its subset covers the problem, and the Datapass dbt emulation;
- snake_case tables and columns, explicit output order, NULL and tie rules, statement-vs-reference conflicts resolved and documented per exercise;
- ZillaCode's two tests are the visible and hidden fixtures (inputs only: every expected row is recomputed from the Datapass SQL reference and reviewed), plus authored edge fixtures for ties, NULLs and empty groups;
- CodeDELeet's SparkLite/dbtLite variants and its unverified SQL were not copied: the references were rewritten and are graded in CI.

`scripts/authoring/gen_zilla.py` regenerates the pack from the CodeDELeet checkout.

## Fluent / visual learning donors

Relevant repositories audited:

- `Fluent2_J_Formation`
- `Fluent2_J_Viz`
- `Fluent2_J_VisualAlgo`
- `Fluent2_J_CloudArchi`
- `Fluent2_J_CodeLab`
- `react_ms_fluent_2_framework`
- `fluent_forgeviz`

Use selectively for:

- Fluent UI composition patterns;
- challenge/catalog layouts;
- visual explanation patterns;
- graph/architecture teaching concepts.

Do not bring another application shell, navigation system or editor.

## Airflow donors

Historical repos audited:

- `airflow_start`
- `airflow_start2`
- `airflow_etladventureworks`
- `airflowcsv`
- `airflow_sqlserver`

Their useful concepts are already represented by consolidated Airflow/dbt donors and cases. Do not vendor full Airflow, Docker state, logs, credentials or old environment files.

Airflow Lab remains a deterministic simulator for DAG dependencies, scheduling, retries, states and logs.

## dbt donors

Historical repos audited:

- `dbt-demo`
- `snowflake_dbt_V1`
- `Building-OLAP-Dimensional-Model-using-BigQuery-and-DBT`

Prefer the current local dbt + DuckDB example retained under `workbench-core/examples/analytics-m2/retail-dbt/`. Use older repos only as exercise/content references.

dbt Lab should use real dbt Core where practical and visualize its real artifacts rather than implement a fake dbt compiler.

## Data/model visualization donors

Repositories audited:

- `reactdatamodel`
- `sql_schema_visualizer`

Useful ideas can be mapped onto the shared React Flow graph foundation. Do not preserve competing graph renderers.

## Fabric toolbox donor

Source: `julian-passebecq/fabricdatapasstoolbox`.

This is **not** the source for Fabric Lab execution. Fabric Lab is intentionally local and simulated.

Only reuse generic checklist/status/tool-discovery concepts if needed. Real Fabric management belongs to optional companion tooling/extensions.

## Contoso

`julian-passebecq/contoso-data-studio` remains a separate C# product.

Allowed integration boundary:

- datasets;
- generated fixtures;
- case-study imports/exports.

Do not embed its C# UI/runtime into this extension.

## Explicit exclusions

Do not copy:

- old top-level React/Vite app shells;
- Monaco/editor wrappers for normal coding;
- duplicate notebook engines;
- duplicate SparkLab implementations;
- duplicate dbt runners;
- a full Airflow installation merely for training;
- cloud credentials or local secrets;
- historical build artifacts, logs, node_modules, virtual environments or Docker state;
- vendor cloud clients where official VS Code extensions already own the integration.

## Active target architecture

```text
VS Code
├─ native editor / files / terminal / Git / Jupyter
├─ Datapass Workbench
│  ├─ Mosaic            → Polars + DuckDB
│  ├─ Practice          → native files + tests
│  ├─ SparkLab          → bounded PySpark simulation
│  ├─ Fabric Lab        → local lakehouse + notebook + pipeline simulation
│  ├─ dbt Lab           → dbt Core + DuckDB + manifest lineage
│  ├─ Airflow Lab       → deterministic DAG simulator
│  └─ Pipeline Lab      → React Flow + local workflow engine
└─ one local FastAPI runtime
   ├─ DuckDB / DuckLake
   ├─ Polars
   ├─ SparkLab
   ├─ dbt adapter
   └─ workflow/scheduler services
```

This repository is now the authoritative implementation target. Historical repos are donors, not parallel products.
