"""Generate content/exercise-packs/spark-lab-v1 from authored specs.

Expected rows are computed by running each reference solution through the real
SparkLab engine over the grader's own typed fixture CTEs; review them by hand.
Run from the repository root with PYTHONPATH=runtime.
"""
from __future__ import annotations

import json
import sys
import tempfile
import textwrap
from pathlib import Path

from pack_quality import write_mutants

ROOT = Path.cwd()
PACK = ROOT / "content" / "exercise-packs" / "spark-lab-v1"
GiB = 1024 ** 3
MiB = 1024 ** 2

F_IMPORT = "from pyspark.sql import functions as F\n"
W_IMPORT = "from pyspark.sql import functions as F\nfrom pyspark.sql.window import Window\n"


def code(text: str) -> str:
    imports, _, body = text.partition("\n\n")
    return imports + "\n" + textwrap.dedent(body).strip("\n") + "\n"


EXERCISES: list[dict] = []


def exercise(**spec):
    EXERCISES.append(spec)


# 1 ---------------------------------------------------------------------------
exercise(
    id="spark-left-join-filter-placement",
    title="Keep every customer when filtering the joined side",
    difficulty="easy",
    topics=["joins", "left-join", "filter-placement"],
    prompt=("Return every customer with each of their COMPLETED orders. A customer with no completed order "
            "still appears once, with NULL order_id and amount. Output customer_id, customer_name, order_id, amount."),
    tables={
        "customers": {"customer_id": "INTEGER", "customer_name": "VARCHAR"},
        "orders": {"order_id": "INTEGER", "customer_id": "INTEGER", "status": "VARCHAR", "amount": "DOUBLE"},
    },
    pitfall=("Filtering on an orders column after a left join removes the rows where the join found no match, "
             "so the left join silently becomes an inner join. Filter the right side before joining."),
    starter=code(F_IMPORT + '''
        customers = spark.table("customers")
        orders = spark.table("orders")
        # Bug: customers without a COMPLETED order disappear.
        joined = customers.join(orders, on="customer_id", how="left")
        result = joined.filter(F.col("status") == "COMPLETED").select("customer_id", "customer_name", "order_id", "amount")
        '''),
    solution=code(F_IMPORT + '''
        customers = spark.table("customers")
        orders = spark.table("orders")
        completed = orders.filter(F.col("status") == "COMPLETED").select("order_id", "customer_id", "amount")
        result = customers.join(completed, on="customer_id", how="left").select("customer_id", "customer_name", "order_id", "amount")
        '''),
    fixtures={
        "example": ("visible", {
            "customers": [{"customer_id": 1, "customer_name": "Ana"}, {"customer_id": 2, "customer_name": "Bo"},
                          {"customer_id": 3, "customer_name": "Cy"}],
            "orders": [{"order_id": 10, "customer_id": 1, "status": "COMPLETED", "amount": 120.0},
                       {"order_id": 11, "customer_id": 1, "status": "CANCELLED", "amount": 40.0},
                       {"order_id": 12, "customer_id": 2, "status": "CANCELLED", "amount": 55.0}],
        }),
        "several-completed-orders": ("hidden", {
            "customers": [{"customer_id": 4, "customer_name": "Di"}, {"customer_id": 5, "customer_name": "Ed"}],
            "orders": [{"order_id": 20, "customer_id": 4, "status": "COMPLETED", "amount": 10.0},
                       {"order_id": 21, "customer_id": 4, "status": "COMPLETED", "amount": 15.5},
                       {"order_id": 22, "customer_id": 5, "status": "PENDING", "amount": 8.0}],
        }),
        "no-orders-at-all": ("edge", {
            "customers": [{"customer_id": 7, "customer_name": "Flo"}],
            "orders": [],
        }),
    },
    exact_schema=["customer_id", "customer_name", "order_id", "amount"],
    hints=["Which rows does a WHERE-style filter on status remove when status is NULL?",
           "Filter orders to COMPLETED first, then left-join customers to that smaller DataFrame."],
    explanation=("A left join keeps unmatched customers by filling the orders columns with NULL. A later filter on "
                 "status evaluates NULL = 'COMPLETED' as unknown and drops those rows. Filtering orders before the join "
                 "keeps the join's left-preserving semantics."),
    follow_ups=["How would you also keep customers whose only orders are CANCELLED, but show a count of them?"],
    mutants=[
        code(F_IMPORT + '''
            customers = spark.table("customers")
            orders = spark.table("orders")
            joined = customers.join(orders, on="customer_id", how="left")
            result = joined.filter(F.col("status") == "COMPLETED").select("customer_id", "customer_name", "order_id", "amount")
            '''),
        code(F_IMPORT + '''
            customers = spark.table("customers")
            orders = spark.table("orders")
            joined = customers.join(orders, on="customer_id", how="left")
            kept = joined.filter((F.col("status") == "COMPLETED") | F.col("status").isNull())
            result = kept.select("customer_id", "customer_name", "order_id", "amount")
            '''),
    ],
)

# 2 ---------------------------------------------------------------------------
exercise(
    id="spark-semi-join-existence",
    title="Customers who ordered: a semi join returns each customer once",
    difficulty="easy",
    topics=["joins", "semi-join", "duplicates"],
    prompt=("Return the customers who placed at least one order in 2026, once each, with only the customer "
            "columns. Output customer_id, customer_name, country."),
    tables={
        "customers": {"customer_id": "INTEGER", "customer_name": "VARCHAR", "country": "VARCHAR"},
        "orders": {"order_id": "INTEGER", "customer_id": "INTEGER", "order_date": "DATE"},
    },
    pitfall=("An inner join returns one row per matching order, so a customer with three orders appears three "
             "times. A left_semi join only tests existence and never duplicates the left side."),
    starter=code(F_IMPORT + '''
        customers = spark.table("customers")
        orders = spark.table("orders")
        orders_2026 = orders.filter(F.col("order_date").between("2026-01-01", "2026-12-31"))
        # Bug: a customer with several 2026 orders is returned several times.
        result = customers.join(orders_2026, on="customer_id", how="inner").select("customer_id", "customer_name", "country")
        '''),
    solution=code(F_IMPORT + '''
        customers = spark.table("customers")
        orders = spark.table("orders")
        orders_2026 = orders.filter(F.col("order_date").between("2026-01-01", "2026-12-31"))
        result = customers.join(orders_2026, on="customer_id", how="left_semi")
        '''),
    fixtures={
        "example": ("visible", {
            "customers": [{"customer_id": 1, "customer_name": "Ana", "country": "FR"},
                          {"customer_id": 2, "customer_name": "Bo", "country": "DE"},
                          {"customer_id": 3, "customer_name": "Cy", "country": "FR"}],
            "orders": [{"order_id": 10, "customer_id": 1, "order_date": "2026-02-01"},
                       {"order_id": 11, "customer_id": 1, "order_date": "2026-03-15"},
                       {"order_id": 12, "customer_id": 3, "order_date": "2025-12-31"}],
        }),
        "year-boundaries": ("hidden", {
            "customers": [{"customer_id": 4, "customer_name": "Di", "country": "ES"},
                          {"customer_id": 5, "customer_name": "Ed", "country": "FR"},
                          {"customer_id": 6, "customer_name": "Flo", "country": "IT"}],
            "orders": [{"order_id": 20, "customer_id": 4, "order_date": "2026-01-01"},
                       {"order_id": 21, "customer_id": 5, "order_date": "2026-12-31"},
                       {"order_id": 22, "customer_id": 5, "order_date": "2026-06-01"},
                       {"order_id": 23, "customer_id": 99, "order_date": "2026-05-05"}],
        }),
        "no-orders": ("edge", {
            "customers": [{"customer_id": 7, "customer_name": "Gus", "country": "FR"}],
            "orders": [],
        }),
    },
    exact_schema=["customer_id", "customer_name", "country"],
    hints=["Count how many rows an inner join produces for a customer with two orders.",
           "join(..., how=\"left_semi\") keeps each left row at most once and adds no right-side columns."],
    explanation=("Existence questions are semi joins. Spark implements left_semi without adding right-side columns "
                 "and without multiplying left rows, so no distinct() is needed afterwards."),
    follow_ups=["Which join type returns the customers with no 2026 order?",
                "Why is join + distinct() more expensive than a semi join on large data?"],
    mutants=[
        code(F_IMPORT + '''
            customers = spark.table("customers")
            orders = spark.table("orders")
            orders_2026 = orders.filter(F.col("order_date").between("2026-01-01", "2026-12-31"))
            result = customers.join(orders_2026, on="customer_id", how="inner").select("customer_id", "customer_name", "country")
            '''),
        code(F_IMPORT + '''
            customers = spark.table("customers")
            orders = spark.table("orders")
            result = customers.join(orders, on="customer_id", how="left_semi")
            '''),
        code(F_IMPORT + '''
            customers = spark.table("customers")
            orders = spark.table("orders")
            orders_2026 = orders.filter((F.col("order_date") > "2026-01-01") & (F.col("order_date") < "2026-12-31"))
            result = customers.join(orders_2026, on="customer_id", how="left_semi")
            '''),
    ],
)

