"""Generate content/exercise-packs/spark-sql-v1 from authored specs: a light Spark SQL Practice track.

One card per key topic (NULLs, aggregation, joins, windows, dates, top-N, strings), written in Spark SQL (ANSI mode,
as in Spark 4 and Databricks SQL). Practice translates each submission to DuckDB with sqlglot (runtime/sqldialects,
language `sparksql`, dialect `spark`) and really runs it: "Spark SQL dialect translated to DuckDB, not Spark".
Expected rows are computed by running each reference solution through that same grading path over the grader's own
typed fixture CTEs; review them by hand.
Run from the repository root with PYTHONPATH=runtime (and scripts/authoring for pack_quality).
"""
from __future__ import annotations

import json
import tempfile
import textwrap
from pathlib import Path

from pack_quality import write_mutants

ROOT = Path.cwd()
PACK = ROOT / "content" / "exercise-packs" / "spark-sql-v1"
EXERCISES: list[dict] = []


def sql(text: str) -> str:
    return textwrap.dedent(text).strip("\n") + "\n"


def exercise(**spec):
    spec["starter"], spec["solution"] = sql(spec["starter"]), sql(spec["solution"])
    spec["mutants"] = [sql(m) for m in spec["mutants"]]
    EXERCISES.append(spec)


CUSTOMERS = {"customer_id": "INTEGER", "name": "VARCHAR", "email": "VARCHAR"}
ORDERS = {"order_id": "INTEGER", "customer_id": "INTEGER", "order_date": "DATE", "status": "VARCHAR", "amount": "DOUBLE"}

# 1 NULLs ---------------------------------------------------------------------
exercise(
    id="sparksql-missing-email", title="Customers without a usable email", difficulty="easy",
    topics=["nulls", "filtering"],
    prompt=("Return the customers the marketing team cannot email: email is NULL, empty or only spaces. "
            "Output customer_id, name."),
    tables={"customers": CUSTOMERS},
    pitfall=("email = NULL is never true: a comparison with NULL is NULL, and WHERE keeps only true rows. Use IS NULL, "
             "or fold NULL into a value first with NVL/COALESCE."),
    starter='''
        -- Bug: customers whose email is NULL are missing.
        SELECT customer_id, name
        FROM customers
        WHERE email = NULL OR TRIM(email) = ''
        ''',
    solution='''
        SELECT customer_id, name
        FROM customers
        WHERE NVL(TRIM(email), '') = ''
        ''',
    fixtures={
        "example": ("visible", {"customers": [
            {"customer_id": 1, "name": "Ana", "email": "ana@a.io"}, {"customer_id": 2, "name": "Bo", "email": None},
            {"customer_id": 3, "name": "Cy", "email": ""}]}),
        "spaces-only": ("hidden", {"customers": [
            {"customer_id": 4, "name": "Di", "email": "   "}, {"customer_id": 5, "name": "Ed", "email": " ed@e.io "}]}),
        "everyone-reachable": ("edge", {"customers": [{"customer_id": 6, "name": "Flo", "email": "flo@f.io"}]}),
    },
    exact_schema=["customer_id", "name"],
    hints=["What does email = NULL evaluate to?", "NVL(TRIM(email), '') turns NULL and blank emails into ''."],
    explanation=("SQL uses three-valued logic: email = NULL is NULL, so WHERE drops the row. IS NULL tests for NULL; "
                 "NVL(TRIM(email), '') = '' covers NULL, empty and space-only emails in one predicate."),
    follow_ups=["How would you also reject emails without an @?"],
    mutants=['''
        SELECT customer_id, name FROM customers WHERE email IS NULL OR email = ''
        '''],
)

