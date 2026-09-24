# Exercise authoring

Practice exercises live in versioned packs under `content/exercise-packs/<pack>/`. The runtime registry (`runtime/datapass_runtime/exercise_packs.py`) validates every pack at import; the extension catalog (`src/exerciseCatalog.ts`) reads the same files for the Practice UI.

## Pack formats

- **Per-language pack**: `manifest.json`, `exercises.json` (public definitions), `grading.server.json` (reference solution + fixtures per exercise id). Example: `sql-lab-v1`, `internal-demo`.
- **Semantic pack**: `manifest.json`, `scenarios.json`, `grading.server.json`. One scenario and one fixture set expand into several language variants (`sql`, `python`, `polars`, `sparklab`, `dbt`) registered as `<scenario>-<language>`. Example: `unified-retail-v1`.

Every exercise needs exactly one visible, and any number of hidden and edge fixtures; the public `visible_checks` / `hidden_check_refs` / `edge_check_refs` must match the private fixture ids. **Run visible** grades only visible fixtures; **Submit** grades all of them. Grading compares complete result rows (`validation`: exact schema, bag semantics, numeric tolerance, optional `ordered`); truncated results never pass.

## Fixture tables

- Single table: fixtures use `input_rows`; the submission reads the table `input`. This works for every language.
- Named tables (SQL only): declare one `data_context` entry per table (`name`, `columns`, `sample_rows`) and give every fixture `"input_rows": []` plus `"tables": {"<name>": [rows...]}` with exactly the declared tables. The grader builds one CTE per table. Names are lowercase identifiers and cannot be a catalog layer (`source`, `bronze`, ...). Other languages reject named tables rather than approximating them.
- Column types are applied with `CAST`, so dates, decimals and empty fixtures stay typed. Allowed: `INTEGER`, `BIGINT`, `DOUBLE`, `VARCHAR`, `BOOLEAN`, `DATE`, `TIMESTAMP`, `DECIMAL(p,s)`. Write dates as `YYYY-MM-DD` strings; results serialize dates the same way.
- At most 200 rows per table and per expected result.

## Quality gate

`python scripts/exercise_packs_smoke.py` (CI runtime job) grades every installed exercise through the real worker:

1. the reference solution must pass a full submission;
2. the starter must not pass;
3. each **mutant** in `MUTANTS` must run successfully and still fail. A mutant is the plausible wrong answer the lesson is about (INNER instead of LEFT JOIN, RANK instead of DENSE_RANK, a filter in WHERE instead of ON, ...). If a mutant passes, the hidden/edge fixtures do not discriminate the mistake: add a fixture that does.

When adding an exercise: design the hidden and edge fixtures around the pitfall, compute expected rows by running the reference solution, **review every expected row by hand**, then add at least one mutant.

## Provenance

Record `origin` (`authored` or `migrated`) and a `provenance.source`. `sql-lab-v1` adapts the Datapass `leetcodedataeng` SQL lab (T-SQL rewritten for DuckDB) with newly authored fixtures. Do not import third-party question corpora.

## Known limitation

`grading.server.json` ships inside the VSIX, so a determined learner can read reference solutions and hidden fixtures. Grading integrity is a teaching aid, not an exam control.