# 3 ---------------------------------------------------------------------------
exercise(
    id="spark-count-column-vs-star",
    title="count(\"*\") vs count(column): clicks per campaign",
    difficulty="easy",
    topics=["aggregation", "count", "nulls"],
    prompt=("For each campaign return impressions (every event) and clicks (events whose clicked_at is set). "
            "Output campaign_id, impressions, clicks."),
    tables={"events": {"event_id": "INTEGER", "campaign_id": "VARCHAR", "clicked_at": "TIMESTAMP"}},
    pitfall=("F.count(\"*\") counts rows; F.count(\"column\") counts non-NULL values. F.countDistinct also "
             "merges equal values, so two clicks at the same timestamp count once."),
    starter=code(F_IMPORT + '''
        events = spark.table("events")
        # Bug: clicks equals impressions.
        result = events.groupBy("campaign_id").agg(F.count("*").alias("impressions"), F.count("*").alias("clicks"))
        '''),
    solution=code(F_IMPORT + '''
        events = spark.table("events")
        result = events.groupBy("campaign_id").agg(F.count("*").alias("impressions"), F.count("clicked_at").alias("clicks"))
        '''),
    fixtures={
        "example": ("visible", {"events": [
            {"event_id": 1, "campaign_id": "spring", "clicked_at": None},
            {"event_id": 2, "campaign_id": "spring", "clicked_at": "2026-03-01 10:00:00"},
            {"event_id": 3, "campaign_id": "spring", "clicked_at": None},
            {"event_id": 4, "campaign_id": "summer", "clicked_at": "2026-06-01 09:00:00"}]}),
        "same-second-clicks": ("hidden", {"events": [
            {"event_id": 10, "campaign_id": "fall", "clicked_at": "2026-10-01 08:00:00"},
            {"event_id": 11, "campaign_id": "fall", "clicked_at": "2026-10-01 08:00:00"},
            {"event_id": 12, "campaign_id": "fall", "clicked_at": None},
            {"event_id": 13, "campaign_id": "winter", "clicked_at": None}]}),
        "no-clicks": ("edge", {"events": [
            {"event_id": 20, "campaign_id": "launch", "clicked_at": None},
            {"event_id": 21, "campaign_id": "launch", "clicked_at": None}]}),
    },
    exact_schema=["campaign_id", "impressions", "clicks"],
    hints=["Which of count(\"*\") and count(\"clicked_at\") ignores NULL?"],
    explanation=("count(\"*\") counts rows, count(col) counts non-NULL values of col, countDistinct(col) counts "
                 "distinct non-NULL values. A campaign with no click still has impressions and 0 clicks."),
    follow_ups=["How would you compute a click-through rate that never divides by zero?"],
    mutants=[
        code(F_IMPORT + '''
            events = spark.table("events")
            result = events.groupBy("campaign_id").agg(F.count("*").alias("impressions"), F.count("*").alias("clicks"))
            '''),
        code(F_IMPORT + '''
            events = spark.table("events")
            result = events.groupBy("campaign_id").agg(F.count("*").alias("impressions"), F.countDistinct("clicked_at").alias("clicks"))
            '''),
    ],
)

# 4 ---------------------------------------------------------------------------
exercise(
    id="spark-null-safe-change-detection",
    title="Detect changed values with eqNullSafe",
    difficulty="medium",
    topics=["nulls", "change-detection", "joins"],
    prompt=("Compare yesterday's and today's customer snapshots. Return the customers present in both whose email "
            "changed, including a change from NULL or to NULL. Output customer_id, old_email, new_email."),
    tables={
        "yesterday": {"customer_id": "INTEGER", "email": "VARCHAR"},
        "today": {"customer_id": "INTEGER", "email": "VARCHAR"},
    },
    pitfall=("old != new is NULL, not true, when either side is NULL, so a filter drops those changes. "
             "~a.eqNullSafe(b) (SQL IS DISTINCT FROM) treats NULL as a comparable value."),
    starter=code(F_IMPORT + '''
        old = spark.table("yesterday").withColumnRenamed("email", "old_email")
        new = spark.table("today").withColumnRenamed("email", "new_email")
        # Bug: a change from or to NULL is missed.
        result = old.join(new, on="customer_id", how="inner").filter(F.col("old_email") != F.col("new_email"))
        '''),
    solution=code(F_IMPORT + '''
        old = spark.table("yesterday").withColumnRenamed("email", "old_email")
        new = spark.table("today").withColumnRenamed("email", "new_email")
        result = old.join(new, on="customer_id", how="inner").filter(~F.col("old_email").eqNullSafe(F.col("new_email")))
        '''),
    fixtures={
        "example": ("visible", {
            "yesterday": [{"customer_id": 1, "email": "ana@a.io"}, {"customer_id": 2, "email": "bo@b.io"},
                          {"customer_id": 3, "email": None}],
            "today": [{"customer_id": 1, "email": "ana@a.io"}, {"customer_id": 2, "email": "bo@new.io"},
                      {"customer_id": 3, "email": "cy@c.io"}],
        }),
        "cleared-and-unchanged-null": ("hidden", {
            "yesterday": [{"customer_id": 4, "email": "di@d.io"}, {"customer_id": 5, "email": None},
                          {"customer_id": 6, "email": "ed@e.io"}],
            "today": [{"customer_id": 4, "email": None}, {"customer_id": 5, "email": None},
                      {"customer_id": 6, "email": "ed@e.io"}, {"customer_id": 7, "email": "new@x.io"}],
        }),
        "nothing-changed": ("edge", {
            "yesterday": [{"customer_id": 8, "email": "x@x.io"}],
            "today": [{"customer_id": 8, "email": "x@x.io"}],
        }),
    },
    exact_schema=["customer_id", "old_email", "new_email"],
    hints=["What does NULL != 'cy@c.io' evaluate to?",
           "Column.eqNullSafe is Spark's <=>: two NULLs are equal and NULL vs a value is not."],
    explanation=("Change detection must treat NULL as a value: NULL to value and value to NULL are changes, NULL to "
                 "NULL is not. ~old.eqNullSafe(new) expresses exactly that; a plain != silently drops both NULL cases."),
    follow_ups=["How would you compare several columns at once without writing one condition per column?"],
    mutants=[
        code(F_IMPORT + '''
            old = spark.table("yesterday").withColumnRenamed("email", "old_email")
            new = spark.table("today").withColumnRenamed("email", "new_email")
            result = old.join(new, on="customer_id", how="inner").filter(F.col("old_email") != F.col("new_email"))
            '''),
        code(F_IMPORT + '''
            old = spark.table("yesterday").withColumnRenamed("email", "old_email")
            new = spark.table("today").withColumnRenamed("email", "new_email")
            joined = old.join(new, on="customer_id", how="inner")
            result = joined.filter((F.col("old_email") != F.col("new_email")) | F.col("old_email").isNull())
            '''),
    ],
)