# 2 Aggregation ---------------------------------------------------------------
exercise(
    id="sparksql-count-if-having", title="Repeat customers and their late orders", difficulty="easy",
    topics=["aggregation", "having"],
    prompt=("For each customer with at least 2 orders (any status), return the number of orders and how many of them "
            "are LATE. Output customer_id, orders, late_orders."),
    tables={"orders": ORDERS},
    pitfall=("A WHERE clause filters rows before GROUP BY, so WHERE status = 'LATE' also changes the order count. "
             "Count conditionally with COUNT_IF instead, and filter groups with HAVING."),
    starter='''
        -- Bug: only LATE orders are counted, so customers with on-time orders drop out.
        SELECT customer_id, COUNT(*) AS orders, COUNT(*) AS late_orders
        FROM orders
        WHERE status = 'LATE'
        GROUP BY customer_id
        HAVING COUNT(*) >= 2
        ''',
    solution='''
        SELECT customer_id, COUNT(*) AS orders, COUNT_IF(status = 'LATE') AS late_orders
        FROM orders
        GROUP BY customer_id
        HAVING COUNT(*) >= 2
        ''',
    fixtures={
        "example": ("visible", {"orders": [
            {"order_id": 1, "customer_id": 10, "order_date": "2026-01-02", "status": "LATE", "amount": 20.0},
            {"order_id": 2, "customer_id": 10, "order_date": "2026-01-05", "status": "ON_TIME", "amount": 35.0},
            {"order_id": 3, "customer_id": 20, "order_date": "2026-01-06", "status": "LATE", "amount": 12.0}]}),
        "no-late-orders": ("hidden", {"orders": [
            {"order_id": 4, "customer_id": 30, "order_date": "2026-02-01", "status": "ON_TIME", "amount": 5.0},
            {"order_id": 5, "customer_id": 30, "order_date": "2026-02-02", "status": "ON_TIME", "amount": 7.0},
            {"order_id": 6, "customer_id": 30, "order_date": "2026-02-03", "status": None, "amount": 9.0}]}),
        "single-orders-only": ("edge", {"orders": [
            {"order_id": 7, "customer_id": 40, "order_date": "2026-03-01", "status": "LATE", "amount": 1.0}]}),
    },
    exact_schema=["customer_id", "orders", "late_orders"],
    hints=["Which rows does WHERE remove before the groups are built?", "COUNT_IF(condition) counts rows where it is true."],
    explanation=("WHERE runs before GROUP BY and HAVING after it. Counting a subset belongs in the aggregate "
                 "(COUNT_IF, or SUM(CASE WHEN ... THEN 1 ELSE 0 END)) so the group keeps all its rows."),
    follow_ups=["Return the late share as a percentage; what does Spark return for 1 / 3?"],
    mutants=['''
        SELECT customer_id, COUNT(*) AS orders, COUNT_IF(status = 'LATE') AS late_orders
        FROM orders GROUP BY customer_id HAVING COUNT_IF(status = 'LATE') >= 1
        '''],
)

