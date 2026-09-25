# bilab: the BI Lab warehouse

The BI Lab teaches data warehousing on the local DuckDB catalog: dimensional modeling (facts, dimensions,
grain, surrogate keys, slowly changing dimensions), SQL lineage and star models. It has no pipelines and
never connects to Power BI, Fabric or any cloud.

## What is real

| Piece | Truth |
| --- | --- |
| Warehouse SQL (`script.py`) | Real. Each statement runs on DuckDB through the catalog's SQL contract (CREATE TABLE/VIEW, INSERT, UPDATE, DELETE, MERGE, DROP, SELECT; no file or network access). A script stops at its first error. |
| Column lineage (`lineage.py`) | A real static analysis of the SQL text with sqlglot (DuckDB dialect). Nothing is executed for it. |
| Star model checks (`model.py`) | Real queries on the tables. The model file is Datapass's own format, not a Power BI file. |

## Lineage

For every column a statement writes (`CREATE TABLE/VIEW ... AS`, `INSERT ... SELECT`, `UPDATE ... SET`,
`MERGE`), the analysis resolves the columns its value is computed from through CTEs, derived tables,
scalar subqueries, `UNION` branches (by position) and window functions:

- `sources`: columns of the tables the statement reads;
- `origins`: the same, followed back through every table the analyzed scripts build, down to tables no
  analyzed statement builds (or to typed-in and generated values, which are their own origin);
- `transform`: `copy`, `rename`, `expression`, `aggregate`, `window`, `constant` or `generated` (a table
  function such as `generate_series`).

Columns used in `WHERE`, `JOIN ... ON`/`USING`, `GROUP BY`, `HAVING`, `QUALIFY` and a `MERGE`'s conditions
are row influence: they do not flow into a value, but they decide which rows exist. `impact(table, column)`
returns what a change reaches: the column values computed from it (`value`) and the tables whose rows it
decides (`rows`); a table whose rows change reaches everything that reads it.

Limits: `SELECT *` over a table whose columns are not known yet is reported as an issue; Jinja (dbt models)
is not rendered here; a statement sqlglot cannot parse is reported and skipped.

## Star model file

```json
{
  "name": "retail_star",
  "tables": [
    {"name": "gold.fct_sales", "role": "fact", "grain": ["order_id", "line_number"]},
    {"name": "gold.dim_customer", "role": "dimension", "key": "customer_key", "business_key": ["customer_id"],
     "unknown_member": -1,
     "scd": {"type": 2, "valid_from": "valid_from", "valid_to": "valid_to", "current_flag": "is_current"}}
  ],
  "relationships": [
    {"from": "gold.fct_sales.customer_key", "to": "gold.dim_customer.customer_key",
     "cardinality": "many-to-one", "cross_filter": "single", "active": true}
  ]
}
```

Roles are `fact`, `dimension` and `bridge`. Relationship settings use Power BI's vocabulary (cardinality,
cross-filter direction `single`/`both`, active) because those are a semantic model's decisions. Type 2
validity assumes an exclusive `valid_to` and an open end of `9999-12-31` (`open_end`, or `null`).

Checks (status `pass`, `fail`, or `warn` for allowed designs that are usually a smell):

- tables: `table_exists`, `columns_exist`;
- dimensions: `key_unique`, `key_not_null`, `unknown_member`;
- facts and bridges: `grain_unique`;
- type 2 dimensions: `scd2_valid_range`, `scd2_one_current`, `scd2_current_flag`, `scd2_no_overlap`,
  `scd2_no_gap` (the unknown member is left out);
- relationships: `relationship_columns`, `one_side_unique`, `no_null_keys`, `no_orphans`,
  `fact_to_dimension` (fact-to-fact warns), `single_active_path`, `cross_filter` (both directions warns
  unless a bridge is involved), `many_to_many` (warns: prefer a bridge).

## Practice

`exercise.py` is the scenario model of the `warehouse` (a SQL script) and `bi-model` (a model file)
exercise languages, graded by `datapass_runtime/warehouse_grading.py` on an isolated catalog per check.
See `docs/EXERCISE_AUTHORING.md`.
