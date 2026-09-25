"""Generate content/exercise-packs/sqlpool-v1 from authored specs.

Expected rows are computed by running each reference script through the SQL pool
grader (`datapass_runtime.sqlpool_grading.run_fixture`); review them by hand. The
generator also checks that starters and mutants run and fail (a starter may fail to
run only when listed in STARTER_ERRORS_BY_DESIGN). Run from the repository root with
PYTHONPATH=runtime.
"""
from __future__ import annotations

import copy
import json
import textwrap
from datetime import date, timedelta
from pathlib import Path

from pack_quality import write_mutants

ROOT = Path.cwd()
PACK = ROOT / "content" / "exercise-packs" / "sqlpool-v1"
EXERCISES: list[dict] = []
STARTER_ERRORS_BY_DESIGN = {"sp-fabric-port"}


def code(text: str) -> str:
    return textwrap.dedent(text).strip("\n") + "\n"


def exercise(**spec):
    spec.setdefault("flavor", "synapse")
    EXERCISES.append(spec)


def table(name, rows, represented=None, design=None, types=None, columns=None):
    entry = {"name": name, "rows": rows}
    if columns:
        entry["columns"] = columns
    if types:
        entry["types"] = types
    if represented:
        entry["represented_rows"] = represented
    if design:
        entry["design"] = design
    return entry


FACT_TYPES = {"order_id": "INTEGER", "store_id": "VARCHAR", "amount": "DOUBLE"}


def sales(n=160):
    return [{"order_id": i, "store_id": f"S{(i % 8) + 1:02d}", "amount": float(((i % 9) + 1) * 10)} for i in range(1, n + 1)]


STORES = [{"store_id": f"S{i:02d}", "store_name": f"Store {i}", "region": ["North", "South", "East", "West"][i % 4]}
          for i in range(1, 9)]

# 1 ------------------------------------------------------------------------------------------------
REPORT = ("SELECT s.region, SUM(f.amount) AS revenue FROM dbo.fact_sales AS f "
          "JOIN dbo.dim_store AS s ON f.store_id = s.store_id GROUP BY s.region")


def dim_store(design, where=""):
    return code(f"""
        -- dim_store has 8 rows; the sales report joins every sale (1.2 billion) to its store.
        CREATE TABLE dbo.dim_store
        WITH ( {design} )
        AS
        SELECT store_id, store_name, region
        FROM bronze.stores{where};
    """)


def replicate_scenario(stores, outcome, **extra):
    return {"tables": [table("bronze.stores", stores),
                       table("dbo.fact_sales", sales(), 1.2e9, "DISTRIBUTION = HASH(order_id), CLUSTERED COLUMNSTORE INDEX",
                             FACT_TYPES)],
            "query": REPORT, "outcome": outcome, **extra}


exercise(
    id="sp-replicate-dimension", title="Replicate a small dimension", difficulty="easy",
    topics=["distribution", "replicated-tables", "data-movement"],
    prompt=("dbo.fact_sales (1.2 billion rows) is hash distributed on order_id. The revenue-by-region report joins it "
            "to dbo.dim_store, which you create from bronze.stores (8 stores). Choose dim_store's distribution so the "
            "join itself needs no data movement: today every run broadcasts the stores."),
    sections=[("Graded", "The data movement of the report query (SELECT s.region, SUM(f.amount) ... JOIN dbo.dim_store "
                         "... GROUP BY s.region), the distribution of dbo.dim_store, and the report's rows.")],
    starter=dim_store("DISTRIBUTION = ROUND_ROBIN, CLUSTERED COLUMNSTORE INDEX"),
    solution=dim_store("DISTRIBUTION = REPLICATE, CLUSTERED INDEX (store_id)"),
    fixtures=[
        ("report-movement", "visible", replicate_scenario(STORES, "movement")),
        ("dim-design", "hidden", replicate_scenario(STORES, "designs", only=["dbo.dim_store"],
                                                    columns=["table", "distribution"])),
        ("report-rows", "edge", replicate_scenario(STORES, "result")),
    ],
    mutants=[dim_store("DISTRIBUTION = HASH(store_id), CLUSTERED COLUMNSTORE INDEX"),
             dim_store("DISTRIBUTION = REPLICATE, CLUSTERED INDEX (store_id)", "\nWHERE store_id <> 'S08'")],
    hints=["A replicated table keeps a full copy on every compute node, so any distribution can join to it locally.",
           "The GROUP BY on region still shuffles: the fact is distributed on order_id. Only the join's movement goes away."],
    explanation=("DISTRIBUTION = REPLICATE copies the 8 stores to every compute node, so the join runs inside each "
                 "distribution. A round-robin or HASH(store_id) dimension has to be broadcast on every run, because the "
                 "fact is distributed on order_id. The aggregation still shuffles on region; that is a separate step."),
    follow_ups=["When does a replicated table stop being a good idea? Think about size (the guidance says under 2 GB) "
                "and how often it changes."],
)

# 2 ------------------------------------------------------------------------------------------------
RETURNS = [{"return_id": 1000 + i, "order_id": i * 4, "refund_amount": float(5 * (i % 6 + 1))} for i in range(1, 41)]
RETURNS_TYPES = {"return_id": "INTEGER", "order_id": "INTEGER", "refund_amount": "DOUBLE"}
JOIN_QUERY = ("SELECT f.order_id, SUM(r.refund_amount) AS refunded FROM dbo.fact_sales AS f "
              "JOIN dbo.fact_returns AS r ON f.order_id = r.order_id GROUP BY f.order_id")


def colocate_scenario(outcome, returns=RETURNS, **extra):
    return {"tables": [table("dbo.fact_sales", sales(), 1.2e9, "DISTRIBUTION = HASH(order_id), CLUSTERED COLUMNSTORE INDEX",
                             FACT_TYPES),
                       table("dbo.fact_returns", returns, 3e8, "DISTRIBUTION = ROUND_ROBIN, CLUSTERED COLUMNSTORE INDEX",
                             RETURNS_TYPES)],
            "query": JOIN_QUERY, "outcome": outcome, **extra}


def colocate(key="order_id", select="*", swap=True, drop=True):
    script = f"""
        -- dbo.fact_returns (300 million rows) is ROUND_ROBIN: the join to dbo.fact_sales shuffles it on every run.
        CREATE TABLE dbo.fact_returns_new
        WITH ( DISTRIBUTION = HASH({key}), CLUSTERED COLUMNSTORE INDEX )
        AS
        SELECT {select}
        FROM dbo.fact_returns;
    """
    if swap:
        script += """
        RENAME OBJECT dbo.fact_returns TO fact_returns_old;
        RENAME OBJECT dbo.fact_returns_new TO fact_returns;
        """
    if drop:
        script += """
        DROP TABLE dbo.fact_returns_old;
        """
    return code(script)