# 3 Joins ---------------------------------------------------------------------
exercise(
    id="sparksql-left-anti-join", title="Customers who never ordered: LEFT ANTI JOIN", difficulty="easy",
    topics=["joins", "anti-join", "nulls"],
    prompt="Return the customers who have no order at all. Output customer_id, name.",
    tables={"customers": CUSTOMERS, "orders": ORDERS},
    pitfall=("NOT IN (subquery) returns no row at all as soon as the subquery holds a NULL (guest orders have no "
             "customer_id). Spark's LEFT ANTI JOIN, like NOT EXISTS, only keeps rows without a match and ignores NULLs."),
    starter='''
        -- Bug: returns nothing once an order has a NULL customer_id.
        SELECT customer_id, name
        FROM customers
        WHERE customer_id NOT IN (SELECT customer_id FROM orders)
        ''',
    solution='''
        SELECT c.customer_id, c.name
        FROM customers AS c
        LEFT ANTI JOIN orders AS o ON c.customer_id = o.customer_id
        ''',
    fixtures={
        "example": ("visible", {
            "customers": [{"customer_id": 1, "name": "Ana", "email": "ana@a.io"},
                          {"customer_id": 2, "name": "Bo", "email": "bo@b.io"}],
            "orders": [{"order_id": 10, "customer_id": 1, "order_date": "2026-01-02", "status": "ON_TIME", "amount": 5.0}]}),
        "guest-order": ("hidden", {
            "customers": [{"customer_id": 3, "name": "Cy", "email": None}, {"customer_id": 4, "name": "Di", "email": None}],
            "orders": [{"order_id": 11, "customer_id": 3, "order_date": "2026-01-03", "status": "ON_TIME", "amount": 5.0},
                       {"order_id": 12, "customer_id": None, "order_date": "2026-01-04", "status": "ON_TIME", "amount": 9.0}]}),
        "no-orders": ("edge", {"customers": [{"customer_id": 5, "name": "Ed", "email": None}], "orders": []}),
    },
    exact_schema=["customer_id", "name"],
    hints=["What is 4 NOT IN (3, NULL)?", "Spark has LEFT ANTI JOIN: rows of the left side with no match on the right."],
    explanation=("x NOT IN (3, NULL) is NULL, never true, so one NULL in the subquery empties the result. An anti join "
                 "(LEFT ANTI JOIN or NOT EXISTS) compares with =, where a NULL key simply never matches."),
    follow_ups=["Rewrite the answer with NOT EXISTS; which plan does Spark choose for each?"],
    mutants=['''
        SELECT c.customer_id, c.name FROM customers AS c LEFT SEMI JOIN orders AS o ON c.customer_id = o.customer_id
        '''],
)

# 4 Windows: dedup -------------------------------------------------------------
exercise(
    id="sparksql-qualify-latest", title="Latest order per customer with QUALIFY", difficulty="medium",
    topics=["windows", "deduplication", "qualify"],
    prompt=("Return each customer's latest order, the whole row: the most recent order_date, and the highest order_id "
            "when two orders share that date. Output order_id, customer_id, order_date, status, amount."),
    tables={"orders": ORDERS},
    pitfall=("MAX() per column mixes values from different rows (the latest date with another order's amount). Rank "
             "the rows in a window and keep the first one; QUALIFY filters on the window without a subquery. RANK keeps "
             "every tied row, ROW_NUMBER exactly one."),
    starter='''
        -- Bug: each column's MAX may come from a different order.
        SELECT MAX(order_id) AS order_id, customer_id, MAX(order_date) AS order_date,
               MAX(status) AS status, MAX(amount) AS amount
        FROM orders
        GROUP BY customer_id
        ''',
    solution='''
        SELECT order_id, customer_id, order_date, status, amount
        FROM orders
        QUALIFY ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_date DESC, order_id DESC) = 1
        ''',
    fixtures={
        "example": ("visible", {"orders": [
            {"order_id": 1, "customer_id": 10, "order_date": "2026-01-02", "status": "ON_TIME", "amount": 80.0},
            {"order_id": 2, "customer_id": 10, "order_date": "2026-01-09", "status": "LATE", "amount": 15.0},
            {"order_id": 3, "customer_id": 20, "order_date": "2026-01-04", "status": "ON_TIME", "amount": 7.5}]}),
        "same-day-orders": ("hidden", {"orders": [
            {"order_id": 4, "customer_id": 30, "order_date": "2026-02-01", "status": "ON_TIME", "amount": 99.0},
            {"order_id": 5, "customer_id": 30, "order_date": "2026-02-01", "status": "LATE", "amount": 1.0}]}),
        "single-order": ("edge", {"orders": [
            {"order_id": 6, "customer_id": 40, "order_date": "2026-03-01", "status": "ON_TIME", "amount": 3.0}]}),
    },
    exact_schema=["order_id", "customer_id", "order_date", "status", "amount"],
    hints=["Do MAX(order_date) and MAX(amount) come from the same row?",
           "ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...) = 1 in a QUALIFY clause."],
    explanation=("Aggregates work column by column, so they cannot pick a row. A window numbers the rows inside each "
                 "customer; QUALIFY keeps number 1. The tie-breaker (order_id DESC) makes the answer deterministic."),
    follow_ups=["Without QUALIFY (Apache Spark before 4.x), how do you write this with a subquery?"],
    mutants=['''
        SELECT order_id, customer_id, order_date, status, amount FROM orders
        QUALIFY RANK() OVER (PARTITION BY customer_id ORDER BY order_date DESC) = 1
        '''],
)