# 5 ---------------------------------------------------------------------------
exercise(
    id="spark-full-outer-reconcile",
    title="Reconcile two systems with a full outer join",
    difficulty="medium",
    topics=["joins", "full-outer-join", "reconciliation"],
    prompt=("billing and ledger should hold the same invoices. Return one row per invoice found in either system "
            "with status 'missing_in_ledger', 'missing_in_billing', 'amount_mismatch' or 'match'. Amounts are never "
            "NULL in the source tables. Output invoice_id, billed_amount, booked_amount, status."),
    tables={
        "billing": {"invoice_id": "INTEGER", "billed_amount": "DOUBLE"},
        "ledger": {"invoice_id": "INTEGER", "booked_amount": "DOUBLE"},
    },
    pitfall=("A left join only sees invoices that exist in billing, so ledger-only invoices never show up. "
             "With on=\"invoice_id\", a full join returns a single invoice_id column filled from either side."),
    starter=code(F_IMPORT + '''
        billing = spark.table("billing")
        ledger = spark.table("ledger")
        # Bug: invoices that exist only in the ledger are missing.
        joined = billing.join(ledger, on="invoice_id", how="left")
        result = joined.withColumn(
            "status",
            F.when(F.col("booked_amount").isNull(), "missing_in_ledger")
            .when(F.col("billed_amount").isNull(), "missing_in_billing")
            .when(F.col("billed_amount") != F.col("booked_amount"), "amount_mismatch")
            .otherwise("match"),
        )
        '''),
    solution=code(F_IMPORT + '''
        billing = spark.table("billing")
        ledger = spark.table("ledger")
        joined = billing.join(ledger, on="invoice_id", how="full")
        result = joined.withColumn(
            "status",
            F.when(F.col("booked_amount").isNull(), "missing_in_ledger")
            .when(F.col("billed_amount").isNull(), "missing_in_billing")
            .when(F.col("billed_amount") != F.col("booked_amount"), "amount_mismatch")
            .otherwise("match"),
        )
        '''),
    fixtures={
        "example": ("visible", {
            "billing": [{"invoice_id": 1, "billed_amount": 100.0}, {"invoice_id": 2, "billed_amount": 50.0},
                        {"invoice_id": 3, "billed_amount": 75.0}],
            "ledger": [{"invoice_id": 1, "booked_amount": 100.0}, {"invoice_id": 2, "booked_amount": 45.0},
                       {"invoice_id": 4, "booked_amount": 20.0}],
        }),
        "disjoint-systems": ("hidden", {
            "billing": [{"invoice_id": 10, "billed_amount": 10.0}],
            "ledger": [{"invoice_id": 11, "booked_amount": 11.0}, {"invoice_id": 12, "booked_amount": 12.0}],
        }),
        "empty-billing": ("edge", {
            "billing": [],
            "ledger": [{"invoice_id": 20, "booked_amount": 5.0}],
        }),
    },
    exact_schema=["invoice_id", "billed_amount", "booked_amount", "status"],
    hints=["Which join type keeps unmatched rows from both sides?",
           "when() conditions are tested in order: check the missing sides before comparing amounts."],
    explanation=("Reconciliation needs every key from both systems: a full outer join. Joining on a column name "
                 "merges the two invoice_id columns into one, so it is never NULL, while each amount column is NULL "
                 "on the side where the invoice is missing."),
    follow_ups=["What changes if amounts can be NULL in the source tables?"],
    mutants=[
        code(F_IMPORT + '''
            billing = spark.table("billing")
            ledger = spark.table("ledger")
            joined = billing.join(ledger, on="invoice_id", how="left")
            result = joined.withColumn(
                "status",
                F.when(F.col("booked_amount").isNull(), "missing_in_ledger")
                .when(F.col("billed_amount").isNull(), "missing_in_billing")
                .when(F.col("billed_amount") != F.col("booked_amount"), "amount_mismatch")
                .otherwise("match"),
            )
            '''),
        code(F_IMPORT + '''
            billing = spark.table("billing")
            ledger = spark.table("ledger")
            joined = billing.join(ledger, on="invoice_id", how="inner")
            result = joined.withColumn(
                "status",
                F.when(F.col("billed_amount") != F.col("booked_amount"), "amount_mismatch").otherwise("match"),
            )
            '''),
    ],
)

# 6 ---------------------------------------------------------------------------
exercise(
    id="spark-join-fanout-before-sum",
    title="Aggregate before joining to avoid fan-out",
    difficulty="hard",
    topics=["joins", "fan-out", "aggregation"],
    prompt=("An order can use several promo codes. For each customer return revenue (the sum of order amounts, each "
            "order counted once) and promo_uses (the number of promo codes applied to their orders; 0 when none). "
            "Output customer_id, revenue, promo_uses."),
    tables={
        "orders": {"order_id": "INTEGER", "customer_id": "INTEGER", "amount": "DOUBLE"},
        "order_promos": {"order_id": "INTEGER", "promo_code": "VARCHAR"},
    },
    pitfall=("Joining orders to a one-to-many table repeats each order once per promo code, so summing amount "
             "after the join counts an order several times. Reduce the many side to one row per order first."),
    starter=code(F_IMPORT + '''
        orders = spark.table("orders")
        promos = spark.table("order_promos")
        # Bug: an order with two promo codes is counted twice in revenue.
        joined = orders.join(promos, on="order_id", how="left")
        result = joined.groupBy("customer_id").agg(F.sum("amount").alias("revenue"), F.count("promo_code").alias("promo_uses"))
        '''),
    solution=code(F_IMPORT + '''
        orders = spark.table("orders")
        promos = spark.table("order_promos")
        promo_counts = promos.groupBy("order_id").agg(F.count("*").alias("promo_count"))
        result = (
            orders.join(promo_counts, on="order_id", how="left")
            .groupBy("customer_id")
            .agg(F.sum("amount").alias("revenue"), F.sum(F.coalesce(F.col("promo_count"), F.lit(0))).alias("promo_uses"))
        )
        '''),
    fixtures={
        "example": ("visible", {
            "orders": [{"order_id": 1, "customer_id": 10, "amount": 100.0},
                       {"order_id": 2, "customer_id": 10, "amount": 50.0},
                       {"order_id": 3, "customer_id": 20, "amount": 80.0}],
            "order_promos": [{"order_id": 1, "promo_code": "SPRING"}, {"order_id": 1, "promo_code": "VIP"},
                             {"order_id": 3, "promo_code": "SPRING"}],
        }),
        "three-promos-and-none": ("hidden", {
            "orders": [{"order_id": 4, "customer_id": 30, "amount": 40.0},
                       {"order_id": 5, "customer_id": 30, "amount": 60.0},
                       {"order_id": 6, "customer_id": 40, "amount": 25.0}],
            "order_promos": [{"order_id": 5, "promo_code": "A"}, {"order_id": 5, "promo_code": "B"},
                             {"order_id": 5, "promo_code": "C"}],
        }),
        "no-promos": ("edge", {
            "orders": [{"order_id": 7, "customer_id": 50, "amount": 12.5}],
            "order_promos": [],
        }),
    },
    exact_schema=["customer_id", "revenue", "promo_uses"],
    hints=["After the join, how many rows does order 1 of the example have?",
           "groupBy(\"order_id\") on order_promos gives one row per order; join that instead.",
           "A left join leaves promo_count NULL for orders without promos: coalesce it to 0 before summing."],
    explanation=("Joining on a key that is unique on only one side multiplies rows. Aggregate the many side to the "
                 "join grain first (one row per order), then join and aggregate to the customer grain. The left join "
                 "keeps orders without promo codes, and coalesce turns their missing count into 0."),
    follow_ups=["How would you detect fan-out in a pipeline before it corrupts a revenue table?"],
    mutants=[
        code(F_IMPORT + '''
            orders = spark.table("orders")
            promos = spark.table("order_promos")
            joined = orders.join(promos, on="order_id", how="left")
            result = joined.groupBy("customer_id").agg(F.sum("amount").alias("revenue"), F.count("promo_code").alias("promo_uses"))
            '''),
        code(F_IMPORT + '''
            orders = spark.table("orders")
            promos = spark.table("order_promos")
            promo_counts = promos.groupBy("order_id").agg(F.count("*").alias("promo_count"))
            result = (
                orders.join(promo_counts, on="order_id", how="inner")
                .groupBy("customer_id")
                .agg(F.sum("amount").alias("revenue"), F.sum("promo_count").alias("promo_uses"))
            )
            '''),
    ],
)