exercise(
    id="sp-colocate-fact-join", title="Co-locate two fact tables on their join key", difficulty="medium",
    topics=["distribution", "ctas", "data-movement"],
    prompt=("dbo.fact_sales is hash distributed on order_id; dbo.fact_returns is ROUND_ROBIN, so joining them on order_id "
            "shuffles 300 million returns on every run. Rebuild dbo.fact_returns with CTAS so the join and its GROUP BY "
            "f.order_id need no data movement, swap the names with RENAME OBJECT so it is still called dbo.fact_returns, "
            "and drop the old table."),
    sections=[("Graded", "The data movement of the join query, the distribution of dbo.fact_returns, whether the rows are "
                         "all still there, and that no old copy is left behind.")],
    starter=colocate("order_id", swap=False, drop=False).replace("HASH(order_id)", "ROUND_ROBIN"),
    solution=colocate(),
    fixtures=[
        ("join-movement", "visible", colocate_scenario("movement")),
        ("returns-design", "hidden", colocate_scenario("designs", only=["dbo.fact_returns"],
                                                       columns=["table", "distribution", "distribution_columns"])),
        ("no-leftover", "hidden", colocate_scenario(
            "result", query="SELECT COUNT(*) AS leftover FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME LIKE 'fact_returns_%'")),
        ("rows-kept", "edge", colocate_scenario(
            "result", query="SELECT COUNT(*) AS returns, SUM(refund_amount) AS refunded FROM dbo.fact_returns")),
    ],
    mutants=[colocate("return_id"), colocate(select="return_id, CAST(order_id AS BIGINT) AS order_id, refund_amount"),
             colocate(drop=False)],
    hints=["You can't change a table's distribution in place: CTAS a new table, then swap names.",
           "Both sides of the join must be hash distributed on the join column, with the same data type."],
    explanation=("CTAS with DISTRIBUTION = HASH(order_id) puts every return on the same distribution as its sale, so the "
                 "join runs locally, and so does GROUP BY f.order_id. Two RENAME OBJECT statements swap the names as a "
                 "metadata operation. Changing order_id's type to BIGINT would break the alignment again: the data "
                 "types of the join columns must match."),
    follow_ups=["Why re-create statistics after a CTAS swap in a real pool?"],
)

# 3 ------------------------------------------------------------------------------------------------
def events(n=180):
    rows = []
    for i in range(1, n + 1):
        if i % 20 in (1, 2, 3, 4, 5, 6, 7):
            customer = "C000"  # a bot account: 35% of the events
        elif i % 10 == 9:
            customer = None
        else:
            customer = f"C{i:03d}"
        rows.append({"event_id": i, "customer_id": customer,
                     "event_date": (date(2026, 3, 1) + timedelta(days=i % 10)).isoformat(),
                     "device": ["web", "ios", "android"][i % 3]})
    return rows


EVENT_TYPES = {"event_id": "INTEGER", "customer_id": "VARCHAR", "event_date": "DATE", "device": "VARCHAR"}


def skew_scenario(outcome, **extra):
    return {"tables": [table("bronze.web_events", events(), 4.5e9, types=EVENT_TYPES)], "outcome": outcome, **extra}


def events_table(key):
    return code(f"""
        -- 4.5 billion events a year. Analysts filter by event_date and join to customers, but a bot account
        -- (C000) produces 35% of the events and 10% have no customer at all.
        CREATE TABLE dbo.fact_web_events
        WITH ( DISTRIBUTION = HASH({key}), CLUSTERED COLUMNSTORE INDEX )
        AS
        SELECT event_id, customer_id, event_date, device
        FROM bronze.web_events;
    """)


exercise(
    id="sp-skew-free-key", title="Choose a distribution column without skew", difficulty="medium",
    topics=["distribution", "data-skew"],
    prompt=("Create dbo.fact_web_events from bronze.web_events, hash distributed on a column that spreads the rows "
            "evenly over the 60 distributions: less than 10% difference between the fullest and the emptiest one. A bot "
            "account makes 35% of the events, 10% of the events have no customer, and there are only a few days and "
            "three devices."),
    sections=[("Graded", "The distribution of dbo.fact_web_events: HASH, and whether its skew is 10% or more; its "
                         "distribution column; and its row count."),
              ("The lab's skew model", "Every key value that repeats and holds at least 1% of the rows is placed on a "
               "distribution by a stable hash; NULL keys all land on one distribution; values seen once and rarer values "
               "spread evenly, since each stands for many distinct values at scale. Skew is (max - min) / max rows per "
               "distribution, the check the Synapse guidance uses.")],
    starter=events_table("customer_id"), solution=events_table("event_id"),
    fixtures=[
        ("skew", "visible", skew_scenario("distribution", only=["dbo.fact_web_events"],
                                          columns=["table", "distribution", "skew_over_10pct"])),
        ("key", "hidden", skew_scenario("designs", only=["dbo.fact_web_events"],
                                        columns=["table", "distribution", "distribution_columns"])),
        ("rows", "edge", skew_scenario("result", query="SELECT COUNT(*) AS events FROM dbo.fact_web_events")),
    ],
    mutants=[events_table("event_date"), events_table("device")],
    hints=["All rows with the same key value land on the same distribution, and so do all NULLs.",
           "A date column concentrates each day on one distribution, and few distinct values leave distributions empty."],
    explanation=("Only a column with many distinct values and no NULLs spreads evenly: event_id. customer_id puts the "
                 "bot's 35% and every NULL on single distributions; event_date and device have too few values, so most "
                 "distributions stay empty. Queries that filter on one date would also run on a single distribution."),
    follow_ups=["When would you accept some skew to avoid data movement on a frequent join?"],
)

# 4 ------------------------------------------------------------------------------------------------
RAW = [{"order_id": i, "payload": f"line {i}", "loaded_at": f"2026-03-05 0{i % 10}:00:00"} for i in range(1, 61)]


def staging(options):
    return code(f"""
        -- dbo.stg_orders is emptied and reloaded every night, then read once by the transformation.
        CREATE TABLE dbo.stg_orders
        WITH ( {options} )
        AS
        SELECT order_id, payload, loaded_at
        FROM bronze.orders_raw;
    """)


def staging_scenario(outcome, rows=RAW, **extra):
    return {"tables": [table("bronze.orders_raw", rows, types={"order_id": "INTEGER", "payload": "VARCHAR",
                                                                  "loaded_at": "VARCHAR"})],
            "outcome": outcome, **extra}