# 5 Windows: LAG ----------------------------------------------------------------
exercise(
    id="sparksql-lag-change", title="Change since the previous reading with LAG", difficulty="medium",
    topics=["windows", "lag"],
    prompt=("Meters report readings. For each reading return change: this value minus the same meter's previous value "
            "(by reading_date); the first reading of a meter has a NULL change. "
            "Output meter_id, reading_date, value, change."),
    tables={"readings": {"meter_id": "VARCHAR", "reading_date": "DATE", "value": "DOUBLE"}},
    pitfall=("Without PARTITION BY, LAG reads the previous row of the whole table, so a meter's first reading is "
             "compared with another meter. Replacing the first NULL with 0 invents a change equal to the whole value."),
    starter='''
        -- Bug: the previous row may belong to another meter.
        SELECT meter_id, reading_date, value,
               value - LAG(value) OVER (ORDER BY meter_id, reading_date) AS change
        FROM readings
        ''',
    solution='''
        SELECT meter_id, reading_date, value,
               value - LAG(value) OVER (PARTITION BY meter_id ORDER BY reading_date) AS change
        FROM readings
        ''',
    fixtures={
        "example": ("visible", {"readings": [
            {"meter_id": "A", "reading_date": "2026-01-01", "value": 100.0},
            {"meter_id": "A", "reading_date": "2026-01-02", "value": 130.0},
            {"meter_id": "B", "reading_date": "2026-01-01", "value": 40.0}]}),
        "unsorted-meters": ("hidden", {"readings": [
            {"meter_id": "C", "reading_date": "2026-02-03", "value": 12.0},
            {"meter_id": "D", "reading_date": "2026-02-01", "value": 50.0},
            {"meter_id": "C", "reading_date": "2026-02-01", "value": 10.0},
            {"meter_id": "D", "reading_date": "2026-02-02", "value": 45.0}]}),
        "one-reading": ("edge", {"readings": [{"meter_id": "E", "reading_date": "2026-03-01", "value": 0.0}]}),
    },
    exact_schema=["meter_id", "reading_date", "value", "change"],
    hints=["Which rows does LAG see without PARTITION BY?", "A meter's first reading has no previous value: keep NULL."],
    explanation=("PARTITION BY restarts the window for every meter, so LAG never crosses from one meter to the next. "
                 "LAG returns NULL for the first row of a partition, and the prompt keeps that NULL."),
    follow_ups=["Return only the readings whose change is negative (a meter reset)."],
    mutants=['''
        SELECT meter_id, reading_date, value,
               value - NVL(LAG(value) OVER (PARTITION BY meter_id ORDER BY reading_date), 0) AS change
        FROM readings
        '''],
)

