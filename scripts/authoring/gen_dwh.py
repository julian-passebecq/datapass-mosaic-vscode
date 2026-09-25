"""Generate content/exercise-packs/dwh-v1 (BI Lab: data warehousing) from authored specs.

Expected rows are computed by running each reference through the BI Lab grader
(`datapass_runtime.warehouse_grading.run_fixture`); review them by hand. The generator also checks that
starters and mutants run and fail. Run from the repository root with PYTHONPATH=runtime.
"""
from __future__ import annotations

import copy
import json
import re
import textwrap
from pathlib import Path

from pack_quality import write_mutants

ROOT = Path.cwd()
PACK = ROOT / "content" / "exercise-packs" / "dwh-v1"
EXERCISES: list[dict] = []
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def code(text: str) -> str:
    return textwrap.dedent(text).strip("\n") + "\n"


def exercise(**spec):
    spec.setdefault("language", "warehouse")
    EXERCISES.append(spec)


def T(name, rows, types=None, columns=None):
    """A fixture table; columns whose values all look like dates are typed DATE."""
    entry = {"name": name, "rows": rows}
    cols = columns or (list(rows[0]) if rows else [])
    typed = dict(types or {})
    for column in cols:
        values = [r[column] for r in rows if r[column] is not None]
        if column not in typed and values and all(isinstance(v, str) and DATE.match(v) for v in values):
            typed[column] = "DATE"
    if columns:
        entry["columns"] = columns
    if typed:
        entry["types"] = typed
    return entry


def rows(columns, *values):
    names = columns.split()
    return [dict(zip(names, v)) for v in values]


def S(outcome, **kw):
    return {"outcome": outcome, **kw}


RUNS_NOTE = ("The check runs your script {n} times in a row on the same catalog, like a scheduled load: before each run "
             "the day's batch replaces {batch}. Your script must be rerunnable: running it again on the same batch "
             "changes nothing.")

# =================================================================================================
# 1. Flatten a snowflaked hierarchy
# =================================================================================================
PRODUCTS = rows("product_id product_name subcategory_id list_price",
                ("P01", "Trail Tent 2P", 10, 199.0), ("P02", "Down Bag -5", 11, 159.0),
                ("P03", "Dynamic Rope 60m", 20, 139.0), ("P04", "Rain Jacket", 30, 99.0),
                ("P05", "Gift Card", None, 50.0))
SUBCATEGORIES = rows("subcategory_id subcategory_name category_id",
                     (10, "Tents", 1), (11, "Sleeping bags", 1), (20, "Ropes", 2), (30, "Jackets", 3))
CATEGORIES = rows("category_id category_name", (1, "Camping"), (2, "Climbing"), (3, "Apparel"))


def hierarchy(products=PRODUCTS, subcategories=SUBCATEGORIES, categories=CATEGORIES):
    return [T("source.erp_products", products, types={"subcategory_id": "INTEGER"}),
            T("source.erp_subcategories", subcategories), T("source.erp_categories", categories)]


FLATTEN = code("""
    CREATE OR REPLACE TABLE gold.dim_product AS
    SELECT ROW_NUMBER() OVER (ORDER BY p.product_id) AS product_key,
           p.product_id,
           p.product_name,
           COALESCE(s.subcategory_name, 'Unassigned') AS subcategory,
           COALESCE(c.category_name, 'Unassigned') AS category,
           p.list_price
    FROM source.erp_products AS p
    LEFT JOIN source.erp_subcategories AS s ON s.subcategory_id = p.subcategory_id
    LEFT JOIN source.erp_categories AS c ON c.category_id = s.category_id;
""")
exercise(
    id="dwh-snowflake-flatten", title="Flatten a snowflaked product hierarchy", difficulty="easy",
    topics=["star-schema", "snowflake", "dimensions"],
    prompt=("The ERP stores products in three tables: source.erp_products -> source.erp_subcategories -> "
            "source.erp_categories (a snowflake). Build gold.dim_product, one flat table the reports can join once: "
            "product_key, product_id, product_name, subcategory, category, list_price. product_key is "
            "ROW_NUMBER() OVER (ORDER BY product_id). Every product must be in the dimension: when its subcategory "
            "or category is missing, report it under 'Unassigned'."),
    sections=[("Star or snowflake", "A snowflake normalizes a dimension into several tables (product -> subcategory "
               "-> category). A star keeps one wide, denormalized table per dimension: fewer joins for every report, "
               "simpler filters, and the hierarchy is still there as columns. Most BI models (Power BI included) "
               "prefer the star."),
              ("Graded", "The rows of gold.dim_product, with products whose subcategory is missing or points to a "
               "category that does not exist.")],
    starter=code("""
        -- The gift card has no subcategory. Where does it go?
        CREATE OR REPLACE TABLE gold.dim_product AS
        SELECT ROW_NUMBER() OVER (ORDER BY p.product_id) AS product_key,
               p.product_id,
               p.product_name,
               s.subcategory_name AS subcategory,
               c.category_name AS category,
               p.list_price
        FROM source.erp_products AS p
        JOIN source.erp_subcategories AS s ON s.subcategory_id = p.subcategory_id
        JOIN source.erp_categories AS c ON c.category_id = s.category_id;
    """),
    solution=FLATTEN,
    fixtures=[
        ("dimension", "visible", S("table", tables=hierarchy(), table="gold.dim_product")),
        ("orphan-category", "hidden", S("table", table="gold.dim_product", tables=hierarchy(
            subcategories=SUBCATEGORIES + rows("subcategory_id subcategory_name category_id", (40, "Stoves", 9)),
            products=PRODUCTS + rows("product_id product_name subcategory_id list_price", ("P06", "Gas Stove", 40, 45.0))))),
        ("missing-subcategory", "edge", S("table", table="gold.dim_product", tables=hierarchy(
            products=PRODUCTS + rows("product_id product_name subcategory_id list_price", ("P07", "Headlamp", 99, 29.0))))),
    ],
    mutants=[FLATTEN.replace("LEFT JOIN source.erp_categories", "JOIN source.erp_categories"),
             FLATTEN.replace("COALESCE(c.category_name, 'Unassigned')", "COALESCE(c.category_name, s.subcategory_name)")],
    hints=["An inner join keeps only the rows that match on both sides.",
           "LEFT JOIN both levels, then COALESCE the missing names."],
    explanation=("LEFT JOINs keep every product even when a level of the hierarchy is missing, and COALESCE gives "
                 "those rows a visible 'Unassigned' member instead of NULL (a NULL category disappears or shows as "
                 "blank in most reports). An inner join silently drops the gift card and any product whose "
                 "subcategory points nowhere, so revenue by category no longer adds up to total revenue."),
    follow_ups=["When would you keep a snowflake anyway? Think about a very large hierarchy shared by several "
                "dimensions, or a model where the hierarchy changes independently."],
)

# =================================================================================================
# 2. Surrogate keys and the unknown member
# =================================================================================================
CATALOG = rows("product_id product_name category",
               ("P01", "Trail Tent 2P", "Camping"), ("P02", "Down Bag -5", "Camping"), ("P03", "Rain Jacket", "Apparel"))
LINES = rows("order_id line_number product_id quantity net_amount",
             ("SO1", 1, "P01", 1, 199.0), ("SO1", 2, "P03", 2, 188.0), ("SO2", 1, "P02", 1, 159.0),
             ("SO3", 1, "P99", 1, 75.0), ("SO3", 2, "P03", 1, 99.0))


def keyed(lines=LINES, products=CATALOG):
    return [T("source.erp_products", products), T("source.shop_order_lines", lines)]


UNKNOWN = code("""
    CREATE OR REPLACE TABLE gold.dim_product AS
    SELECT ROW_NUMBER() OVER (ORDER BY product_id) AS product_key, product_id, product_name, category
    FROM source.erp_products
    UNION ALL
    SELECT -1, 'UNKNOWN', 'Unknown product', 'Unknown';

    CREATE OR REPLACE TABLE gold.fct_sales AS
    SELECT l.order_id, l.line_number, COALESCE(d.product_key, -1) AS product_key, l.quantity, l.net_amount
    FROM source.shop_order_lines AS l
    LEFT JOIN gold.dim_product AS d ON d.product_id = l.product_id;
""")
REVENUE_BY_CATEGORY = ("SELECT d.category, SUM(f.net_amount) AS revenue FROM gold.fct_sales AS f "
                       "JOIN gold.dim_product AS d ON d.product_key = f.product_key GROUP BY d.category")
exercise(
    id="dwh-surrogate-unknown", title="Surrogate keys and the unknown member", difficulty="easy",
    topics=["surrogate-keys", "unknown-member", "facts"],
    prompt=("Build gold.dim_product (product_key, product_id, product_name, category) with product_key = "
            "ROW_NUMBER() OVER (ORDER BY product_id), plus the unknown member: product_key -1, product_id 'UNKNOWN', "
            "product_name 'Unknown product', category 'Unknown'. Then build gold.fct_sales (order_id, line_number, "
            "product_key, quantity, net_amount) from source.shop_order_lines: one row per line, product_key looked up "
            "in the dimension, and -1 when the product is not in it (the shop sells items the ERP has not sent yet)."),
    sections=[("Why surrogate keys", "A surrogate key is a meaningless integer the warehouse owns. It stays stable "
               "when a source renames or reuses its codes, it lets one business key have several versions (type 2), "
               "and it gives missing references somewhere to point: the unknown member (-1). A fact row with a NULL "
               "key vanishes from every report that joins the dimension."),
              ("Graded", "gold.fct_sales, revenue by category through the dimension (the report every user runs), "
               "and the rows of gold.dim_product.")],
    starter=code("""
        CREATE OR REPLACE TABLE gold.dim_product AS
        SELECT ROW_NUMBER() OVER (ORDER BY product_id) AS product_key, product_id, product_name, category
        FROM source.erp_products;

        CREATE OR REPLACE TABLE gold.fct_sales AS
        SELECT l.order_id, l.line_number, d.product_key, l.quantity, l.net_amount
        FROM source.shop_order_lines AS l
        JOIN gold.dim_product AS d ON d.product_id = l.product_id;
    """),
    solution=UNKNOWN,
    fixtures=[
        ("fact", "visible", S("table", tables=keyed(), table="gold.fct_sales")),
        ("report", "hidden", S("result", tables=keyed(), query=REVENUE_BY_CATEGORY)),
        ("dimension", "edge", S("table", tables=keyed(lines=LINES[:2]), table="gold.dim_product")),
    ],
    mutants=[UNKNOWN.replace("COALESCE(d.product_key, -1)", "d.product_key"),
             UNKNOWN.replace("LEFT JOIN gold.dim_product", "JOIN gold.dim_product"),
             UNKNOWN.replace("\nUNION ALL\nSELECT -1, 'UNKNOWN', 'Unknown product', 'Unknown';", ";")],
    hints=["Add the -1 row with UNION ALL when you build the dimension.",
           "LEFT JOIN the dimension and COALESCE the key to -1."],
    explanation=("The LEFT JOIN keeps the line of the product the ERP does not know yet, and COALESCE points it to the "
                 "unknown member, which exists in the dimension. Revenue by category then still adds up to total "
                 "revenue, with the unexplained part visible as 'Unknown' instead of silently missing. A NULL key or an "
                 "inner join loses the sale in every report that joins the dimension."),
    follow_ups=["When the ERP sends P99 later, what should happen to the sales already pointing to -1? See the late "
                "arriving dimension exercise for the inferred member technique."],
)

# =================================================================================================
# 3. Date dimension
# =================================================================================================
DATE_COLUMNS = ("date_key, full_date, calendar_year, calendar_quarter, month_number, month_name, day_name, "
                "is_weekend, fiscal_year, fiscal_quarter")