exercise(
    id="sp-staging-heap", title="Design a staging table for fast loads", difficulty="easy",
    topics=["indexes", "staging", "distribution"],
    prompt=("Create the staging table dbo.stg_orders from bronze.orders_raw. It is emptied and reloaded every night and "
            "read once by the next step, which joins nothing on it. Use the table design the Synapse guidance "
            "recommends for such staging tables."),
    sections=[("Graded", "The distribution and index of dbo.stg_orders, and that it holds every row.")],
    starter=staging("DISTRIBUTION = HASH(order_id)"), solution=staging("DISTRIBUTION = ROUND_ROBIN, HEAP"),
    fixtures=[
        ("design", "visible", staging_scenario("designs", only=["dbo.stg_orders"],
                                               columns=["table", "distribution", "index"])),
        ("rows", "hidden", staging_scenario("result", query="SELECT COUNT(*) AS loaded FROM dbo.stg_orders")),
        ("other-night", "edge", staging_scenario("result", rows=RAW[:17],
                                                 query="SELECT COUNT(*) AS loaded, MAX(order_id) AS last FROM dbo.stg_orders")),
    ],
    mutants=[staging("DISTRIBUTION = ROUND_ROBIN"), staging("DISTRIBUTION = HASH(order_id), HEAP")],
    hints=["Leaving out the index option gives a clustered columnstore index, the default.",
           "Round-robin distribution needs no key and spreads rows evenly; a heap is the fastest structure to load."],
    explanation=("ROUND_ROBIN avoids hashing every row on load, and HEAP skips building columnstore rowgroups. That is "
                 "the recommended combination for a staging table that is reloaded and read once. The default (a "
                 "clustered columnstore index) pays off for large tables that are queried many times."),
    follow_ups=["Which design would you give the final fact table this staging data feeds?"],
)

# 5 ------------------------------------------------------------------------------------------------
Q1_DAYS = ["2026-01-01", "2026-01-15", "2026-01-31", "2026-02-01", "2026-02-01", "2026-02-14", "2026-02-28",
           "2026-03-01", "2026-03-01", "2026-03-01", "2026-03-20", "2026-03-31"]
Q1_DAYS_EDGE = ["2026-01-31", "2026-01-31", "2026-02-01", "2026-02-28", "2026-03-01", "2026-03-02"]


def q1_rows(days):
    return [{"order_id": i + 1, "order_date": d, "amount": float(10 * (i + 1))} for i, d in enumerate(days)]


def q1_table(partition):
    return code(f"""
        CREATE TABLE dbo.fact_sales_q1
        WITH
        (   DISTRIBUTION = HASH(order_id)
        ,   CLUSTERED COLUMNSTORE INDEX
        ,   PARTITION ( {partition} )
        )
        AS
        SELECT order_id, order_date, amount
        FROM bronze.sales_q1;
    """)


def q1_scenario(days):
    return {"tables": [table("bronze.sales_q1", q1_rows(days), types={"order_id": "INTEGER", "order_date": "DATE",
                                                                        "amount": "DOUBLE"})],
            "outcome": "partitions", "only": ["dbo.fact_sales_q1"], "columns": ["table", "partition_number", "rows"]}


exercise(
    id="sp-partition-range-right", title="Monthly partitions: RANGE LEFT or RIGHT", difficulty="medium",
    topics=["partitioning", "boundaries"],
    prompt=("Create dbo.fact_sales_q1 partitioned on order_date with the boundary values '2026-02-01' and '2026-03-01', "
            "so January, February and March each get their own partition, and the 1st of February and the 1st of March "
            "belong to their own month."),
    sections=[("Graded", "The number of rows in each partition, for Q1 orders that include the first and last day of "
                         "each month.")],
    starter=q1_table("order_date RANGE FOR VALUES ('2026-02-01', '2026-03-01')"),
    solution=q1_table("order_date RANGE RIGHT FOR VALUES ('2026-02-01', '2026-03-01')"),
    fixtures=[
        ("q1-orders", "visible", q1_scenario(Q1_DAYS)),
        ("month-ends", "hidden", q1_scenario(Q1_DAYS_EDGE)),
        ("only-boundaries", "edge", q1_scenario(["2026-02-01", "2026-03-01", "2026-03-01"])),
    ],
    mutants=[q1_table("order_date RANGE LEFT FOR VALUES ('2026-02-01', '2026-03-01')"),
             q1_table("order_date RANGE RIGHT FOR VALUES ('2026-01-31', '2026-02-28')")],
    hints=["Two boundaries make three partitions; the question is which side each boundary value falls on.",
           "RANGE is LEFT by default: the boundary value belongs to the partition on its left."],
    explanation=("With RANGE RIGHT, each boundary value starts the partition on its right: 2026-02-01 is the first day "
                 "of partition 2. With RANGE LEFT (the default), 2026-02-01 would be the last value of the January "
                 "partition. For date boundaries on the first day of a month, RANGE RIGHT is what you want."),
    follow_ups=["Which boundaries would give the same partitions with RANGE LEFT?"],
)

# 6 ------------------------------------------------------------------------------------------------
MONTHLY_2026 = ", ".join(f"'2026-{m:02d}-01'" for m in range(2, 13))


def year_rows(extra_days=()):
    rows, i = [], 0
    for month in range(1, 13):
        for day in (1, 10, 20, 28):
            i += 1
            rows.append({"order_id": i, "order_date": f"2026-{month:02d}-{day:02d}", "amount": float(month * 100 + day)})
    for d in extra_days:
        i += 1
        rows.append({"order_id": i, "order_date": d, "amount": 1.0})
    return rows


def elimination_scenario(outcome, extra_days=(), **extra):
    return {"tables": [table("dbo.fact_sales_m", year_rows(extra_days), 1.2e9,
                             f"DISTRIBUTION = HASH(order_id), CLUSTERED COLUMNSTORE INDEX, "
                             f"PARTITION (order_date RANGE RIGHT FOR VALUES ({MONTHLY_2026}))",
                             {"order_id": "INTEGER", "order_date": "DATE", "amount": "DOUBLE"})],
            "outcome": outcome, **extra}


def february(where):
    return code(f"""
        -- dbo.fact_sales_m is partitioned by month on order_date (12 partitions for 2026).
        SELECT COUNT(*) AS orders, SUM(amount) AS revenue
        FROM dbo.fact_sales_m
        WHERE {where};
    """)