# 6 Dates: DATEDIFF --------------------------------------------------------------
exercise(
    id="sparksql-datediff-shipping", title="Days to ship: DATEDIFF(end, start)", difficulty="easy",
    topics=["dates", "datediff"],
    prompt=("For each shipment return days_to_ship, the number of days from order_date to shipped_date (0 when shipped "
            "the same day, NULL when not shipped yet). Output order_id, days_to_ship."),
    tables={"shipments": {"order_id": "INTEGER", "order_date": "DATE", "shipped_date": "DATE"}},
    pitfall=("Spark's DATEDIFF(endDate, startDate) puts the end first, the opposite of T-SQL's DATEDIFF(day, start, "
             "end). Swapped arguments give negative durations."),
    starter='''
        -- Bug: every duration comes out negative.
        SELECT order_id, DATEDIFF(order_date, shipped_date) AS days_to_ship
        FROM shipments
        ''',
    solution='''
        SELECT order_id, DATEDIFF(shipped_date, order_date) AS days_to_ship
        FROM shipments
        ''',
    fixtures={
        "example": ("visible", {"shipments": [
            {"order_id": 1, "order_date": "2026-01-02", "shipped_date": "2026-01-05"},
            {"order_id": 2, "order_date": "2026-01-03", "shipped_date": None}]}),
        "month-boundary": ("hidden", {"shipments": [
            {"order_id": 3, "order_date": "2026-01-30", "shipped_date": "2026-02-02"},
            {"order_id": 4, "order_date": "2024-02-28", "shipped_date": "2024-03-01"}]}),
        "same-day": ("edge", {"shipments": [{"order_id": 5, "order_date": "2026-03-01", "shipped_date": "2026-03-01"}]}),
    },
    exact_schema=["order_id", "days_to_ship"],
    hints=["Which argument comes first in Spark's DATEDIFF?", "Order 4 crosses 29 February 2024."],
    explanation=("DATEDIFF(end, start) counts days from start to end. A NULL shipped_date gives NULL, which is what "
                 "the prompt asks for unshipped orders."),
    follow_ups=["Count the orders shipped within 2 days per week of order_date."],
    mutants=['''
        SELECT order_id, DATEDIFF(shipped_date, order_date) + 1 AS days_to_ship FROM shipments
        '''],
)

# 7 Dates: monthly buckets --------------------------------------------------------
exercise(
    id="sparksql-monthly-revenue", title="Monthly revenue across years: TRUNC to the month", difficulty="medium",
    topics=["dates", "aggregation"],
    prompt=("Return the revenue of each calendar month, as the first day of the month (a DATE) and the sum of amount. "
            "Output month, revenue."),
    tables={"orders": ORDERS},
    pitfall=("MONTH(order_date) is only the month number, so January 2025 and January 2026 land in the same group. "
             "TRUNC(order_date, 'MM') keeps the year and returns a DATE; DATE_TRUNC('MONTH', ...) returns a TIMESTAMP."),
    starter='''
        -- Bug: January 2025 and January 2026 are added together.
        SELECT MONTH(order_date) AS month, SUM(amount) AS revenue
        FROM orders
        GROUP BY MONTH(order_date)
        ''',
    solution='''
        SELECT TRUNC(order_date, 'MM') AS month, SUM(amount) AS revenue
        FROM orders
        GROUP BY TRUNC(order_date, 'MM')
        ''',
    fixtures={
        "example": ("visible", {"orders": [
            {"order_id": 1, "customer_id": 1, "order_date": "2026-01-05", "status": "ON_TIME", "amount": 10.0},
            {"order_id": 2, "customer_id": 2, "order_date": "2026-01-20", "status": "ON_TIME", "amount": 15.0},
            {"order_id": 3, "customer_id": 1, "order_date": "2026-02-01", "status": "LATE", "amount": 7.0}]}),
        "two-januaries": ("hidden", {"orders": [
            {"order_id": 4, "customer_id": 3, "order_date": "2025-01-31", "status": "ON_TIME", "amount": 100.0},
            {"order_id": 5, "customer_id": 3, "order_date": "2026-01-01", "status": "ON_TIME", "amount": 1.0}]}),
        "one-order": ("edge", {"orders": [
            {"order_id": 6, "customer_id": 4, "order_date": "2026-12-31", "status": "ON_TIME", "amount": 2.5}]}),
    },
    exact_schema=["month", "revenue"],
    hints=["Is MONTH('2025-01-31') different from MONTH('2026-01-01')?", "TRUNC(date, 'MM') keeps year and month."],
    explanation=("A month bucket needs the year too. TRUNC(order_date, 'MM') maps every date to the first day of its "
                 "month as a DATE, which groups, sorts and joins to a calendar table cleanly."),
    follow_ups=["Add the months with no order (revenue 0) from a calendar table."],
    mutants=['''
        SELECT DATE_FORMAT(order_date, 'MM') AS month, SUM(amount) AS revenue FROM orders GROUP BY DATE_FORMAT(order_date, 'MM')
        '''],
)