DATE_DIM = code("""
    CREATE OR REPLACE TABLE gold.dim_date AS
    SELECT CAST(strftime(d, '%Y%m%d') AS INTEGER) AS date_key,
           CAST(d AS DATE) AS full_date,
           year(d) AS calendar_year,
           quarter(d) AS calendar_quarter,
           month(d) AS month_number,
           monthname(d) AS month_name,
           dayname(d) AS day_name,
           isodow(d) >= 6 AS is_weekend,
           CASE WHEN month(d) >= 7 THEN year(d) + 1 ELSE year(d) END AS fiscal_year,
           (month(d) + 5) % 12 // 3 + 1 AS fiscal_quarter
    FROM generate_series(DATE '2026-01-01', DATE '2026-12-31', INTERVAL 1 DAY) AS days(d)
    UNION ALL
    SELECT -1, NULL, NULL, NULL, NULL, 'Unknown', 'Unknown', NULL, NULL, NULL;
""")
exercise(
    id="dwh-date-dimension", title="Build a date dimension with a fiscal calendar", difficulty="easy",
    topics=["date-dimension", "dimensions", "role-playing"],
    prompt=("Build gold.dim_date for every day of 2026 with the columns " + DATE_COLUMNS + ". date_key is the "
            "integer yyyymmdd (20260105). month_name and day_name are English names ('January', 'Monday'); "
            "is_weekend is TRUE on Saturday and Sunday. The fiscal year starts on 1 July and is named after the "
            "year it ends in: 2026-07-01 is in fiscal year 2027, fiscal quarter 1; 2026-06-30 is in fiscal year "
            "2026, fiscal quarter 4. Add the unknown row: date_key -1, month_name and day_name 'Unknown', every "
            "other column NULL."),
    sections=[("Why a date table", "Every fact joins a date. A date dimension holds the calendar and fiscal "
               "attributes once (and holidays, weeks, periods...), so reports never recompute them and every fact "
               "uses the same definitions. One date table can play several roles (order date, ship date): see the "
               "star model exercise."),
              ("Graded", "A few chosen days (a Sunday, the fiscal year boundary), the number of days and weekend days, "
               "and the number of days per fiscal year and quarter.")],
    starter=code("""
        CREATE OR REPLACE TABLE gold.dim_date AS
        SELECT CAST(strftime(d, '%Y%m%d') AS INTEGER) AS date_key,
               CAST(d AS DATE) AS full_date,
               year(d) AS calendar_year,
               quarter(d) AS calendar_quarter,
               month(d) AS month_number,
               monthname(d) AS month_name,
               dayname(d) AS day_name,
               dayofweek(d) IN (6, 7) AS is_weekend,
               year(d) AS fiscal_year,
               quarter(d) AS fiscal_quarter
        FROM generate_series(DATE '2026-01-01', DATE '2026-12-31', INTERVAL 1 DAY) AS days(d);
    """),
    solution=DATE_DIM,
    fixtures=[
        ("sample-days", "visible", S("result", query=(
            "SELECT * FROM gold.dim_date WHERE date_key IN (20260101, 20260104, 20260630, 20260701, 20261003, "
            "20261231, -1)"))),
        ("counts", "hidden", S("result", query=(
            "SELECT COUNT(*) AS days, COUNT(DISTINCT full_date) AS dates, "
            "COUNT(*) FILTER (WHERE is_weekend) AS weekend_days FROM gold.dim_date WHERE date_key > 0"))),
        ("fiscal", "edge", S("result", query=(
            "SELECT fiscal_year, fiscal_quarter, COUNT(*) AS days, MIN(full_date) AS first_day "
            "FROM gold.dim_date WHERE date_key > 0 GROUP BY fiscal_year, fiscal_quarter"))),
    ],
    mutants=[DATE_DIM.replace("CASE WHEN month(d) >= 7 THEN year(d) + 1 ELSE year(d) END",
                              "CASE WHEN month(d) >= 7 THEN year(d) ELSE year(d) - 1 END"),
             DATE_DIM.replace("isodow(d) >= 6", "dayofweek(d) IN (6, 7)"),
             DATE_DIM.replace("generate_series(DATE '2026-01-01', DATE '2026-12-31'", "range(DATE '2026-01-01', DATE '2026-12-31'")],
    hints=["DuckDB's dayofweek() numbers Sunday 0 to Saturday 6; isodow() numbers Monday 1 to Sunday 7.",
           "generate_series includes its end; range does not.",
           "Months 7 to 12 belong to the next fiscal year. (month + 5) % 12 // 3 + 1 turns July into quarter 1 (// is integer division)."],
    explanation=("A generated calendar with one row per day, integer smart keys (yyyymmdd) that sort and partition "
                 "well, and the fiscal attributes computed once. The traps are all conventions: which day numbering "
                 "the engine uses for weekends, whether the series includes its last day, and which year names a "
                 "fiscal year. Getting them right in one table means every report agrees."),
    follow_ups=["Add is_holiday from a holiday table, and a week_start column (Monday). Why do smart date keys break "
                "the 'meaningless surrogate key' rule, and why is it accepted for dates?"],
)

# =================================================================================================
# 4. Junk dimension
# =================================================================================================
ORDERS = rows("order_id channel payment_type is_gift order_total",
              ("SO1", "web", "card", False, 120.0), ("SO2", "store", "cash", False, 80.0),
              ("SO3", "web", "card", True, 60.0), ("SO4", "marketplace", None, False, 45.0),
              ("SO5", "web", "card", False, 30.0))
JUNK = code("""
    CREATE OR REPLACE TABLE gold.dim_order_profile AS
    SELECT ROW_NUMBER() OVER (ORDER BY channel, payment_type, is_gift) AS order_profile_key,
           channel, payment_type, is_gift
    FROM (SELECT DISTINCT channel,
                 COALESCE(payment_type, 'not provided') AS payment_type,
                 COALESCE(is_gift, FALSE) AS is_gift
          FROM source.shop_orders) AS profiles;

    CREATE OR REPLACE TABLE gold.fct_orders AS
    SELECT o.order_id, p.order_profile_key, o.order_total
    FROM source.shop_orders AS o
    LEFT JOIN gold.dim_order_profile AS p
           ON p.channel = o.channel
          AND p.payment_type = COALESCE(o.payment_type, 'not provided')
          AND p.is_gift = COALESCE(o.is_gift, FALSE);
""")
exercise(
    id="dwh-junk-dimension", title="Gather low-cardinality flags in a junk dimension", difficulty="easy",
    topics=["junk-dimension", "dimensions", "nulls"],
    prompt=("Orders carry three small flags: channel, payment_type and is_gift. Instead of three tiny dimensions, "
            "build one junk dimension gold.dim_order_profile (order_profile_key, channel, payment_type, is_gift) "
            "with one row per combination that occurs, and gold.fct_orders (order_id, order_profile_key, order_total). "
            "A missing payment_type is stored as 'not provided' and a missing is_gift as FALSE. order_profile_key is "
            "ROW_NUMBER() OVER (ORDER BY channel, payment_type, is_gift), after replacing the missing values. Every "
            "order gets a key."),
    sections=[("Junk dimension", "Low-cardinality flags and indicators that belong to no real dimension are grouped "
               "in one small table of their combinations. The fact keeps a single key instead of several text columns "
               "or several one-column dimensions."),
              ("Graded", "gold.fct_orders, the rows of gold.dim_order_profile, and orders whose is_gift is missing.")],
    starter=code("""
        CREATE OR REPLACE TABLE gold.dim_order_profile AS
        SELECT ROW_NUMBER() OVER (ORDER BY channel, payment_type, is_gift) AS order_profile_key,
               channel, payment_type, is_gift
        FROM (SELECT DISTINCT channel, payment_type, is_gift FROM source.shop_orders) AS profiles;

        CREATE OR REPLACE TABLE gold.fct_orders AS
        SELECT o.order_id, p.order_profile_key, o.order_total
        FROM source.shop_orders AS o
        LEFT JOIN gold.dim_order_profile AS p
               ON p.channel = o.channel AND p.payment_type = o.payment_type AND p.is_gift = o.is_gift;
    """),
    solution=JUNK,
    fixtures=[
        ("fact", "visible", S("table", tables=[T("source.shop_orders", ORDERS)], table="gold.fct_orders")),
        ("dimension", "hidden", S("table", tables=[T("source.shop_orders", ORDERS)], table="gold.dim_order_profile")),
        ("missing-gift-flag", "edge", S("table", table="gold.fct_orders", tables=[T("source.shop_orders", ORDERS + rows(
            "order_id channel payment_type is_gift order_total", ("SO6", "store", "cash", None, 25.0)))])),
    ],
    mutants=[JUNK.replace("AND p.payment_type = COALESCE(o.payment_type, 'not provided')", "AND p.payment_type = o.payment_type"),
             JUNK.replace("COALESCE(payment_type, 'not provided') AS payment_type", "payment_type")
                 .replace("AND p.payment_type = COALESCE(o.payment_type, 'not provided')",
                          "AND p.payment_type IS NOT DISTINCT FROM o.payment_type"),
             JUNK.replace("AND p.is_gift = COALESCE(o.is_gift, FALSE)", "AND p.is_gift = o.is_gift")],
    hints=["NULL = NULL is not true, so a join on a NULL column never matches.",
           "Replace missing values the same way in the dimension and in the lookup."],
    explanation=("Replacing the missing values before building the combinations gives every order a profile, and the "
                 "lookup must apply exactly the same replacements. Joining on a column that is NULL never matches "
                 "(NULL = NULL is unknown), so those orders get no key and fall out of every report on the profile."),
    follow_ups=["If channel had 50 values and payment_type 20, would you still pre-build every combination, or only "
                "those seen? What changes when a new combination appears tomorrow?"],
)

# =================================================================================================
# 5. SCD type 1
# =================================================================================================
DIM1_COLUMNS = "customer_key customer_id customer_name city email"
DIM1 = rows(DIM1_COLUMNS, (1, "C001", "Alice Martin", "Paris", "alice@example.com"),
            (2, "C002", "Bruno Keller", "Geneva", "bruno@example.com"),
            (3, "C003", "Chloe Diaz", "Madrid", "chloe@example.com"))
UPD = "customer_id customer_name city email"
DAY1_UPDATES = rows(UPD, ("C002", "Bruno Keller", "Zurich", "bruno@example.com"),
                    ("C004", "David Okafor", "Lagos", "david@example.com"))
DAY2_UPDATES = rows(UPD, ("C001", "Alice Martin", "Paris", "alice@example.com"),
                    ("C004", "David Okafor", "Lagos", "d.okafor@example.com"),
                    ("C005", "Emma Rossi", "Milan", "emma@example.com"))


def scd1_runs(*batches):
    return [{"tables": [T("silver.customer_updates", batch)]} for batch in batches]


def dim1():
    return T("gold.dim_customer", DIM1, types={"customer_key": "INTEGER"})


SCD1 = code("""
    -- Type 1: overwrite the attributes in place; the customer keeps its key.
    UPDATE gold.dim_customer AS d
    SET customer_name = u.customer_name, city = u.city, email = u.email
    FROM silver.customer_updates AS u
    WHERE d.customer_id = u.customer_id;

    -- New customers get the next keys.
    INSERT INTO gold.dim_customer (customer_key, customer_id, customer_name, city, email)
    SELECT (SELECT MAX(customer_key) FROM gold.dim_customer) + ROW_NUMBER() OVER (ORDER BY u.customer_id),
           u.customer_id, u.customer_name, u.city, u.email
    FROM silver.customer_updates AS u
    WHERE NOT EXISTS (SELECT 1 FROM gold.dim_customer AS d WHERE d.customer_id = u.customer_id);
""")
SALES_BY_KEY = rows("order_id customer_key net_amount", ("SO1", 1, 100.0), ("SO2", 2, 50.0), ("SO3", 3, 70.0))
exercise(
    id="dwh-scd1-overwrite", title="Slowly changing dimension type 1: overwrite in place", difficulty="easy",
    topics=["scd-type-1", "surrogate-keys", "incremental-load"],
    prompt=("gold.dim_customer (customer_key, customer_id, customer_name, city, email) is type 1: it keeps only the "
            "current values. Each day silver.customer_updates brings the customers created or changed in the CRM "
            "(customer_id, customer_name, city, email). Write the daily load: update existing customers in place, "
            "keeping their customer_key, and insert new ones with keys continuing after the highest existing key, "
            "numbered in customer_id order."),
    sections=[("Type 1", "Type 1 overwrites: the dimension shows today's values and forgets the old ones, so past "
               "sales are reported with the customer's current city. It suits corrections and attributes whose "
               "history nobody analyses. The customer_key must never change: facts already point to it."),
              ("Runs", RUNS_NOTE.format(n="two or three", batch="silver.customer_updates")),
              ("Graded", "gold.dim_customer after two days, after replaying the second day, and revenue by customer "
               "through the keys that existing sales already use.")],
    starter=code("""
        INSERT INTO gold.dim_customer (customer_key, customer_id, customer_name, city, email)
        SELECT (SELECT MAX(customer_key) FROM gold.dim_customer) + ROW_NUMBER() OVER (ORDER BY customer_id),
               customer_id, customer_name, city, email
        FROM silver.customer_updates;
    """),
    solution=SCD1,
    fixtures=[
        ("two-days", "visible", S("table", tables=[dim1()], table="gold.dim_customer",
                                  runs=scd1_runs(DAY1_UPDATES, DAY2_UPDATES))),
        ("replayed-day", "hidden", S("table", tables=[dim1()], table="gold.dim_customer",
                                     runs=scd1_runs(DAY1_UPDATES, DAY2_UPDATES, DAY2_UPDATES))),
        ("existing-sales", "edge", S("result", tables=[dim1(), T("gold.fct_sales", SALES_BY_KEY)],
                                     runs=scd1_runs(DAY1_UPDATES, DAY2_UPDATES), query=(
            "SELECT d.customer_id, d.city, SUM(f.net_amount) AS revenue FROM gold.fct_sales AS f "
            "JOIN gold.dim_customer AS d ON d.customer_key = f.customer_key GROUP BY d.customer_id, d.city"))),
    ],
    mutants=[code("""
        DELETE FROM gold.dim_customer WHERE customer_id IN (SELECT customer_id FROM silver.customer_updates);
        INSERT INTO gold.dim_customer (customer_key, customer_id, customer_name, city, email)
        SELECT (SELECT MAX(customer_key) FROM gold.dim_customer) + ROW_NUMBER() OVER (ORDER BY customer_id),
               customer_id, customer_name, city, email
        FROM silver.customer_updates;
    """), SCD1.split("-- New customers")[0]],
    hints=["UPDATE ... FROM changes existing rows; INSERT ... WHERE NOT EXISTS adds only the new customers.",
           "Deleting and re-inserting a customer gives it a new key: what happens to the sales pointing to the old one?"],
    explanation=("An UPDATE in place keeps each customer's surrogate key, so every fact row already loaded still "
                 "points to the right customer, and the NOT EXISTS guard makes the load rerunnable. Deleting and "
                 "re-inserting looks equivalent in the dimension, but the customer gets a new key and the existing "
                 "sales now point to nobody (or to someone else)."),
    follow_ups=["Write the same load as one MERGE statement. What does a MERGE need to generate the new keys?"],
)

# =================================================================================================
# 6. SCD type 2
# =================================================================================================
DIM2_COLUMNS = "customer_key customer_id city segment valid_from valid_to is_current"
DIM2 = rows(DIM2_COLUMNS,
            (1, "C001", "Paris", "Consumer", "2026-01-01", "2026-02-15", False),
            (2, "C001", "Lyon", "Consumer", "2026-02-15", "9999-12-31", True),
            (3, "C002", "Geneva", "Small Business", "2026-01-01", "9999-12-31", True),
            (4, "C003", "Madrid", None, "2026-01-01", "9999-12-31", True))
SNAP = "snapshot_date customer_id city segment"
SNAP1 = rows(SNAP, ("2026-03-01", "C001", "Lyon", "Consumer"), ("2026-03-01", "C002", "Zurich", "Small Business"),
             ("2026-03-01", "C003", "Madrid", None), ("2026-03-01", "C004", "Oslo", "Corporate"))