# 7 ---------------------------------------------------------------------------
exercise(
    id="spark-running-total-ties",
    title="Running balance when dates tie: RANGE vs ROWS frames",
    difficulty="hard",
    topics=["window-functions", "window-frames", "ties"],
    prompt=("For each account return every transaction with running_balance: the sum of that account's amounts up to "
            "and including this transaction, in (txn_date, txn_id) order. Two transactions on the same date get "
            "different balances. Output account_id, txn_id, txn_date, amount, running_balance."),
    tables={"transactions": {"account_id": "VARCHAR", "txn_id": "INTEGER", "txn_date": "DATE", "amount": "DOUBLE"}},
    pitfall=("With orderBy and no explicit frame, Spark uses RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW: "
             "rows that tie on the ordering key are peers and all get the total of the whole tie group."),
    starter=code(W_IMPORT + '''
        transactions = spark.table("transactions")
        # Bug: transactions on the same date show the same balance.
        w = Window.partitionBy("account_id").orderBy("txn_date")
        result = transactions.withColumn("running_balance", F.sum("amount").over(w))
        '''),
    solution=code(W_IMPORT + '''
        transactions = spark.table("transactions")
        w = (
            Window.partitionBy("account_id")
            .orderBy("txn_date", "txn_id")
            .rowsBetween(Window.unboundedPreceding, Window.currentRow)
        )
        result = transactions.withColumn("running_balance", F.sum("amount").over(w))
        '''),
    fixtures={
        "example": ("visible", {"transactions": [
            {"account_id": "A", "txn_id": 1, "txn_date": "2026-01-01", "amount": 100.0},
            {"account_id": "A", "txn_id": 2, "txn_date": "2026-01-02", "amount": -30.0},
            {"account_id": "A", "txn_id": 3, "txn_date": "2026-01-02", "amount": 50.0},
            {"account_id": "B", "txn_id": 4, "txn_date": "2026-01-01", "amount": 10.0}]}),
        "three-way-tie": ("hidden", {"transactions": [
            {"account_id": "C", "txn_id": 10, "txn_date": "2026-02-01", "amount": 5.0},
            {"account_id": "C", "txn_id": 11, "txn_date": "2026-02-01", "amount": 5.0},
            {"account_id": "C", "txn_id": 12, "txn_date": "2026-02-01", "amount": 5.0},
            {"account_id": "D", "txn_id": 13, "txn_date": "2026-02-01", "amount": 1.0}]}),
        "single-transaction": ("edge", {"transactions": [
            {"account_id": "E", "txn_id": 20, "txn_date": "2026-03-01", "amount": 0.0}]}),
    },
    exact_schema=["account_id", "txn_id", "txn_date", "amount", "running_balance"],
    hints=["What frame does Spark use when a window has orderBy but no rowsBetween?",
           "Order by txn_date then txn_id so every row has a unique position, and say ROWS explicitly."],
    explanation=("The default frame of an ordered window is RANGE-based, so peers (equal ordering values) share one "
                 "running total. A unique ordering (txn_date, txn_id) plus an explicit "
                 "rowsBetween(Window.unboundedPreceding, Window.currentRow) gives one balance per transaction, "
                 "deterministically."),
    follow_ups=["Why is rowsBetween without the txn_id tie-breaker still unsafe?",
                "When is the RANGE behavior actually what you want?"],
    mutants=[
        code(W_IMPORT + '''
            transactions = spark.table("transactions")
            w = Window.partitionBy("account_id").orderBy("txn_date")
            result = transactions.withColumn("running_balance", F.sum("amount").over(w))
            '''),
        code(W_IMPORT + '''
            transactions = spark.table("transactions")
            w = Window.orderBy("txn_date", "txn_id").rowsBetween(Window.unboundedPreceding, Window.currentRow)
            result = transactions.withColumn("running_balance", F.sum("amount").over(w))
            '''),
    ],
)

# 8 ---------------------------------------------------------------------------
exercise(
    id="spark-coalesce-output-partitions",
    title="Fewer output partitions without a shuffle: coalesce vs repartition",
    difficulty="easy",
    topics=["partitions", "coalesce", "shuffle"],
    prompt=("Keep the French (country = 'FR') events with event_id, event_date and amount. The writer downstream "
            "must receive at most 16 partitions, and the plan must not add a shuffle."),
    tables={"events": {"event_id": "INTEGER", "event_date": "DATE", "country": "VARCHAR", "amount": "DOUBLE"}},
    pitfall=("repartition(n) always performs a full shuffle. coalesce(n) only merges existing partitions, so it "
             "reduces the partition count without moving rows across the network."),
    starter=code(F_IMPORT + '''
        events = spark.table("events")
        # 16 partitions, but repartition() shuffles every surviving row.
        result = events.filter(F.col("country") == "FR").select("event_id", "event_date", "amount").repartition(16)
        '''),
    solution=code(F_IMPORT + '''
        events = spark.table("events")
        result = events.filter(F.col("country") == "FR").select("event_id", "event_date", "amount").coalesce(16)
        '''),
    fixtures={
        "example": ("visible", {"events": [
            {"event_id": 1, "event_date": "2026-05-01", "country": "FR", "amount": 10.0},
            {"event_id": 2, "event_date": "2026-05-01", "country": "DE", "amount": 20.0},
            {"event_id": 3, "event_date": "2026-05-02", "country": "FR", "amount": 30.0}]}),
        "mixed-countries": ("hidden", {"events": [
            {"event_id": 4, "event_date": "2026-05-03", "country": "FR", "amount": 5.0},
            {"event_id": 5, "event_date": "2026-05-03", "country": "BE", "amount": 6.0},
            {"event_id": 6, "event_date": "2026-05-04", "country": "FR", "amount": 7.5}]}),
        "no-french-events": ("edge", {"events": [
            {"event_id": 7, "event_date": "2026-05-05", "country": "ES", "amount": 1.0}]}),
    },
    exact_schema=["event_id", "event_date", "amount"],
    spark_plan={
        "profile": "generic_8x8", "aqe": True,
        "scale": {"events": {"rows": 2_400_000_000, "bytes": 96 * GiB, "partitions": 1536}},
        "checks": [
            {"id": "plan-no-shuffle", "description": "The plan adds no shuffle exchange.",
             "rule": "max_exchanges", "value": 0},
            {"id": "plan-at-most-16-partitions", "description": "The result has at most 16 partitions.",
             "rule": "max_output_partitions", "value": 16},
        ],
    },
    hints=["Which of repartition() and coalesce() is a narrow transformation?"],
    explanation=("coalesce(16) merges the 1,536 scan partitions into 16 without an exchange. The trade-off: Spark "
                 "pushes the coalesce into the scan stage, so the filter itself then runs in only 16 tasks. When the "
                 "upstream work is heavy, repartition(16) can be faster despite its shuffle; here the filter is cheap, "
                 "so avoiding a 96 GB-scale shuffle wins."),
    follow_ups=["When would repartition(16) be the better choice before a write?",
                "What does coalesce(4000) do when there are only 1,536 partitions?"],
    mutants=[
        code(F_IMPORT + '''
            events = spark.table("events")
            result = events.filter(F.col("country") == "FR").select("event_id", "event_date", "amount").repartition(16)
            '''),
        code(F_IMPORT + '''
            events = spark.table("events")
            result = events.filter(F.col("country") == "FR").select("event_id", "event_date", "amount").coalesce(64)
            '''),
        code(F_IMPORT + '''
            events = spark.table("events")
            result = events.filter(F.col("country") == "FR").select("event_id", "event_date", "amount")
            '''),
    ],
)

# 9 ---------------------------------------------------------------------------
exercise(
    id="spark-one-pass-aggregation",
    title="Compute several metrics in one groupBy",
    difficulty="easy",
    topics=["aggregation", "shuffle", "plan"],
    prompt=("For each customer return order_count (every order, including orders with a NULL amount) and revenue. "
            "Compute both in a single pass: the plan may use at most one shuffle exchange. "
            "Output customer_id, order_count, revenue."),
    tables={"orders": {"order_id": "INTEGER", "customer_id": "INTEGER", "amount": "DOUBLE"}},
    pitfall=("Each groupBy shuffles its input. Two groupBys on the same key followed by a join shuffle the orders "
             "twice, although one groupBy(...).agg(...) can compute every metric in one exchange."),
    starter=code(F_IMPORT + '''
        orders = spark.table("orders")
        # Right result, but the orders are shuffled twice.
        counts = orders.groupBy("customer_id").agg(F.count("*").alias("order_count"))
        revenue = orders.groupBy("customer_id").agg(F.sum("amount").alias("revenue"))
        result = counts.join(revenue, on="customer_id", how="inner")
        '''),
    solution=code(F_IMPORT + '''
        orders = spark.table("orders")
        result = orders.groupBy("customer_id").agg(F.count("*").alias("order_count"), F.sum("amount").alias("revenue"))
        '''),
    fixtures={
        "example": ("visible", {"orders": [
            {"order_id": 1, "customer_id": 10, "amount": 20.0},
            {"order_id": 2, "customer_id": 10, "amount": 30.0},
            {"order_id": 3, "customer_id": 20, "amount": 5.0}]}),
        "null-amounts": ("hidden", {"orders": [
            {"order_id": 4, "customer_id": 30, "amount": None},
            {"order_id": 5, "customer_id": 30, "amount": 12.0},
            {"order_id": 6, "customer_id": 40, "amount": None}]}),
        "single-order": ("edge", {"orders": [
            {"order_id": 7, "customer_id": 50, "amount": 0.0}]}),
    },
    exact_schema=["customer_id", "order_count", "revenue"],
    spark_plan={
        "profile": "generic_8x8", "aqe": True,
        "scale": {"orders": {"rows": 300_000_000, "bytes": 24 * GiB, "partitions": 192}},
        "checks": [
            {"id": "plan-single-shuffle", "description": "The plan uses at most one shuffle exchange.",
             "rule": "max_exchanges", "value": 1},
        ],
    },
    hints=["agg() accepts several aggregate expressions.",
           "count(\"amount\") skips NULL amounts; the prompt counts every order."],
    explanation=("One groupBy(\"customer_id\").agg(count, sum) needs one hash exchange by customer_id. The two-groupBy "
                 "version exchanges the orders twice; the join itself adds no third exchange because both sides are "
                 "already hash-partitioned by customer_id, but the extra full shuffle remains."),
    follow_ups=["Why does the join of the two aggregates not need its own exchange?"],
    mutants=[
        code(F_IMPORT + '''
            orders = spark.table("orders")
            counts = orders.groupBy("customer_id").agg(F.count("*").alias("order_count"))
            revenue = orders.groupBy("customer_id").agg(F.sum("amount").alias("revenue"))
            result = counts.join(revenue, on="customer_id", how="inner")
            '''),
        code(F_IMPORT + '''
            orders = spark.table("orders")
            result = orders.groupBy("customer_id").agg(F.count("amount").alias("order_count"), F.sum("amount").alias("revenue"))
            '''),
    ],
)

