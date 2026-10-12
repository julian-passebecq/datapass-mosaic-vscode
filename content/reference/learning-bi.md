# BI and dimensional modeling

Cheatsheet for the Learning path *BI, governance and performance*. The BI Lab runs warehouse SQL for real on the local
DuckDB catalog; its star model file uses Power BI's relationship vocabulary, but there is no Power BI or DAX engine.

## Star schema

| Piece | Rule |
|---|---|
| Grain | one sentence: "one row per order line". Declare it first. |
| Fact | foreign keys + measures at that grain |
| Dimension | one wide, denormalized table per entity, joined directly to the fact |
| Surrogate key | warehouse-owned integer key; an "unknown" member for missing references |
| Snowflake | a dimension split into sub-tables: more joins for the same answer |

## Measures

| Kind | Example | Rule |
|---|---|---|
| Additive | sales amount, quantity | sum over every dimension |
| Semi-additive | account balance, stock level | sum across accounts or stores, not over time (take last or average) |
| Non-additive | margin %, ratio | recompute from additive parts |

## History (slowly changing dimensions)

| Type | Behaviour |
|---|---|
| 1 | overwrite; no history |
| 2 | new row per version with `valid_from`, `valid_to`, `is_current`; facts keep the version's surrogate key |
| 3 | one "previous value" column |

Point-in-time join: `fact.date >= dim.valid_from AND fact.date < dim.valid_to`. Joining on the business key alone
multiplies rows.

## Fact table types

Transaction (one row per event) · periodic snapshot (state at each period end) · accumulating snapshot (one row per
process, milestone dates filled in) · factless (events or coverage with no measure).

## Semantic models (Power BI vocabulary)

- Relationships: one-to-many from dimension to fact; **single** cross-filter direction by default.
- Role-playing date: one active relationship, others inactive and activated per measure.
- Many-to-many through a bridge table.
- Storage modes: **Import** (compressed copy, scheduled refresh), **DirectQuery** (queries the source), **Direct Lake**
  (Fabric: reads Delta tables in OneLake).