SNAP2 = rows(SNAP, ("2026-03-02", "C001", "Lyon", "Consumer"), ("2026-03-02", "C002", "Zurich", "Small Business"),
             ("2026-03-02", "C003", "Madrid", "Consumer"), ("2026-03-02", "C004", "Oslo", "Corporate"))
SCD2_MODEL = {"tables": [{"name": "gold.dim_customer", "role": "dimension", "key": "customer_key",
                          "business_key": ["customer_id"],
                          "scd": {"type": 2, "valid_from": "valid_from", "valid_to": "valid_to",
                                  "current_flag": "is_current"}}]}


def snap_runs(*snapshots):
    return [{"tables": [T("silver.customer_snapshot", s, types={"segment": "VARCHAR"})]} for s in snapshots]


def dim2():
    return T("gold.dim_customer", DIM2, types={"segment": "VARCHAR", "customer_key": "INTEGER"})


SCD2 = code("""
    -- 1. Close the current version of every customer whose tracked attributes changed.
    UPDATE gold.dim_customer AS d
    SET valid_to = s.snapshot_date, is_current = FALSE
    FROM silver.customer_snapshot AS s
    WHERE d.customer_id = s.customer_id
      AND d.is_current
      AND (d.city IS DISTINCT FROM s.city OR d.segment IS DISTINCT FROM s.segment);

    -- 2. Open a version for every customer without a current one: the changed ones and the new ones.
    INSERT INTO gold.dim_customer (customer_key, customer_id, city, segment, valid_from, valid_to, is_current)
    SELECT (SELECT MAX(customer_key) FROM gold.dim_customer) + ROW_NUMBER() OVER (ORDER BY s.customer_id),
           s.customer_id, s.city, s.segment, s.snapshot_date, DATE '9999-12-31', TRUE
    FROM silver.customer_snapshot AS s
    WHERE NOT EXISTS (SELECT 1 FROM gold.dim_customer AS d WHERE d.customer_id = s.customer_id AND d.is_current);
""")
exercise(
    id="dwh-scd2-apply", title="Slowly changing dimension type 2: keep the history", difficulty="medium",
    topics=["scd-type-2", "incremental-load", "nulls"],
    prompt=("gold.dim_customer (customer_key, customer_id, city, segment, valid_from, valid_to, is_current) keeps "
            "the history of city and segment: one row per version. valid_to is exclusive and 9999-12-31 while the "
            "version is current. Each day silver.customer_snapshot (snapshot_date, customer_id, city, segment) holds "
            "every customer as the CRM sees them that day. Write the daily load: when city or segment changed "
            "(NULL counts as a value), close the current version on snapshot_date and open a new one from "
            "snapshot_date; open a first version for new customers; do nothing for unchanged ones. New versions get "
            "keys after the highest key, numbered in customer_id order."),
    sections=[("Type 2", "Type 2 adds a row for each change, so a sale can be reported with the city the customer "
               "had when they bought. Each version has its own surrogate key; facts store the key of the version "
               "valid at the time of the event. valid_from/valid_to (exclusive end) tell which version was valid "
               "when, and is_current finds today's one."),
              ("Runs", RUNS_NOTE.format(n="one to three", batch="silver.customer_snapshot")),
              ("Graded", "The dimension after one day, after two days (including a segment that goes from NULL to a "
               "value), after replaying a day, and the dimension's SCD2 checks: one current version per customer, no "
               "overlap and no gap between versions.")],
    starter=code("""
        -- Today's values replace yesterday's: the history is lost.
        UPDATE gold.dim_customer AS d
        SET city = s.city, segment = s.segment
        FROM silver.customer_snapshot AS s
        WHERE d.customer_id = s.customer_id AND d.is_current;
    """),
    solution=SCD2,
    fixtures=[
        ("first-day", "visible", S("table", tables=[dim2()], table="gold.dim_customer", runs=snap_runs(SNAP1))),
        ("second-day", "hidden", S("table", tables=[dim2()], table="gold.dim_customer", runs=snap_runs(SNAP1, SNAP2))),
        ("replayed-day", "hidden", S("table", tables=[dim2()], table="gold.dim_customer",
                                     runs=snap_runs(SNAP1, SNAP2, SNAP2))),
        ("scd2-checks", "edge", S("checks", tables=[dim2()], model=SCD2_MODEL, runs=snap_runs(SNAP1, SNAP2, SNAP2))),
    ],
    mutants=[SCD2.replace("(d.city IS DISTINCT FROM s.city OR d.segment IS DISTINCT FROM s.segment)",
                          "(d.city <> s.city OR d.segment <> s.segment)"),
             SCD2.replace("SET valid_to = s.snapshot_date,", "SET valid_to = s.snapshot_date - INTERVAL 1 DAY,"),
             SCD2.replace("WHERE d.customer_id = s.customer_id AND d.is_current);", "WHERE d.customer_id = s.customer_id);"),
             SCD2.replace("  AND d.is_current\n", "")],
    hints=["Compare with the CURRENT version only, and use IS DISTINCT FROM: NULL <> 'Consumer' is not true.",
           "Close first, then insert for every customer who has no current version left."],
    explanation=("Closing the changed versions first leaves exactly the changed and the new customers without a "
                 "current version, so one INSERT ... WHERE NOT EXISTS opens all the new versions, and replaying the "
                 "same snapshot finds nothing to change. IS DISTINCT FROM treats NULL as a value, so a segment going "
                 "from NULL to 'Consumer' is a change. The closing date equals the next valid_from, so versions never "
                 "overlap and never leave a gap."),
    follow_ups=["A customer disappears from the snapshot: should the load close its current version? What would a "
                "reappearance do then?", "Add a row hash of the tracked columns to detect changes: why is it useful "
                "with 40 tracked columns?"],
)

# =================================================================================================
# 7. Type 1 attribute inside a type 2 dimension
# =================================================================================================
DIM6_COLUMNS = "customer_key customer_id email city valid_from valid_to is_current"
DIM6 = rows(DIM6_COLUMNS,
            (1, "C001", "alice@old.example", "Paris", "2026-01-01", "2026-02-15", False),
            (2, "C001", "alice@old.example", "Lyon", "2026-02-15", "9999-12-31", True),
            (3, "C002", "bruno@example.com", "Geneva", "2026-01-01", "9999-12-31", True))
SNAP6 = "snapshot_date customer_id email city"
SNAP6_1 = rows(SNAP6, ("2026-03-01", "C001", "alice@new.example", "Lyon"),
               ("2026-03-01", "C002", "bruno@example.com", "Zurich"), ("2026-03-01", "C003", "chloe@example.com", "Madrid"))
SNAP6_2 = rows(SNAP6, ("2026-03-02", "C001", "alice@new.example", "Lyon"),
               ("2026-03-02", "C002", "bruno.k@example.com", "Basel"), ("2026-03-02", "C003", "chloe@example.com", "Madrid"))
HYBRID = code("""
    -- email is type 1: the new value overwrites every version of the customer.
    UPDATE gold.dim_customer AS d
    SET email = s.email
    FROM silver.customer_snapshot AS s
    WHERE d.customer_id = s.customer_id AND d.email IS DISTINCT FROM s.email;

    -- city is type 2: close the current version when it changes...
    UPDATE gold.dim_customer AS d
    SET valid_to = s.snapshot_date, is_current = FALSE
    FROM silver.customer_snapshot AS s
    WHERE d.customer_id = s.customer_id AND d.is_current AND d.city IS DISTINCT FROM s.city;

    -- ...and open a new one (new customers too).
    INSERT INTO gold.dim_customer (customer_key, customer_id, email, city, valid_from, valid_to, is_current)
    SELECT (SELECT MAX(customer_key) FROM gold.dim_customer) + ROW_NUMBER() OVER (ORDER BY s.customer_id),
           s.customer_id, s.email, s.city, s.snapshot_date, DATE '9999-12-31', TRUE
    FROM silver.customer_snapshot AS s
    WHERE NOT EXISTS (SELECT 1 FROM gold.dim_customer AS d WHERE d.customer_id = s.customer_id AND d.is_current);
""")


def hybrid_runs(*snapshots):
    return [{"tables": [T("silver.customer_snapshot", s)]} for s in snapshots]


def dim6():
    return T("gold.dim_customer", DIM6, types={"customer_key": "INTEGER"})


exercise(
    id="dwh-scd2-type1-attribute", title="A type 1 attribute inside a type 2 dimension", difficulty="medium",
    topics=["scd-type-2", "scd-type-1", "scd-type-6"],
    prompt=("gold.dim_customer (customer_key, customer_id, email, city, valid_from, valid_to, is_current) tracks the "
            "history of city (type 2), but email is type 1: a new email is a correction that must appear on every "
            "version of the customer, and never creates a version. Each day silver.customer_snapshot "
            "(snapshot_date, customer_id, email, city) holds every customer. Write the daily load. New versions and "
            "new customers get keys after the highest key, in customer_id order; versions close on snapshot_date "
            "(exclusive valid_to, 9999-12-31 while current)."),
    sections=[("Mixing types", "A dimension usually mixes types per column: type 2 for what analysts slice history by "
               "(city, segment), type 1 for corrections and contact data (email). Overwriting the type 1 column on "
               "all versions keeps it consistent whichever version a fact points to. Adding the current value next "
               "to the historical one on every row is called type 6 (1 + 2 + 3)."),
              ("Runs", RUNS_NOTE.format(n="one to three", batch="silver.customer_snapshot")),
              ("Graded", "The dimension after one day, after two days (a customer changing both email and city), and "
               "after replaying the second day.")],
    starter=code("""
        -- Every change opens a version, and the old versions keep the old email.
        UPDATE gold.dim_customer AS d
        SET valid_to = s.snapshot_date, is_current = FALSE
        FROM silver.customer_snapshot AS s
        WHERE d.customer_id = s.customer_id AND d.is_current
          AND (d.city IS DISTINCT FROM s.city OR d.email IS DISTINCT FROM s.email);

        INSERT INTO gold.dim_customer (customer_key, customer_id, email, city, valid_from, valid_to, is_current)
        SELECT (SELECT MAX(customer_key) FROM gold.dim_customer) + ROW_NUMBER() OVER (ORDER BY s.customer_id),
               s.customer_id, s.email, s.city, s.snapshot_date, DATE '9999-12-31', TRUE
        FROM silver.customer_snapshot AS s
        WHERE NOT EXISTS (SELECT 1 FROM gold.dim_customer AS d WHERE d.customer_id = s.customer_id AND d.is_current);
    """),
    solution=HYBRID,
    fixtures=[
        ("first-day", "visible", S("table", tables=[dim6()], table="gold.dim_customer", runs=hybrid_runs(SNAP6_1))),
        ("second-day", "hidden", S("table", tables=[dim6()], table="gold.dim_customer", runs=hybrid_runs(SNAP6_1, SNAP6_2))),
        ("replayed-day", "edge", S("table", tables=[dim6()], table="gold.dim_customer",
                                   runs=hybrid_runs(SNAP6_1, SNAP6_2, SNAP6_2))),
    ],
    mutants=[HYBRID.replace("WHERE d.customer_id = s.customer_id AND d.email IS DISTINCT FROM s.email;",
                            "WHERE d.customer_id = s.customer_id AND d.is_current AND d.email IS DISTINCT FROM s.email;"),
             HYBRID[HYBRID.index("-- city is type 2"):]],
    hints=["The type 1 UPDATE has no is_current filter: it rewrites all the customer's rows.",
           "Only a city change closes a version."],
    explanation=("The type 1 update runs on every row of the customer, so each historical version shows the corrected "
                 "email; the type 2 part then only looks at city. Creating a version for an email change multiplies "
                 "versions for no analytical reason, and updating only the current row leaves the old email on the "
                 "versions that old sales point to."),
    follow_ups=["Add current_city (type 6): every version also shows the customer's city today. Which statement "
                "maintains it?"],
)

# =================================================================================================
# 8. SCD type 3
# =================================================================================================
DIM3 = rows("customer_key customer_id segment previous_segment segment_changed_on",
            (1, "C001", "Consumer", None, None), (2, "C002", "Small Business", None, None), (3, "C003", None, None, None))
SNAP3 = "snapshot_date customer_id segment"
SNAP3_1 = rows(SNAP3, ("2026-03-01", "C001", "Corporate"), ("2026-03-01", "C002", "Small Business"),
               ("2026-03-01", "C003", "Consumer"))
SNAP3_2 = rows(SNAP3, ("2026-03-02", "C001", "Public Sector"), ("2026-03-02", "C002", "Small Business"),
               ("2026-03-02", "C003", "Consumer"))
SCD3 = code("""
    UPDATE gold.dim_customer AS d
    SET previous_segment = d.segment,
        segment = s.segment,
        segment_changed_on = s.snapshot_date
    FROM silver.customer_snapshot AS s
    WHERE d.customer_id = s.customer_id
      AND d.segment IS DISTINCT FROM s.segment;
""")


def dim3():
    return T("gold.dim_customer", DIM3, types={"segment": "VARCHAR", "previous_segment": "VARCHAR",
                                               "segment_changed_on": "DATE", "customer_key": "INTEGER"})