# 10 --------------------------------------------------------------------------
exercise(
    id="spark-broadcast-dimension",
    title="Broadcast a dimension above the auto-broadcast threshold",
    difficulty="medium",
    topics=["joins", "broadcast-join", "shuffle"],
    prompt=("Return revenue per region. stores is 48 MB, above the default 10 MB "
            "spark.sql.autoBroadcastJoinThreshold, so Spark plans a sort-merge join that shuffles all of sales "
            "(72 GB). Make the join a broadcast join so that only the groupBy(\"region\") shuffle remains. "
            "Sales for an unknown store are excluded. Output region, revenue."),
    tables={
        "sales": {"sale_id": "INTEGER", "store_id": "INTEGER", "amount": "DOUBLE"},
        "stores": {"store_id": "INTEGER", "region": "VARCHAR"},
    },
    pitfall=("Spark broadcasts automatically only below spark.sql.autoBroadcastJoinThreshold (10 MB by default). "
             "F.broadcast() on the small side overrides that; broadcasting the large side instead fails in real "
             "Spark, which refuses to broadcast more than 8 GB."),
    starter=code(F_IMPORT + '''
        sales = spark.table("sales")
        stores = spark.table("stores")
        # Right result, but a sort-merge join shuffles both inputs.
        result = sales.join(stores, on="store_id", how="inner").groupBy("region").agg(F.sum("amount").alias("revenue"))
        '''),
    solution=code(F_IMPORT + '''
        sales = spark.table("sales")
        stores = spark.table("stores")
        result = sales.join(F.broadcast(stores), on="store_id", how="inner").groupBy("region").agg(F.sum("amount").alias("revenue"))
        '''),
    fixtures={
        "example": ("visible", {
            "sales": [{"sale_id": 1, "store_id": 1, "amount": 100.0}, {"sale_id": 2, "store_id": 2, "amount": 40.0},
                      {"sale_id": 3, "store_id": 1, "amount": 60.0}],
            "stores": [{"store_id": 1, "region": "North"}, {"store_id": 2, "region": "South"}],
        }),
        "unknown-store": ("hidden", {
            "sales": [{"sale_id": 4, "store_id": 3, "amount": 10.0}, {"sale_id": 5, "store_id": 4, "amount": 15.0},
                      {"sale_id": 6, "store_id": 99, "amount": 5.0}],
            "stores": [{"store_id": 3, "region": "East"}, {"store_id": 4, "region": "East"}],
        }),
        "no-sales": ("edge", {
            "sales": [],
            "stores": [{"store_id": 5, "region": "West"}],
        }),
    },
    exact_schema=["region", "revenue"],
    spark_plan={
        "profile": "generic_8x8", "aqe": True,
        "scale": {
            "sales": {"rows": 600_000_000, "bytes": 72 * GiB, "partitions": 576},
            "stores": {"rows": 40_000, "bytes": 48 * MiB, "partitions": 1},
        },
        "checks": [
            {"id": "plan-broadcast-join", "description": "The sales-stores join is a broadcast hash join.",
             "rule": "min_broadcast_joins", "value": 1},
            {"id": "plan-single-shuffle", "description": "Only the groupBy(\"region\") shuffle exchange remains.",
             "rule": "max_exchanges", "value": 1},
        ],
    },
    hints=["F.broadcast(df) marks a DataFrame to be sent to every executor.",
           "Keep sales on the left and broadcast the small right side."],
    explanation=("A broadcast hash join ships the 48 MB stores table to every executor and streams sales without "
                 "moving it, which removes both join exchanges. The aggregation by region still needs one hash "
                 "exchange. Broadcasting costs executor and driver memory, so reserve it for inputs that comfortably "
                 "fit, or raise the threshold deliberately."),
    follow_ups=["Could AQE have switched to a broadcast join at runtime here? Why not?",
                "What happens with F.broadcast(sales)?"],
    mutants=[
        code(F_IMPORT + '''
            sales = spark.table("sales")
            stores = spark.table("stores")
            result = sales.join(stores, on="store_id", how="inner").groupBy("region").agg(F.sum("amount").alias("revenue"))
            '''),
        code(F_IMPORT + '''
            sales = spark.table("sales")
            stores = spark.table("stores")
            result = stores.join(F.broadcast(sales), on="store_id", how="inner").groupBy("region").agg(F.sum("amount").alias("revenue"))
            '''),
        code(F_IMPORT + '''
            sales = spark.table("sales")
            stores = spark.table("stores")
            result = sales.join(F.broadcast(stores), on="store_id", how="left").groupBy("region").agg(F.sum("amount").alias("revenue"))
            '''),
    ],
)

# 11 --------------------------------------------------------------------------
exercise(
    id="spark-remove-random-repartition",
    title="Drop the random repartition before a window",
    difficulty="medium",
    topics=["partitions", "window-functions", "shuffle"],
    prompt=("Number each customer's orders chronologically as order_seq (1 = first order; order_id breaks ties "
            "on order_ts). The inherited code calls repartition(400) first \"to speed things up\". The plan may use "
            "at most one shuffle exchange. Output order_id, customer_id, order_ts, amount, order_seq."),
    tables={"orders": {"order_id": "INTEGER", "customer_id": "INTEGER", "order_ts": "TIMESTAMP", "amount": "DOUBLE"}},
    pitfall=("repartition(400) distributes rows round-robin, so the window still has to shuffle again by "
             "customer_id: two full shuffles for one result. A window partitioned by customer_id brings its own "
             "exchange."),
    starter=code(W_IMPORT + '''
        orders = spark.table("orders")
        w = Window.partitionBy("customer_id").orderBy("order_ts", "order_id")
        # Right result, but repartition(400) adds a second full shuffle.
        result = orders.repartition(400).withColumn("order_seq", F.row_number().over(w))
        '''),
    solution=code(W_IMPORT + '''
        orders = spark.table("orders")
        w = Window.partitionBy("customer_id").orderBy("order_ts", "order_id")
        result = orders.withColumn("order_seq", F.row_number().over(w))
        '''),
    fixtures={
        "example": ("visible", {"orders": [
            {"order_id": 1, "customer_id": 10, "order_ts": "2026-01-05 10:00:00", "amount": 20.0},
            {"order_id": 2, "customer_id": 10, "order_ts": "2026-01-03 09:00:00", "amount": 15.0},
            {"order_id": 3, "customer_id": 20, "order_ts": "2026-01-04 08:00:00", "amount": 30.0}]}),
        "timestamp-ties": ("hidden", {"orders": [
            {"order_id": 4, "customer_id": 30, "order_ts": "2026-02-01 12:00:00", "amount": 5.0},
            {"order_id": 5, "customer_id": 30, "order_ts": "2026-02-01 12:00:00", "amount": 6.0},
            {"order_id": 6, "customer_id": 30, "order_ts": "2026-01-31 23:59:59", "amount": 7.0}]}),
        "single-order": ("edge", {"orders": [
            {"order_id": 7, "customer_id": 40, "order_ts": "2026-03-01 00:00:00", "amount": 1.0}]}),
    },
    exact_schema=["order_id", "customer_id", "order_ts", "amount", "order_seq"],
    spark_plan={
        "profile": "generic_8x8", "aqe": True,
        "scale": {"orders": {"rows": 300_000_000, "bytes": 24 * GiB, "partitions": 192}},
        "checks": [
            {"id": "plan-single-shuffle", "description": "The plan uses at most one shuffle exchange.",
             "rule": "max_exchanges", "value": 1},
        ],
    },
    hints=["Which exchange does Window.partitionBy(\"customer_id\") already require?",
           "Does a round-robin repartition put one customer's orders in the same partition?"],
    explanation=("The window needs rows clustered by customer_id and adds that hash exchange itself. A round-robin "
                 "repartition(400) does not cluster by customer, so the window shuffles again. Removing it leaves one "
                 "exchange. repartition(400, \"customer_id\") would also pass: its hash partitioning already satisfies "
                 "the window, so it replaces the window's exchange rather than adding one."),
    follow_ups=["When is an explicit repartition before a window worth it?"],
    mutants=[
        code(W_IMPORT + '''
            orders = spark.table("orders")
            w = Window.partitionBy("customer_id").orderBy("order_ts", "order_id")
            result = orders.repartition(400).withColumn("order_seq", F.row_number().over(w))
            '''),
        code(W_IMPORT + '''
            orders = spark.table("orders")
            w = Window.partitionBy("customer_id").orderBy("order_ts", "order_id")
            result = orders.repartition(400, "order_id").withColumn("order_seq", F.row_number().over(w))
            '''),
        code(W_IMPORT + '''
            orders = spark.table("orders")
            w = Window.partitionBy("customer_id").orderBy(F.col("order_ts").desc(), F.col("order_id").desc())
            result = orders.withColumn("order_seq", F.row_number().over(w))
            '''),
    ],
)