exercise(
    id="sp-partition-elimination", title="Let the pool skip partitions", difficulty="medium",
    topics=["partitioning", "partition-elimination", "sargable-predicates"],
    prompt=("This February report works, but it scans all 12 monthly partitions of dbo.fact_sales_m. Rewrite its WHERE "
            "clause so the pool only scans February's partition, with the same result."),
    sections=[("Graded", "How many partitions the query scans, and its result, including a day with orders on the 1st "
                         "of March.")],
    starter=february("YEAR(order_date) = 2026 AND MONTH(order_date) = 2"),
    solution=february("order_date >= '2026-02-01' AND order_date < '2026-03-01'"),
    fixtures=[
        ("scans", "visible", elimination_scenario("scans")),
        ("result", "hidden", elimination_scenario("result")),
        ("march-first", "edge", elimination_scenario("result", extra_days=("2026-03-01", "2026-02-28"))),
    ],
    mutants=[february("order_date BETWEEN '2026-02-01' AND '2026-03-01'"),
             february("CAST(order_date AS VARCHAR(10)) LIKE '2026-02%'")],
    hints=["The pool can only skip partitions when the partition column itself is compared with constants.",
           "BETWEEN includes both ends: '2026-03-01' is already March."],
    explanation=("YEAR(order_date) and MONTH(order_date) hide the partition column inside functions, so every partition "
                 "is scanned. order_date >= '2026-02-01' AND order_date < '2026-03-01' compares the column itself with "
                 "constants, so only February's partition is read. With BETWEEN ... AND '2026-03-01', March 1st would "
                 "be counted and its partition scanned too."),
    follow_ups=["With a clustered columnstore index, what else can skip data inside a partition?"],
)

# 7 ------------------------------------------------------------------------------------------------
def three_years():
    rows, i = [], 0
    for year in (2024, 2025, 2026):
        for month in range(1, 13):
            for day in (1, 8, 15, 22, 28):
                i += 1
                rows.append({"order_id": i, "order_date": f"{year}-{month:02d}-{day:02d}", "amount": float(i % 50 + 1)})
    return rows


def months_between(first, last):
    out, y, m = [], first[0], first[1]
    while (y, m) <= last:
        out.append(f"'{y}-{m:02d}-01'")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


MONTHS_3Y = ", ".join(months_between((2024, 2), (2026, 12)))
QUARTERS_3Y = ", ".join(f"'{y}-{m:02d}-01'" for y in (2024, 2025, 2026) for m in (1, 4, 7, 10) if (y, m) != (2024, 1))
WEEKS_3Y = ", ".join(f"'{(date(2024, 1, 1) + timedelta(weeks=w)).isoformat()}'" for w in range(1, 157))
YEARS_3Y = "'2025-01-01', '2026-01-01'"


def three_year_table(boundaries):
    return code(f"""
        -- 2.4 billion sales over 2024-2026. Daily partitions would leave a few thousand rows per
        -- distribution and partition: far too few for columnstore rowgroups.
        CREATE TABLE dbo.fact_sales_3y
        WITH
        (   DISTRIBUTION = HASH(order_id)
        ,   CLUSTERED COLUMNSTORE INDEX
        ,   PARTITION ( order_date RANGE RIGHT FOR VALUES ({boundaries}) )
        )
        AS
        SELECT order_id, order_date, amount
        FROM bronze.sales_3y;
    """)


def health_scenario(outcome, **extra):
    return {"tables": [table("bronze.sales_3y", three_years(), 2.4e9, types={"order_id": "INTEGER", "order_date": "DATE",
                                                                                "amount": "DOUBLE"})],
            "outcome": outcome, **extra}


exercise(
    id="sp-columnstore-partition-size", title="Partitions big enough for columnstore", difficulty="hard",
    topics=["partitioning", "columnstore", "rowgroups"],
    prompt=("bronze.sales_3y stands for 2.4 billion sales spread evenly over 2024, 2025 and 2026. Create "
            "dbo.fact_sales_3y (HASH(order_id), clustered columnstore) partitioned on order_date with calendar boundaries "
            "(RANGE RIGHT, on the first day of a period). Choose the finest granularity (day, week, month, quarter or "
            "year) that keeps at least 1 million rows per distribution in every populated partition."),
    sections=[("Graded", "The number of populated partitions and whether every one of them reaches 1 million rows per "
                         "distribution (the lab counts rows at scale: 60 distributions per partition); the "
                         "partition column; the row count."),
              ("Rule of thumb", "Columnstore compresses best with about 1 million rows per rowgroup, and a dedicated SQL "
               "pool already splits every partition into 60 distributions: a partition needs 60 million rows or more.")],
    starter=three_year_table(YEARS_3Y), solution=three_year_table(MONTHS_3Y),
    fixtures=[
        ("health", "visible", health_scenario("partition_health", only=["dbo.fact_sales_3y"],
                                              columns=["table", "populated_partitions", "columnstore_ok"])),
        ("column", "hidden", health_scenario("designs", only=["dbo.fact_sales_3y"],
                                             columns=["table", "partition_column", "partition_range"])),
        ("rows", "edge", health_scenario("result", query="SELECT COUNT(*) AS sales FROM dbo.fact_sales_3y")),
    ],
    mutants=[three_year_table(WEEKS_3Y), three_year_table(QUARTERS_3Y)],
    hints=["2.4 billion rows over 36 months is about 67 million a month: divide by 60 distributions.",
           "Weekly partitions hold about 15 million rows each; is that enough for 60 distributions?"],
    explanation=("Monthly partitions hold about 67 million rows, so about 1.1 million per distribution: every rowgroup can "
                 "be full. Weekly partitions fall to about 256,000 rows per distribution, and daily ones to a few "
                 "thousand: columnstore compression suffers. Quarters and years also reach the target, but they are "
                 "coarser than needed for monthly loads and switching."),
    follow_ups=["How many partitions would you keep if the table grew to 10 billion rows?"],
)

# 8 ------------------------------------------------------------------------------------------------
PRODUCTS = [{"product_id": i, "product_name": f"Product {i}", "color": ["Red", "Blue", "Black", "White"][i % 4],
             "list_price": float(10 * i)} for i in range(1, 21)]
CHANGES = [{"product_id": 3, "product_name": "Product 3 v2", "color": "Green", "list_price": 35.0},
           {"product_id": 7, "product_name": "Product 7", "color": "Black", "list_price": 75.0},
           {"product_id": 12, "product_name": "Product 12 XL", "color": "Blue", "list_price": 130.0},
           {"product_id": 21, "product_name": "Product 21", "color": "Red", "list_price": 210.0},
           {"product_id": 22, "product_name": "Product 22", "color": "White", "list_price": 220.0}]
PRODUCT_TYPES = {"product_id": "INTEGER", "product_name": "VARCHAR", "color": "VARCHAR", "list_price": "DOUBLE"}


def upsert_scenario(outcome, changes=CHANGES, **extra):
    return {"tables": [table("dbo.dim_product", PRODUCTS, None, "DISTRIBUTION = HASH(product_id), CLUSTERED COLUMNSTORE INDEX",
                             PRODUCT_TYPES),
                       table("bronze.product_changes", changes, types=PRODUCT_TYPES)],
            "outcome": outcome, **extra}