exercise(
    id="dwh-scd3-previous-value", title="Slowly changing dimension type 3: the previous value", difficulty="easy",
    topics=["scd-type-3", "incremental-load", "nulls"],
    prompt=("Sales managers want to compare each customer's segment with the one before the last reorganisation, "
            "without full history. gold.dim_customer (customer_key, customer_id, segment, previous_segment, "
            "segment_changed_on) is type 3 on segment. Each day silver.customer_snapshot (snapshot_date, customer_id, "
            "segment) holds every existing customer. When a segment changes (NULL counts as a value), keep the old "
            "one in previous_segment, store the new one, and set segment_changed_on to snapshot_date. An unchanged "
            "customer is left untouched."),
    sections=[("Type 3", "Type 3 keeps a limited history in extra columns (current and previous value) on one row. "
               "Reports can show 'before / after' side by side, but a second change overwrites the first previous "
               "value: only one step of history survives."),
              ("Runs", RUNS_NOTE.format(n="one to three", batch="silver.customer_snapshot")),
              ("Graded", "The dimension after one day, after two changes in a row, and after replaying a day.")],
    starter=code("""
        UPDATE gold.dim_customer AS d
        SET segment = s.segment
        FROM silver.customer_snapshot AS s
        WHERE d.customer_id = s.customer_id;
    """),
    solution=SCD3,
    fixtures=[
        ("first-day", "visible", S("table", tables=[dim3()], table="gold.dim_customer", runs=snap_runs(SNAP3_1))),
        ("second-change", "hidden", S("table", tables=[dim3()], table="gold.dim_customer", runs=snap_runs(SNAP3_1, SNAP3_2))),
        ("replayed-day", "edge", S("table", tables=[dim3()], table="gold.dim_customer",
                                   runs=snap_runs(SNAP3_1, SNAP3_2, SNAP3_2))),
    ],
    mutants=[SCD3.replace("\n  AND d.segment IS DISTINCT FROM s.segment;", ";"),
             SCD3.replace("AND d.segment IS DISTINCT FROM s.segment;", "AND d.segment <> s.segment;")],
    hints=["In an UPDATE, every expression on the right reads the row as it was before the update.",
           "Only update the customers whose segment really changed, or a replay erases previous_segment."],
    explanation=("One UPDATE shifts the current value into previous_segment and stores the new one; SQL evaluates all "
                 "right-hand sides on the old row, so the order of the SET clauses does not matter. The change "
                 "condition is what makes the load rerunnable: without it a replay copies the current segment into "
                 "previous_segment and the real previous value is lost."),
    follow_ups=["When does type 3 beat type 2? Think of a one-off reorganisation where everyone wants 'old vs new "
                "territory' on the same row."],
)

# =================================================================================================
# 9. Point-in-time join
# =================================================================================================
PIT_DIM = rows("customer_key customer_id segment valid_from valid_to is_current",
               (1, "C001", "Consumer", "2026-01-01", "2026-02-15", False),
               (2, "C001", "Corporate", "2026-02-15", "9999-12-31", True),
               (3, "C002", "Small Business", "2026-01-01", "9999-12-31", True),
               (4, "C003", "Consumer", "2026-02-01", "9999-12-31", True))
PIT_SALES = rows("order_id customer_id order_date net_amount",
                 ("SO1", "C001", "2026-01-10", 100.0), ("SO2", "C001", "2026-02-20", 200.0),
                 ("SO3", "C002", "2026-01-15", 50.0))
PIT = code("""
    SELECT COALESCE(d.segment, 'Unknown') AS segment, SUM(s.net_amount) AS revenue
    FROM silver.sales AS s
    LEFT JOIN gold.dim_customer AS d
           ON d.customer_id = s.customer_id
          AND s.order_date >= d.valid_from
          AND s.order_date < d.valid_to
    GROUP BY COALESCE(d.segment, 'Unknown');
""")


def pit(extra=()):
    return [T("gold.dim_customer", PIT_DIM), T("silver.sales", PIT_SALES + list(extra))]


exercise(
    id="dwh-point-in-time", title="Report with the version valid at the time of the sale", difficulty="medium",
    topics=["scd-type-2", "point-in-time", "joins"],
    prompt=("silver.sales (order_id, customer_id, order_date, net_amount) still carries the customer's business "
            "key. gold.dim_customer is type 2 (customer_key, customer_id, segment, valid_from, valid_to, is_current; "
            "valid_to is exclusive). Write a SELECT of revenue by segment as it was when each order was placed: "
            "columns segment and revenue. Sales whose customer has no version valid on the order date count under "
            "'Unknown'."),
    sections=[("Point in time", "Joining a type 2 dimension on the business key alone returns every version; joining "
               "on is_current reports history with today's attributes. The version valid at the event's date is the "
               "one where valid_from <= date < valid_to. That is also how a fact load picks the surrogate key to "
               "store."),
              ("Graded", "Revenue by segment, including an order placed on the very day a customer changed segment "
               "and an order placed before the customer's first version.")],
    starter=code("""
        SELECT d.segment, SUM(s.net_amount) AS revenue
        FROM silver.sales AS s
        JOIN gold.dim_customer AS d ON d.customer_id = s.customer_id AND d.is_current
        GROUP BY d.segment;
    """),
    solution=PIT,
    fixtures=[
        ("by-segment", "visible", S("result", tables=pit())),
        ("change-day", "hidden", S("result", tables=pit(rows("order_id customer_id order_date net_amount",
                                                             ("SO4", "C001", "2026-02-15", 70.0))))),
        ("before-first-version", "edge", S("result", tables=pit(rows("order_id customer_id order_date net_amount",
                                                                     ("SO4", "C001", "2026-02-15", 70.0),
                                                                     ("SO5", "C003", "2026-01-20", 40.0))))),
    ],
    mutants=[PIT.replace("AND s.order_date >= d.valid_from\n      AND s.order_date < d.valid_to",
                         "AND s.order_date BETWEEN d.valid_from AND d.valid_to"),
             PIT.replace("LEFT JOIN gold.dim_customer", "JOIN gold.dim_customer")],
    hints=["valid_to is exclusive: the day a new version starts belongs to the new version only.",
           "A LEFT JOIN keeps sales that no version covers."],
    explanation=("The range condition picks exactly one version per sale, because consecutive versions share the "
                 "boundary date and the end is exclusive. BETWEEN includes valid_to, so a sale on the change day "
                 "matches two versions and is counted twice. The LEFT JOIN plus COALESCE keeps revenue complete when "
                 "a sale predates the first known version."),
    follow_ups=["Rewrite the report for 'revenue by segment as of today': which single change do you make?"],
)

# =================================================================================================
# 10. Late arriving dimension: inferred members
# =================================================================================================
LATE_DIM = rows("customer_key customer_id customer_name city is_inferred",
                (1, "C001", "Alice Martin", "Paris", False), (2, "C002", "Bruno Keller", "Geneva", False))
CRM = "customer_id customer_name city"
ORD = "order_id customer_id net_amount"
LATE_RUN1 = [T("silver.crm_customers", rows(CRM, ("C001", "Alice Martin", "Paris"), ("C002", "Bruno Keller", "Geneva"))),
             T("silver.orders", rows(ORD, ("SO1", "C001", 100.0), ("SO2", "C003", 60.0)))]
LATE_RUN2 = [T("silver.crm_customers", rows(CRM, ("C001", "Alice Martin", "Lyon"), ("C002", "Bruno Keller", "Geneva"),
                                            ("C003", "Chloe Diaz", "Madrid"))),
             T("silver.orders", rows(ORD, ("SO3", "C003", 80.0), ("SO4", "C004", 20.0)))]
LATE_FACT = T("gold.fct_sales", [], columns=["order_id", "customer_key", "net_amount"],
              types={"order_id": "VARCHAR", "customer_key": "INTEGER", "net_amount": "DOUBLE"})
LATE = code("""
    -- 1. CRM batch: overwrite known customers in place (type 1). An inferred member becomes a real one.
    UPDATE gold.dim_customer AS d
    SET customer_name = c.customer_name, city = c.city, is_inferred = FALSE
    FROM silver.crm_customers AS c
    WHERE d.customer_id = c.customer_id;

    INSERT INTO gold.dim_customer (customer_key, customer_id, customer_name, city, is_inferred)
    SELECT (SELECT MAX(customer_key) FROM gold.dim_customer) + ROW_NUMBER() OVER (ORDER BY c.customer_id),
           c.customer_id, c.customer_name, c.city, FALSE
    FROM silver.crm_customers AS c
    WHERE NOT EXISTS (SELECT 1 FROM gold.dim_customer AS d WHERE d.customer_id = c.customer_id);

    -- 2. Customers seen in orders but not sent by the CRM yet: inferred members, with their own key.
    INSERT INTO gold.dim_customer (customer_key, customer_id, customer_name, city, is_inferred)
    SELECT (SELECT MAX(customer_key) FROM gold.dim_customer) + ROW_NUMBER() OVER (ORDER BY o.customer_id),
           o.customer_id, 'Unknown (inferred)', 'Unknown', TRUE
    FROM (SELECT DISTINCT customer_id FROM silver.orders) AS o
    WHERE NOT EXISTS (SELECT 1 FROM gold.dim_customer AS d WHERE d.customer_id = o.customer_id);

    -- 3. Facts, each order once.
    INSERT INTO gold.fct_sales (order_id, customer_key, net_amount)
    SELECT o.order_id, d.customer_key, o.net_amount
    FROM silver.orders AS o
    JOIN gold.dim_customer AS d ON d.customer_id = o.customer_id
    WHERE NOT EXISTS (SELECT 1 FROM gold.fct_sales AS f WHERE f.order_id = o.order_id);
""")


def late(*runs):
    return {"tables": [T("gold.dim_customer", LATE_DIM, types={"customer_key": "INTEGER"}), LATE_FACT],
            "runs": [{"tables": r} for r in runs]}


exercise(
    id="dwh-late-arriving-dimension", title="Late arriving customers: inferred members", difficulty="hard",
    topics=["late-arriving-dimension", "inferred-member", "incremental-load"],
    prompt=("Orders sometimes arrive before the CRM sends the customer. Each day brings silver.crm_customers "
            "(customer_id, customer_name, city: every customer the CRM knows) and silver.orders (order_id, "
            "customer_id, net_amount: the day's new orders). gold.dim_customer (customer_key, customer_id, "
            "customer_name, city, is_inferred) is type 1 and gold.fct_sales (order_id, customer_key, net_amount) "
            "starts empty. Write the daily load: update known customers from the CRM and insert new ones; give "
            "every order customer the CRM has not sent an inferred member (customer_name 'Unknown (inferred)', city "
            "'Unknown', is_inferred TRUE) with its own key; when the CRM later sends that customer, complete the "
            "inferred row in place (is_inferred FALSE) instead of adding a row; load each order once. New keys follow "
            "the highest key in customer_id order, CRM customers first, then inferred members."),
    sections=[("Inferred members", "A fact cannot wait for its dimension. Pointing it to the unknown member (-1) "
               "loses the link for ever: when the customer arrives, the old facts still say 'unknown'. An inferred "
               "member is a placeholder row with the real business key and its own surrogate key; the facts point to "
               "it, and when the dimension row arrives it is filled in place, so the old facts get the real "
               "attributes."),
              ("Runs", RUNS_NOTE.format(n="one to three", batch="silver.crm_customers and silver.orders")),
              ("Graded", "The facts after the first day, the dimension after the customer arrives, and the facts "
               "after replaying the second day.")],
    starter=code("""
        UPDATE gold.dim_customer AS d
        SET customer_name = c.customer_name, city = c.city
        FROM silver.crm_customers AS c
        WHERE d.customer_id = c.customer_id;

        INSERT INTO gold.dim_customer (customer_key, customer_id, customer_name, city, is_inferred)
        SELECT (SELECT MAX(customer_key) FROM gold.dim_customer) + ROW_NUMBER() OVER (ORDER BY c.customer_id),
               c.customer_id, c.customer_name, c.city, FALSE
        FROM silver.crm_customers AS c
        WHERE NOT EXISTS (SELECT 1 FROM gold.dim_customer AS d WHERE d.customer_id = c.customer_id);

        -- Orders of customers the CRM has not sent yet go to the unknown member.
        INSERT INTO gold.fct_sales (order_id, customer_key, net_amount)
        SELECT o.order_id, COALESCE(d.customer_key, -1), o.net_amount
        FROM silver.orders AS o
        LEFT JOIN gold.dim_customer AS d ON d.customer_id = o.customer_id
        WHERE NOT EXISTS (SELECT 1 FROM gold.fct_sales AS f WHERE f.order_id = o.order_id);
    """),
    solution=LATE,
    fixtures=[
        ("first-day-facts", "visible", S("table", table="gold.fct_sales", **late(LATE_RUN1))),
        ("customer-arrives", "hidden", S("table", table="gold.dim_customer", **late(LATE_RUN1, LATE_RUN2))),
        ("replayed-facts", "edge", S("table", table="gold.fct_sales", **late(LATE_RUN1, LATE_RUN2, LATE_RUN2))),
    ],
    mutants=[LATE.replace("WHERE d.customer_id = c.customer_id;", "WHERE d.customer_id = c.customer_id AND NOT d.is_inferred;")
                 .replace("WHERE NOT EXISTS (SELECT 1 FROM gold.dim_customer AS d WHERE d.customer_id = c.customer_id);",
                          "WHERE NOT EXISTS (SELECT 1 FROM gold.dim_customer AS d WHERE d.customer_id = c.customer_id "
                          "AND NOT d.is_inferred);"),
             LATE.replace("\nWHERE NOT EXISTS (SELECT 1 FROM gold.fct_sales AS f WHERE f.order_id = o.order_id);", ";")],
    hints=["Load the CRM first, then create inferred members for the order customers still missing, then the facts.",
           "The CRM update must also match inferred rows: that is how they become real."],
    explanation=("The inferred member gives the fact a real key on day one. When the CRM sends the customer, the type 1 "
                 "update fills that same row, so every fact already loaded reports the real name and city. Inserting "
                 "the arriving customer as a new row instead leaves two rows for one customer, and the -1 approach "
                 "never reconnects the day-one orders."),
    follow_ups=["With a type 2 customer dimension, should the arriving attributes overwrite the inferred version or "
                "open a new one? Kimball's answer: overwrite the inferred version, since it never held real values."],
)

