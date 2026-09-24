# Claude handoff — Datapass Workbench VS Code

Date: 2026-09-24

## 1. Start here

Repository: `julian-passebecq/datapass-mosaic-vscode`

Active implementation branch:

```text
codex/bootstrap-datapass-workbench
```

Do **not** restart from `main`. At audit time, `main` was effectively the one-line initial repository while the implementation branch was 201 commits ahead.

Known good implementation baseline before this documentation pass:

```text
ae489cd161e4565808a056de17b42241c63ecc20
Smoke test versioned Practice grading
2026-09-24 13:54:10 UTC
```

GitHub Actions run for that baseline:

```text
run 36008901370
extension: success
runtime:   success
```

This handoff pass subsequently added truth-model/documentation commits. Treat the current tip of `codex/bootstrap-datapass-workbench` as the branch to continue from, subject to CI.

## 2. Why the project looked stopped

The work did not disappear. It was left on `codex/bootstrap-datapass-workbench` while `main` remained essentially empty.

The branch also progressed materially beyond the older checkpoint `abfe28df`. In particular, the execution bridge was completed further than earlier notes implied:

- real native SQL execution from Mosaic;
- shared local runtime/catalog state;
- real bounded Pipeline Lab activity execution;
- managed runtime environment setup;
- native-file Practice grading with separate Run/Submit behavior;
- VSIX package-boundary checks;
- extracted dbt sample outside donor trees.

Do not repeat those migrations.

## 3. Product architecture

Datapass Workbench is one VS Code extension, not a collection of separate apps.

```text
VS Code
├─ native editor / files / terminal / Git / Jupyter
└─ Datapass Workbench
   ├─ Mosaic
   ├─ Practice
   ├─ Fabric Lab
   ├─ SparkLab / ZilaCode
   ├─ dbt Lab
   ├─ Airflow Lab
   └─ Pipeline Lab
          │
          ▼
      one FastAPI runtime
      ├─ DuckDB / optional DuckLake
      ├─ Polars
      ├─ bounded SparkLab
      ├─ shared catalog/kernel
      ├─ exercise grading
      └─ bounded pipeline execution
```

Keep separate:

- Datapass WorkNotebook: standalone public/reference/cheatsheet experience.
- Contoso Data Studio: separate C# product; datasets/cases may cross the boundary.
- historical donors: references only.

## 4. Current surface status

### Mosaic

Implemented:

- draggable/resizable `react-grid-layout` surface;
- persistent webview layout state;
- native VS Code SQL/Python/Markdown scratch files;
- real active-file SQL execution through the FastAPI runtime;
- SQL result preview;
- shared local catalog display.

Important gap:

- the Python/Polars card opens native files but does not yet expose the same polished execution workflow as SQL.
- Do not solve this by silently enabling arbitrary Python. See the trusted-Python boundary below.

### Practice

Implemented:

- versioned exercise catalog;
- searchable Practice UI;
- native VS Code solution files;
- real shared-runtime grading;
- separate visible checks vs submission;
- status/check feedback in the webview;
- smoke coverage for versioned grading.

This is no longer just a scaffold.

### Fabric Lab

Implemented:

- Fabric-inspired local teaching flow;
- connected retail demo scaffolding;
- real local medallion demo with DuckDB/Polars;
- preview/KPI results;
- links into SparkLab and Pipeline Lab.

Truth boundary:

- this is not an implicit Microsoft Fabric client;
- orchestration/Fabric chrome are teaching semantics;
- real local engines must be labeled as such.

### SparkLab / ZilaCode

Runtime capability exists and is bounded.

Current webview is still relatively thin:

- operation/capability reference;
- open Spark/Python scratch;
- jump to Practice.

Priority improvement: add a direct, clearly bounded SparkLab execution/inspection workflow using the existing safe parser/runtime. Do not imply a real distributed Spark cluster.

### dbt Lab

Implemented:

- extracted local sample under `samples/dbt/retail-dbt`;
- dbt CLI + dbt-duckdb probing;
- static project lineage fallback;
- real `dbt build` path when tooling is installed;
- prefer real `target/manifest.json` after execution.

Gap:

- Pipeline Lab accepts a dbt activity in the design grammar, but native pipeline dbt execution is intentionally **not wired yet**. `runtime/datapass_runtime/native_pipeline.py` currently fails clearly and directs users to dbt Lab.

### Airflow Lab

Implemented as deterministic UI-side simulation:

- DAG definition;
- dependencies;
- retries;
- retry delay;
- trigger rules;
- task states;
- simulated logs;
- step/run-to-end/reset.

Do not replace this with a full Airflow install merely to teach scheduling semantics.

### Pipeline Lab

Implemented:

- bounded Python-like AST compiler;
- literal-only task declarations;
- dependency graph;
- source diagnostics;
- shared React Flow visualization;
- real local execution for supported activity bodies;
- task run history/result states.

Critical distinction:

```text
pipeline SOURCE: compiled only, NEVER eval/exec
activity BODY: may execute through the shared local runtime
schedule: metadata / teaching semantics
```

Currently wired activity bodies:

- SQL
- quality
- Python
- Polars

dbt syntax exists but runtime execution is not wired.

## 5. Runtime and security model

Key files:

- `runtime/datapass_runtime/main.py`
- `runtime/datapass_runtime/execution.py`
- `runtime/datapass_runtime/kernels.py`
- `runtime/datapass_runtime/native_pipeline.py`
- `runtime/datapass_runtime/pipeline_compiler.py`

The runtime is a loopback FastAPI control plane.

The kernel worker provides lifecycle isolation and timeout/restart semantics. It is **not a hostile-code sandbox**.

Environment filtering removes obvious TOKEN/SECRET/PASSWORD/API_KEY variables before spawning a worker, but that does not make arbitrary Python safe.

### Trusted Python issue to resolve deliberately

`execution.py` only enables Python when `trusted_python=True`.

The API derives that from:

```text
DATAPASS_TRUSTED_PYTHON=1
```

Normal managed-runtime startup does not silently opt the user into this, which is the correct safety posture.

Therefore:

- SQL works in the normal local runtime.
- bounded SparkLab semantics work through their safe parser.
- arbitrary Python/Polars execution must remain explicitly trusted.

Next implementation should create an explicit UX/project setting for trusted local Python rather than simply setting the environment flag globally.

Suggested contract direction:

```json
{
  "runtime": {
    "storage": "duckdb",
    "pythonCommand": "python",
    "trustedLocalPython": false
  }
}
```

Requirements:

- default false;
- clear warning that it executes local code;
- workspace-scoped/project-scoped choice;
- no misleading “sandbox” wording;
- update runtime state/capabilities visibly.

## 6. Important files

Extension host:

- `src/extension.ts`
- `src/workbenchPanel.ts`
- `src/runtimeManager.ts`
- `src/workbenchState.ts`

Webview:

- `src/webview/WorkbenchApp.tsx`
- `src/webview/MosaicSurface.tsx`
- `src/webview/PracticeSurface.tsx`
- `src/webview/FabricSurface.tsx`
- `src/webview/SparkLabSurface.tsx`
- `src/webview/PipelineSurface.tsx`
- `src/webview/AirflowSurface.tsx`
- `src/webview/DbtSurface.tsx`
- `src/webview/SharedGraphCanvas.tsx`

Contracts/project:

- `src/webview/contracts.ts`
- `src/project/projectManifestModel.ts`
- `src/project/projectManifest.ts`

Runtime/tests:

- `runtime/datapass_runtime/main.py`
- `runtime/datapass_runtime/execution.py`
- `runtime/datapass_runtime/kernels.py`
- `runtime/datapass_runtime/native_pipeline.py`
- `scripts/runtime_smoke.py`
- `scripts/runtime_endpoint_smoke.mjs`
- `scripts/scaffold_smoke.mjs`
- `scripts/package_smoke.mjs`
- `.github/workflows/ci.yml`

## 7. Donor policy

Already audited in `docs/HARVEST_AUDIT.md`.

Use:

- `workbench-core/`
- `migration-sources/`
- `legacy-donors/`

only to recover a proven capability or content item.

Do not:

- add another React app shell;
- add another Monaco/editor layer;
- add another notebook runtime;
- add a duplicate Spark implementation;
- copy a full Airflow deployment;
- duplicate dbt execution;
- turn Fabric Lab into an unreviewed cloud control plane.