def upsert(distribution="HASH(product_id)", keep="WHERE NOT EXISTS (SELECT 1 FROM bronze.product_changes AS s "
                                                  "WHERE s.product_id = p.product_id)"):
    return code(f"""
        -- Apply bronze.product_changes to dbo.dim_product with the pool's CTAS pattern.
        CREATE TABLE dbo.dim_product_upsert
        WITH ( DISTRIBUTION = {distribution}, CLUSTERED COLUMNSTORE INDEX )
        AS
        SELECT s.product_id, s.product_name, s.color, s.list_price
        FROM bronze.product_changes AS s
        UNION ALL
        SELECT p.product_id, p.product_name, p.color, p.list_price
        FROM dbo.dim_product AS p
        {keep};

        RENAME OBJECT dbo.dim_product TO dim_product_old;
        RENAME OBJECT dbo.dim_product_upsert TO dim_product;
        DROP TABLE dbo.dim_product_old;
    """)


exercise(
    id="sp-ctas-upsert", title="Upsert a dimension with CTAS", difficulty="hard",
    topics=["ctas", "upsert", "rename-object"],
    prompt=("Apply bronze.product_changes to dbo.dim_product: changed products take their new values, new products are "
            "added, the others stay as they are. Use the dedicated SQL pool pattern: CTAS the new version of the table "
            "(the changes UNION ALL the untouched rows), swap the names with RENAME OBJECT and drop the old table. Keep "
            "the table's distribution and index."),
    sections=[("Graded", "The rows of dbo.dim_product after your script, its design, and a second batch of changes.")],
    starter=upsert(keep=""), solution=upsert(),
    fixtures=[
        ("rows", "visible", upsert_scenario("table", table="dbo.dim_product")),
        ("design", "hidden", upsert_scenario("designs", only=["dbo.dim_product"],
                                             columns=["table", "distribution", "distribution_columns", "index"])),
        ("new-only", "edge", upsert_scenario("table", changes=CHANGES[3:], table="dbo.dim_product")),
    ],
    mutants=[upsert(distribution="ROUND_ROBIN"),
             upsert(keep="WHERE p.product_id NOT IN (SELECT product_id FROM bronze.product_changes WHERE color = 'Green')")],
    hints=["The untouched rows are the products that do not appear in the changes: NOT EXISTS.",
           "A CTAS doesn't copy the old table's design: state DISTRIBUTION and the index again."],
    explanation=("The CTAS writes the complete new version in one fully parallel statement: all changed and new rows, "
                 "plus the existing rows that no change touches (NOT EXISTS). Two renames swap the tables. A MERGE "
                 "gives the same rows; CTAS is the classic dedicated pool pattern for large tables because it writes "
                 "in parallel and needs little logging."),
    follow_ups=["How would you also remove products that the source marks as deleted?"],
)

# 9 ------------------------------------------------------------------------------------------------
P_BOUNDARIES = "'2026-02-01', '2026-03-01', '2026-04-01'"
P_DESIGN = (f"DISTRIBUTION = HASH(order_id), CLUSTERED COLUMNSTORE INDEX, "
            f"PARTITION (order_date RANGE RIGHT FOR VALUES ({P_BOUNDARIES}))")
P_TYPES = {"order_id": "INTEGER", "customer_id": "VARCHAR", "order_date": "DATE", "amount": "DOUBLE"}
JAN_FEB = [{"order_id": i, "customer_id": f"C{i % 7}", "order_date": f"2026-0{1 + (i % 2)}-{(i % 27) + 1:02d}",
            "amount": float(i * 3)} for i in range(1, 25)]
STALE_MARCH = [{"order_id": 900 + i, "customer_id": "C9", "order_date": f"2026-03-0{i}", "amount": 1.0} for i in (1, 2)]
MARCH = [{"order_id": 100 + i, "customer_id": f"C{i % 5}", "order_date": f"2026-03-{i + 1:02d}", "amount": float(i * 5)}
         for i in range(1, 11)]
MONTHS_QUERY = ("SELECT MONTH(order_date) AS month, COUNT(*) AS orders, SUM(amount) AS revenue "
                "FROM dbo.fact_sales_p GROUP BY MONTH(order_date)")


def switch_scenario(outcome, fact=JAN_FEB, **extra):
    return {"tables": [table("dbo.fact_sales_p", fact, 9e8, P_DESIGN, P_TYPES),
                       table("bronze.march_orders", MARCH, types=P_TYPES)],
            "outcome": outcome, **extra}


def switch(last):
    return code(f"""
        -- Stage March with exactly the design of dbo.fact_sales_p (the partitions must line up), load it, then
        -- switch the March partition in.
        CREATE TABLE dbo.fact_sales_stage
        WITH
        (   DISTRIBUTION = HASH(order_id)
        ,   CLUSTERED COLUMNSTORE INDEX
        ,   PARTITION ( order_date RANGE RIGHT FOR VALUES ({P_BOUNDARIES}) )
        )
        AS
        SELECT * FROM dbo.fact_sales_p WHERE 1 = 2;

        INSERT INTO dbo.fact_sales_stage
        SELECT order_id, customer_id, order_date, amount FROM bronze.march_orders;

        {last}
    """)


exercise(
    id="sp-partition-switch", title="Load a month with a partition switch", difficulty="hard",
    topics=["partitioning", "partition-switching", "loading"],
    prompt=("dbo.fact_sales_p is partitioned by month (RANGE RIGHT on '2026-02-01', '2026-03-01', '2026-04-01': "
            "partition 3 is March). Load bronze.march_orders through a staging table and a partition switch. The "
            "starter already creates dbo.fact_sales_stage with the same design and loads it; finish with the switch. "
            "If March already has rows in the fact table, the switch must replace them."),
    sections=[("Graded", "The orders and revenue per month in dbo.fact_sales_p, that the staging table is left empty, and "
                         "a fact table that already has two stale March orders."),
              ("Switch rules", "Both tables need the same columns, distribution, index and partition boundaries; the "
               "target partition must be empty unless you ask for WITH (TRUNCATE_TARGET = ON).")],
    starter=switch("-- TODO: switch March into dbo.fact_sales_p"),
    solution=switch("ALTER TABLE dbo.fact_sales_stage SWITCH PARTITION 3 TO dbo.fact_sales_p PARTITION 3\n"
                    "WITH (TRUNCATE_TARGET = ON);"),
    fixtures=[
        ("months", "visible", switch_scenario("result", query=MONTHS_QUERY)),
        ("stage-empty", "hidden", switch_scenario("result", query="SELECT COUNT(*) AS staged FROM dbo.fact_sales_stage")),
        ("stale-march", "edge", switch_scenario("result", fact=JAN_FEB + STALE_MARCH, query=MONTHS_QUERY)),
    ],
    mutants=[switch("INSERT INTO dbo.fact_sales_p SELECT * FROM dbo.fact_sales_stage;"),
             switch("ALTER TABLE dbo.fact_sales_stage SWITCH PARTITION 4 TO dbo.fact_sales_p PARTITION 4;")],
    hints=["ALTER TABLE <stage> SWITCH PARTITION n TO <fact> PARTITION n moves a whole partition as metadata.",
           "WITH (TRUNCATE_TARGET = ON) replaces what the target partition held."],
    explanation=("Partition switching moves a staged partition into the fact table as a metadata operation: no rows are "
                 "copied and nothing is logged row by row. It needs identical designs and boundaries. TRUNCATE_TARGET "
                 "replaces stale rows of the target partition. An INSERT ... SELECT copies the rows and leaves the "
                 "staging table full."),
    follow_ups=["How would you remove the oldest month of a 36-month fact table with a switch?"],
)