# 8 Top-N per group ----------------------------------------------------------------
exercise(
    id="sparksql-top2-with-ties", title="Top 2 products per category, ties included", difficulty="medium",
    topics=["windows", "top-n", "cte"],
    prompt=("Return, per category, the products whose revenue is among the 2 highest distinct revenue values of that "
            "category (all tied products are kept). Output category, product, revenue."),
    tables={"sales": {"category": "VARCHAR", "product": "VARCHAR", "revenue": "DOUBLE"}},
    pitfall=("ROW_NUMBER cuts a tie arbitrarily; RANK skips a number after a tie (1, 1, 3) so the second value "
             "disappears. DENSE_RANK numbers distinct values (1, 1, 2)."),
    starter='''
        -- Bug: a tie is cut, and which product survives is arbitrary.
        WITH ranked AS (
          SELECT category, product, revenue,
                 ROW_NUMBER() OVER (PARTITION BY category ORDER BY revenue DESC, product) AS rk
          FROM sales
        )
        SELECT category, product, revenue FROM ranked WHERE rk <= 2
        ''',
    solution='''
        WITH ranked AS (
          SELECT category, product, revenue,
                 DENSE_RANK() OVER (PARTITION BY category ORDER BY revenue DESC) AS rk
          FROM sales
        )
        SELECT category, product, revenue FROM ranked WHERE rk <= 2
        ''',
    fixtures={
        "example": ("visible", {"sales": [
            {"category": "books", "product": "atlas", "revenue": 50.0},
            {"category": "books", "product": "bible", "revenue": 50.0},
            {"category": "books", "product": "comic", "revenue": 20.0},
            {"category": "books", "product": "diary", "revenue": 5.0},
            {"category": "games", "product": "chess", "revenue": 30.0}]}),
        "tie-for-second": ("hidden", {"sales": [
            {"category": "toys", "product": "ball", "revenue": 90.0},
            {"category": "toys", "product": "kite", "revenue": 40.0},
            {"category": "toys", "product": "yoyo", "revenue": 40.0},
            {"category": "toys", "product": "top", "revenue": 10.0}]}),
        "one-product": ("edge", {"sales": [{"category": "misc", "product": "pen", "revenue": 1.0}]}),
    },
    exact_schema=["category", "product", "revenue"],
    hints=["Compare ROW_NUMBER, RANK and DENSE_RANK on 50, 50, 20.", "The prompt counts distinct revenue values."],
    explanation=("DENSE_RANK gives equal values the same number without gaps, so rk <= 2 keeps every product whose "
                 "revenue is one of the two highest distinct values."),
    follow_ups=["What changes if the business wants at most 2 products, ties broken by product name?"],
    mutants=['''
        WITH ranked AS (SELECT category, product, revenue,
          RANK() OVER (PARTITION BY category ORDER BY revenue DESC) AS rk FROM sales)
        SELECT category, product, revenue FROM ranked WHERE rk <= 2
        '''],
)

