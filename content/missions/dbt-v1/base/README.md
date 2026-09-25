# shop: the analytics team's dbt project

The dbt project of a small outdoor retailer's analytics team, run with dbt Core and dbt-duckdb on the Datapass
catalog. The ingestion lands the shop's and the ERP's exports in a raw schema (`raw_schema` in `dbt_project.yml`);
the project cleans them in staging views and builds the marts.

- `models/staging/`: one view per landing table (`_sources.yml` declares them).
- `models/marts/fct_order_lines.sql`: one row per order line, with the order date, the customer and the product
  category.
- `tests/`: singular tests. Generic tests live next to the models in `_staging.yml` and `_marts.yml`.

Run it from this folder: `dbt build`. The dbt Lab generates the `datapass_missions` profile in
`.datapass/dbt/profiles.yml` (the local DuckDB catalog, target schema `dbt_dev`).
