# The BI Lab warehouse, the dbt way

The same star as `bi/warehouse/*.sql`, organised as dbt teams usually organise a project:

- `models/staging/`: one view per source table (renamed, typed, cleaned), in `silver`. `_sources.yml` declares the
  raw tables of `bi/warehouse/00_sources.sql` and tests their keys.
- `models/intermediate/`: `int_customer_versions`, an ephemeral model (inlined as a CTE) that turns the CRM change
  log into type 2 versions.
- `models/marts/`: the star in the `warehouse` layer: `dim_date`, `dim_customer` (type 2, unknown member -1),
  `dim_product`, `fct_sales` (incremental on order_id + line_number, with the `-- depends_on:` hint its incremental
  filter needs) and `fct_returns`. `_marts.yml` holds the tests: keys, accepted values and the relationships that a
  warehouse does not enforce.
- `snapshots/snap_erp_products.sql`: the history of product prices from the first run on (check strategy).
- `tests/`: a singular test; `macros/`: `generate_schema_name` (custom schemas used as is) and `date_key`.

## In the BI Lab

Build the warehouse first (it loads the sources), then open the **dbt** tab and run `dbt build`. The Datapass dbt
emulation renders the Jinja in a sandbox and runs the SQL on the local catalog; it follows dbt Core and dbt-duckdb
for a documented subset and was checked against them, but it is not dbt Core.

## With real dbt Core

The project also runs with dbt Core and dbt-duckdb. Stop the Datapass runtime first: DuckDB lets one process at a
time write the catalog file. Then, from this folder:

```bash
dbt build --profiles-dir .
```

with a `profiles.yml` next to `dbt_project.yml`:

```yaml
datapass_bi:
  target: dev
  outputs:
    dev:
      type: duckdb
      path: '../../.datapass/data/workspace.duckdb'
      schema: silver
      threads: 1
```
