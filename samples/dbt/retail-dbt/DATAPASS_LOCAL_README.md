# Local dbt project

Review SQL, macros and project hooks before running. No code was run by the exporter.
This is an isolated teaching project, not an automatic clone of the Datapass workspace catalog.

Install dbt-duckdb in your chosen virtual environment, then:

```sh
dbt build --project-dir . --profiles-dir . --profile datapass_retail
```

Import `target/manifest.json` and `target/run_results.json` from the SAME invocation into Datapass. A later `dbt docs generate` can replace the manifest invocation ID; capture matching artifacts first.
