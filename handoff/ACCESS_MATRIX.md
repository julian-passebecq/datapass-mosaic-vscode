# Access matrix

One row per capability. Source: CLAUDE.md truth model and docs/HANDOFF.md. "Runtime" means the local FastAPI process
(managed Python venv made by Setup runtime). "Trusted Python" is the explicit opt-in (manifest flag, per-machine modal,
Workspace Trust). Network is loopback at most; no cloud connection exists. "unverified" means not read in the code for this table.

| Capability | Python needed | Trusted Python | Runtime | Network | dbt tools | bash/pwsh | Workspace Trust | Files written |
|---|---|---|---|---|---|---|---|---|
| Learning: read lessons, notes, cheatsheets | no | no | no | none | no | no | not needed (Restricted Mode allows reading) | notes and acknowledgements in workspace state |
| Learning: run lesson examples | yes (SQL via runtime; Python/Polars examples via kernel) | Python/Polars examples only | yes | loopback | no | no | required (execution disabled in Restricted Mode) | example files in workspace |
| Learning: concept checks (quiz) | yes (runtime grades) | no | yes | loopback | no | no | unverified | `.datapass/progress.json` only for Practice passes |
| Learning: flashcard review | no | no | no | none | no | no | unverified | review state (not `.datapass/progress.json`) |
| Build: new blank workspace | yes (runtime) | no (stays off) | yes | loopback | no | no | unverified | `.datapass/project.json` with catalog.seed none |
| Build: new file, import dataset | no | no | import may use runtime | loopback | no | no | unverified | new file only; never overwrites |
| Mosaic exchange import / export | no | no | no | none | no | no | unverified | cells as native files (never run); export file with names and hashes |
| Mosaic SQL | yes | no | yes | loopback | no | no | unverified | `.datapass/mosaic.json`, `.datapass/data/` |
| Mosaic Python / Polars | yes | yes | yes | loopback | no | no | required | `.datapass/data/` |
| SQL dialects | yes | no | yes | loopback | no | no | unverified | none beyond Mosaic |
| Practice (SQL and dialects, quiz) | yes | no | yes | loopback | no | no | unverified | `.datapass/progress.json`, solution files |
| Practice Python / Polars / pytest | yes | yes | yes | loopback | no | no | required | solution files, `.datapass/progress.json` |
| Projects | yes | no | yes | loopback | no | no | unverified | `.datapass/progress.json`, run journal |
| Cloud Lab: pipelines view and run (simulated) | yes | no (notebooks run on SparkLab AST) | yes | loopback | no | no | unverified | `.datapass/data/` lab state |
| Cloud Lab: pipeline editing | no for editing; yes to run | no | only to run | loopback | no | no | unverified | the pipeline JSON in place; new and exported JSON |
| Cloud Lab: SQL pool, Databricks | yes | no | yes | loopback | no | no | unverified | `.datapass/data/` |
| BI Lab | yes | no | yes | loopback | no | no | unverified | warehouse scripts, `bi/model.json` |
| SparkLab | yes | Polars engine only | yes | loopback | no | no | Polars: required | `.datapass/data/` |
| Airflow Lab, Pipeline Lab | yes | no | yes | loopback | no | no | unverified | `.datapass/data/` |
| dbt Lab | yes (managed venv) | no | yes | loopback; tool install downloads packages on explicit action | yes (Install dbt tools) | terminal of the learner's shell | unverified | `.datapass/dbt/profiles.yml`, dbt `target/` |
| Terminal Lab | yes | no | yes | loopback | no | yes (bash, Git Bash, pwsh or Windows PowerShell) | unverified | `missions/<id>/`, attic copies in `.datapass/missions/attic/` |
| Infra Lab (13 missions) | yes | no | yes | loopback | no | no (Pseudoterminal, no process) | unverified | `<folder>/.infralab/world.json`, mission files |
| Lakehouse Lab | yes | Polars missions only | yes | loopback; Setup downloads ducklake and delta extensions once | no | no | Polars: required | `lakehouse/<id>/` |
| API Lab | yes | yes (ingest.py) | yes | loopback (own port) | no | no | required | `missions/<id>/ingest.py`, bronze tables |
| Runtime status bar, CodeLens, schemas, walkthrough | no | no | status only | loopback | no | no | unverified | none |