# 10 -----------------------------------------------------------------------------------------------
CUSTOMER_SETUP = code("""
    CREATE TABLE dbo.dim_customer
    (   customer_id VARCHAR(10) NOT NULL
    ,   customer_name VARCHAR(50) NOT NULL
    ,   city VARCHAR(30)
    ,   updated_at DATETIME2 NOT NULL
    ,   CONSTRAINT pk_dim_customer PRIMARY KEY NONCLUSTERED (customer_id) NOT ENFORCED
    )
    WITH ( DISTRIBUTION = REPLICATE, CLUSTERED INDEX (customer_id) );
""")
UPDATES = [{"customer_id": "C1", "customer_name": "Ada", "city": "Paris", "updated_at": "2026-03-01 09:00:00"},
           {"customer_id": "C1", "customer_name": "Ada", "city": "Lyon", "updated_at": "2026-03-04 10:00:00"},
           {"customer_id": "C2", "customer_name": "Ben", "city": "Nice", "updated_at": "2026-03-02 08:00:00"},
           {"customer_id": "C3", "customer_name": "Chloe", "city": "Lille", "updated_at": "2026-03-01 12:00:00"},
           {"customer_id": "C3", "customer_name": "Chloe M.", "city": "Lille", "updated_at": "2026-03-03 12:00:00"},
           {"customer_id": "C3", "customer_name": "Chloe", "city": "Lille", "updated_at": "2026-03-02 12:00:00"}]
UPDATE_TYPES = {"customer_id": "VARCHAR", "customer_name": "VARCHAR", "city": "VARCHAR", "updated_at": "TIMESTAMP"}


def customer_scenario(outcome, updates=UPDATES, **extra):
    return {"tables": [table("bronze.customer_updates", updates, types=UPDATE_TYPES)], "setup": CUSTOMER_SETUP,
            "outcome": outcome, **extra}


def customer_load(select):
    return code(f"""
        -- dbo.dim_customer declares PRIMARY KEY NONCLUSTERED (customer_id) NOT ENFORCED.
        INSERT INTO dbo.dim_customer (customer_id, customer_name, city, updated_at)
        {select};
    """)


LATEST = ("SELECT customer_id, customer_name, city, updated_at\n"
          "FROM (\n"
          "    SELECT customer_id, customer_name, city, updated_at,\n"
          "           ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY updated_at DESC) AS rn\n"
          "    FROM bronze.customer_updates\n"
          ") AS latest\n"
          "WHERE rn = 1")
exercise(
    id="sp-not-enforced-key", title="A primary key that doesn't stop duplicates", difficulty="medium",
    topics=["keys", "constraints", "deduplication"],
    prompt=("Load bronze.customer_updates into the empty dbo.dim_customer. Its PRIMARY KEY on customer_id is NOT "
            "ENFORCED (the only kind a dedicated SQL pool accepts), so the pool will happily store duplicate keys. Keep "
            "exactly one row per customer: the one with the latest updated_at."),
    sections=[("Graded", "The rows of dbo.dim_customer after your load, for two batches of updates."),
              ("Keys in a dedicated pool (and Fabric Warehouse)", "PRIMARY KEY and UNIQUE are only allowed as NONCLUSTERED "
               "NOT ENFORCED: the optimizer uses them as hints, but nothing checks them. Your load has to guarantee "
               "uniqueness.")],
    starter=customer_load("SELECT customer_id, customer_name, city, updated_at\nFROM bronze.customer_updates"),
    solution=customer_load(LATEST),
    fixtures=[
        ("latest-rows", "visible", customer_scenario("table", table="dbo.dim_customer")),
        ("other-batch", "hidden", customer_scenario("table", updates=UPDATES[2:] + [
            {"customer_id": "C4", "customer_name": "Dan", "city": "Metz", "updated_at": "2026-03-05 07:00:00"}],
            table="dbo.dim_customer")),
        ("key-kept", "edge", customer_scenario("constraints", only=["dbo.dim_customer"])),
    ],
    mutants=[customer_load("SELECT DISTINCT customer_id, customer_name, city, updated_at\nFROM bronze.customer_updates"),
             customer_load(LATEST.replace("updated_at DESC", "updated_at ASC"))],
    hints=["ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY updated_at DESC) numbers each customer's rows from the latest.",
           "DISTINCT only removes rows that are identical in every column."],
    explanation=("NOT ENFORCED means the pool never rejects a duplicate key, so deduplication is the load's job. "
                 "Numbering each customer's rows from the latest and keeping row 1 loads one row per customer. "
                 "DISTINCT keeps both versions of a customer whose city changed."),
    follow_ups=["What can go wrong in queries when a NOT ENFORCED primary key is in fact violated?"],
)

# 11 -----------------------------------------------------------------------------------------------
DAILY_SETUP = code("""
    CREATE TABLE dbo.daily_sales
    (   order_date DATE NOT NULL
    ,   orders BIGINT NOT NULL
    ,   revenue DECIMAL(18, 2)
    )
    WITH ( DISTRIBUTION = REPLICATE, CLUSTERED INDEX (order_date) );
""")
DAY_ROWS = [{"order_id": i, "order_date": f"2026-03-0{4 + (i % 3)}", "amount": float(i * 2)} for i in range(1, 31)]
RUNS = code("""
    EXEC dbo.usp_load_daily_sales @day = '2026-03-05';
    EXEC dbo.usp_load_daily_sales @day = '2026-03-05';
    EXEC dbo.usp_load_daily_sales '2026-03-06';
""")


def daily_scenario(rows=DAY_ROWS, runs=RUNS):
    return {"tables": [table("dbo.fact_sales_d", rows, 3e7, "DISTRIBUTION = HASH(order_id), CLUSTERED COLUMNSTORE INDEX",
                             {"order_id": "INTEGER", "order_date": "DATE", "amount": "DOUBLE"})],
            "setup": DAILY_SETUP, "after": runs, "outcome": "table", "table": "dbo.daily_sales"}


