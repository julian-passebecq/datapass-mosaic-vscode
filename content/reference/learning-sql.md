# SQL cheatsheet

Reference for the Learning path "SQL and data semantics". Every example runs on DuckDB, the local engine of Mosaic.

## Logical order of a query

`FROM` and joins → `WHERE` → `GROUP BY` → `HAVING` → window functions and `SELECT` → `QUALIFY` → `DISTINCT` →
`ORDER BY` → `LIMIT`. A step can only use what earlier steps produced: `WHERE` cannot see a window function or an
alias from `SELECT`.

## Joins

| Join | Keeps |
|---|---|
| `INNER JOIN` | matching pairs only |
| `LEFT JOIN` | every left row; unmatched ones get NULL on the right |
| `FULL OUTER JOIN` | matching pairs plus unmatched rows of both sides |
| `WHERE EXISTS (...)` (semi join) | left rows with at least one match, once each |
| `WHERE NOT EXISTS (...)` (anti join) | left rows with no match |

- Duplicate keys multiply rows: 2 matches on the left and 3 on the right give 6 rows.
- `NULL = NULL` is unknown: NULL keys never match with `=`. Use `IS NOT DISTINCT FROM` when they must.
- In a `LEFT JOIN`, a condition on the right table belongs in `ON`. In `WHERE` it drops the unmatched rows and turns
  the join into an inner join.

## Aggregation and grain

```sql
SELECT customer_id,
       COUNT(*) AS orders,                                  -- rows
       COUNT(coupon) AS with_coupon,                        -- non-NULL values
       SUM(amount) FILTER (WHERE status = 'DONE') AS done   -- conditional
FROM orders
GROUP BY customer_id
HAVING COUNT(*) > 1;
```

- `WHERE` filters rows before grouping, `HAVING` filters groups after.
- `SUM` over no row is NULL; `COUNT` is 0. `AVG` ignores NULLs.
- The `GROUP BY` columns are the key (the grain) of the result: "one row per customer".
- Fan-out: aggregate the many side to the key of the one side before joining, or amounts are counted once per match.
- `ROLLUP(a, b)`: detail, subtotal per `a`, grand total. `CUBE(a, b)`: every combination. `GROUPING SETS ((a), (b))`:
  the listed groupings. `GROUPING(b) = 1` marks a rolled-up row.

## CTEs and subqueries

```sql
WITH per_customer AS (
  SELECT customer_id, AVG(amount) AS avg_amount FROM orders GROUP BY customer_id
)
SELECT * FROM per_customer
WHERE avg_amount > (SELECT AVG(amount) FROM orders);   -- scalar subquery
```

- A scalar subquery must return at most one row.
- `x NOT IN (SELECT y ...)` returns nothing when `y` contains a NULL. Prefer `NOT EXISTS`.

## Set operations

| Operation | Result |
|---|---|
| `UNION ALL` | every row of both inputs |
| `UNION` | distinct rows of both inputs |
| `INTERSECT` | distinct rows present in both |
| `EXCEPT` | distinct rows of the first input missing from the second |

Columns match by position; names come from the first `SELECT`. DuckDB adds `UNION BY NAME`. Set operations treat two
NULLs as equal.

## Window functions

```sql
SELECT *,
       SUM(amount) OVER (PARTITION BY account ORDER BY day
                         ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running_total,
       ROW_NUMBER() OVER (PARTITION BY account ORDER BY day DESC) AS recency
FROM movements
QUALIFY recency <= 3;
```

- With `ORDER BY` and no frame, the default frame is `RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW`: rows that
  tie on the order value share a total. Use `ROWS` and a tie-breaker for a row-by-row running total.
- On 10, 10, 8: `ROW_NUMBER` 1, 2, 3; `RANK` 1, 1, 3; `DENSE_RANK` 1, 1, 2.
- `LAG(x)` / `LEAD(x)` read the previous / next row of the partition.
- Latest row per key: `QUALIFY ROW_NUMBER() OVER (PARTITION BY key ORDER BY updated_at DESC) = 1`.

## NULL in one table

| Expression | Result |
|---|---|
| `NULL = NULL` | NULL |
| `NULL IS NOT DISTINCT FROM NULL` | true |
| `NULL AND false` | false |
| `NULL OR true` | true |
| `COALESCE(NULL, 0)` | 0 |