# 12 --------------------------------------------------------------------------
exercise(
    id="spark-window-instead-of-self-join",
    title="Replace an aggregate self-join with a window",
    difficulty="medium",
    topics=["window-functions", "joins", "shuffle"],
    prompt=("Return every order with its customer's total (customer_total) and the order's share of it "
            "(amount_share = amount / customer_total). The inherited code aggregates and joins the totals back; "
            "compute it with at most one shuffle exchange. "
            "Output order_id, customer_id, amount, customer_total, amount_share."),
    tables={"orders": {"order_id": "INTEGER", "customer_id": "INTEGER", "amount": "DOUBLE"}},
    pitfall=("groupBy + join back shuffles the orders for the aggregate and again for the join. A window partitioned "
             "by customer_id computes the same total on every row with a single exchange. Adding orderBy to that "
             "window would turn the total into a running sum."),
    starter=code(F_IMPORT + '''
        orders = spark.table("orders")
        # Right result, but the orders are shuffled for the aggregate and again for the join.
        totals = orders.groupBy("customer_id").agg(F.sum("amount").alias("customer_total"))
        joined = orders.join(totals, on="customer_id", how="inner")
        result = (
            joined.withColumn("amount_share", F.col("amount") / F.col("customer_total"))
            .select("order_id", "customer_id", "amount", "customer_total", "amount_share")
        )
        '''),
    solution=code(W_IMPORT + '''
        orders = spark.table("orders")
        w = Window.partitionBy("customer_id")
        result = (
            orders.withColumn("customer_total", F.sum("amount").over(w))
            .withColumn("amount_share", F.col("amount") / F.col("customer_total"))
        )
        '''),
    fixtures={
        "example": ("visible", {"orders": [
            {"order_id": 1, "customer_id": 10, "amount": 20.0},
            {"order_id": 2, "customer_id": 10, "amount": 30.0},
            {"order_id": 3, "customer_id": 20, "amount": 50.0}]}),
        "three-orders": ("hidden", {"orders": [
            {"order_id": 4, "customer_id": 30, "amount": 10.0},
            {"order_id": 5, "customer_id": 30, "amount": 10.0},
            {"order_id": 6, "customer_id": 30, "amount": 20.0}]}),
        "single-order": ("edge", {"orders": [
            {"order_id": 7, "customer_id": 40, "amount": 5.0}]}),
    },
    exact_schema=["order_id", "customer_id", "amount", "customer_total", "amount_share"],
    spark_plan={
        "profile": "generic_8x8", "aqe": True,
        "scale": {"orders": {"rows": 300_000_000, "bytes": 24 * GiB, "partitions": 192}},
        "checks": [
            {"id": "plan-single-shuffle", "description": "The plan uses at most one shuffle exchange.",
             "rule": "max_exchanges", "value": 1},
        ],
    },
    hints=["F.sum(\"amount\").over(Window.partitionBy(\"customer_id\")) puts the customer total on every row.",
           "Leave orderBy out of this window: with orderBy the default frame stops at the current row."],
    explanation=("A window aggregate keeps every input row and needs one hash exchange by customer_id. The self-join "
                 "version exchanges the orders once for the aggregate and once more for the join (the aggregated side "
                 "is already partitioned by customer_id, so it is reused)."),
    follow_ups=["When is the groupBy + broadcast join version a reasonable alternative?"],
    mutants=[
        code(F_IMPORT + '''
            orders = spark.table("orders")
            totals = orders.groupBy("customer_id").agg(F.sum("amount").alias("customer_total"))
            joined = orders.join(totals, on="customer_id", how="inner")
            result = (
                joined.withColumn("amount_share", F.col("amount") / F.col("customer_total"))
                .select("order_id", "customer_id", "amount", "customer_total", "amount_share")
            )
            '''),
        code(W_IMPORT + '''
            orders = spark.table("orders")
            w = Window.partitionBy("customer_id").orderBy("order_id")
            result = (
                orders.withColumn("customer_total", F.sum("amount").over(w))
                .withColumn("amount_share", F.col("amount") / F.col("customer_total"))
            )
            '''),
    ],
)


# Polars variants ---------------------------------------------------------------
# Polars is the single-machine alternative to PySpark: the same lesson, on the same fixtures, graded against
# the rows the SparkLab reference computes. Only lessons whose starter returns wrong rows get one; the plan
# lessons (partitions, broadcast, shuffles) have no Polars equivalent. Each variant joins its Spark exercise's
# Practice card through `semantic.id`. `pl_code` adds the typed frames built from the fixture tables.
POLARS_TYPES = {"INTEGER": "pl.Int64", "VARCHAR": "pl.String", "DOUBLE": "pl.Float64",
                "DATE": "pl.String", "TIMESTAMP": "pl.String"}
POLARS_PARSE = {"DATE": "str.to_date()", "TIMESTAMP": 'str.to_datetime("%Y-%m-%d %H:%M:%S")'}


def polars_frames(tables: dict) -> str:
    """Typed Polars frames from the fixture tables (lists of row dicts), empty tables included."""
    lines = []
    for name, columns in tables.items():
        schema = ", ".join(f'"{column}": {POLARS_TYPES[kind]}' for column, kind in columns.items())
        parsed = [f'pl.col("{column}").{POLARS_PARSE[kind]}' for column, kind in columns.items() if kind in POLARS_PARSE]
        frame = f"pl.DataFrame({name}, schema={{{schema}}}, orient=\"row\")"
        lines.append(f"{name} = {frame}" + (f".with_columns({', '.join(parsed)})" if parsed else ""))
    return "\n".join(lines)