def procedure(body):
    return code(f"""
        CREATE PROCEDURE dbo.usp_load_daily_sales @day DATE
        AS
        BEGIN
        {textwrap.indent(textwrap.dedent(body).strip(), '    ')}
        END
    """)


INSERT_DAY = """
    INSERT INTO dbo.daily_sales (order_date, orders, revenue)
    SELECT @day, COUNT(*), SUM(amount)
    FROM dbo.fact_sales_d
    WHERE order_date = @day;
"""
exercise(
    id="sp-procedure-daily-rebuild", title="A stored procedure that reloads one day", difficulty="medium",
    topics=["stored-procedures", "idempotence", "parameters"],
    prompt=("Write dbo.usp_load_daily_sales @day DATE. It recomputes one day of dbo.daily_sales (order_date, orders, "
            "revenue) from dbo.fact_sales_d. The pipeline may run it again for the same day after a failure, so a "
            "rerun must replace the day, never add it twice."),
    sections=[("Graded", "The rows of dbo.daily_sales after the check runs your procedure for 2026-03-05, again for "
                         "2026-03-05, then for 2026-03-06."),
              ("Lab procedures", "The procedure body is T-SQL translated for the lab's subset. Parameters are substituted "
               "as values, and procedures are created in their own batch.")],
    starter=procedure(INSERT_DAY),
    solution=procedure("DELETE FROM dbo.daily_sales WHERE order_date = @day;\n" + textwrap.dedent(INSERT_DAY)),
    fixtures=[
        ("rerun-safe", "visible", daily_scenario()),
        ("three-days", "hidden", daily_scenario(runs=RUNS + "EXEC dbo.usp_load_daily_sales @day = '2026-03-04';\n")),
        ("day-without-sales", "edge", daily_scenario(runs="EXEC dbo.usp_load_daily_sales @day = '2026-03-09';\n")),
    ],
    mutants=[procedure("DELETE FROM dbo.daily_sales;\n" + textwrap.dedent(INSERT_DAY)),
             procedure("DELETE FROM dbo.daily_sales WHERE order_date = @day;\n"
                       + textwrap.dedent(INSERT_DAY).replace("WHERE order_date = @day", "WHERE order_date >= @day"))],
    hints=["Delete the day before inserting it: running the procedure twice then gives the same table.",
           "@day is replaced by its value everywhere in the body."],
    explanation=("Deleting the day before inserting it makes the procedure idempotent: a rerun for the same day replaces "
                 "the row instead of duplicating it. Deleting everything would wipe the other days, and a >= filter "
                 "would mix later days into this one."),
    follow_ups=["How would the Synapse pipeline call this procedure (SQL pool stored procedure activity)?"],
)

# 12 -----------------------------------------------------------------------------------------------
EXPORT = [{"order_id": i, "customer_name": f"Customer {i}", "amount": round(12.3456 * i, 4),
           "ordered_at": f"2026-03-0{1 + i % 5} 1{i % 10}:15:00"} for i in range(1, 13)]
EXPORT_TYPES = {"order_id": "INTEGER", "customer_name": "VARCHAR", "amount": "DOUBLE", "ordered_at": "TIMESTAMP"}


def fabric_scenario(outcome, **extra):
    return {"flavor": "fabric", "tables": [table("bronze.orders_export", EXPORT, types=EXPORT_TYPES)],
            "outcome": outcome, **extra}


def orders_script(columns, options=""):
    body = "\n,   ".join(columns)
    return code(f"""
        CREATE TABLE dbo.fact_orders
        (   {body}
        ){options};

        INSERT INTO dbo.fact_orders (order_id, customer_name, amount, ordered_at)
        SELECT order_id, customer_name, amount, ordered_at
        FROM bronze.orders_export;
    """)


SYNAPSE_COLUMNS = ["order_id INT NOT NULL", "customer_name NVARCHAR(60) NOT NULL", "amount MONEY NOT NULL",
                   "ordered_at DATETIME NOT NULL"]
FABRIC_COLUMNS = ["order_id INT NOT NULL", "customer_name VARCHAR(60) NOT NULL", "amount DECIMAL(19, 4) NOT NULL",
                  "ordered_at DATETIME2(6) NOT NULL"]
exercise(
    id="sp-fabric-port", title="Port a dedicated pool table to Fabric Warehouse", difficulty="medium", flavor="fabric",
    topics=["fabric-warehouse", "migration", "data-types"],
    prompt=("This script comes from an Azure Synapse dedicated SQL pool. Port it to Microsoft Fabric Data Warehouse: "
            "remove what Fabric manages itself, and replace the data types a Fabric table can't use by their migration "
            "equivalents, keeping the values exact. Keep the column names and load the same rows."),
    sections=[("Graded", "The rows of dbo.fact_orders (the amounts keep their 4 decimals), its column types in the "
                         "lab's DuckDB catalog, and the total amount."),
              ("Fabric Data Warehouse", "No DISTRIBUTION, index or PARTITION options: Fabric stores tables as Delta in "
               "OneLake and manages the layout; WITH (CLUSTER BY (...)) sets data clustering. Types to replace: money, "
               "smallmoney, datetime, smalldatetime, nvarchar, nchar, tinyint, binary, datetimeoffset.")],
    starter=orders_script(SYNAPSE_COLUMNS, "\nWITH ( DISTRIBUTION = HASH(order_id), CLUSTERED COLUMNSTORE INDEX )"),
    solution=orders_script(FABRIC_COLUMNS),
    fixtures=[
        ("rows", "visible", fabric_scenario("table", table="dbo.fact_orders")),
        ("types", "hidden", fabric_scenario("result", query=(
            "SELECT column_name AS column_name, data_type AS data_type FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE table_name = 'fact_orders'"))),
        ("total", "edge", fabric_scenario("result", query="SELECT SUM(amount) AS total FROM dbo.fact_orders")),
    ],
    mutants=[orders_script([c.replace("DECIMAL(19, 4)", "DECIMAL(10, 0)") for c in FABRIC_COLUMNS]),
             orders_script([c.replace("DECIMAL(19, 4)", "DECIMAL(19, 1)") for c in FABRIC_COLUMNS])],
    hints=["money becomes decimal(19,4), nvarchar becomes varchar and datetime becomes datetime2.",
           "Fabric refuses WITH (DISTRIBUTION ...); CLUSTER BY is its only table option here."],
    explanation=("Fabric Data Warehouse manages distribution, file layout and indexing itself, so the Synapse table "
                 "options go, and CLUSTER BY is the only layout option. money keeps 4 decimals as decimal(19,4); "
                 "nvarchar becomes varchar (Fabric strings are UTF-8) and datetime becomes datetime2. A decimal with "
                 "fewer decimals would silently round the amounts."),
    follow_ups=["Add WITH (CLUSTER BY (ordered_at)): what kind of query does data clustering help?"],
)


