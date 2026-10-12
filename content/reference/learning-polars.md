# Polars cheatsheet

Reference for the Learning path "Polars DataFrames". Polars runs as real local Python: Datapass refuses it until you
enable trusted local Python for the workspace, and never falls back to a simulation. `display(lazy_frame)` collects a
LazyFrame and shows Polars' own plan from `LazyFrame.explain()`.

## Contexts and expressions

```python
import polars as pl

df.select(pl.col("customer_id"), (pl.col("amount") * 1.2).alias("gross"))   # only these columns
df.with_columns(pl.col("day").str.to_date())                                # add or replace columns
df.filter((pl.col("status") == "DONE") & pl.col("amount").is_not_null())
df.group_by("customer_id").agg(pl.len().alias("orders"), pl.col("amount").sum())
df.sort("amount", descending=True)
```

- Expressions in one context run in parallel on the input: use a second `with_columns` to reuse a new column.
- `pl.len()` counts rows; `pl.col(x).count()` counts non-null values.
- `group_by` does not keep order unless `maintain_order=True`.

## Conditions and nulls

| Need | Expression |
|---|---|
| CASE WHEN | `pl.when(cond).then(a).when(cond2).then(b).otherwise(c)` |
| Is null | `pl.col("x").is_null()` / `.is_not_null()` |
| Replace null | `pl.col("x").fill_null(0)`, `fill_null(strategy="forward")` |
| Null-safe equality | `pl.col("a").eq_missing(pl.col("b"))` |

A filter treats a null predicate as false.

## Namespaces instead of Python loops

- Text: `pl.col("name").str.to_lowercase()`, `.str.contains("x")`, `.str.split(",")`, `.str.to_date()`.
- Dates: `pl.col("ts").dt.date()`, `.dt.year()`, `.dt.truncate("1mo")`.
- Lists: `pl.col("tags").list.len()`, `.explode("tags")` on the frame.
- Avoid `map_elements(lambda ...)`: it runs Python per value and is invisible to the optimizer.

## Window expressions

```python
df.with_columns(
    pl.col("amount").sum().over("customer_id").alias("customer_total"),
    pl.col("amount").cum_sum().over("account", order_by="day").alias("running_total"),
)
```

## Lazy queries

```python
result = (
    pl.scan_parquet("lake/orders/*.parquet")      # or df.lazy()
    .filter(pl.col("status") == "DONE")
    .group_by("customer_id")
    .agg(pl.col("amount").sum().alias("revenue"))
)
print(result.explain())    # optimized plan, read from the bottom up
table = result.collect()   # run once, at the end
result.sink_parquet("out/revenue.parquet")   # streaming write for large results
```

- `scan_*` reads lazily; `read_*` loads now.
- The optimizer pushes filters into the scan (predicate pushdown) and reads only used columns (projection pushdown).
- A `collect()` in the middle splits the plan and loses those optimizations.

## Joins

| `how=` | Result |
|---|---|
| `"inner"` | matching pairs |
| `"left"` | every left row, nulls when unmatched |
| `"right"` | every right row |
| `"full"` | both sides, nulls when unmatched |
| `"semi"` | left rows with a match, once, left columns only |
| `"anti"` | left rows without a match |
| `"cross"` | every combination |

```python
customers.join(orders.filter(pl.col("status") == "COMPLETED"), on="customer_id", how="left")
customers.join(orders, left_on="customer_id", right_on="id", how="inner", validate="1:m")
```

- Null keys do not match unless `nulls_equal=True` (`join_nulls` in older versions).
- A clashing column from the right side gets the suffix `_right` (`suffix=` changes it).
- Filter the right frame before a left join; a filter on a right column afterwards drops the unmatched rows.
