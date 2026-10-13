# PLAN - Mosaic / Datapass Workbench

Updated 2026-10-02 for the user-authorized guided-learning implementation pass.

## Current branch and status

GitHub `julian-passebecq/datapass-mosaic-vscode` is the working repository. GitLab project 86999630 had the same main commit, `60192bd59c50e6a04b513c5e72d8042ca47917fa`, when checked; no newer work was found there. Do not push this tranche to both services independently.

**PR #72**, branch `feat/guided-learning-workspace`, contains the new Learning layer. It is not yet a release or a main-branch merge. Read `handoff/LEARNING_WORKSPACE.md` and `docs/MOSAIC_LEARNING.md`. Consult the exact current CI run before treating it as qualified.

The 2026-09-26 plan, full package actuals and decisions are preserved byte-for-byte in `handoff/archive/PLAN-2026-09-26.md`. The original V1 pause/status is `handoff/V1-STATUS.md`; this newly authorized feature work supersedes the pause only for this tranche.

## What exists already - do not rebuild

V1, V2 light packages and governance remain. Native editors, Practice/Review/Interview, the free-form Mosaic surface, Projects, SQL dialects, SparkLab/Polars, Airflow, Cloud, BI, dbt Core, Terminal, Infra, Lakehouse and API labs keep their current owners. Version 0.2.0 was released before governance; the branch manifest stays 0.2.0 until a separately qualified release.

## Learning tranche

| Work | Status in PR #72 |
| --- | --- |
| Six paths / nineteen lessons, strict inert catalog | Implemented |
| Read / Watch / Try / Exercise / Explain / Compare | Implemented |
| Collapsible in-page rail, movable native Learning Path tree | Implemented |
| Native example files, unchanged-source highlights, existing runners | Implemented |
| Existing Practice grading and hints, no duplicate score | Implemented |
| Join/window/partition toy visualizations | Implemented, labelled illustrative |
| Existing runtime result/plan display, source freshness and comparison | Implemented |
| Notes, reading acknowledgements, resume and explicit export | Implemented |
| Local Node and renderer checks | Initial 25 Node and 15 renderer checks passed; renderer transport mocked |
| Existing four CI gates plus new packaged Learning journey | Qualification on the current PR head required |

The CI workflow is unchanged. New tests are appended to existing npm test scripts; existing checks are retained. No automatic deployment, release tag or main-branch merge is part of this pass.

## Follow-up order

First qualify the packaged user journey and retain all existing regression checks. Then improve runtime-fed visual diagrams and authoring on these same contracts. Keep arbitrary notebook execution, universal layout dragging, live Parquet X-Ray and telemetry export out of this tranche.

BI-3, the next versioned release, fuller Delta/Iceberg, Cloud dbt and other older roadmap items remain in the archived plan; they have not silently become completed work. Do not create a new Spark engine, grading engine, Hop bridge or Studio shell here.