POLARS: dict[str, dict] = {
    "spark-left-join-filter-placement": dict(
        pitfall=("A filter on an orders column after a left join removes the customers the join could not match: "
                 "their status is null, and Polars' filter keeps only rows where the predicate is true. Filter the "
                 "right side before joining."),
        starter='''
            # Bug: customers without a COMPLETED order disappear.
            joined = customers.join(orders, on="customer_id", how="left")
            result = joined.filter(pl.col("status") == "COMPLETED").select("customer_id", "customer_name", "order_id", "amount")
            display(result)
            ''',
        solution='''
            completed = orders.filter(pl.col("status") == "COMPLETED").select("order_id", "customer_id", "amount")
            result = customers.join(completed, on="customer_id", how="left").select("customer_id", "customer_name", "order_id", "amount")
            display(result)
            ''',
        hints=["What does filter do with a row whose status is null?",
               "Filter orders to COMPLETED first, then left-join customers to that smaller frame."],
        mutants=['''
            joined = customers.join(orders, on="customer_id", how="left")
            kept = joined.filter((pl.col("status") == "COMPLETED") | pl.col("status").is_null())
            display(kept.select("customer_id", "customer_name", "order_id", "amount"))
            '''],
    ),
    "spark-semi-join-existence": dict(
        pitfall=("An inner join returns one row per matching order, so a customer with three orders appears three "
                 "times. how=\"semi\" only tests existence and never duplicates the left frame (PySpark's left_semi)."),
        starter='''
            orders_2026 = orders.filter(pl.col("order_date").is_between(date(2026, 1, 1), date(2026, 12, 31)))
            # Bug: a customer with several 2026 orders is returned several times.
            result = customers.join(orders_2026, on="customer_id", how="inner").select("customer_id", "customer_name", "country")
            display(result)
            ''',
        solution='''
            orders_2026 = orders.filter(pl.col("order_date").is_between(date(2026, 1, 1), date(2026, 12, 31)))
            display(customers.join(orders_2026, on="customer_id", how="semi"))
            ''',
        hints=["Which join type keeps the left rows that have a match, without adding any column?",
               "is_between includes both bounds by default (closed=\"both\")."],
        imports="from datetime import date\n",
        mutants=['''
            display(customers.join(orders, on="customer_id", how="semi"))
            ''', '''
            orders_2026 = orders.filter(pl.col("order_date").is_between(date(2026, 1, 1), date(2026, 12, 31), closed="none"))
            display(customers.join(orders_2026, on="customer_id", how="semi"))
            '''],
    ),
    "spark-count-column-vs-star": dict(
        pitfall=("pl.len() counts rows; pl.col(...).count() counts non-null values (PySpark's count(\"*\") and "
                 "count(column)). n_unique() also merges equal values and counts null as one more value."),
        starter='''
            # Bug: clicks equals impressions.
            result = events.group_by("campaign_id").agg(pl.len().alias("impressions"), pl.len().alias("clicks"))
            display(result)
            ''',
        solution='''
            result = events.group_by("campaign_id").agg(
                pl.len().alias("impressions"), pl.col("clicked_at").count().alias("clicks")
            )
            display(result)
            ''',
        hints=["Which expression ignores null values: pl.len() or pl.col(...).count()?",
               "Two clicks at the same timestamp are still two clicks."],
        mutants=['''
            result = events.group_by("campaign_id").agg(
                pl.len().alias("impressions"), pl.col("clicked_at").n_unique().alias("clicks")
            )
            display(result)
            '''],
    ),
    "spark-null-safe-change-detection": dict(
        pitfall=("old != new is null, not true, when either side is null, so filter drops those changes. "
                 "ne_missing (PySpark's ~eqNullSafe, SQL IS DISTINCT FROM) treats null as a comparable value."),
        starter='''
            old = yesterday.rename({"email": "old_email"})
            new = today.rename({"email": "new_email"})
            # Bug: a change from or to null is missed.
            result = old.join(new, on="customer_id", how="inner").filter(pl.col("old_email") != pl.col("new_email"))
            display(result)
            ''',
        solution='''
            old = yesterday.rename({"email": "old_email"})
            new = today.rename({"email": "new_email"})
            result = old.join(new, on="customer_id", how="inner").filter(pl.col("old_email").ne_missing(pl.col("new_email")))
            display(result)
            ''',
        hints=["What is the result of null != 'a@b.io' in Polars?",
               "Polars has null-aware comparisons: eq_missing and ne_missing."],
        mutants=['''
            old = yesterday.rename({"email": "old_email"})
            new = today.rename({"email": "new_email"})
            joined = old.join(new, on="customer_id", how="inner")
            display(joined.filter((pl.col("old_email") != pl.col("new_email")) | pl.col("old_email").is_null()))
            '''],
    ),
    "spark-full-outer-reconcile": dict(
        pitfall=("A left join only sees invoices that exist in billing. Polars' full join keeps both key columns "
                 "(invoice_id and invoice_id_right) unless coalesce=True; PySpark's on=\"invoice_id\" merges them. "
                 "And inside when/then, a bare string is a column name: wrap labels in pl.lit()."),
        starter='''
            # Bug: invoices that exist only in the ledger are missing.
            joined = billing.join(ledger, on="invoice_id", how="left")
            result = joined.with_columns(
                pl.when(pl.col("booked_amount").is_null()).then(pl.lit("missing_in_ledger"))
                .when(pl.col("billed_amount").is_null()).then(pl.lit("missing_in_billing"))
                .when(pl.col("billed_amount") != pl.col("booked_amount")).then(pl.lit("amount_mismatch"))
                .otherwise(pl.lit("match"))
                .alias("status")
            )
            display(result)
            ''',
        solution='''
            joined = billing.join(ledger, on="invoice_id", how="full", coalesce=True)
            result = joined.with_columns(
                pl.when(pl.col("booked_amount").is_null()).then(pl.lit("missing_in_ledger"))
                .when(pl.col("billed_amount").is_null()).then(pl.lit("missing_in_billing"))
                .when(pl.col("billed_amount") != pl.col("booked_amount")).then(pl.lit("amount_mismatch"))
                .otherwise(pl.lit("match"))
                .alias("status")
            )
            display(result)
            ''',
        hints=["Which join type keeps the rows of both frames?",
               "After a Polars full join, print the columns: is there one invoice_id or two?"],
        mutants=['''
            joined = billing.join(ledger, on="invoice_id", how="full")
            result = joined.with_columns(
                pl.when(pl.col("booked_amount").is_null()).then(pl.lit("missing_in_ledger"))
                .when(pl.col("billed_amount").is_null()).then(pl.lit("missing_in_billing"))
                .when(pl.col("billed_amount") != pl.col("booked_amount")).then(pl.lit("amount_mismatch"))
                .otherwise(pl.lit("match"))
                .alias("status")
            )
            display(result.select("invoice_id", "billed_amount", "booked_amount", "status"))
            '''],
    ),
    "spark-join-fanout-before-sum": dict(
        pitfall=("Joining orders to a one-to-many frame repeats each order once per promo code, so summing amount "
                 "after the join counts an order several times. Reduce the many side to one row per order first."),
        starter='''
            # Bug: an order with two promo codes is counted twice in revenue.
            joined = orders.join(order_promos, on="order_id", how="left")
            result = joined.group_by("customer_id").agg(
                pl.col("amount").sum().alias("revenue"), pl.col("promo_code").count().alias("promo_uses")
            )
            display(result)
            ''',
        solution='''
            promo_counts = order_promos.group_by("order_id").agg(pl.len().alias("promo_count"))
            result = (
                orders.join(promo_counts, on="order_id", how="left")
                .group_by("customer_id")
                .agg(pl.col("amount").sum().alias("revenue"), pl.col("promo_count").fill_null(0).sum().alias("promo_uses"))
            )
            display(result)
            ''',
        hints=["How many rows does an order with two promo codes have after the join?",
               "Count promo codes per order first, then join one row per order."],
        mutants=['''
            joined = orders.join(order_promos, on="order_id", how="left").unique(subset=["order_id"])
            result = joined.group_by("customer_id").agg(
                pl.col("amount").sum().alias("revenue"), pl.col("promo_code").count().alias("promo_uses")
            )
            display(result)
            '''],
    ),
    "spark-running-total-ties": dict(
        pitfall=("An end-of-day balance (PySpark's default RANGE frame) gives every transaction of a day the same "
                 "total. A Polars window follows the frame's row order, not an ORDER BY: sort by (txn_date, txn_id) "
                 "before cum_sum, or pass order_by to over()."),
        starter='''
            # Bug: transactions on the same date show the same balance.
            daily = (
                transactions.group_by("account_id", "txn_date").agg(pl.col("amount").sum().alias("day_total"))
                .sort("account_id", "txn_date")
                .with_columns(pl.col("day_total").cum_sum().over("account_id").alias("running_balance"))
                .drop("day_total")
            )
            result = transactions.join(daily, on=["account_id", "txn_date"], how="left")
            display(result)
            ''',
        solution='''
            result = transactions.sort("account_id", "txn_date", "txn_id").with_columns(
                pl.col("amount").cum_sum().over("account_id").alias("running_balance")
            )
            display(result)
            ''',
        hints=["Should two transactions on the same date share a balance?",
               "cum_sum follows the rows' current order: which order does the prompt ask for?"],
        # Rows arrive out of order: a cumulative sum must sort first.
        extra_fixtures={
            "unsorted-input": ("hidden", {"transactions": [
                {"account_id": "F", "txn_id": 32, "txn_date": "2026-04-03", "amount": 7.0},
                {"account_id": "F", "txn_id": 30, "txn_date": "2026-04-01", "amount": 100.0},
                {"account_id": "F", "txn_id": 31, "txn_date": "2026-04-01", "amount": -40.0},
            ]}),
        },
        mutants=['''
            result = transactions.with_columns(pl.col("amount").cum_sum().over("account_id").alias("running_balance"))
            display(result)
            '''],
    ),
}


def pl_code(spec: dict, body: str, imports: str = "") -> str:
    return (f"{imports}import polars as pl\n\n{polars_frames(spec['tables'])}\n"
            + textwrap.dedent(body).strip("\n") + "\n")