# -- pack assembly ---------------------------------------------------------------------------------
PRODUCT = {"synapse": "Azure Synapse dedicated SQL pool", "fabric": "Microsoft Fabric Data Warehouse"}
SIMULATOR = ("Your T-SQL script runs on the lab's simulated {product}: the statements are translated to DuckDB for a "
             "documented subset and the data really runs, on an isolated catalog built for each check. Distributions "
             "(60), partitions, columnstore rowgroups and the data movement of plans are modelled from Synapse's design "
             "rules; they are not Synapse telemetry. Nothing connects to Azure or Fabric. End statements with ; "
             "(procedures take their own GO batch).")


def definition(spec: dict, rank: int) -> dict:
    by_visibility = {"visible": [], "hidden": [], "edge": []}
    for fid, visibility, _ in spec["fixtures"]:
        by_visibility[visibility].append(fid)
    product = PRODUCT[spec["flavor"]]
    sections = [{"title": "Simulator", "body": SIMULATOR.format(product=product)}]
    sections += [{"title": title, "body": body} for title, body in spec["sections"]]
    projections = {json.dumps(scenario.get("columns")) for _, _, scenario in spec["fixtures"]}
    exact = json.loads(projections.pop()) if len(projections) == 1 else None
    validation = {
        "kind": "rows", "ordered": False, "duplicate_sensitive": True,
        "relative_tolerance": 1e-09, "absolute_tolerance": 1e-06,
        "required_columns": exact or [], "exact_schema": exact,
        "forbidden_extra_columns": True, "null_semantics": "equal",
    }
    return {
        "schema_version": 1, "id": spec["id"], "version": "1", "title": spec["title"],
        "difficulty": spec["difficulty"], "topics": spec["topics"],
        "tags": ["cloud-lab", "sql-pool", spec["flavor"], "simulated"],
        "origin": "authored", "language": "sqlpool", "runtime": "datapass-sqlpool-sim-v1",
        "prompt": spec["prompt"], "sections": sections, "starter_source": spec["starter"],
        "fixtures": [{"id": f"{spec['id']}-fixtures", "version": "1"}],
        "visible_checks": [{"id": fid, "description": "Simulated SQL pool outcome for the public scenario."}
                           for fid in by_visibility["visible"]],
        "hidden_check_refs": by_visibility["hidden"], "edge_check_refs": by_visibility["edge"],
        "hints": spec["hints"], "solution": {"available": True, "reveal": "explicit"},
        "explanation": spec["explanation"], "follow_ups": spec["follow_ups"],
        "canonical_placement": {"domain": "cloud-sql-pool", "topic": spec["topics"][0]},
        "related_associations": ["cloud-lab/sql-pool"],
        "recommendation": {"rank": rank, "reason": "Cloud Lab SQL pool progression"},
        "validator_version": "rows-v2", "validation": validation,
        "runtime_requirements": ["sqlpool-simulator"],
        "provenance": {
            "source": "Authored for Datapass Workbench: Synapse dedicated SQL pool and Fabric Warehouse design rules",
            "fixtures": "Authored scenarios; expected rows computed by running the reference and reviewed",
        },
        "constraints": {"truth": (f"Simulated {product}: data statements run on an isolated local DuckDB catalog; "
                                  "distributions, partitions and data movement are modelled.")},
        "truth": "simulated",
    }


def outcome(source, scenario):
    from datapass_runtime.sqlpool_grading import ScriptRejected, run_fixture
    from sqlpoollab.exercise import PoolScenario
    from sqlpoollab.model import PoolError
    try:
        return run_fixture(source, PoolScenario.model_validate(scenario)), None
    except (ScriptRejected, PoolError) as exc:
        return None, str(exc)


def main() -> None:
    from datapass_runtime.exercise_contracts import RowValidation
    from datapass_runtime.exercise_packs import PackRegistry
    from datapass_runtime.exercise_validation import validate_result
    ids = [spec["id"] for spec in EXERCISES]
    assert len(ids) == len(set(ids))
    definitions, grading, problems = [], {}, []
    for rank, spec in enumerate(EXERCISES, start=1):
        public = definition(spec, rank)
        definitions.append(public)
        validation = RowValidation.model_validate(public["validation"])
        fixtures = []
        for fid, visibility, scenario in spec["fixtures"]:
            rows, error = outcome(spec["solution"], copy.deepcopy(scenario))
            if error:
                problems.append(f"{spec['id']}/{fid}: reference rejected: {error}")
                rows = []
            fixtures.append({"id": fid, "visibility": visibility, "input_rows": [], "scenario": scenario, "expected": rows})
        grading[spec["id"]] = {"solution": spec["solution"], "fixtures": fixtures}
        for label, source in [("starter", spec["starter"])] + [(f"mutant {i}", m) for i, m in enumerate(spec["mutants"])]:
            failed = False
            for fixture in fixtures:
                rows, error = outcome(source, copy.deepcopy(fixture["scenario"]))
                if error:
                    if not (label == "starter" and spec["id"] in STARTER_ERRORS_BY_DESIGN):
                        problems.append(f"{spec['id']}: {label} does not run: {error}")
                    failed = True
                    break
                columns = fixture["scenario"].get("columns") or (list(rows[0]) if rows else [])
                if not validate_result({"rows": rows, "columns": columns, "truncated": False}, fixture["expected"], validation):
                    failed = True
            if not failed:
                problems.append(f"{spec['id']}: {label} passes every check")
    manifest = {"schema_version": 1, "id": "sqlpool-v1", "version": "1",
                "title": "Cloud Lab: SQL pool design (simulated Synapse dedicated SQL pool and Fabric Warehouse)",
                "enabled": True, "provenance": {"source": "Authored for Datapass Workbench"}}
    PackRegistry().register(manifest, definitions, grading)
    PACK.mkdir(parents=True, exist_ok=True)
    for name, data in (("manifest.json", manifest), ("exercises.json", definitions), ("grading.server.json", grading)):
        (PACK / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_mutants(PACK, {spec["id"]: spec["mutants"] for spec in EXERCISES})
    for spec in EXERCISES:
        print(f"== {spec['id']}")
        for fixture in grading[spec["id"]]["fixtures"]:
            print(f"   {fixture['id']:22s}", json.dumps(fixture["expected"])[:400])
    if problems:
        print("\nPROBLEMS:\n  " + "\n  ".join(problems))


if __name__ == "__main__":
    main()
