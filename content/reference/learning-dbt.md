# dbt and loading patterns cheatsheet

Reference for the Learning lessons on dbt, idempotent loads and incremental loads. Two places in Datapass use dbt:
the **dbt Lab** runs real dbt Core and dbt-duckdb that you install explicitly and run in a VS Code terminal; the
**BI Lab** dbt tab and the `dbt-v1` Practice pack use the Datapass dbt emulation, labelled "not dbt Core".

## Project layout

```
models/staging/stg_orders.sql      -- one model per source table: rename, cast, clean
models/marts/fct_orders.sql        -- business models: joins, grain, measures
models/marts/_marts.yml            -- descriptions and data tests
tests/assert_order_totals.sql      -- singular tests
snapshots/products_snapshot.sql    -- SCD type 2 history
```

## Models

```sql
-- models/marts/fct_orders.sql
{{ config(materialized='table') }}
select o.order_id, o.customer_id, sum(l.amount) as amount
from {{ ref('stg_orders') }} as o
join {{ ref('stg_order_lines') }} as l using (order_id)
group by o.order_id, o.customer_id
```

- `ref('model')` resolves the relation and records the dependency (the DAG).
- `source('shop', 'orders')` points at a declared raw table and enables freshness checks.
- Materializations: `view`, `table`, `incremental`, `ephemeral`.

## Data tests

```yaml
models:
  - name: fct_orders
    columns:
      - name: order_id
        data_tests: [unique, not_null]
      - name: customer_id
        data_tests:
          - not_null
          - relationships:
              arguments: {to: ref('dim_customers'), field: customer_id}
      - name: status
        data_tests:
          - accepted_values:
              arguments: {values: ['placed', 'shipped', 'returned']}
              config: {severity: warn, where: "order_date >= '2026-01-01'"}
```

- A test is a query returning the failing rows; zero rows means pass.
- `relationships` checks only non-null child values: add `not_null` too.
- Older projects write `tests:` instead of `data_tests:` and put `to`, `field` and `values` directly under the test
  name; check the syntax your dbt version expects.
- `severity: warn`, `warn_if: ">10"`, `error_if: ">100"`; `where:` narrows the rows tested.
- Singular test: a `.sql` file in `tests/` selecting violations.
- `dbt build` runs models, tests, seeds and snapshots in DAG order and skips the children of a failed test.

## Incremental models

```sql
{{ config(materialized='incremental', unique_key='order_id') }}
select * from {{ ref('stg_orders') }}
{% if is_incremental() %}
where updated_at > (select coalesce(max(updated_at), '1900-01-01') from {{ this }})
{% endif %}
```

- `is_incremental()` is true when the table exists and the run is not `--full-refresh`.
- Without `unique_key`, new rows are appended; with it, rows with an existing key are replaced (idempotent).
- A `ref()` used only inside `is_incremental()` must be declared (`-- depends_on: {{ ref('x') }}`).

## Snapshots (SCD type 2)

- `strategy: timestamp` with `updated_at`, or `strategy: check` with `check_cols`.
- dbt adds `dbt_valid_from`, `dbt_valid_to` (NULL while current), `dbt_scd_id`, `dbt_updated_at`.
- `invalidate_hard_deletes` (or `hard_deletes: invalidate` in recent versions) closes rows deleted at the source.

## Idempotent and incremental loading

| Pattern | Idempotent? |
|---|---|
| `INSERT` every batch | no: reruns duplicate rows |
| Upsert / `MERGE` on a unique key | yes |
| Delete-then-insert or overwrite one partition | yes |
| Insert keys not already present (anti join) | yes |

```sql
-- Next batch with a stored watermark (all rows on the first run).
SELECT s.*
FROM source_rows s
WHERE NOT EXISTS (SELECT 1 FROM watermark w WHERE w.table_name = 'source_rows')
   OR s.updated_at > (SELECT loaded_until FROM watermark w WHERE w.table_name = 'source_rows');
```

- Advance the watermark only after the load commits.
- Reread a lookback window for late rows; the upsert makes the overlap harmless.
- Hard deletes need soft deletes, CDC or a periodic full comparison.
- Backfill: rerun with explicit date bounds instead of the stored watermark.