# =================================================================================================
# 11. Grain: allocate an order-level amount to the lines
# =================================================================================================
ALLOC_ORDERS = rows("order_id channel shipping_fee", ("SO1", "web", 5.0), ("SO2", "store", 0.0), ("SO3", "web", 6.0))
ALLOC_LINES = rows("order_id line_number quantity unit_price",
                   ("SO1", 1, 1, 199.0), ("SO1", 2, 2, 99.0), ("SO2", 1, 1, 139.0), ("SO3", 1, 1, 30.0), ("SO3", 2, 3, 10.0))


def alloc(orders=(), lines=()):
    return [T("source.shop_orders", ALLOC_ORDERS + list(orders)),
            T("source.shop_order_lines", ALLOC_LINES + list(lines))]


ALLOCATE = code("""
    CREATE OR REPLACE TABLE gold.fct_sales AS
    WITH lines AS (
        SELECT order_id,
               line_number,
               quantity * unit_price AS line_amount,
               SUM(quantity * unit_price) OVER (PARTITION BY order_id) AS order_amount,
               COUNT(*) OVER (PARTITION BY order_id) AS order_lines
        FROM source.shop_order_lines
    )
    SELECT l.order_id,
           l.line_number,
           l.line_amount,
           CASE WHEN l.order_amount = 0 THEN o.shipping_fee / l.order_lines
                ELSE o.shipping_fee * l.line_amount / l.order_amount END AS shipping_allocated
    FROM lines AS l
    JOIN source.shop_orders AS o ON o.order_id = l.order_id;
""")
exercise(
    id="dwh-grain-allocation", title="Declare the grain: allocate the shipping fee to the lines", difficulty="medium",
    topics=["grain", "facts", "allocation"],
    prompt=("gold.fct_sales has one row per order line (its grain), but the shipping fee is known per order "
            "(source.shop_orders.shipping_fee). Build gold.fct_sales (order_id, line_number, line_amount, "
            "shipping_allocated) from source.shop_order_lines: line_amount = quantity * unit_price, and the order's "
            "shipping fee split across its lines in proportion to line_amount. If an order's lines add up to 0, split "
            "its fee equally between its lines. The allocated amounts of an order must add up to its fee."),
    sections=[("Grain", "The grain says what one fact row is. Every measure must be true at that grain: an "
               "order-level amount repeated on each line is counted once per line as soon as someone sums it. Either "
               "allocate it down to the grain (as here), or keep it in a separate fact at the order grain."),
              ("Graded", "The fact rows, shipping by channel summed from the lines (it must equal the orders' fees), "
               "and an order whose lines are all free.")],
    starter=code("""
        -- The order's shipping fee is repeated on every line.
        CREATE OR REPLACE TABLE gold.fct_sales AS
        SELECT l.order_id, l.line_number, l.quantity * l.unit_price AS line_amount, o.shipping_fee AS shipping_allocated
        FROM source.shop_order_lines AS l
        JOIN source.shop_orders AS o ON o.order_id = l.order_id;
    """),
    solution=ALLOCATE,
    fixtures=[
        ("lines", "visible", S("table", tables=alloc(), table="gold.fct_sales")),
        ("shipping-by-channel", "hidden", S("result", tables=alloc(), query=(
            "SELECT o.channel, ROUND(SUM(f.shipping_allocated), 6) AS shipping FROM gold.fct_sales AS f "
            "JOIN source.shop_orders AS o ON o.order_id = f.order_id GROUP BY o.channel"))),
        ("free-lines", "edge", S("table", table="gold.fct_sales", tables=alloc(
            orders=rows("order_id channel shipping_fee", ("SO4", "web", 4.0)),
            lines=rows("order_id line_number quantity unit_price", ("SO4", 1, 1, 0.0), ("SO4", 2, 2, 0.0))))),
    ],
    mutants=[ALLOCATE.replace("CASE WHEN l.order_amount = 0 THEN o.shipping_fee / l.order_lines\n            ELSE o.shipping_fee * l.line_amount / l.order_amount END",
                              "o.shipping_fee / l.order_lines"),
             ALLOCATE.replace("CASE WHEN l.order_amount = 0 THEN o.shipping_fee / l.order_lines\n            ELSE o.shipping_fee * l.line_amount / l.order_amount END",
                              "o.shipping_fee * l.line_amount / l.order_amount")],
    hints=["A window SUM(...) OVER (PARTITION BY order_id) gives each line its order's total.",
           "Guard the division: an order of free lines has a total of 0."],
    explanation=("Each line gets fee * line_amount / order_amount, so the allocations of an order add up to its fee "
                 "and shipping can be summed at any level (by product, by category) without double counting. The "
                 "equal split is only a fallback for orders whose total is 0; without it the division gives NULL and "
                 "the fee disappears."),
    follow_ups=["Rounding each allocation to cents can make an order's total differ by a cent. How would you put the "
                "remainder on the largest line?"],
)

# =================================================================================================
# 12. Periodic snapshot
# =================================================================================================
INV_PRODUCTS = rows("product_id category", ("P1", "Camping"), ("P2", "Camping"), ("P3", "Apparel"))
MOVES = rows("product_id movement_date quantity", ("P1", "2026-01-05", 10), ("P1", "2026-01-20", -3),
             ("P1", "2026-03-10", -2), ("P2", "2026-02-01", 5))
SNAPSHOT = code("""
    CREATE OR REPLACE TABLE gold.fct_inventory_monthly AS
    WITH months AS (
        SELECT CAST(m AS DATE) AS month_start
        FROM generate_series(DATE '2026-01-01', DATE '2026-04-01', INTERVAL 1 MONTH) AS g(m)
    ),
    monthly AS (
        SELECT product_id, CAST(date_trunc('month', movement_date) AS DATE) AS month_start, SUM(quantity) AS moved
        FROM source.inventory_movements
        GROUP BY product_id, CAST(date_trunc('month', movement_date) AS DATE)
    )
    SELECT p.product_id,
           m.month_start,
           SUM(COALESCE(x.moved, 0)) OVER (PARTITION BY p.product_id ORDER BY m.month_start) AS closing_quantity
    FROM source.erp_products AS p
    CROSS JOIN months AS m
    LEFT JOIN monthly AS x ON x.product_id = p.product_id AND x.month_start = m.month_start;
""")


def inventory(moves=MOVES):
    return [T("source.erp_products", INV_PRODUCTS), T("source.inventory_movements", moves)]


exercise(
    id="dwh-periodic-snapshot", title="Periodic snapshot: stock at the end of each month", difficulty="medium",
    topics=["periodic-snapshot", "semi-additive", "facts"],
    prompt=("source.inventory_movements (product_id, movement_date, quantity) records receipts (+) and sales (-). "
            "Build gold.fct_inventory_monthly (product_id, month_start, closing_quantity): one row for every product "
            "of source.erp_products and every month from 2026-01-01 to 2026-04-01, where closing_quantity is the "
            "stock at the end of that month (all movements up to then). Months without movements and products that "
            "never moved still get their row."),
    sections=[("Periodic snapshot", "A transaction fact records events; a periodic snapshot records a state at regular "
               "intervals (stock, balances, headcount), one row per entity and period, even when nothing happened. "
               "Its measures are semi-additive: summing closing stock over products is right, summing it over months "
               "is meaningless (use the last or the average)."),
              ("Graded", "The snapshot rows, units on hand per month (summed over products, which is allowed), and a "
               "product that only moves in the last month.")],
    starter=code("""
        CREATE OR REPLACE TABLE gold.fct_inventory_monthly AS
        SELECT product_id,
               CAST(date_trunc('month', movement_date) AS DATE) AS month_start,
               SUM(quantity) AS closing_quantity
        FROM source.inventory_movements
        GROUP BY product_id, CAST(date_trunc('month', movement_date) AS DATE);
    """),
    solution=SNAPSHOT,
    fixtures=[
        ("snapshot", "visible", S("table", tables=inventory(), table="gold.fct_inventory_monthly")),
        ("on-hand", "hidden", S("result", tables=inventory(), query=(
            "SELECT month_start, SUM(closing_quantity) AS units_on_hand FROM gold.fct_inventory_monthly "
            "GROUP BY month_start"))),
        ("late-mover", "edge", S("table", table="gold.fct_inventory_monthly", tables=inventory(
            MOVES + rows("product_id movement_date quantity", ("P3", "2026-04-20", 8))))),
    ],
    mutants=[SNAPSHOT.replace("SUM(COALESCE(x.moved, 0)) OVER (PARTITION BY p.product_id ORDER BY m.month_start)",
                              "COALESCE(x.moved, 0)"),
             SNAPSHOT.replace("FROM source.erp_products AS p", "FROM (SELECT DISTINCT product_id FROM source.inventory_movements) AS p")],
    hints=["Build the grid first: every product CROSS JOIN every month.",
           "A running SUM(...) OVER (PARTITION BY product ORDER BY month) turns movements into stock."],
    explanation=("The grid of products x months guarantees a row per period even without movements, and the running "
                 "total carries the stock forward. Grouping the movements alone gives net changes, not stock, and "
                 "only for months where something moved; products that never moved disappear."),
    follow_ups=["Write the 'average closing stock per product over the quarter' query. Why is SUM over months wrong "
                "here?"],
)

# =================================================================================================
# 13. Accumulating snapshot
# =================================================================================================
EVENT = "order_id event_type event_date"
EV1 = rows(EVENT, ("O1", "ordered", "2026-03-01"), ("O1", "packed", "2026-03-02"), ("O2", "ordered", "2026-03-02"))
EV2 = rows(EVENT, ("O1", "shipped", "2026-03-03"), ("O2", "packed", "2026-03-03"), ("O3", "ordered", "2026-03-03"))
EV3 = rows(EVENT, ("O1", "delivered", "2026-03-05"), ("O2", "shipped", "2026-03-06"), ("O3", "packed", "2026-03-06"))
FULFILLMENT = T("gold.fct_order_fulfillment", [], columns=["order_id", "ordered_on", "packed_on", "shipped_on",
                                                          "delivered_on", "days_to_ship", "status"],
                types={"order_id": "VARCHAR", "ordered_on": "DATE", "packed_on": "DATE", "shipped_on": "DATE",
                       "delivered_on": "DATE", "days_to_ship": "INTEGER", "status": "VARCHAR"})
ACCUMULATE = code("""
    MERGE INTO gold.fct_order_fulfillment AS f
    USING (
        SELECT order_id,
               MIN(event_date) FILTER (WHERE event_type = 'ordered') AS ordered_on,
               MIN(event_date) FILTER (WHERE event_type = 'packed') AS packed_on,
               MIN(event_date) FILTER (WHERE event_type = 'shipped') AS shipped_on,
               MIN(event_date) FILTER (WHERE event_type = 'delivered') AS delivered_on
        FROM silver.order_events
        GROUP BY order_id
    ) AS e
    ON f.order_id = e.order_id
    WHEN MATCHED THEN UPDATE SET
        ordered_on = COALESCE(f.ordered_on, e.ordered_on),
        packed_on = COALESCE(f.packed_on, e.packed_on),
        shipped_on = COALESCE(f.shipped_on, e.shipped_on),
        delivered_on = COALESCE(f.delivered_on, e.delivered_on)
    WHEN NOT MATCHED THEN INSERT (order_id, ordered_on, packed_on, shipped_on, delivered_on)
        VALUES (e.order_id, e.ordered_on, e.packed_on, e.shipped_on, e.delivered_on);

    UPDATE gold.fct_order_fulfillment
    SET days_to_ship = date_diff('day', ordered_on, shipped_on),
        status = CASE WHEN delivered_on IS NOT NULL THEN 'delivered'
                      WHEN shipped_on IS NOT NULL THEN 'shipped'
                      WHEN packed_on IS NOT NULL THEN 'packed'
                      ELSE 'ordered' END;
""")


def events(*batches):
    return {"tables": [FULFILLMENT], "runs": [{"tables": [T("silver.order_events", b)]} for b in batches]}


exercise(
    id="dwh-accumulating-snapshot", title="Accumulating snapshot: an order's milestones", difficulty="hard",
    topics=["accumulating-snapshot", "merge", "incremental-load"],
    prompt=("gold.fct_order_fulfillment (order_id, ordered_on, packed_on, shipped_on, delivered_on, days_to_ship, "
            "status) has one row per order that is updated as its milestones happen. Each day silver.order_events "
            "(order_id, event_type, event_date) brings the day's events: 'ordered', 'packed', 'shipped', "
            "'delivered'. Write the daily load: create the row of a new order, fill the milestone dates that arrive "
            "without erasing the ones already known, then set days_to_ship (days from ordered_on to shipped_on, NULL "
            "until shipped) and status (the latest milestone reached)."),
    sections=[("Accumulating snapshot", "A third kind of fact table: one row per process instance (an order, a claim, "
               "an application) with a date column per milestone and lag measures between them. Unlike a transaction "
               "fact, its rows are updated as the process moves on. It answers 'how long between packing and "
               "shipping?' with a subtraction instead of a self-join over events."),
              ("Runs", RUNS_NOTE.format(n="two or three", batch="silver.order_events")),
              ("Graded", "The table after two days, after three days, and after replaying the second day.")],
    starter=code("""
        -- One row per event: a transaction fact, not one row per order.
        INSERT INTO gold.fct_order_fulfillment (order_id, ordered_on, packed_on, shipped_on, delivered_on, status)
        SELECT order_id,
               CASE WHEN event_type = 'ordered' THEN event_date END,
               CASE WHEN event_type = 'packed' THEN event_date END,
               CASE WHEN event_type = 'shipped' THEN event_date END,
               CASE WHEN event_type = 'delivered' THEN event_date END,
               event_type
        FROM silver.order_events;
    """),
    solution=ACCUMULATE,
    fixtures=[
        ("two-days", "visible", S("table", table="gold.fct_order_fulfillment", **events(EV1, EV2))),
        ("three-days", "hidden", S("table", table="gold.fct_order_fulfillment", **events(EV1, EV2, EV3))),
        ("replayed-day", "edge", S("table", table="gold.fct_order_fulfillment", **events(EV1, EV2, EV2))),
    ],
    mutants=[ACCUMULATE.replace("COALESCE(f.ordered_on, e.ordered_on)", "e.ordered_on")
                       .replace("COALESCE(f.packed_on, e.packed_on)", "e.packed_on")
                       .replace("COALESCE(f.shipped_on, e.shipped_on)", "e.shipped_on")
                       .replace("COALESCE(f.delivered_on, e.delivered_on)", "e.delivered_on"),
             ACCUMULATE.replace("date_diff('day', ordered_on, shipped_on)", "date_diff('day', packed_on, shipped_on)")],
    hints=["Pivot the day's events to one row per order first (MIN(...) FILTER (WHERE event_type = ...)).",
           "MERGE: insert new orders, and for existing ones keep a known date with COALESCE(f.x, e.x)."],
    explanation=("Pivoting the events gives one row per order and batch; the MERGE inserts new orders and, for "
                 "existing ones, only fills milestones that were still empty, so a day without a 'packed' event does "
                 "not erase yesterday's packing date and a replayed day changes nothing. Lags and status are derived "
                 "from the dates afterwards, on every row."),
    follow_ups=["An order is cancelled after packing. Where would you record it, and what happens to days_to_ship?"],
)