# 9 Strings ---------------------------------------------------------------------
exercise(
    id="sparksql-email-domains", title="Customers per email domain", difficulty="easy",
    topics=["strings", "aggregation"],
    prompt=("Count the customers per email domain (the part after @), case-insensitively and in lower case. Ignore "
            "customers without an email. Output domain, customers."),
    tables={"customers": CUSTOMERS},
    pitfall=("String comparison and GROUP BY are case-sensitive in Spark: 'Mail.io' and 'mail.io' are two groups. "
             "Normalize with LOWER before grouping; SPLIT_PART(email, '@', 2) is the part after the @."),
    starter='''
        -- Bug: the same domain in different cases is counted twice.
        SELECT SPLIT_PART(email, '@', 2) AS domain, COUNT(*) AS customers
        FROM customers
        WHERE email IS NOT NULL
        GROUP BY SPLIT_PART(email, '@', 2)
        ''',
    solution='''
        SELECT LOWER(SPLIT_PART(email, '@', 2)) AS domain, COUNT(*) AS customers
        FROM customers
        WHERE email IS NOT NULL
        GROUP BY LOWER(SPLIT_PART(email, '@', 2))
        ''',
    fixtures={
        "example": ("visible", {"customers": [
            {"customer_id": 1, "name": "Ana", "email": "ana@mail.io"},
            {"customer_id": 2, "name": "Bo", "email": "bo@Mail.io"},
            {"customer_id": 3, "name": "Cy", "email": "cy@corp.eu"}]}),
        "missing-emails": ("hidden", {"customers": [
            {"customer_id": 4, "name": "Di", "email": None},
            {"customer_id": 5, "name": "Ed", "email": "ED@CORP.EU"},
            {"customer_id": 6, "name": "Flo", "email": "flo@corp.eu"}]}),
        "nobody-with-email": ("edge", {"customers": [{"customer_id": 7, "name": "Gus", "email": None}]}),
    },
    exact_schema=["domain", "customers"],
    hints=["Are 'Mail.io' and 'mail.io' equal in Spark?", "LOWER(SPLIT_PART(email, '@', 2))."],
    explanation=("GROUP BY compares strings exactly. Lower-casing the domain first puts every spelling of a domain in "
                 "one group; the WHERE clause drops customers without an email before counting."),
    follow_ups=["Which customers have an email with no @ at all?"],
    mutants=['''
        SELECT LOWER(SPLIT_PART(email, '@', 2)) AS domain, COUNT(*) AS customers
        FROM customers GROUP BY LOWER(SPLIT_PART(email, '@', 2))
        '''],
)


# -----------------------------------------------------------------------------
def definition(spec: dict, rank: int) -> dict:
    sample_tables = next(iter(spec["fixtures"].values()))[1]
    table_lines = [f"{name}({', '.join(f'{c} {t}' for c, t in cols.items())})" for name, cols in spec["tables"].items()]
    by_visibility = {"visible": [], "hidden": [], "edge": []}
    for fid, (visibility, _) in spec["fixtures"].items():
        by_visibility[visibility].append(fid)
    return {
        "schema_version": 1, "id": spec["id"], "version": "1", "title": spec["title"],
        "difficulty": spec["difficulty"], "topics": spec["topics"], "tags": ["spark-lab", "spark-sql"],
        "origin": "authored", "language": "sparksql", "runtime": "spark-sql-dialect-duckdb-v1",
        "prompt": spec["prompt"],
        "sections": [
            {"title": "Tables", "body": "\n".join(table_lines)},
            {"title": "Output", "body": f"Columns in this order: {', '.join(spec['exact_schema'])}. Row order does not matter."},
            {"title": "Common pitfall", "body": spec["pitfall"]},
        ],
        "starter_source": spec["starter"],
        "fixtures": [{"id": f"{spec['id']}-fixtures", "version": "1"}],
        "visible_checks": [{"id": fid, "description": "Public example: the tables shown in data_context."}
                           for fid in by_visibility["visible"]],
        "hidden_check_refs": by_visibility["hidden"], "edge_check_refs": by_visibility["edge"],
        "hints": spec["hints"], "solution": {"available": True, "reveal": "explicit"},
        "explanation": spec["explanation"], "follow_ups": spec["follow_ups"],
        "canonical_placement": {"domain": "spark-sql", "topic": spec["topics"][0]},
        "related_associations": ["sparklab/spark-sql"],
        "recommendation": {"rank": rank, "reason": "Spark SQL track"},
        "validator_version": "rows-v2",
        "validation": {
            "kind": "rows", "ordered": False, "duplicate_sensitive": True,
            "relative_tolerance": 1e-09, "absolute_tolerance": 1e-06,
            "required_columns": spec["exact_schema"], "exact_schema": spec["exact_schema"],
            "forbidden_extra_columns": True, "null_semantics": "equal",
        },
        "data_context": [{"name": name, "columns": cols, "sample_rows": sample_tables[name]}
                         for name, cols in spec["tables"].items()],
        "output_schema": {column: "value" for column in spec["exact_schema"]},
        "runtime_requirements": [],
        "provenance": {"source": "Authored for Datapass Workbench: Spark SQL track of the Spark Lab",
                       "fixtures": "Authored for Datapass; expected rows computed from the reference solution and reviewed"},
        "constraints": {
            "fixtures": "At most 200 rows per table; complete results are graded, truncated results never pass.",
            "truth": ("Spark SQL dialect translated to DuckDB, not Spark: sqlglot translates a documented subset "
                      "(runtime/sqldialects) and the result really runs on DuckDB."),
        },
        "truth": "semantic-emulation",
    }


