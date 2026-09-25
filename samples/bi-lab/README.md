# BI Lab

A small data warehouse for an outdoor retailer, built on the local DuckDB catalog.

- `warehouse/*.sql` run in name order (**Build warehouse** in the BI Lab):
  - `00_sources.sql` creates the CRM, ERP and shop source tables (rerunning it resets them);
  - `01` to `04` build the dimensions: a date dimension (with the unknown date -1 and a July fiscal year), a type 2
    customer dimension, the product hierarchy flattened into one table, and a junk dimension of order flags;
  - `05` and `06` build the facts: sales at the order-line grain (point-in-time customer keys, role-playing dates,
    unknown members instead of NULL keys) and returns sharing the same conformed dimensions.
- `model.json` is the star model: which tables are facts and dimensions, their keys, grain and SCD type, and the
  relationships with their cardinality, cross-filter direction and active flag. The BI Lab checks it on the data.

Every statement really runs on DuckDB. The Lineage tab traces each column back to its source columns by
analysing the SQL text (sqlglot); nothing connects to Power BI or a cloud.

Try changing a script and building again: join `dim_customer` on `is_current` in `05_fct_sales.sql`, or make the
ship date relationship active in `model.json`, and see what the checks and the lineage say.