# =================================================================================================
# 14. Factless fact
# =================================================================================================
PROMO_PRODUCTS = rows("product_key product_name", (1, "Trail Tent"), (2, "Rope"), (3, "Rain Jacket"), (4, "Stove"))
COVERAGE = rows("product_key promo_code date_key",
                *[(p, "SPRING", d) for p in (1, 2, 3) for d in (20260301, 20260302, 20260303)])
PROMO_SALES = rows("product_key date_key quantity", (1, 20260302, 2))
FACTLESS = code("""
    SELECT c.promo_code, p.product_name
    FROM gold.fct_promotion_coverage AS c
    JOIN gold.dim_product AS p ON p.product_key = c.product_key
    LEFT JOIN gold.fct_sales AS s ON s.product_key = c.product_key AND s.date_key = c.date_key
    GROUP BY c.promo_code, p.product_name
    HAVING COUNT(s.product_key) = 0;
""")


def promo(coverage=COVERAGE, sales=PROMO_SALES):
    return [T("gold.dim_product", PROMO_PRODUCTS), T("gold.fct_promotion_coverage", coverage),
            T("gold.fct_sales", sales)]


exercise(
    id="dwh-factless-coverage", title="Factless fact: promoted products that did not sell", difficulty="medium",
    topics=["factless-fact", "anti-join", "facts"],
    prompt=("gold.fct_promotion_coverage (product_key, promo_code, date_key) has no measure: one row says 'this "
            "product was on this promotion that day'. gold.fct_sales (product_key, date_key, quantity) holds the "
            "sales and gold.dim_product (product_key, product_name) the products. Write a SELECT of the promoted "
            "products that sold nothing on any day of their promotion: columns promo_code and product_name."),
    sections=[("Factless facts", "Some events have no measure: attendance, eligibility, promotion coverage. A "
               "factless fact records that the combination existed. Its classic use is the 'what did not happen' "
               "question: the sales fact alone cannot say which promoted products did not sell, because a missing "
               "sale leaves no row."),
              ("Graded", "The unsold promoted products, including a product that sold only outside its promotion's "
               "days and a product on two promotions.")],
    starter=code("""
        SELECT DISTINCT c.promo_code, p.product_name
        FROM gold.fct_promotion_coverage AS c
        JOIN gold.dim_product AS p ON p.product_key = c.product_key
        WHERE c.product_key NOT IN (SELECT product_key FROM gold.fct_sales);
    """),
    solution=FACTLESS,
    fixtures=[
        ("spring", "visible", S("result", tables=promo())),
        ("sold-outside-window", "hidden", S("result", tables=promo(sales=PROMO_SALES + rows(
            "product_key date_key quantity", (2, 20260310, 1))))),
        ("two-promotions", "edge", S("result", tables=promo(
            coverage=COVERAGE + rows("product_key promo_code date_key", (2, "SUMMER", 20260601), (4, "SUMMER", 20260601),
                                     (4, "SUMMER", 20260602)),
            sales=PROMO_SALES + rows("product_key date_key quantity", (2, 20260310, 1), (2, 20260601, 1))))),
    ],
    mutants=[code("""
        SELECT DISTINCT c.promo_code, p.product_name
        FROM gold.fct_promotion_coverage AS c
        JOIN gold.dim_product AS p ON p.product_key = c.product_key
        WHERE NOT EXISTS (SELECT 1 FROM gold.fct_sales AS s WHERE s.product_key = c.product_key AND s.date_key = c.date_key);
    """), FACTLESS.replace("LEFT JOIN gold.fct_sales AS s ON s.product_key = c.product_key AND s.date_key = c.date_key",
                           "LEFT JOIN gold.fct_sales AS s ON s.product_key = c.product_key")],
    hints=["Match sales on the product AND the covered day.",
           "Group by promotion and product: 'nothing on any day' is a condition on the group, not on a row."],
    explanation=("The coverage fact supplies the rows that should exist; the LEFT JOIN on product and day finds the "
                 "matching sales, and HAVING COUNT(...) = 0 keeps the promotion-product pairs with no sale on any "
                 "covered day. Checking 'no sales at all' ignores the promotion's dates, and a per-day anti-join "
                 "returns products that simply had one quiet day."),
    follow_ups=["Turn the question around: the uplift of promoted products compared with the same weeks without "
                "promotion. Which fact tables do you need?"],
)

# =================================================================================================
# 15. Drill across conformed dimensions
# =================================================================================================
DA_PRODUCTS = rows("product_key category", (1, "Camping"), (2, "Camping"), (3, "Apparel"))
DA_DATES = rows("date_key year_month", (20260105, "2026-01"), (20260120, "2026-01"), (20260210, "2026-02"),
                (20260225, "2026-02"))
DA_SALES = rows("order_id line_number date_key product_key net_amount",
                ("SO1", 1, 20260105, 1, 200.0), ("SO1", 2, 20260105, 3, 100.0), ("SO2", 1, 20260120, 1, 60.0),
                ("SO3", 1, 20260210, 1, 150.0), ("SO4", 1, 20260210, 2, 80.0))
DA_RETURNS = rows("return_id date_key product_key refund_amount", ("R1", 20260120, 1, 50.0))
DRILL = code("""
    WITH sales AS (
        SELECT p.category, d.year_month, SUM(f.net_amount) AS sales
        FROM gold.fct_sales AS f
        JOIN gold.dim_product AS p ON p.product_key = f.product_key
        JOIN gold.dim_date AS d ON d.date_key = f.date_key
        GROUP BY p.category, d.year_month
    ),
    refunds AS (
        SELECT p.category, d.year_month, SUM(r.refund_amount) AS refunds
        FROM gold.fct_returns AS r
        JOIN gold.dim_product AS p ON p.product_key = r.product_key
        JOIN gold.dim_date AS d ON d.date_key = r.date_key
        GROUP BY p.category, d.year_month
    )
    SELECT COALESCE(s.category, r.category) AS category,
           COALESCE(s.year_month, r.year_month) AS year_month,
           COALESCE(s.sales, 0) AS sales,
           COALESCE(r.refunds, 0) AS refunds,
           COALESCE(s.sales, 0) - COALESCE(r.refunds, 0) AS net_sales
    FROM sales AS s
    FULL OUTER JOIN refunds AS r ON r.category = s.category AND r.year_month = s.year_month;
""")


def drill(returns=DA_RETURNS):
    return [T("gold.dim_product", DA_PRODUCTS), T("gold.dim_date", DA_DATES), T("gold.fct_sales", DA_SALES),
            T("gold.fct_returns", returns)]


exercise(
    id="dwh-drill-across", title="Drill across two facts without double counting", difficulty="medium",
    topics=["conformed-dimensions", "drill-across", "fan-trap"],
    prompt=("gold.fct_sales (order_id, line_number, date_key, product_key, net_amount) and gold.fct_returns "
            "(return_id, date_key, product_key, refund_amount) share the conformed dimensions gold.dim_product "
            "(product_key, category) and gold.dim_date (date_key, year_month). Write a SELECT of category, "
            "year_month, sales, refunds and net_sales (sales - refunds) for every category and month that has sales "
            "or returns; a side with nothing counts 0."),
    sections=[("Drill across", "Two facts at different grains never join row to row: every sale of a product would "
               "meet every return of that product (a fan trap), and the sums multiply. Aggregate each fact to the "
               "shared (conformed) attributes first, then join the two result sets on those attributes. That is what "
               "BI tools do when one visual shows measures from two fact tables."),
              ("Graded", "Net sales by category and month, including a month with returns but no sales for that "
               "category.")],
    starter=code("""
        SELECT p.category, d.year_month,
               SUM(f.net_amount) AS sales,
               COALESCE(SUM(r.refund_amount), 0) AS refunds,
               SUM(f.net_amount) - COALESCE(SUM(r.refund_amount), 0) AS net_sales
        FROM gold.fct_sales AS f
        JOIN gold.dim_product AS p ON p.product_key = f.product_key
        JOIN gold.dim_date AS d ON d.date_key = f.date_key
        LEFT JOIN gold.fct_returns AS r ON r.product_key = f.product_key
        GROUP BY p.category, d.year_month;
    """),
    solution=DRILL,
    fixtures=[
        ("net-sales", "visible", S("result", tables=drill())),
        ("second-return", "hidden", S("result", tables=drill(DA_RETURNS + rows(
            "return_id date_key product_key refund_amount", ("R2", 20260225, 1, 30.0))))),
        ("returns-only-month", "edge", S("result", tables=drill(DA_RETURNS + rows(
            "return_id date_key product_key refund_amount", ("R3", 20260225, 3, 100.0))))),
    ],
    mutants=[DRILL.replace("FULL OUTER JOIN refunds", "LEFT JOIN refunds"),
             code("""
        SELECT p.category, d.year_month,
               SUM(f.net_amount) AS sales,
               COALESCE(SUM(r.refund_amount), 0) AS refunds,
               SUM(f.net_amount) - COALESCE(SUM(r.refund_amount), 0) AS net_sales
        FROM gold.fct_sales AS f
        JOIN gold.dim_product AS p ON p.product_key = f.product_key
        JOIN gold.dim_date AS d ON d.date_key = f.date_key
        LEFT JOIN gold.fct_returns AS r ON r.product_key = f.product_key AND r.date_key = f.date_key
        GROUP BY p.category, d.year_month;
    """)],
    hints=["Aggregate sales and returns separately to (category, year_month).",
           "A FULL OUTER JOIN keeps cells that exist on one side only."],
    explanation=("Each fact is summed to the conformed grain (category, month) on its own, so no row is repeated, and "
                 "the FULL OUTER JOIN keeps cells that only one fact has. Joining the facts first multiplies rows "
                 "(each return meets every sale of its product) and inflates both sums; a LEFT JOIN from sales drops "
                 "the months where a category only had returns."),
    follow_ups=["Why must dim_product be the same table (or identical values) for both facts? What breaks if returns "
                "used their own product categories?"],
)

# =================================================================================================
# 16. Bridge table with allocation factors
# =================================================================================================
BR_CUSTOMERS = rows("customer_key customer_name segment", (1, "Alice", "Consumer"), (2, "Bruno", "Consumer"),
                    (3, "Chloe", "Business"))
BR_BRIDGE = rows("account_key customer_key allocation_pct", (1, 1, 0.5), (1, 2, 0.5), (2, 2, 0.25), (2, 3, 0.75),
                 (3, 3, 1.0))
BR_FEES = rows("account_key month_start fee_amount", (1, "2026-01-01", 10.0), (2, "2026-01-01", 40.0),
               (3, "2026-01-01", 20.0), (1, "2026-02-01", 10.0))
BRIDGE = code("""
    SELECT c.segment, ROUND(SUM(f.fee_amount * b.allocation_pct), 2) AS fees
    FROM gold.fct_account_fees AS f
    JOIN gold.bridge_account_holder AS b ON b.account_key = f.account_key
    JOIN gold.dim_customer AS c ON c.customer_key = b.customer_key
    GROUP BY c.segment;
""")


def bridge(bridge_rows=BR_BRIDGE, fees=BR_FEES):
    return [T("gold.dim_customer", BR_CUSTOMERS), T("gold.bridge_account_holder", bridge_rows),
            T("gold.fct_account_fees", fees)]