def expected_rows(engine, spec: dict, tables: dict) -> list[dict]:
    from datapass_runtime.exercise_contracts import ExerciseDefinition
    from datapass_runtime.exercise_packs import Fixture
    from datapass_runtime.exercises import _fixture_ctes
    model = ExerciseDefinition.model_validate(definition(spec, 1))
    fixture = Fixture(id="x", visibility="visible", input_rows=[], expected=[], tables=tables)
    run = engine.execute({
        "cell_id": "gen", "notebook_id": "gen-" + spec["id"], "language": "sparksql", "code": spec["solution"],
        "_exercise_fixture_ctes": _fixture_ctes(model, fixture),
        "_exercise_schema": {c.name: dict(c.columns) for c in model.data_context},
    })
    if run["status"] != "success":
        raise SystemExit(f"{spec['id']}: reference failed: {run.get('error')}")
    if run["result"]["columns"] != spec["exact_schema"]:
        raise SystemExit(f"{spec['id']}: reference columns {run['result']['columns']} != {spec['exact_schema']}")
    return run["result"]["rows"]


def main() -> None:
    from datapass_runtime.execution import Engine
    from datapass_runtime.exercise_packs import PackRegistry
    assert len({s["id"] for s in EXERCISES}) == len(EXERCISES)
    definitions, grading = [], {}
    with tempfile.TemporaryDirectory() as temp:
        engine = Engine(Path(temp), mode="duckdb")
        for rank, spec in enumerate(EXERCISES, start=1):
            definitions.append(definition(spec, rank))
            grading[spec["id"]] = {"solution": spec["solution"], "fixtures": [
                {"id": fid, "visibility": visibility, "input_rows": [], "tables": tables,
                 "expected": expected_rows(engine, spec, tables)}
                for fid, (visibility, tables) in spec["fixtures"].items()]}
        engine.catalog.db.close()
    manifest = {"schema_version": 1, "id": "spark-sql-v1", "version": "1",
                "title": "Spark SQL: key patterns (Spark SQL translated to DuckDB)", "enabled": True,
                "provenance": {"source": "Authored for Datapass Workbench"}}
    PackRegistry().register(manifest, definitions, grading)  # validate before writing
    PACK.mkdir(parents=True, exist_ok=True)
    for name, data in (("manifest.json", manifest), ("exercises.json", definitions), ("grading.server.json", grading)):
        (PACK / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    quality = PACK / "quality.json"
    if not quality.exists():
        quality.write_text(json.dumps({"flags": {"runnable_starters": True}}) + "\n", encoding="utf-8", newline="\n")
    write_mutants(PACK, {spec["id"]: spec["mutants"] for spec in EXERCISES}, replace_all=True)
    for ident, graded in grading.items():
        print(f"== {ident}")
        for fixture in graded["fixtures"]:
            print(f"   {fixture['id']:22s}", json.dumps(fixture["expected"]))


if __name__ == "__main__":
    main()