def polars_variant(spec: dict) -> dict:
    """The Polars variant of a Spark exercise: same prompt and fixtures, Polars pitfall, starter and solution."""
    polars = POLARS[spec["id"]]
    imports = polars.get("imports", "")
    fixtures = dict(spec["fixtures"])
    fixtures.update(polars.get("extra_fixtures", {}))
    return {
        **spec,
        "id": spec["id"] + "-polars",
        "language": "polars",
        "spark_id": spec["id"],
        "pitfall": polars["pitfall"],
        "starter": pl_code(spec, polars["starter"], imports),
        "solution": pl_code(spec, polars["solution"], imports),
        "hints": polars["hints"],
        "fixtures": fixtures,
        "mutants": [pl_code(spec, mutant, imports) for mutant in polars["mutants"]],
        "spark_plan": None,
    }


# -----------------------------------------------------------------------------
def definition(spec: dict, rank: int) -> dict:
    sample_name = next(iter(spec["fixtures"]))
    sample_tables = spec["fixtures"][sample_name][1]
    table_lines = [f"{name}({', '.join(f'{c} {t}' for c, t in cols.items())})" for name, cols in spec["tables"].items()]
    polars = spec.get("language") == "polars"
    sections = [
        {"title": "Tables", "body": "\n".join(table_lines)},
        *([{"title": "Polars", "body": (
            "Real Polars in the trusted local Python worker (enable trusted Python first). Each table arrives as a "
            "list of row dicts in a variable of the same name; the starter turns them into typed frames. Show the "
            "result with display(...). Same lesson and data as the PySpark variant on this card.")}] if polars else []),
        {"title": "Output", "body": f"Columns in this order: {', '.join(spec['exact_schema'])}. Row order does not matter."},
        {"title": "Common pitfall", "body": spec["pitfall"]},
    ]
    if spec.get("spark_plan"):
        sections.append({"title": "Plan requirement (simulated)", "body": (
            "Besides the result rows, Submit grades the Spark plan SparkLab models for your code at the input sizes "
            "listed below. The model applies Spark's exchange and join-strategy rules; it is not Apache Spark, and "
            "no data of that size is processed.")})
    by_visibility = {"visible": [], "hidden": [], "edge": []}
    for fid, (visibility, _) in spec["fixtures"].items():
        by_visibility[visibility].append(fid)
    item = {
        "schema_version": 1,
        "id": spec["id"],
        "version": "1",
        "title": spec["title"],
        "difficulty": spec["difficulty"],
        "topics": spec["topics"],
        "tags": ["spark-lab", "polars"] if polars else ["spark-lab", "sparklab", "pyspark"],
        "origin": "authored",
        "language": "polars" if polars else "sparklab",
        "runtime": "shared-polars-v1" if polars else "shared-sparklab-v1",
        "prompt": spec["prompt"],
        "sections": sections,
        "starter_source": spec["starter"],
        "fixtures": [{"id": f"{spec['id']}-fixtures", "version": "1"}],
        "visible_checks": [{"id": fid, "description": "Public example: the tables shown in data_context."}
                           for fid in by_visibility["visible"]],
        "hidden_check_refs": by_visibility["hidden"],
        "edge_check_refs": by_visibility["edge"],
        "hints": spec["hints"],
        "solution": {"available": True, "reveal": "explicit"},
        "explanation": spec["explanation"],
        "follow_ups": spec["follow_ups"],
        "canonical_placement": {"domain": "sparklab", "topic": spec["topics"][0]},
        "related_associations": ["sparklab/spark-concepts"],
        "recommendation": {"rank": rank, "reason": "Spark lab progression"},
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
        "runtime_requirements": [] if polars else ["sparklab"],
        "provenance": {
            "source": "Authored for Datapass Workbench: Spark DataFrame pitfalls and plan choices on SparkLab",
            "fixtures": ("Authored for Datapass; expected rows computed from the SparkLab reference solution and "
                         "reviewed" if polars else
                         "Authored for Datapass; expected rows computed from the reference solution and reviewed"),
        },
        "constraints": {
            "fixtures": "At most 200 rows per table; complete results are graded, truncated results never pass.",
            "truth": ("Real Polars, run by the trusted local Python worker (not a sandbox)." if polars else
                      "Result rows run locally on DuckDB through SparkLab's bounded PySpark subset. Plan checks grade "
                      "SparkLab's simulated Spark plan, not Apache Spark."),
        },
        "truth": "real" if polars else "semantic-emulation",
    }
    if polars:
        # Joins the Spark exercise's Practice card: same problem, another language.
        item["semantic"] = {
            "id": spec["spark_id"], "version": "1", "industry": "Spark lab: DataFrame pitfalls",
            "learning_objectives": [spec["title"], "Express the same DataFrame lesson in PySpark and Polars"],
            "variants": {"sparklab": spec["spark_id"], "polars": spec["id"]},
            "supported_operations": POLARS_OPERATIONS,
            "optimization": spec["explanation"],
            "reflection": "Which part of this lesson is Spark-specific, and which holds in any DataFrame engine?",
        }
    if spec.get("spark_plan"):
        item["spark_plan"] = spec["spark_plan"]
    return item


POLARS_OPERATIONS = ["filter", "select", "join", "group_by", "agg", "with_columns", "sort", "over"]


def expected_rows(engine, spec: dict, tables: dict) -> list[dict]:
    from datapass_runtime.exercise_contracts import ExerciseDefinition
    from datapass_runtime.exercise_packs import Fixture
    from datapass_runtime.exercises import _fixture_ctes
    definition_model = ExerciseDefinition.model_validate(definition(spec, 1))
    fixture = Fixture(id="x", visibility="visible", input_rows=[], expected=[], tables=tables)
    request = {
        "cell_id": "gen", "notebook_id": "gen-" + spec["id"], "language": "sparklab", "code": spec["solution"],
        "_exercise_fixture_ctes": _fixture_ctes(definition_model, fixture),
        "_exercise_tables": {c.name: list(c.columns) for c in definition_model.data_context},
        "_exercise_table_counts": {name: len(rows) for name, rows in tables.items()},
        "profile": "generic_8x8", "aqe": True,
    }
    run = engine.execute(request)
    engine.parsers.pop(request["notebook_id"], None)
    if run["status"] != "success":
        raise SystemExit(f"{spec['id']}: reference failed: {run.get('error')}")
    if run["result"]["columns"] != spec["exact_schema"]:
        raise SystemExit(f"{spec['id']}: reference columns {run['result']['columns']} != {spec['exact_schema']}")
    return run["result"]["rows"]


def main() -> None:
    from datapass_runtime.execution import Engine
    ids = [spec["id"] for spec in EXERCISES]
    assert len(ids) == len(set(ids))
    definitions, grading = [], {}
    with tempfile.TemporaryDirectory() as temp:
        engine = Engine(Path(temp), mode="duckdb")
        for rank, spec in enumerate(EXERCISES, start=1):
            for variant in [spec] + ([polars_variant(spec)] if spec["id"] in POLARS else []):
                definitions.append(definition(variant, rank))
                fixtures = []
                for fid, (visibility, tables) in variant["fixtures"].items():
                    # The SparkLab reference computes the expected rows of both languages.
                    fixtures.append({"id": fid, "visibility": visibility, "input_rows": [], "tables": tables,
                                     "expected": expected_rows(engine, spec, tables)})
                grading[variant["id"]] = {"solution": variant["solution"], "fixtures": fixtures}
        engine.catalog.db.close()
    manifest = {
        "schema_version": 1, "id": "spark-lab-v1", "version": "1",
        "title": "Spark lab: DataFrame pitfalls and plan choices (SparkLab, simulated plans)",
        "enabled": True,
        "provenance": {"source": "Authored for Datapass Workbench"},
    }
    # Validate against the real registry before writing anything.
    from datapass_runtime.exercise_packs import PackRegistry
    PackRegistry().register(manifest, definitions, grading)
    PACK.mkdir(parents=True, exist_ok=True)
    for name, data in (("manifest.json", manifest), ("exercises.json", definitions), ("grading.server.json", grading)):
        (PACK / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    mutants = {spec["id"]: spec["mutants"] for spec in EXERCISES}
    mutants.update({spec["id"] + "-polars": polars_variant(spec)["mutants"] for spec in EXERCISES if spec["id"] in POLARS})
    write_mutants(PACK, mutants)
    for ident, graded in grading.items():
        print(f"== {ident}")
        for fixture in graded["fixtures"]:
            print(f"   {fixture['id']:28s}", json.dumps(fixture["expected"]))


if __name__ == "__main__":
    main()