exercise(
    id="dwh-bridge-allocation", title="Many-to-many through a bridge table", difficulty="hard",
    topics=["bridge-table", "many-to-many", "allocation"],
    prompt=("An account can have several holders and a customer several accounts. gold.bridge_account_holder "
            "(account_key, customer_key, allocation_pct) links them, with allocation_pct adding up to 1 per account. "
            "gold.fct_account_fees (account_key, month_start, fee_amount) is at the account grain and "
            "gold.dim_customer (customer_key, customer_name, segment) describes holders. Write a SELECT of fees by "
            "customer segment (columns segment, fees rounded to 2 decimals) that allocates each account's fees to "
            "its holders by allocation_pct, so the segments add up to the total fees."),
    sections=[("Bridge tables", "A many-to-many between a fact and a dimension goes through a bridge table. Joining "
               "through it repeats each fact row once per holder: fine for 'which accounts does Bruno hold', wrong "
               "for sums, which count a joint account's fees once per holder. A weighting (allocation) factor on the "
               "bridge splits the measure so totals stay correct; the unweighted join is still useful as an "
               "'impact' view."),
              ("Graded", "Fees by segment with two joint accounts, then with uneven weights, then with an account "
               "whose holders are all in one segment.")],
    starter=code("""
        SELECT c.segment, ROUND(SUM(f.fee_amount), 2) AS fees
        FROM gold.fct_account_fees AS f
        JOIN gold.bridge_account_holder AS b ON b.account_key = f.account_key
        JOIN gold.dim_customer AS c ON c.customer_key = b.customer_key
        GROUP BY c.segment;
    """),
    solution=BRIDGE,
    fixtures=[
        ("by-segment", "visible", S("result", tables=bridge())),
        ("uneven-weights", "hidden", S("result", tables=bridge(bridge_rows=rows(
            "account_key customer_key allocation_pct", (1, 1, 0.7), (1, 3, 0.3), (2, 2, 0.25), (2, 3, 0.75),
            (3, 3, 1.0))))),
        ("same-segment-holders", "edge", S("result", tables=bridge(fees=BR_FEES + rows(
            "account_key month_start fee_amount", (1, "2026-03-01", 30.0))))),
    ],
    mutants=[code("""
        SELECT c.segment,
               ROUND(SUM(f.fee_amount / (SELECT COUNT(*) FROM gold.bridge_account_holder AS x
                                         WHERE x.account_key = f.account_key)), 2) AS fees
        FROM gold.fct_account_fees AS f
        JOIN gold.bridge_account_holder AS b ON b.account_key = f.account_key
        JOIN gold.dim_customer AS c ON c.customer_key = b.customer_key
        GROUP BY c.segment;
    """), code("""
        SELECT c.segment, ROUND(SUM(DISTINCT f.fee_amount), 2) AS fees
        FROM gold.fct_account_fees AS f
        JOIN gold.bridge_account_holder AS b ON b.account_key = f.account_key
        JOIN gold.dim_customer AS c ON c.customer_key = b.customer_key
        GROUP BY c.segment;
    """)],
    hints=["Multiply each fee by the holder's allocation_pct before summing.",
           "Check: the segments' fees must add up to SUM(fee_amount) of the fact."],
    explanation=("Weighting each joined row by allocation_pct splits a joint account's fee among its holders, so every "
                 "euro is counted exactly once and the segments add up to the fact's total. The plain join counts a "
                 "joint account once per holder; an equal split ignores the agreed weights; SUM(DISTINCT) merges "
                 "unrelated fees that happen to have the same amount."),
    follow_ups=["In a Power BI model, how would the bridge relate to dim_customer and to the account dimension so a "
                "customer filter reaches the fees? See the bridge model exercise."],
)

# =================================================================================================
# 17. Lineage: governed revenue
# =================================================================================================
GOV_ORDERS = rows("order_id order_date order_total shipping_fee", ("SO1", "2026-03-01", 401.0, 5.0),
                  ("SO2", "2026-03-02", 139.0, 0.0))
GOV_LINES = rows("order_id line_number quantity unit_price discount_amount",
                 ("SO1", 1, 1, 199.0, 0.0), ("SO1", 2, 2, 99.0, 2.0), ("SO2", 1, 1, 139.0, 0.0))
GOVERNED = code("""
    CREATE OR REPLACE TABLE gold.fct_order_revenue AS
    SELECT o.order_id,
           o.order_date,
           SUM(l.quantity * l.unit_price - l.discount_amount) AS net_revenue
    FROM source.shop_orders AS o
    JOIN source.shop_order_lines AS l ON l.order_id = o.order_id
    GROUP BY o.order_id, o.order_date;
""")


def governed(orders=GOV_ORDERS):
    return [T("source.shop_orders", orders), T("source.shop_order_lines", GOV_LINES)]


exercise(
    id="dwh-lineage-governed-revenue", title="Column lineage: revenue computed from the right source",
    difficulty="medium", topics=["sql-lineage", "data-governance", "facts"],
    prompt=("Build gold.fct_order_revenue (order_id, order_date, net_revenue) where net_revenue is the sum of the "
            "order's lines: quantity * unit_price - discount_amount (source.shop_order_lines). Finance certifies "
            "this column only if its lineage leads to the order lines: source.shop_orders.order_total is typed at "
            "the till, includes shipping and is sometimes stale, so no part of net_revenue may come from it (or "
            "from shipping_fee), not even as a fallback. The BI Lab's Lineage tab shows the same analysis."),
    sections=[("Column lineage", "Column-level lineage traces each output column back to the source columns its "
               "value is computed from, through CTEs, joins and staging tables. It answers 'where does this number "
               "come from?' (certification, audits) and 'what breaks if this column changes?' (impact analysis). "
               "Here it is computed from your SQL text by sqlglot, the way tools such as dbt, OpenLineage or "
               "Purview parse SQL."),
              ("Graded", "The rows of gold.fct_order_revenue, the source columns of net_revenue (traced back through "
               "any staging tables you create), and an order whose header total is stale.")],
    starter=code("""
        CREATE OR REPLACE TABLE gold.fct_order_revenue AS
        SELECT order_id, order_date, order_total - shipping_fee AS net_revenue
        FROM source.shop_orders;
    """),
    solution=GOVERNED,
    fixtures=[
        ("revenue", "visible", S("table", tables=governed(), table="gold.fct_order_revenue")),
        ("net-revenue-lineage", "hidden", S("lineage", tables=governed(), lineage_of=["gold.fct_order_revenue.net_revenue"],
                                            lineage_depth="origins", columns=["table", "column", "source"])),
        ("stale-header", "edge", S("table", table="gold.fct_order_revenue", tables=governed(rows(
            "order_id order_date order_total shipping_fee", ("SO1", "2026-03-01", 420.0, 5.0),
            ("SO2", "2026-03-02", 139.0, 0.0))))),
    ],
    mutants=[code("""
        CREATE OR REPLACE TABLE gold.fct_order_revenue AS
        WITH lines AS (
            SELECT order_id, SUM(quantity * unit_price - discount_amount) AS net
            FROM source.shop_order_lines
            GROUP BY order_id
        )
        SELECT o.order_id, o.order_date, COALESCE(l.net, o.order_total - o.shipping_fee) AS net_revenue
        FROM source.shop_orders AS o
        LEFT JOIN lines AS l ON l.order_id = o.order_id;
    """), GOVERNED.replace("l.quantity * l.unit_price - l.discount_amount", "l.quantity * l.unit_price")],
    hints=["Aggregate the lines per order and join them to the orders for order_date.",
           "A COALESCE fallback to the header still makes net_revenue depend on order_total, even if it never fires."],
    explanation=("net_revenue is computed from the three line columns only, so its lineage is exactly what Finance "
                 "certifies. The fallback version returns the same numbers today, but its lineage includes "
                 "order_total and shipping_fee: the day an order arrives without lines, it silently reports the till's "
                 "figure. Lineage makes that dependency visible before it produces a wrong number."),
    follow_ups=["Open the Lineage tab of the BI Lab on the sample warehouse and find every gold column that depends "
                "on source.erp_products.unit_cost. What would a rename of that column break?"],
)

# =================================================================================================
# 18. Lineage: personal data
# =================================================================================================
PII = rows("customer_id customer_name email birth_date city segment",
           ("C001", "Alice Martin", "alice.martin@example.com", "1990-04-02", "Lyon", "Consumer"),
           ("C002", "Bruno Keller", "bruno@keller.ch", "1962-11-20", "Geneva", "Small Business"),
           ("C003", "Chloe Diaz", "chloe@mail.es", "1985-07-09", "Madrid", None))
PUBLIC = code("""
    CREATE OR REPLACE VIEW gold.dim_customer_public AS
    SELECT customer_id,
           city,
           COALESCE(segment, 'Unknown') AS segment,
           split_part(email, '@', 2) AS email_domain
    FROM source.crm_customers;
""")


def pii(extra=()):
    return [T("source.crm_customers", PII + list(extra), types={"segment": "VARCHAR"})]


exercise(
    id="dwh-lineage-personal-data", title="Column lineage: keep personal data out of a shared view",
    difficulty="medium", topics=["sql-lineage", "data-governance", "personal-data"],
    prompt=("Analysts get a view without personal data. Create the view gold.dim_customer_public (customer_id, city, "
            "segment, email_domain) over source.crm_customers (customer_id, customer_name, email, birth_date, city, "
            "segment): segment is 'Unknown' when missing, and email_domain is the part of the email after '@'. The "
            "data protection rule is checked on lineage: email_domain is the only column allowed to derive from "
            "email, and no column may derive from customer_name or birth_date, even partly."),
    sections=[("Lineage as a control", "Masking or deriving a personal field (initials, age band, a segment guessed "
               "from the birth date) still makes the output depend on it, and column lineage shows it. Governance "
               "tools tag sensitive source columns and follow their lineage to every report; a view that must stay "
               "free of personal data is checked the same way here."),
              ("Graded", "The rows of the view, the source columns of each of its columns, and a customer without a "
               "segment born before 1970.")],
    starter=code("""
        CREATE OR REPLACE VIEW gold.dim_customer_public AS
        SELECT customer_id, customer_name, email, city, segment
        FROM source.crm_customers;
    """),
    solution=PUBLIC,
    fixtures=[
        ("view", "visible", S("table", tables=pii(), table="gold.dim_customer_public")),
        ("view-lineage", "hidden", S("lineage", tables=pii(), lineage_of=["gold.dim_customer_public"],
                                     lineage_depth="origins", columns=["table", "column", "source"])),
        ("older-customer", "edge", S("table", table="gold.dim_customer_public", tables=pii(rows(
            "customer_id customer_name email birth_date city segment",
            ("C004", "David Okafor", "d.okafor@example.com", "1950-02-11", "Lagos", None))))),
    ],
    mutants=[PUBLIC.replace("COALESCE(segment, 'Unknown') AS segment",
                            "COALESCE(segment, CASE WHEN birth_date < DATE '1970-01-01' THEN 'Senior' ELSE 'Unknown' END) AS segment")],
    hints=["split_part(email, '@', 2) keeps the domain.",
           "Any expression that reads birth_date or customer_name puts it in the column's lineage, whatever the result."],
    explanation=("Each column of the view derives only from allowed source columns: customer_id, city and segment "
                 "copy theirs, email_domain derives from email. A segment guessed from the birth date gives the same "
                 "rows for most customers but makes segment depend on birth_date, which is exactly what the rule "
                 "forbids; lineage catches it even when the data does not."),
    follow_ups=["Which of these columns would you still classify as personal data under GDPR, even without names? "
                "(Think of rare city + segment combinations.)"],
)

# =================================================================================================
# 19. Star model: relationships, cardinality, role-playing date (bi-model)
# =================================================================================================
def model_text(model: dict) -> str:
    return json.dumps(model, indent=2) + "\n"


STAR_FACT = rows("order_id line_number order_date_key ship_date_key customer_key customer_id product_key net_amount",
                 ("SO1", 1, 20260105, 20260107, 1, "C001", 1, 199.0), ("SO1", 2, 20260105, 20260107, 1, "C001", 3, 188.0),
                 ("SO2", 1, 20260220, -1, 2, "C001", 2, 159.0), ("SO3", 1, 20260301, 20260303, 3, "C002", 3, 99.0),
                 ("SO4", 1, 20260303, 20260303, -1, "C009", 1, 75.0))
STAR_DATES = rows("date_key full_date month_name", (20260105, "2026-01-05", "January"), (20260107, "2026-01-07", "January"),
                  (20260220, "2026-02-20", "February"), (20260301, "2026-03-01", "March"),
                  (20260303, "2026-03-03", "March"), (-1, None, "Unknown"))
STAR_CUSTOMERS = rows("customer_key customer_id city valid_from valid_to is_current",
                      (1, "C001", "Paris", "2026-01-01", "2026-02-15", False),
                      (2, "C001", "Lyon", "2026-02-15", "9999-12-31", True),
                      (3, "C002", "Geneva", "2026-01-01", "9999-12-31", True),
                      (-1, "UNKNOWN", "Unknown", "1900-01-01", "9999-12-31", True))
STAR_PRODUCTS = rows("product_key product_id category", (1, "P01", "Camping"), (2, "P02", "Camping"),
                     (3, "P03", "Apparel"), (-1, "UNKNOWN", "Unknown"))


def star(customers=STAR_CUSTOMERS):
    return [T("gold.fct_sales", STAR_FACT), T("gold.dim_date", STAR_DATES, types={"full_date": "DATE"}),
            T("gold.dim_customer", customers), T("gold.dim_product", STAR_PRODUCTS)]


def rel(source, target, active=True, cross_filter="single", cardinality="many-to-one"):
    return {"from": source, "to": target, "cardinality": cardinality, "cross_filter": cross_filter, "active": active}


STAR_MODEL = {
    "name": "sales_star",
    "tables": [
        {"name": "gold.fct_sales", "role": "fact", "grain": ["order_id", "line_number"]},
        {"name": "gold.dim_date", "role": "dimension", "key": "date_key", "unknown_member": -1},
        {"name": "gold.dim_customer", "role": "dimension", "key": "customer_key", "business_key": ["customer_id"],
         "unknown_member": -1,
         "scd": {"type": 2, "valid_from": "valid_from", "valid_to": "valid_to", "current_flag": "is_current"}},
        {"name": "gold.dim_product", "role": "dimension", "key": "product_key", "business_key": ["product_id"],
         "unknown_member": -1},
    ],
    "relationships": [
        rel("gold.fct_sales.order_date_key", "gold.dim_date.date_key"),
        rel("gold.fct_sales.ship_date_key", "gold.dim_date.date_key", active=False),
        rel("gold.fct_sales.customer_key", "gold.dim_customer.customer_key"),
        rel("gold.fct_sales.product_key", "gold.dim_product.product_key"),
    ],
}
STAR_STARTER = copy.deepcopy(STAR_MODEL)
STAR_STARTER["tables"][2].pop("scd")
STAR_STARTER["relationships"][1]["active"] = True
STAR_STARTER["relationships"][2] = rel("gold.fct_sales.customer_id", "gold.dim_customer.customer_id")


def star_variant(**changes):
    model = copy.deepcopy(STAR_MODEL)
    for index, value in changes.get("relationships", {}).items():
        model["relationships"][index] = value
    if changes.get("drop_scd"):
        model["tables"][2].pop("scd")
    return model_text(model)