The VSIX intentionally excludes donor/development trees.

## 8. Priority continuation plan

Proceed in this order unless a newly reproduced bug blocks the sequence.

### P0 — preserve the working branch

1. Continue from `codex/bootstrap-datapass-workbench`.
2. Keep CI green after every coherent tranche.
3. Do not force-push/rewrite the long branch history.
4. Keep the branch-to-main PR as draft until manual F5 smoke testing is satisfactory.

### P1 — trusted Python/Polars UX

Implement explicit workspace/project opt-in.

Acceptance criteria:

- default remains disabled;
- state is visible in Workbench;
- managed runtime receives the flag only after explicit opt-in;
- Python/Polars buttons clearly explain why disabled when untrusted;
- tests cover default-disabled and enabled configuration;
- no claim of sandboxing.

### P1 — direct SparkLab execution experience

Use the existing bounded SparkLab parser/runtime.

Target:

- open/edit code in native VS Code;
- run supported SparkLab source;
- show result rows;
- show logical/teaching physical plan;
- visibly mark simulated stages/shuffle/cost;
- reject unsupported syntax clearly.

Do not add a second Spark engine.

### P1 — end-to-end Extension Host smoke

Automated unit/smoke gates are green, but add/strengthen extension-host/E2E coverage for:

1. create `.datapass/project.json`;
2. setup/start runtime;
3. run Mosaic SQL;
4. create/open Practice exercise and submit;
5. compile/run Pipeline Lab;
6. run retail demo;
7. inspect Airflow simulator;
8. dbt static lineage and real dbt route when available.

### P2 — pipeline dbt activity

Either:

- wire it to the existing real dbt Core adapter with strict project/resource validation, or
- keep it disabled and make the UI/compiler state explicit.

Do not fake successful dbt execution.

### P2 — Mosaic durability and UX

The layout currently survives via webview state. Evaluate whether project-portable Mosaic layouts should be stored under `.datapass/`.

If added:

- version the schema;
- keep source files native;
- do not serialize runtime secrets;
- gracefully migrate old layouts.

### P2 — broader teaching content

After the runtime/surface contracts stabilize, promote additional exercises/cases from existing donor content rather than expanding shells first.

## 9. Required tests

Extension:

```bash
npm install --no-audit --no-fund
npm run compile
npm test
```

Runtime:

```bash
python -m pip install ./runtime
python -m compileall -q runtime/datapass_runtime runtime/sparklab
python scripts/runtime_smoke.py
```

Current CI runs both extension and runtime jobs.

Manual test:

1. open the repo in VS Code;
2. press F5;
3. in Extension Development Host open a disposable data-project folder;
4. open Datapass activity bar;
5. Setup runtime;
6. Create `.datapass` project;
7. Mosaic: open/run SQL and inspect preview/catalog;
8. Practice: open an exercise, edit native solution, Run visible, Submit;
9. Pipeline: create source, compile graph, run supported activities;
10. Fabric Lab: create/repair retail demo, execute medallion flow;
11. Airflow: step/run/reset;
12. dbt: verify static lineage; if dbt Core + dbt-duckdb exist, run build and verify manifest-backed lineage.

## 10. Definition of done for the next Claude tranche

Do not report the project as finished merely because it compiles.

A tranche is done when:

- implementation matches the truth labels;
- no duplicate runtime/editor is introduced;
- security boundary is preserved;
- TypeScript build passes;
- Node smoke tests pass;
- Python runtime smoke passes;
- user-facing flow is manually exercised where applicable;
- docs/contracts are updated in the same tranche.

## 11. What not to do

- Do not restart this project from scratch.
- Do not develop on the empty `main` branch as if it were authoritative.
- Do not silently enable trusted Python.
- Do not eval/exec pipeline source.
- Do not claim SparkLab is a real Spark cluster.
- Do not claim Airflow simulation is real Airflow.
- Do not claim Fabric Lab is connected to Microsoft Fabric unless a future explicit connector is added.
- Do not make static dbt lineage look like a successful dbt run.
- Do not import whole donor repos into the production VSIX.
- Do not create competing app shells.

Read `CLAUDE.md`, `docs/ARCHITECTURE.md`, `docs/HARVEST_AUDIT.md`, and this file before changing architecture.
