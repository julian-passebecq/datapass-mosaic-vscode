# Legacy donor inventory

Selected reusable source material from prior Datapass projects is preserved here for migration into the VS Code workbench.

## Already active
The current `workbench-core/` already contains FastAPI APIs, exercise packs/grading, notebook-core, local data/lakehouse, kernels, SparkLab, pipeline compiler/runner/grading, dbt runner/drills, analytics contracts and local cases. Do not duplicate these.

## Donors
- `react_ms_fluent_2_framework`: challenge contracts, progress model, notebook language detection, workflow/lineage semantics, learning/workbench UI patterns.
- `Fluent2_J_CodeLab`: LeetCode-style challenge/catalog UI patterns.
- `Fluent2_J_CloudArchi`: cloud/pipeline teaching patterns.
- `leetcodedataeng`: curriculum, SQL challenges, cheatsheets, progress backup and ZillaCode-derived material.

## Deliberate exclusions
No old app shells, Monaco wrappers, Contoso C# source, Fabric cloud client, Airflow logs/.env/credentials/Docker state, or duplicate SparkLab/dbt runtimes.

Nothing under `legacy-donors/` is production code. Promote pieces deliberately after adapting them to VS Code boundaries.