REL_COLUMNS = ["relationship", "cardinality", "cross_filter", "active", "observed"]
exercise(
    id="bi-model-relationships", title="Star model: keys, cardinality and a role-playing date", difficulty="easy",
    language="bi-model", topics=["star-schema", "relationships", "role-playing"],
    prompt=("Write the star model file for four gold tables. gold.fct_sales (grain: order_id, line_number) has "
            "order_date_key, ship_date_key, customer_key, product_key (and a leftover customer_id). gold.dim_date "
            "(key date_key), gold.dim_customer (key customer_key, business key customer_id, type 2 with valid_from, "
            "valid_to, is_current) and gold.dim_product (key product_key, business key product_id) each have the "
            "unknown member -1. Relate the fact to each dimension, many-to-one with single cross-filtering: the "
            "order date is the active date relationship and the ship date the inactive one; the customer goes "
            "through the surrogate key."),
    sections=[("Model file", "The file is the BI Lab's star model (bi/model.json): tables with their role (fact, "
               "dimension, bridge), keys, grain, SCD settings, and relationships with the settings a Power BI "
               "semantic model uses: cardinality, cross-filter direction (single or both) and active. It is "
               "Datapass's own format, not a Power BI file. Each check below runs a real query on the tables."),
              ("Role-playing dimensions", "One dimension can relate to the same fact several times (order date, ship "
               "date). A model allows only one active path between two tables, so the other relationships are "
               "inactive and a measure uses them explicitly (USERELATIONSHIP in DAX), or the dimension is copied per "
               "role."),
              ("Graded", "The model checks (keys, grain, SCD2 validity, unknown members, relationships), the "
               "relationships with the cardinality the data shows, and the checks again after the customer "
               "dimension gets a new version.")],
    starter=model_text(STAR_STARTER),
    solution=model_text(STAR_MODEL),
    fixtures=[
        ("checks", "visible", S("checks", tables=star())),
        ("relationships", "hidden", S("relationships", tables=star(), columns=REL_COLUMNS)),
        ("new-version", "edge", S("checks", tables=star(STAR_CUSTOMERS[:2] + rows(
            "customer_key customer_id city valid_from valid_to is_current",
            (3, "C002", "Geneva", "2026-01-01", "2026-03-01", False),
            (4, "C002", "Zurich", "2026-03-01", "9999-12-31", True),
            (-1, "UNKNOWN", "Unknown", "1900-01-01", "9999-12-31", True))))),
    ],
    mutants=[star_variant(relationships={1: rel("gold.fct_sales.ship_date_key", "gold.dim_date.date_key")}),
             star_variant(relationships={2: rel("gold.fct_sales.customer_id", "gold.dim_customer.customer_id")}),
             star_variant(relationships={3: rel("gold.fct_sales.product_key", "gold.dim_product.product_key",
                                                cross_filter="both")}),
             star_variant(drop_scd=True)],
    hints=["The 'one' side of a many-to-one must be unique: in a type 2 dimension, customer_id repeats.",
           "Two active relationships between the same two tables make the filter path ambiguous."],
    explanation=("Relating on the surrogate key keeps the 'one' side unique, which a type 2 dimension's business key "
                 "is not (one row per version). Only one relationship between two tables can be active, so the ship "
                 "date is modelled as inactive and used on demand. Single-direction filtering from dimensions to the "
                 "fact is the default star; 'both' adds ambiguous paths and slows the model."),
    follow_ups=["Drop the leftover customer_id from the fact: why do facts keep only surrogate keys and degenerate "
                "dimensions such as order_id?"],
)

# =================================================================================================
# 20. Star model with a bridge (bi-model)
# =================================================================================================
BM_ACCOUNTS = rows("account_key account_type", (1, "joint"), (2, "joint"), (3, "single"))


def bridge_model_tables():
    return [T("gold.dim_customer", BR_CUSTOMERS), T("gold.dim_account", BM_ACCOUNTS),
            T("gold.bridge_account_holder", BR_BRIDGE), T("gold.fct_account_fees", BR_FEES)]


BRIDGE_MODEL = {
    "name": "account_fees",
    "tables": [
        {"name": "gold.fct_account_fees", "role": "fact", "grain": ["account_key", "month_start"]},
        {"name": "gold.dim_account", "role": "dimension", "key": "account_key"},
        {"name": "gold.dim_customer", "role": "dimension", "key": "customer_key"},
        {"name": "gold.bridge_account_holder", "role": "bridge", "grain": ["account_key", "customer_key"]},
    ],
    "relationships": [
        rel("gold.fct_account_fees.account_key", "gold.dim_account.account_key"),
        rel("gold.bridge_account_holder.account_key", "gold.dim_account.account_key", cross_filter="both"),
        rel("gold.bridge_account_holder.customer_key", "gold.dim_customer.customer_key"),
    ],
}
BRIDGE_STARTER = {
    "name": "account_fees",
    "tables": [
        {"name": "gold.fct_account_fees", "role": "fact", "grain": ["account_key", "month_start"]},
        {"name": "gold.dim_customer", "role": "dimension", "key": "customer_key"},
        {"name": "gold.bridge_account_holder", "role": "fact", "grain": ["account_key", "customer_key"]},
    ],
    "relationships": [
        rel("gold.fct_account_fees.account_key", "gold.bridge_account_holder.account_key",
            cardinality="many-to-many", cross_filter="both"),
        rel("gold.bridge_account_holder.customer_key", "gold.dim_customer.customer_key"),
    ],
}


def bridge_variant(edit):
    model = copy.deepcopy(BRIDGE_MODEL)
    edit(model)
    return model_text(model)


exercise(
    id="bi-model-bridge", title="Star model: a many-to-many through a bridge", difficulty="medium",
    language="bi-model", topics=["bridge-table", "relationships", "cross-filter"],
    prompt=("Model account fees for four gold tables: gold.fct_account_fees (grain: account_key, month_start), "
            "gold.dim_account (key account_key), gold.dim_customer (key customer_key) and gold.bridge_account_holder "
            "(role bridge, grain: account_key, customer_key). A customer filter must reach the fees: relate the fact "
            "to dim_account, the bridge to dim_account and the bridge to dim_customer, all many-to-one and active. "
            "Only the bridge-to-account relationship filters in both directions."),
    sections=[("Bridges in a model", "A fact never relates directly to a table where its key repeats (that is a "
               "many-to-many). The bridge sits between the account and its holders: dim_customer filters the bridge, "
               "the bridge must filter dim_account (the 'one' side, hence both directions on that relationship only), "
               "and dim_account filters the fees. Everywhere else, keep single direction."),
              ("Graded", "The model checks, including the cross-filter check (both directions only where a bridge is "
               "involved), and the relationships with the cardinality the data shows.")],
    starter=model_text(BRIDGE_STARTER),
    solution=model_text(BRIDGE_MODEL),
    fixtures=[
        ("checks", "visible", S("checks", tables=bridge_model_tables())),
        ("relationships", "hidden", S("relationships", tables=bridge_model_tables(), columns=REL_COLUMNS)),
        ("more-holders", "edge", S("checks", tables=[T("gold.dim_customer", BR_CUSTOMERS), T("gold.dim_account", BM_ACCOUNTS),
                                                     T("gold.bridge_account_holder", BR_BRIDGE + rows(
                                                         "account_key customer_key allocation_pct", (3, 1, 0.0))),
                                                     T("gold.fct_account_fees", BR_FEES)])),
    ],
    mutants=[bridge_variant(lambda m: (m["relationships"][0].update(cross_filter="both"),
                                       m["relationships"][1].update(cross_filter="single"))),
             bridge_variant(lambda m: m["tables"][3].update(role="fact")),
             bridge_variant(lambda m: m["relationships"][2].update(cross_filter="both"))],
    hints=["The fact relates to dim_account, not to the bridge.",
           "Filters flow from the 'one' side to the 'many' side; the bridge must push the customer filter up to "
           "dim_account."],
    explanation=("The bridge turns the many-to-many into two many-to-one relationships. Both-direction filtering on "
                 "the bridge-to-account relationship lets a customer selection reach dim_account and, through it, the "
                 "fees; every other relationship stays single-direction, which keeps the filter paths unambiguous. "
                 "Relating the fact straight to the bridge is a many-to-many that double counts."),
    follow_ups=["With this model, a 'fees' measure summed for one customer counts a joint account's full fee. How do "
                "you apply allocation_pct in the measure (see the bridge allocation exercise)?"],
)

# -- pack assembly ---------------------------------------------------------------------------------
WAREHOUSE = ("Your SQL script runs for real on DuckDB, on an isolated catalog built for each check from the tables "
             "the exercise describes; your workspace catalog is never read or written. Name tables with their layer "
             "(source., silver., gold.). A script can hold several statements separated by ; (CREATE TABLE/VIEW, "
             "INSERT, UPDATE, DELETE, MERGE, DROP, SELECT) and stops at the first error. Column lineage, when graded, "
             "is a static analysis of your SQL text (sqlglot).")
MODEL_FILE = ("Your answer is the star model file (JSON). Each check seeds the tables in an isolated DuckDB catalog "
              "and runs the model checks on them as real queries. Nothing connects to Power BI.")


def definition(spec: dict, rank: int) -> dict:
    by_visibility = {"visible": [], "hidden": [], "edge": []}
    for fid, visibility, _ in spec["fixtures"]:
        by_visibility[visibility].append(fid)
    model = spec["language"] == "bi-model"
    custom = dict(spec["sections"])
    if model:
        head = {"title": "Model file", "body": MODEL_FILE + (" " + custom["Model file"] if "Model file" in custom else "")}
    else:
        head = {"title": "Warehouse", "body": WAREHOUSE}
    sections = [head] + [{"title": t, "body": b} for t, b in spec["sections"] if t != "Model file"]
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
        "tags": ["bi-lab", "data-warehousing", "star-model" if model else "warehouse-sql"],
        "origin": "authored", "language": spec["language"], "runtime": "datapass-warehouse-v1",
        "prompt": spec["prompt"], "sections": sections, "starter_source": spec["starter"],
        "fixtures": [{"id": f"{spec['id']}-fixtures", "version": "1"}],
        "visible_checks": [{"id": fid, "description": "Outcome of the public scenario on an isolated DuckDB catalog."}
                           for fid in by_visibility["visible"]],
        "hidden_check_refs": by_visibility["hidden"], "edge_check_refs": by_visibility["edge"],
        "hints": spec["hints"], "solution": {"available": True, "reveal": "explicit"},
        "explanation": spec["explanation"], "follow_ups": spec["follow_ups"],
        "canonical_placement": {"domain": "bi-data-warehousing", "topic": spec["topics"][0]},
        "related_associations": ["bi-lab/warehouse"],
        "recommendation": {"rank": rank, "reason": "BI Lab data warehousing progression"},
        "validator_version": "rows-v2", "validation": validation,
        "runtime_requirements": ["duckdb"],
        "provenance": {
            "source": "Authored for Datapass Workbench: dimensional modeling (Kimball) and warehouse loading patterns",
            "fixtures": "Authored scenarios; expected rows computed by running the reference and reviewed",
        },
        "constraints": {"truth": ("Real DuckDB execution on an isolated local catalog; column lineage is a static "
                                  "analysis of the SQL text; model checks are real queries.")},
        "truth": "real",
    }


def outcome(source, scenario, language):
    from bilab.exercise import WarehouseScenario
    from datapass_runtime.warehouse_grading import Rejected, run_fixture
    try:
        return run_fixture(source, WarehouseScenario.model_validate(scenario), language), None
    except Rejected as exc:
        return None, str(exc)


def main() -> None:
    from bilab.exercise import WarehouseScenario, graded_columns, project
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
            raw, error = outcome(spec["solution"], copy.deepcopy(scenario), spec["language"])
            if error:
                problems.append(f"{spec['id']}/{fid}: reference rejected: {error}")
                raw = []
            parsed = WarehouseScenario.model_validate(scenario)
            expected = project(raw, graded_columns(parsed, raw))
            fixtures.append({"id": fid, "visibility": visibility, "input_rows": [], "scenario": scenario,
                             "expected": expected})
        grading[spec["id"]] = {"solution": spec["solution"], "fixtures": fixtures}
        for index, mutant in enumerate(spec["mutants"]):
            if mutant == spec["solution"]:
                problems.append(f"{spec['id']}: mutant {index} is identical to the solution")
        for label, source in [("starter", spec["starter"])] + [(f"mutant {i}", m) for i, m in enumerate(spec["mutants"])]:
            failed = False
            for fixture in fixtures:
                raw, error = outcome(source, copy.deepcopy(fixture["scenario"]), spec["language"])
                if error:
                    problems.append(f"{spec['id']}: {label} does not run: {error}")
                    failed = True
                    break
                parsed = WarehouseScenario.model_validate(fixture["scenario"])
                columns = graded_columns(parsed, raw)
                result = {"rows": project(raw, columns), "columns": columns, "truncated": False}
                if not validate_result(result, fixture["expected"], validation):
                    failed = True
            if not failed:
                problems.append(f"{spec['id']}: {label} passes every check")
    manifest = {"schema_version": 1, "id": "dwh-v1", "version": "1",
                "title": "BI Lab: data warehousing (dimensional modeling, SCD, lineage, star models)",
                "enabled": True, "provenance": {"source": "Authored for Datapass Workbench"}}
    PackRegistry().register(manifest, definitions, grading)
    PACK.mkdir(parents=True, exist_ok=True)
    for name, data in (("manifest.json", manifest), ("exercises.json", definitions), ("grading.server.json", grading)):
        (PACK / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_mutants(PACK, {spec["id"]: spec["mutants"] for spec in EXERCISES})
    for spec in EXERCISES:
        print(f"== {spec['id']}")
        for fixture in grading[spec["id"]]["fixtures"]:
            print(f"   {fixture['id']:22s}", json.dumps(fixture["expected"])[:600])
    if problems:
        print("\nPROBLEMS:\n  " + "\n  ".join(problems))


if __name__ == "__main__":
    main()
