"""Generate content/exercise-packs/dbt-v1 (BI Lab: dbt) from authored specs.

Expected rows are computed by running each reference through the dbt emulation grader
(`datapass_runtime.dbt_project_grading.run_fixture`); review them by hand. The generator checks that starters and
mutants run and fail. With DATAPASS_DBT_PYTHON pointing at a Python that has dbt-core and dbt-duckdb, it also runs
every reference fixture through real dbt Core and compares the graded rows (columns that depend on the wall
clock are skipped). Run from the repository root with PYTHONPATH=runtime.
"""
from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

from pack_quality import write_mutants

ROOT = Path.cwd()
PACK = ROOT / "content" / "exercise-packs" / "dbt-v1"
EXERCISES: list[dict] = []
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
STAMP = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


def code(text: str) -> str:
    return textwrap.dedent(text).strip("\n") + "\n"


def exercise(**spec):
    EXERCISES.append(spec)


def T(name, rows, types=None, columns=None):
    entry = {"name": name, "rows": rows}
    cols = columns or (list(rows[0]) if rows else [])
    typed = dict(types or {})
    for column in cols:
        values = [r[column] for r in rows if r[column] is not None]
        if column not in typed and values and all(isinstance(v, str) and DATE.match(v) for v in values):
            typed[column] = "DATE"
        elif column not in typed and values and all(isinstance(v, str) and STAMP.match(v) for v in values):
            typed[column] = "TIMESTAMP"
    if columns:
        entry["columns"] = columns
    if typed:
        entry["types"] = typed
    return entry


def rows(columns, *values):
    names = columns.split()
    return [dict(zip(names, v)) for v in values]


SCHEMA_MACRO = code("""
    {% macro generate_schema_name(custom_schema_name, node) -%}
        {%- if custom_schema_name is none -%}{{ target.schema }}{%- else -%}{{ custom_schema_name | trim }}{%- endif -%}
    {%- endmacro %}
""")
PROJECT = code("""
    name: shop
    version: '1.0.0'
    config-version: 2
    profile: datapass

    models:
      shop:
        staging:
          +materialized: view
          +schema: silver
        marts:
          +materialized: table
          +schema: gold
""")
SOURCES = code("""
    version: 2
    sources:
      - name: shop
        schema: source
        tables:
          - name: orders
          - name: order_lines
          - name: events
      - name: crm
        schema: source
        tables:
          - name: customers
""")


def files(extra=None, macro=True, project=PROJECT):
    base = {"dbt_project.yml": project, "models/staging/_sources.yml": SOURCES}
    if macro:
        base["macros/generate_schema_name.sql"] = SCHEMA_MACRO
    base.update(extra or {})
    return base


def run(command="build", tables=(), select=(), now="2026-03-01 06:00:00", full_refresh=False, setup=None, vars=None):
    step = {"command": command, "now": now}
    if tables:
        step["tables"] = list(tables)
    if select:
        step["select"] = list(select)
    if full_refresh:
        step["full_refresh"] = True
    if setup:
        step["setup"] = setup
    if vars:
        step["vars"] = vars
    return step


def S(outcome, file, project_files, runs, **kw):
    return {"outcome": outcome, "file": file, "files": project_files, "runs": runs, **kw}


ORDERS = rows("order_id customer_id status amount_cents ordered_at is_test",
              ("O1", "C1", "PLACED", 1250, "2026-02-01 09:00:00", False),
              ("O2", "C2", "shipped", 4000, "2026-02-02 10:30:00", False),
              ("O3", "C1", "Returned", 999, "2026-02-03 11:00:00", False),
              ("T9", "C9", "placed", 1, "2026-02-03 12:00:00", True))


def orders_table(extra=()):
    return T("source.orders", ORDERS + list(extra), types={"amount_cents": "INTEGER"})


STG_ORDERS = code("""
    select
        order_id,
        customer_id,
        lower(status) as status,
        amount_cents / 100.0 as amount,
        cast(ordered_at as date) as order_date
    from {{ source('shop', 'orders') }}
    where not is_test
""")

# =================================================================================================
# 1. ref and source build the DAG
# =================================================================================================
FCT_ORDERS_REF = code("""
    select order_date, count(*) as orders, sum(amount) as revenue
    from {{ ref('stg_orders') }}
    group by order_date
""")
exercise(
    id="dbt-ref-builds-the-dag", title="ref() and source() build the DAG", difficulty="easy", language="dbt-sql",
    topics=["ref", "dag", "selection"],
    prompt=("models/marts/fct_daily_orders.sql (gold) sums orders and revenue per order_date from the staging model "
            "stg_orders (silver). It reads silver.stg_orders by its table name, so dbt does not know it depends on "
            "stg_orders. Rewrite it so that `dbt build --select +fct_daily_orders` (the model and everything upstream) "
            "works on a fresh warehouse. Output columns: order_date, orders, revenue."),
    sections=[("ref and source", "{{ ref('model') }} and {{ source('src', 'table') }} are how dbt learns the "
               "dependencies: they build the DAG that orders the run, powers selection (+model, model+), lineage and "
               "docs, and resolve to the right schema in each environment. A hard-coded table name works only if "
               "someone built that table before, in the right order."),
              ("Graded", "dbt build --select +fct_daily_orders on a warehouse where nothing is built yet: the nodes "
               "that run and their status, then the rows of gold.fct_daily_orders.")],
    file="models/marts/fct_daily_orders.sql",
    starter=code("""
        select order_date, count(*) as orders, sum(amount) as revenue
        from silver.stg_orders
        group by order_date
    """),
    solution=FCT_ORDERS_REF,
    fixtures=[
        ("select-upstream", "visible", S("nodes", "models/marts/fct_daily_orders.sql",
                                          files({"models/staging/stg_orders.sql": STG_ORDERS}),
                                          [run(select=["+fct_daily_orders"])], tables=[orders_table()])),
        ("daily-rows", "hidden", S("table", "models/marts/fct_daily_orders.sql",
                                   files({"models/staging/stg_orders.sql": STG_ORDERS}),
                                   [run(select=["+fct_daily_orders"])], tables=[orders_table()], table="gold.fct_daily_orders")),
        ("select-downstream", "edge", S("nodes", "models/marts/fct_daily_orders.sql",
                                        files({"models/staging/stg_orders.sql": STG_ORDERS}),
                                        [run(select=["stg_orders+"])], tables=[orders_table()])),
    ],
    mutants=[FCT_ORDERS_REF.replace("{{ ref('stg_orders') }}", "{{ source('shop', 'orders') }}")],
    hints=["{{ ref('stg_orders') }} resolves to silver.stg_orders and records the dependency.",
           "+model selects the model and everything it depends on; model+ the model and everything that depends on it."],
    explanation=("With ref(), dbt knows fct_daily_orders depends on stg_orders: +fct_daily_orders selects both and "
                 "builds them in order, and stg_orders+ also rebuilds the mart. With a hard-coded name the DAG has no "
                 "edge: the selection runs the mart alone, before its input exists, and it fails. Reading the source "
                 "directly would skip the staging logic (test orders, cents to amounts)."),
    follow_ups=["What does `dbt build --select stg_orders+ --exclude fct_daily_orders` run?"],
)

# =================================================================================================
# 2. A staging model
# =================================================================================================
exercise(
    id="dbt-staging-model", title="A staging model: rename, type, clean", difficulty="easy", language="dbt-sql",
    topics=["staging", "source", "modeling-layers"],
    prompt=("Write models/staging/stg_orders.sql (materialized as a view in silver by dbt_project.yml) over "
            "{{ source('shop', 'orders') }} (order_id, customer_id, status, amount_cents, ordered_at, is_test). One "
            "row per real order (test orders out), with: order_id, customer_id, status in lower case, amount in "
            "currency units (amount_cents / 100.0) and order_date (the date part of ordered_at)."),
    sections=[("Staging", "The staging layer has one model per source table: rename, cast, clean and filter, nothing "
               "joined or aggregated. Every later model reads the staging model, never the raw source, so a source "
               "change is fixed in one place."),
              ("Graded", "The rows of silver.stg_orders, with orders in mixed-case statuses and a test order.")],
    file="models/staging/stg_orders.sql",
    starter=code("""
        select order_id, customer_id, status, amount_cents, ordered_at
        from {{ source('shop', 'orders') }}
    """),
    solution=STG_ORDERS,
    fixtures=[
        ("staged", "visible", S("table", "models/staging/stg_orders.sql", files(), [run(select=["stg_orders"])],
                                tables=[orders_table()], table="silver.stg_orders")),
        ("more-orders", "hidden", S("table", "models/staging/stg_orders.sql", files(), [run(select=["stg_orders"])],
                                    tables=[orders_table(rows("order_id customer_id status amount_cents ordered_at is_test",
                                                              ("O4", "C3", "Shipped", 5, "2026-02-04 23:59:00", False)))],
                                    table="silver.stg_orders")),
    ],
    mutants=[STG_ORDERS.replace("where not is_test\n", ""), STG_ORDERS.replace("amount_cents / 100.0", "amount_cents / 100")
             .replace("lower(status)", "status")],
    hints=["cast(ordered_at as date) keeps the date part.", "where not is_test removes the test orders."],
    explanation=("A staging model is a thin, typed, cleaned view of one source table. Lower-casing statuses and "
                 "converting cents here means every downstream model agrees on the values; filtering test orders here "
                 "means no report ever sees them."),
    follow_ups=["Why is staging usually a view, and when would you make it a table?"],
)

# =================================================================================================
# 3. Generic tests in YAML
# =================================================================================================
DIM_CUSTOMERS = code("""
    select customer_id, name from {{ source('crm', 'customers') }}
""")
FCT_ORDERS = code("""
    select order_id, customer_id, status, amount from {{ ref('stg_orders') }}
""")
CUSTOMERS = rows("customer_id name", ("C1", "Alice"), ("C2", "Bruno"), ("C3", "Chloe"))
TESTS_YML = code("""
    version: 2
    models:
      - name: fct_orders
        columns:
          - name: order_id
            data_tests: [unique, not_null]
          - name: customer_id
            data_tests:
              - not_null
              - relationships:
                  arguments:
                    to: ref('dim_customers')
                    field: customer_id
          - name: status
            data_tests:
              - accepted_values:
                  arguments:
                    values: ['placed', 'shipped', 'returned']
""")


def tested_project():
    return files({"models/staging/stg_orders.sql": STG_ORDERS, "models/marts/dim_customers.sql": DIM_CUSTOMERS,
                  "models/marts/fct_orders.sql": FCT_ORDERS})


def orders_with(*extra):
    return [orders_table(rows("order_id customer_id status amount_cents ordered_at is_test", *extra)),
            T("source.customers", CUSTOMERS)]


exercise(
    id="dbt-generic-tests", title="Generic tests: unique, not_null, relationships, accepted_values", difficulty="easy",
    language="dbt-yml", topics=["tests", "data-quality", "relationships"],
    prompt=("Write models/marts/_marts.yml with the data tests of fct_orders (order_id, customer_id, status, amount): "
            "order_id is unique and never null; customer_id is never null and exists in dim_customers.customer_id; "
            "status is one of 'placed', 'shipped', 'returned' (in that order). Use dbt's built-in generic tests."),
    sections=[("Data tests", "A generic test is a query that returns the failing rows: unique, not_null, "
               "accepted_values and relationships (referential integrity, the foreign key a warehouse does not "
               "enforce). dbt build runs them right after the model, and a failing test skips what depends on it."),
              ("Graded", "dbt build on clean data (every test passes), then on data with a duplicate order, an order "
               "of an unknown customer and an unexpected status: which tests pass and which fail.")],
    file="models/marts/_marts.yml",
    starter=code("""
        version: 2
        models:
          - name: fct_orders
            columns:
              - name: order_id
                data_tests: [not_null]
    """),
    solution=TESTS_YML,
    fixtures=[
        ("clean", "visible", S("nodes", "models/marts/_marts.yml", tested_project(), [run()], tables=orders_with())),
        ("unknown-customer", "hidden", S("nodes", "models/marts/_marts.yml", tested_project(), [run()],
                                         tables=orders_with(("O5", "C7", "placed", 100, "2026-02-05 10:00:00", False)))),
        ("duplicate-and-status", "edge", S("nodes", "models/marts/_marts.yml", tested_project(), [run()],
                                           tables=orders_with(("O1", "C2", "lost", 100, "2026-02-05 10:00:00", False)))),
    ],
    mutants=[TESTS_YML.replace("data_tests: [unique, not_null]", "data_tests: [not_null]"),
             TESTS_YML.replace("to: ref('dim_customers')", "to: ref('fct_orders')"),
             TESTS_YML.replace("values: ['placed', 'shipped', 'returned']", "values: ['placed', 'shipped', 'returned', 'lost']")],
    hints=["Each test sits under the column it tests, in data_tests.",
           "relationships takes to: ref('dim_customers') and field: customer_id."],
    explanation=("unique + not_null declare the grain; relationships is the referential integrity a warehouse does "
                 "not enforce; accepted_values catches new statuses before a report silently drops them. dbt names "
                 "each test after its model, column and arguments, and runs it right after the model."),
    follow_ups=["Which of these tests would you put on the source instead of the mart, and why?"],
)

# =================================================================================================
# 4. A singular test
# =================================================================================================
LINES = rows("order_id line_number amount_cents", ("O1", 1, 1000), ("O1", 2, 250), ("O2", 1, 4000), ("O3", 1, 999))
SINGULAR = code("""
    -- Orders whose total differs from the sum of their lines.
    select o.order_id, o.amount_cents, coalesce(sum(l.amount_cents), 0) as lines_cents
    from {{ source('shop', 'orders') }} as o
    left join {{ source('shop', 'order_lines') }} as l on l.order_id = o.order_id
    where not o.is_test
    group by o.order_id, o.amount_cents
    having o.amount_cents <> coalesce(sum(l.amount_cents), 0)
""")


def singular_tables(lines=LINES, extra_orders=()):
    return [orders_table(extra_orders), T("source.order_lines", lines, types={"amount_cents": "INTEGER"})]


exercise(
    id="dbt-singular-test", title="A singular test: totals must match their lines", difficulty="medium",
    language="dbt-sql", topics=["tests", "data-quality"],
    prompt=("Write the singular test tests/assert_order_total_matches_lines.sql: it returns every real order (not a "
            "test order) whose amount_cents differs from the sum of its lines in source order_lines (order_id, "
            "line_number, amount_cents). An order without lines counts as 0. Return order_id, amount_cents and "
            "lines_cents."),
    sections=[("Singular tests", "A singular test is a SQL file in tests/: any row it returns is a failure. It covers "
               "the rules generic tests cannot express, such as a header that must match its detail lines."),
              ("Graded", "dbt test: the test's status and number of failures on consistent data, on an order whose "
               "lines do not add up, and on an order without lines.")],
    file="tests/assert_order_total_matches_lines.sql",
    starter=code("""
        select o.order_id, o.amount_cents, sum(l.amount_cents) as lines_cents
        from {{ source('shop', 'orders') }} as o
        join {{ source('shop', 'order_lines') }} as l on l.order_id = o.order_id
        group by o.order_id, o.amount_cents
        having o.amount_cents = sum(l.amount_cents)
    """),
    solution=SINGULAR,
    fixtures=[
        ("consistent", "visible", S("nodes", "tests/assert_order_total_matches_lines.sql", files(), [run("test")],
                                    tables=singular_tables(), columns=["name", "status", "failures"])),
        ("wrong-total", "hidden", S("nodes", "tests/assert_order_total_matches_lines.sql", files(), [run("test")],
                                    tables=singular_tables(LINES[:1] + LINES[2:]), columns=["name", "status", "failures"])),
        ("order-without-lines", "edge", S("nodes", "tests/assert_order_total_matches_lines.sql", files(), [run("test")],
                                          tables=singular_tables(extra_orders=rows("order_id customer_id status amount_cents ordered_at is_test",
                                                                                   ("O4", "C2", "placed", 300, "2026-02-04 10:00:00", False))),
                                          columns=["name", "status", "failures"])),
    ],
    mutants=[SINGULAR.replace("left join", "join"), SINGULAR.replace("where not o.is_test\n", "")],
    hints=["A LEFT JOIN keeps the orders without lines; coalesce their sum to 0.",
           "The test fails when it returns rows: select the orders that break the rule."],
    explanation=("The test returns the orders that break the rule, so an empty result is a pass. The LEFT JOIN is "
                 "what catches an order with no lines at all (an inner join would hide exactly the worst case), and "
                 "test orders stay out like everywhere else."),
    follow_ups=["Turn this into a generic test (a {% test %} block) that takes the two relations as arguments."],
)

# =================================================================================================
# 5. Severity and where: what a failing test stops
# =================================================================================================
SEVERITY_YML = code("""
    version: 2
    models:
      - name: stg_orders
        columns:
          - name: order_id
            data_tests: [not_null]
          - name: status
            data_tests:
              - accepted_values:
                  arguments:
                    values: ['placed', 'shipped', 'returned']
                  config:
                    severity: warn
          - name: amount
            data_tests:
              - not_null:
                  config:
                    where: "order_date >= '2026-01-01'"
""")
REVENUE = code("""
    select status, sum(amount) as revenue from {{ ref('stg_orders') }} group by status
""")


def severity_project():
    return files({"models/staging/stg_orders.sql": STG_ORDERS, "models/marts/fct_revenue.sql": REVENUE})


LEGACY = ("L1", "C1", "placed", None, "2025-12-30 10:00:00", False)
NEW_STATUS = ("O7", "C2", "lost", 500, "2026-02-06 10:00:00", False)
MISSING_AMOUNT = ("O8", "C2", "placed", None, "2026-02-07 10:00:00", False)


def severity_tables(*extra):
    return [orders_table(rows("order_id customer_id status amount_cents ordered_at is_test", *extra))]


exercise(
    id="dbt-test-severity-where", title="Test severity and where: warn, do not block", difficulty="medium",
    language="dbt-yml", topics=["tests", "build", "severity"],
    prompt=("Write models/staging/_staging.yml with three tests on stg_orders, knowing that dbt build skips "
            "everything downstream of a failing test: order_id is never null (an error); status is one of 'placed', "
            "'shipped', 'returned' (in that order), but a new status must only warn and never stop fct_revenue; "
            "amount is never null, except that orders before 2026-01-01 (a legacy import) are not checked: use the "
            "test's where config with order_date >= '2026-01-01'."),
    sections=[("dbt build and tests", "dbt build runs each model's tests right after it; a test with severity error "
               "that fails skips every model downstream, so bad data never reaches a report. severity: warn reports "
               "the problem without stopping the run, and where limits a test to the rows it is meant for."),
              ("Graded", "dbt build with a legacy order without amount, with a new status, and with a recent order "
               "without amount: the status of every node, including whether fct_revenue ran.")],
    file="models/staging/_staging.yml",
    starter=code("""
        version: 2
        models:
          - name: stg_orders
            columns:
              - name: order_id
                data_tests: [not_null]
              - name: status
                data_tests:
                  - accepted_values:
                      arguments:
                        values: ['placed', 'shipped', 'returned']
              - name: amount
                data_tests: [not_null]
    """),
    solution=SEVERITY_YML,
    fixtures=[
        ("legacy-order", "visible", S("nodes", "models/staging/_staging.yml", severity_project(), [run()],
                                      tables=severity_tables(LEGACY))),
        ("new-status", "hidden", S("nodes", "models/staging/_staging.yml", severity_project(), [run()],
                                   tables=severity_tables(LEGACY, NEW_STATUS))),
        ("recent-missing-amount", "edge", S("nodes", "models/staging/_staging.yml", severity_project(), [run()],
                                            tables=severity_tables(NEW_STATUS, MISSING_AMOUNT))),
    ],
    mutants=[SEVERITY_YML.replace("              config:\n                severity: warn\n", ""),
             SEVERITY_YML.replace("""          - not_null:
              config:
                where: "order_date >= '2026-01-01'"
""", "          - not_null\n")],
    hints=["Test configs go under config: in the test's entry (dbt 1.10 puts arguments under arguments:).",
           "severity: warn makes a failing test a warning; where: filters the rows the test checks."],
    explanation=("The accepted_values test warns, so a new status is reported but fct_revenue still builds; the "
                 "amount test ignores the legacy rows through where, so only recent missing amounts fail and skip "
                 "the mart. That is the difference between a known, tolerated issue and one that must stop the "
                 "pipeline."),
    follow_ups=["Look at warn_if and error_if: how would you fail only above 10 bad rows?"],
)

# =================================================================================================
# 6. Incremental: append new rows only
# =================================================================================================
EVENTS = "event_id customer_id event_type occurred_at"
EVENTS_DAY1 = rows(EVENTS, (1, "C1", "view", "2026-03-01 08:00:00"), (2, "C2", "view", "2026-03-01 09:00:00"),
                   (3, "C1", "buy", "2026-03-01 10:00:00"))
EVENTS_DAY2 = EVENTS_DAY1 + rows(EVENTS, (4, "C3", "view", "2026-03-02 08:00:00"), (5, "C3", "buy", "2026-03-02 09:00:00"))
INCREMENTAL = code("""
    {{ config(materialized='incremental') }}
    select event_id, customer_id, event_type, occurred_at
    from {{ source('shop', 'events') }}
    {% if is_incremental() %}
    where event_id > (select max(event_id) from {{ this }})
    {% endif %}
""")


def events(*days):
    return [run(tables=[T("source.events", day, types={"event_id": "INTEGER"})], select=["fct_events"], now=f"2026-03-0{i + 1} 06:00:00")
            for i, day in enumerate(days)]


exercise(
    id="dbt-incremental-append", title="An incremental model: process only the new events", difficulty="medium",
    language="dbt-sql", topics=["incremental", "materializations", "is_incremental"],
    prompt=("source events (event_id, customer_id, event_type, occurred_at) only grows, and event_id increases. Write "
            "models/marts/fct_events.sql as an incremental model (gold) that copies the four columns: the first run "
            "loads every event, and each later run inserts only the events with an event_id above the highest one "
            "already loaded. It runs every day on the whole source table."),
    sections=[("Incremental models", "materialized='incremental' builds the table the first time, then only adds (or "
               "replaces) rows: {% if is_incremental() %} holds the filter that selects the new rows, and {{ this }} "
               "is the table itself. Without the filter every run re-inserts everything; with a filter that is too "
               "wide, the last row comes back each day."),
              ("Graded", "gold.fct_events after one day, two days, and the same day run twice.")],
    file="models/marts/fct_events.sql",
    starter=code("""
        {{ config(materialized='incremental') }}
        select event_id, customer_id, event_type, occurred_at
        from {{ source('shop', 'events') }}
    """),
    solution=INCREMENTAL,
    fixtures=[
        ("two-days", "visible", S("table", "models/marts/fct_events.sql", files(), events(EVENTS_DAY1, EVENTS_DAY2),
                                  table="gold.fct_events")),
        ("same-day-twice", "hidden", S("table", "models/marts/fct_events.sql", files(), events(EVENTS_DAY1, EVENTS_DAY1),
                                       table="gold.fct_events")),
        ("three-days", "edge", S("table", "models/marts/fct_events.sql", files(), events(EVENTS_DAY1, EVENTS_DAY2, EVENTS_DAY2),
                                 table="gold.fct_events")),
    ],
    mutants=[INCREMENTAL.replace("where event_id > (select", "where event_id >= (select")],
    hints=["{% if is_incremental() %} ... {% endif %} is false on the first run and true afterwards.",
           "Compare with the highest event_id of {{ this }}, strictly."],
    explanation=("The filter reads the table being built ({{ this }}) to find where the last run stopped; strictly "
                 "greater means the last loaded event is not inserted again. A table materialization would be correct "
                 "too but reprocesses the whole history every day, which is what incremental models avoid."),
    follow_ups=["What happens if an old event is corrected in the source? See the unique_key exercise."],
)

# =================================================================================================
# 7. Incremental with unique_key
# =================================================================================================
STATUS = "order_id status updated_at"
STATUS_DAY1 = rows(STATUS, ("O1", "placed", "2026-03-01 08:00:00"), ("O2", "placed", "2026-03-01 09:00:00"))
STATUS_DAY2 = rows(STATUS, ("O1", "shipped", "2026-03-02 08:00:00"), ("O2", "placed", "2026-03-01 09:00:00"),
                   ("O3", "placed", "2026-03-02 10:00:00"))
STATUS_DAY3 = rows(STATUS, ("O1", "delivered", "2026-03-03 08:00:00"), ("O2", "shipped", "2026-03-03 09:00:00"),
                   ("O3", "placed", "2026-03-02 10:00:00"))
UPSERT = code("""
    {{ config(materialized='incremental', unique_key='order_id') }}
    select order_id, status, updated_at
    from {{ source('shop', 'orders') }}
    {% if is_incremental() %}
    where updated_at > (select max(updated_at) from {{ this }})
    {% endif %}
""")


def statuses(*days):
    return [run(tables=[T("source.orders", day)], select=["fct_order_status"], now=f"2026-03-0{i + 1} 23:00:00")
            for i, day in enumerate(days)]


exercise(
    id="dbt-incremental-unique-key", title="Incremental with unique_key: updates replace rows", difficulty="medium",
    language="dbt-sql", topics=["incremental", "unique-key", "upsert"],
    prompt=("source orders now holds each order's latest status (order_id, status, updated_at), and statuses change. "
            "Write models/marts/fct_order_status.sql as an incremental model (gold, columns order_id, status, "
            "updated_at) that keeps one row per order with its latest status: later runs only process rows updated "
            "after the latest updated_at already loaded, and replace the existing row of an order instead of adding "
            "one."),
    sections=[("unique_key", "With unique_key, an incremental run replaces the rows whose key comes back: dbt-duckdb's "
               "default strategy is delete+insert (merge is also available). Without it, dbt only appends, and an "
               "updated order gets a second row."),
              ("Graded", "gold.fct_order_status after two days of updates, after three days, and with a day run twice.")],
    file="models/marts/fct_order_status.sql",
    starter=code("""
        {{ config(materialized='incremental') }}
        select order_id, status, updated_at
        from {{ source('shop', 'orders') }}
        {% if is_incremental() %}
        where updated_at > (select max(updated_at) from {{ this }})
        {% endif %}
    """),
    solution=UPSERT,
    fixtures=[
        ("two-days", "visible", S("table", "models/marts/fct_order_status.sql", files(), statuses(STATUS_DAY1, STATUS_DAY2),
                                  table="gold.fct_order_status")),
        ("three-days", "hidden", S("table", "models/marts/fct_order_status.sql", files(),
                                   statuses(STATUS_DAY1, STATUS_DAY2, STATUS_DAY3), table="gold.fct_order_status")),
        ("day-run-twice", "edge", S("table", "models/marts/fct_order_status.sql", files(),
                                    statuses(STATUS_DAY1, STATUS_DAY2, STATUS_DAY2), table="gold.fct_order_status")),
    ],
    mutants=[UPSERT.replace("where updated_at > (select", "where updated_at < (select"),
             UPSERT.replace("unique_key='order_id'", "incremental_strategy='append'")],
    hints=["config(unique_key='order_id') makes the incremental run replace an order's row.",
           "Keep the is_incremental() filter on updated_at so old rows are not reprocessed."],
    explanation=("The filter picks the rows changed since the last run, and unique_key makes dbt delete the old row "
                 "of each of those orders before inserting the new one (delete+insert, dbt-duckdb's default). The "
                 "table keeps one row per order; append would stack every status change."),
    follow_ups=["Rows can arrive late with an older updated_at. How does a lookback window (updated_at > max - 2 days) "
                "help, and why does unique_key make it safe?"],
)

# =================================================================================================
# 8. Snapshot, timestamp strategy
# =================================================================================================
CUST = "customer_id city segment updated_at"
CUST_DAY1 = rows(CUST, ("C1", "Paris", "Consumer", "2026-01-01 00:00:00"), ("C2", "Geneva", "Corporate", "2026-01-01 00:00:00"))
CUST_DAY2 = rows(CUST, ("C1", "Lyon", "Consumer", "2026-02-15 00:00:00"), ("C2", "Geneva", "Corporate", "2026-01-01 00:00:00"),
                 ("C3", "Madrid", "Consumer", "2026-02-15 00:00:00"))
CUST_DAY3 = rows(CUST, ("C1", "Lyon", "Corporate", "2026-03-01 00:00:00"), ("C2", "Geneva", "Corporate", "2026-01-01 00:00:00"),
                 ("C3", "Madrid", "Consumer", "2026-02-15 00:00:00"))
SNAP_TS = code("""
    {% snapshot customers_snapshot %}
    {{
        config(
            target_schema='silver',
            unique_key='customer_id',
            strategy='timestamp',
            updated_at='updated_at'
        )
    }}
    select customer_id, city, segment, updated_at from {{ source('crm', 'customers') }}
    {% endsnapshot %}
""")
SNAP_COLUMNS = ["customer_id", "city", "segment", "dbt_valid_from", "dbt_valid_to"]


def snapshot_days(*days):
    return [run("snapshot", tables=[T("source.customers", day)], now=f"2026-03-0{i + 1} 06:00:00") for i, day in enumerate(days)]


exercise(
    id="dbt-snapshot-timestamp", title="A dbt snapshot: SCD type 2 with the timestamp strategy", difficulty="medium",
    language="dbt-sql", topics=["snapshots", "scd-type-2", "timestamp-strategy"],
    prompt=("The CRM table (source crm.customers: customer_id, city, segment, updated_at) only holds today's values, "
            "and updated_at changes whenever a customer changes. Write snapshots/customers_snapshot.sql: a snapshot "
            "named customers_snapshot in the silver schema, keyed on customer_id, that keeps every version with the "
            "timestamp strategy. It runs once a day (dbt snapshot)."),
    sections=[("Snapshots", "A snapshot is dbt's type 2 dimension: each run compares the source with the current "
               "versions and closes a changed one (dbt_valid_to) before inserting the new version. dbt adds "
               "dbt_scd_id, dbt_updated_at, dbt_valid_from and dbt_valid_to (NULL while current). The timestamp "
               "strategy trusts updated_at: a version is valid from the updated_at of the change."),
              ("Graded", "The snapshot (customer_id, city, segment, dbt_valid_from, dbt_valid_to) after one, two and "
               "three daily runs, including a run with no change.")],
    file="snapshots/customers_snapshot.sql",
    starter=code("""
        {% snapshot customers_snapshot %}
        {{ config(target_schema='silver', unique_key='customer_id', strategy='check', check_cols=['city']) }}
        select customer_id, city, segment, updated_at from {{ source('crm', 'customers') }}
        {% endsnapshot %}
    """),
    solution=SNAP_TS,
    fixtures=[
        ("two-days", "visible", S("table", "snapshots/customers_snapshot.sql", files(), snapshot_days(CUST_DAY1, CUST_DAY2),
                                  table="silver.customers_snapshot", columns=SNAP_COLUMNS)),
        ("three-days", "hidden", S("table", "snapshots/customers_snapshot.sql", files(),
                                   snapshot_days(CUST_DAY1, CUST_DAY2, CUST_DAY3), table="silver.customers_snapshot",
                                   columns=SNAP_COLUMNS)),
        ("unchanged-day", "edge", S("table", "snapshots/customers_snapshot.sql", files(),
                                    snapshot_days(CUST_DAY1, CUST_DAY1, CUST_DAY2), table="silver.customers_snapshot",
                                    columns=SNAP_COLUMNS)),
    ],
    mutants=[SNAP_TS.replace("unique_key='customer_id'", "unique_key='city'"),
             SNAP_TS.replace("strategy='timestamp',\n        updated_at='updated_at'", "strategy='check',\n        check_cols=['city', 'segment']")],
    hints=["{% snapshot name %} ... {% endsnapshot %} around a config() and a select.",
           "strategy='timestamp' needs updated_at='updated_at'."],
    explanation=("With the timestamp strategy dbt opens a version when updated_at moves past the current version's, "
                 "and dates it with that updated_at, so the history says when the change happened in the CRM. The "
                 "check strategy would compare columns instead and date versions with the snapshot run, which is "
                 "the fallback when a source has no reliable updated_at."),
    follow_ups=["Build a dimension from the snapshot: see the dim-from-snapshot exercise."],
)

# =================================================================================================
# 9. Snapshot, check strategy and hard deletes
# =================================================================================================
SEG = "customer_id segment"
SEG_DAY1 = rows(SEG, ("C1", "Consumer"), ("C2", "Corporate"), ("C3", None))
SEG_DAY2 = rows(SEG, ("C1", "Corporate"), ("C3", "Consumer"))
SEG_DAY3 = rows(SEG, ("C1", "Corporate"), ("C2", "Corporate"), ("C3", "Consumer"))
SNAP_CHECK = code("""
    {% snapshot segments_snapshot %}
    {{
        config(
            target_schema='silver',
            unique_key='customer_id',
            strategy='check',
            check_cols=['segment'],
            hard_deletes='invalidate'
        )
    }}
    select customer_id, segment from {{ source('crm', 'customers') }}
    {% endsnapshot %}
""")
SEG_COLUMNS = ["customer_id", "segment", "dbt_valid_from", "dbt_valid_to"]


def segment_days(*days):
    return [run("snapshot", tables=[T("source.customers", day, types={"segment": "VARCHAR"})], now=f"2026-03-0{i + 1} 06:00:00")
            for i, day in enumerate(days)]


exercise(
    id="dbt-snapshot-check-deletes", title="Snapshot without updated_at: check strategy and deletions",
    difficulty="hard", language="dbt-sql", topics=["snapshots", "check-strategy", "hard-deletes"],
    prompt=("source crm.customers (customer_id, segment) has no updated_at, and customers can be deleted. Write "
            "snapshots/segments_snapshot.sql: a snapshot named segments_snapshot (silver, key customer_id) that opens "
            "a version when segment changes (NULL counts as a value) and closes the current version of a customer who "
            "disappears from the source. It runs daily at 06:00."),
    sections=[("Check strategy", "Without a trustworthy updated_at, the check strategy compares check_cols with the "
               "current version; versions are dated with the snapshot run (here 06:00 each day). Deleted rows are "
               "ignored by default: hard_deletes='invalidate' closes them (dbt 1.9; the older flag is "
               "invalidate_hard_deletes: true)."),
              ("Graded", "The snapshot (customer_id, segment, dbt_valid_from, dbt_valid_to) after a segment change, a "
               "NULL segment filled in and a deletion, then after the deleted customer comes back.")],
    file="snapshots/segments_snapshot.sql",
    starter=code("""
        {% snapshot segments_snapshot %}
        {{ config(target_schema='silver', unique_key='customer_id', strategy='check', check_cols=['segment']) }}
        select customer_id, segment from {{ source('crm', 'customers') }}
        {% endsnapshot %}
    """),
    solution=SNAP_CHECK,
    fixtures=[
        ("change-and-delete", "visible", S("table", "snapshots/segments_snapshot.sql", files(), segment_days(SEG_DAY1, SEG_DAY2),
                                           table="silver.segments_snapshot", columns=SEG_COLUMNS)),
        ("comes-back", "hidden", S("table", "snapshots/segments_snapshot.sql", files(),
                                   segment_days(SEG_DAY1, SEG_DAY2, SEG_DAY3), table="silver.segments_snapshot",
                                   columns=SEG_COLUMNS)),
        ("no-change", "edge", S("table", "snapshots/segments_snapshot.sql", files(), segment_days(SEG_DAY1, SEG_DAY1),
                                table="silver.segments_snapshot", columns=SEG_COLUMNS)),
    ],
    mutants=[SNAP_CHECK.replace(",\n        hard_deletes='invalidate'", ""),
             SNAP_CHECK.replace("check_cols=['segment']", "check_cols=['customer_id']")],
    hints=["strategy='check' with check_cols=['segment'].", "hard_deletes='invalidate' closes the versions of deleted rows."],
    explanation=("The check strategy compares segment with the current version (a NULL becoming a value is a change) "
                 "and dates each version with the run; hard_deletes='invalidate' closes the version of a customer who "
                 "vanished, and when the customer returns a new version opens. Without it, a deleted customer stays "
                 "current forever."),
    follow_ups=["hard_deletes='new_record' adds a deleted version instead of closing one. When is that better?"],
)

# =================================================================================================
# 10. A dimension from a snapshot
# =================================================================================================
DIM_FROM_SNAPSHOT = code("""
    select
        md5(customer_id || '|' || cast(dbt_valid_from as varchar)) as customer_key,
        customer_id,
        city,
        segment,
        cast(dbt_valid_from as date) as valid_from,
        coalesce(cast(dbt_valid_to as date), date '9999-12-31') as valid_to,
        dbt_valid_to is null as is_current
    from {{ ref('customers_snapshot') }}
""")
DIM_COLUMNS = ["customer_id", "city", "segment", "valid_from", "valid_to", "is_current"]


def dim_days(*days):
    return [run(tables=[T("source.customers", day)], now=f"2026-03-0{i + 1} 06:00:00") for i, day in enumerate(days)]


exercise(
    id="dbt-dim-from-snapshot", title="A type 2 dimension from a snapshot", difficulty="hard", language="dbt-sql",
    topics=["snapshots", "scd-type-2", "dimensions"],
    prompt=("The project has the snapshot customers_snapshot of the previous exercise. Write "
            "models/marts/dim_customer.sql (gold) for reports: customer_key = md5(customer_id || '|' || "
            "cast(dbt_valid_from as varchar)), customer_id, city, segment, valid_from and valid_to as dates, valid_to "
            "9999-12-31 while current, and is_current. It is rebuilt by dbt build after each snapshot."),
    sections=[("From snapshot to dimension", "Snapshots keep dbt's technical columns; the dimension reports use renames "
               "them, gives each version a stable surrogate key (a hash of the key and the start date survives "
               "rebuilds), and replaces the open NULL end with a far-future date so point-in-time joins can use "
               "between-style conditions."),
              ("Graded", "gold.dim_customer after two and three daily builds (the key's hash is checked too).")],
    file="models/marts/dim_customer.sql",
    starter=code("""
        select customer_id, city, segment, dbt_valid_from as valid_from, dbt_valid_to as valid_to
        from {{ ref('customers_snapshot') }}
        where dbt_valid_to is null
    """),
    solution=DIM_FROM_SNAPSHOT,
    fixtures=[
        ("two-days", "visible", S("table", "models/marts/dim_customer.sql", files({"snapshots/customers_snapshot.sql": SNAP_TS}),
                                  dim_days(CUST_DAY1, CUST_DAY2), table="gold.dim_customer", columns=DIM_COLUMNS)),
        ("three-days", "hidden", S("table", "models/marts/dim_customer.sql", files({"snapshots/customers_snapshot.sql": SNAP_TS}),
                                   dim_days(CUST_DAY1, CUST_DAY2, CUST_DAY3), table="gold.dim_customer", columns=DIM_COLUMNS)),
        ("keys", "edge", S("result", "models/marts/dim_customer.sql", files({"snapshots/customers_snapshot.sql": SNAP_TS}),
                           dim_days(CUST_DAY1, CUST_DAY2),
                           query="SELECT customer_id, valid_from, customer_key FROM gold.dim_customer")),
    ],
    mutants=[DIM_FROM_SNAPSHOT.replace("coalesce(cast(dbt_valid_to as date), date '9999-12-31')", "cast(dbt_valid_to as date)"),
             DIM_FROM_SNAPSHOT.replace("md5(customer_id || '|' || cast(dbt_valid_from as varchar))", "md5(customer_id)")],
    hints=["ref('customers_snapshot') reads the snapshot like any model.",
           "coalesce the open dbt_valid_to with date '9999-12-31'."],
    explanation=("The dimension keeps every version of the snapshot, with a surrogate key that changes per version "
                 "(customer_id alone would repeat), business-friendly validity dates and an explicit current flag. "
                 "Filtering to current rows would make it a type 1 dimension again."),
    follow_ups=["Use dbt_valid_to_current=\"'9999-12-31'\" in the snapshot config instead of the coalesce: what "
                "changes for other consumers of the snapshot?"],
)

# =================================================================================================
# 11. generate_schema_name
# =================================================================================================
SCHEMA_OVERRIDE = code("""
    {% macro generate_schema_name(custom_schema_name, node) -%}
        {%- if custom_schema_name is none -%}
            {{ target.schema }}
        {%- else -%}
            {{ custom_schema_name | trim }}
        {%- endif -%}
    {%- endmacro %}
""")


def schema_project():
    return files({"models/staging/stg_orders.sql": STG_ORDERS, "models/marts/fct_daily_orders.sql": FCT_ORDERS_REF}, macro=False)


exercise(
    id="dbt-generate-schema-name", title="Custom schemas: override generate_schema_name", difficulty="medium",
    language="dbt-sql", topics=["macros", "schemas", "environments"],
    prompt=("dbt_project.yml gives staging +schema: silver and marts +schema: gold, and the target schema is silver. "
            "By default dbt builds in \"<target schema>_<custom schema>\" (silver_gold), which is not a layer of the "
            "catalog. Write macros/generate_schema_name.sql so a model with a custom schema is built in that schema "
            "as is, and a model without one in the target schema."),
    sections=[("Schemas per environment", "generate_schema_name decides where each model lands. The default "
               "concatenation keeps developers' schemas apart (dbt_alice_gold); many teams override it so "
               "production uses the custom schema as is, often only for the prod target."),
              ("Graded", "dbt build: where each model lands (relation) and its status.")],
    file="macros/generate_schema_name.sql",
    starter=code("""
        {% macro generate_schema_name(custom_schema_name, node) -%}
            {%- if custom_schema_name is none -%}
                {{ target.schema }}
            {%- else -%}
                {{ target.schema }}_{{ custom_schema_name | trim }}
            {%- endif -%}
        {%- endmacro %}
    """),
    solution=SCHEMA_OVERRIDE,
    fixtures=[
        ("layers", "visible", S("nodes", "macros/generate_schema_name.sql", schema_project(), [run("run")],
                                tables=[orders_table()], columns=["name", "relation", "status"])),
        ("rows", "hidden", S("table", "macros/generate_schema_name.sql", schema_project(), [run("run")],
                             tables=[orders_table()], table="gold.fct_daily_orders")),
    ],
    mutants=[SCHEMA_OVERRIDE.replace("{{ custom_schema_name | trim }}", "{{ target.schema }}")],
    hints=["The macro returns text: the schema name.", "Use custom_schema_name as is when it is not none."],
    explanation=("The override returns the custom schema itself, so staging lands in silver and marts in gold, the "
                 "catalog's layers. Keeping target.schema everywhere would put the marts in silver; the default "
                 "concatenation invents schemas that do not exist in this warehouse."),
    follow_ups=["Make the override apply only when target.name == 'prod', and keep the default for dev."],
)

# =================================================================================================
# 12. A ref only reached in incremental runs
# =================================================================================================
CUTOFF = code("""
    select max(order_date) as last_order_date from {{ ref('stg_orders') }}
""")
CONDITIONAL = code("""
    -- depends_on: {{ ref('order_cutoff') }}
    {{ config(materialized='incremental', unique_key='order_id') }}
    select order_id, status, amount, order_date
    from {{ ref('stg_orders') }}
    {% if is_incremental() %}
    where order_date >= (select last_order_date - 1 from {{ ref('order_cutoff') }})
    {% endif %}
""")


def conditional_project():
    return files({"models/staging/stg_orders.sql": STG_ORDERS, "models/marts/order_cutoff.sql": CUTOFF})


exercise(
    id="dbt-conditional-ref", title="A ref inside is_incremental(): declare the dependency", difficulty="medium",
    language="dbt-sql", topics=["incremental", "dag", "parsing"],
    prompt=("models/marts/fct_recent_orders.sql is incremental on order_id and, in incremental runs, only reprocesses "
            "orders from the day before the latest order date given by the model order_cutoff. The first build "
            "works, but the second fails with a compilation error. Keep the logic and fix the model so every build "
            "works. Columns: order_id, status, amount, order_date."),
    sections=[("Parsing and conditional refs", "dbt parses every model once with is_incremental() false to build the "
               "DAG. A ref() that only runs inside {% if is_incremental() %} is invisible then, so on the next run "
               "dbt refuses it: it cannot order what it does not know. The fix is a `-- depends_on: {{ ref(...) }}` "
               "comment at the top of the model (Jinja still renders it), or a ref outside the if block."),
              ("Graded", "The nodes of two daily builds (status of fct_recent_orders), and its rows after the second.")],
    file="models/marts/fct_recent_orders.sql",
    starter=CONDITIONAL.replace("-- depends_on: {{ ref('order_cutoff') }}\n", ""),
    solution=CONDITIONAL,
    fixtures=[
        ("second-build", "visible", S("nodes", "models/marts/fct_recent_orders.sql", conditional_project(),
                                      [run(tables=[orders_table()]), run(tables=[orders_table()])], only=["fct_recent_orders"])),
        ("rows", "hidden", S("table", "models/marts/fct_recent_orders.sql", conditional_project(),
                             [run(tables=[orders_table()]),
                              run(tables=[orders_table(rows("order_id customer_id status amount_cents ordered_at is_test",
                                                            ("O4", "C3", "placed", 700, "2026-02-04 10:00:00", False)))])],
                             table="gold.fct_recent_orders")),
    ],
    mutants=[CONDITIONAL.replace("-- depends_on: {{ ref('order_cutoff') }}\n", "-- depends_on: order_cutoff\n")],
    hints=["Jinja renders comments' {{ }} too: a SQL comment can carry a ref.",
           "dbt's own error message tells you the hint to add."],
    explanation=("The `-- depends_on:` comment is rendered at parse time, so dbt records the dependency on "
                 "order_cutoff even though the real use is inside the incremental branch. dbt then builds order_cutoff "
                 "first and the incremental run compiles; a plain comment without {{ ref() }} declares nothing."),
    follow_ups=["Why does dbt not simply render both branches at parse time?"],
)

# -- pack assembly ---------------------------------------------------------------------------------
DBT_SECTION = ("Your file joins a small dbt project that the Datapass dbt emulation runs on an isolated DuckDB catalog "
               "built for each check: Jinja is rendered in a sandbox and the SQL really runs. It follows dbt Core and "
               "dbt-duckdb for a documented subset (checked against dbt Core); it is not dbt Core. The target schema "
               "is silver and dbt_project.yml puts staging in silver and marts in gold.")
CLOCK_COLUMNS = {"dbt_valid_from", "dbt_valid_to", "dbt_updated_at", "dbt_scd_id"}


def definition(spec: dict, rank: int) -> dict:
    by_visibility = {"visible": [], "hidden": [], "edge": []}
    for fid, visibility, _ in spec["fixtures"]:
        by_visibility[visibility].append(fid)
    sections = [{"title": "dbt project", "body": DBT_SECTION + f" Your file is {spec['file']}."}]
    sections += [{"title": t, "body": b} for t, b in spec["sections"]]
    projections = set()
    for _, _, scenario in spec["fixtures"]:
        cols = scenario.get("columns") or (["name", "resource_type", "status"] if scenario["outcome"] == "nodes" else None)
        projections.add(json.dumps(cols))
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
        "tags": ["bi-lab", "dbt", "semantic-emulation"],
        "origin": "authored", "language": spec["language"], "runtime": "datapass-dbt-emulation-v1",
        "prompt": spec["prompt"], "sections": sections, "starter_source": spec["starter"],
        "fixtures": [{"id": f"{spec['id']}-fixtures", "version": "1"}],
        "visible_checks": [{"id": fid, "description": "Outcome of the public dbt run on an isolated DuckDB catalog."}
                           for fid in by_visibility["visible"]],
        "hidden_check_refs": by_visibility["hidden"], "edge_check_refs": by_visibility["edge"],
        "hints": spec["hints"], "solution": {"available": True, "reveal": "explicit"},
        "explanation": spec["explanation"], "follow_ups": spec["follow_ups"],
        "canonical_placement": {"domain": "bi-dbt", "topic": spec["topics"][0]},
        "related_associations": ["bi-lab/dbt"],
        "recommendation": {"rank": rank, "reason": "BI Lab dbt progression"},
        "validator_version": "rows-v2", "validation": validation,
        "runtime_requirements": ["duckdb", "jinja2"],
        "provenance": {
            "source": "Authored for Datapass Workbench: dbt practices on the Datapass dbt emulation",
            "fixtures": "Authored scenarios; expected rows computed by running the reference, checked against dbt Core, reviewed",
        },
        "constraints": {"truth": ("Datapass dbt emulation on an isolated local DuckDB catalog: sandboxed Jinja, real "
                                  "SQL, dbt Core semantics for a documented subset; not dbt Core.")},
        "truth": "semantic-emulation",
    }


def outcome(source, scenario):
    from dbtlab.exercise import DbtScenario, graded_columns
    from bilab.exercise import project as project_rows
    from datapass_runtime.dbt_project_grading import Rejected, run_fixture
    from dbtlab.render import RenderError
    try:
        parsed = DbtScenario.model_validate(scenario)
        raw = run_fixture(source, parsed)
        return project_rows(raw, graded_columns(parsed, raw)), None
    except (Rejected, RenderError) as exc:
        return None, str(exc)


def dbt_core() -> list[str] | None:
    python = os.environ.get("DATAPASS_DBT_PYTHON")
    if not python:
        return None
    folder = Path(python).parent
    for name in ("dbt.exe", "dbt"):
        if (folder / name).exists():
            return [str(folder / name)]
    return None


def oracle_rows(dbt: list[str], source: str, scenario: dict, expected: list[dict]) -> str | None:
    """Run the fixture with real dbt Core and compare its graded rows with the expected ones (None when equal)."""
    import duckdb
    from datapass_runtime.catalog import json_value
    from datapass_runtime.exercises import _fixture_sql
    from datapass_runtime.factory_grading import _column_type
    with tempfile.TemporaryDirectory(prefix="datapass-dbt-oracle-", ignore_cleanup_errors=True) as temp:
        folder = Path(temp)
        project_files = {**scenario["files"], scenario["file"]: source}
        for path, text in project_files.items():
            target = folder / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        database = folder / "oracle.duckdb"
        (folder / "profiles.yml").write_text(
            "datapass:\n  target: dev\n  outputs:\n    dev:\n      type: duckdb\n"
            f"      path: '{database.as_posix()}'\n      schema: silver\n      threads: 1\n", encoding="utf-8")

        def seed(tables):
            connection = duckdb.connect(str(database))
            for layer in ("source", "bronze", "silver", "gold", "warehouse"):
                connection.execute(f"CREATE SCHEMA IF NOT EXISTS {layer}")
            for table in tables:
                columns = table.get("columns") or list(table["rows"][0])
                types = {c: table.get("types", {}).get(c) or _column_type([r[c] for r in table["rows"]]) for c in columns}
                connection.execute(f"CREATE OR REPLACE TABLE {table['name']} AS {_fixture_sql(table['rows'], columns, types)}")
            connection.close()

        seed(scenario.get("tables", []))
        results = []
        for step in scenario["runs"]:
            seed(step.get("tables", []))
            if step.get("setup"):
                connection = duckdb.connect(str(database))
                connection.execute(step["setup"])
                connection.close()
            args = [*dbt, step.get("command", "build"), "--profiles-dir", str(folder), "--project-dir", str(folder)]
            if step.get("select"):
                args += ["--select", *step["select"]]
            if step.get("full_refresh"):
                args.append("--full-refresh")
            if step.get("vars"):
                args += ["--vars", json.dumps(step["vars"])]
            subprocess.run(args, capture_output=True, text=True, cwd=folder, timeout=600)
            results = json.loads((folder / "target" / "run_results.json").read_text(encoding="utf-8"))["results"]
        kind = scenario["outcome"]
        columns = scenario.get("columns") or (["name", "resource_type", "status"] if kind == "nodes" else None)
        if kind == "nodes":
            actual = []
            for r in results:
                parts = r["unique_id"].split(".")
                relation = r.get("relation_name")
                relation = ".".join(p.strip('"') for p in relation.split(".")[-2:]) if relation else None
                row = {"name": parts[2], "resource_type": parts[0], "status": r["status"], "failures": r.get("failures"),
                       "relation": relation}
                if scenario.get("only") and row["name"] not in scenario["only"]:
                    continue
                actual.append({c: row.get(c) for c in columns})
        else:
            connection = duckdb.connect(str(database), read_only=True)
            query = f"SELECT * FROM {scenario['table']}" if kind == "table" else scenario["query"]
            cursor = connection.execute(query)
            names = [d[0] for d in cursor.description]
            actual = [dict(zip(names, map(json_value, row))) for row in cursor.fetchall()]
            connection.close()
            if columns:
                actual = [{c: row.get(c) for c in columns} for row in actual]
        # A check-strategy snapshot dates versions with the run: dbt Core uses the wall clock, the emulation the scenario.
        ignore = CLOCK_COLUMNS if "strategy='check'" in source else set()
        norm = lambda data: sorted(json.dumps({k: v for k, v in r.items() if k not in ignore}, sort_keys=True, default=str) for r in data)
        if norm(actual) != norm(expected):
            return f"dbt Core gives {actual[:6]} but the emulation {expected[:6]}"
    return None


def main() -> None:
    from dbtlab.exercise import DbtScenario
    from datapass_runtime.exercise_contracts import RowValidation
    from datapass_runtime.exercise_packs import PackRegistry
    from datapass_runtime.exercise_validation import validate_result
    ids = [spec["id"] for spec in EXERCISES]
    assert len(ids) == len(set(ids))
    dbt = dbt_core()
    definitions, grading, problems = [], {}, []
    for rank, spec in enumerate(EXERCISES, start=1):
        public = definition(spec, rank)
        definitions.append(public)
        validation = RowValidation.model_validate(public["validation"])
        fixtures = []
        for fid, visibility, scenario in spec["fixtures"]:
            DbtScenario.model_validate(scenario)
            expected, error = outcome(spec["solution"], copy.deepcopy(scenario))
            if error:
                problems.append(f"{spec['id']}/{fid}: reference rejected: {error}")
                expected = []
            elif dbt:
                mismatch = oracle_rows(dbt, spec["solution"], scenario, expected)
                if mismatch:
                    problems.append(f"{spec['id']}/{fid}: {mismatch}")
            fixtures.append({"id": fid, "visibility": visibility, "input_rows": [], "scenario": scenario, "expected": expected})
        grading[spec["id"]] = {"solution": spec["solution"], "fixtures": fixtures}
        for index, mutant in enumerate(spec["mutants"]):
            if mutant == spec["solution"]:
                problems.append(f"{spec['id']}: mutant {index} is identical to the solution")
        for label, source in [("starter", spec["starter"])] + [(f"mutant {i}", m) for i, m in enumerate(spec["mutants"])]:
            failed = False
            for fixture in fixtures:
                got, error = outcome(source, copy.deepcopy(fixture["scenario"]))
                if error:
                    failed = True
                    continue
                columns = list(got[0]) if got else []
                if not validate_result({"rows": got, "columns": columns, "truncated": False}, fixture["expected"], validation):
                    failed = True
            if not failed:
                problems.append(f"{spec['id']}: {label} passes every check")
    manifest = {"schema_version": 1, "id": "dbt-v1", "version": "1",
                "title": "BI Lab: dbt (models, tests, incremental models, snapshots) on the Datapass dbt emulation",
                "enabled": True, "provenance": {"source": "Authored for Datapass Workbench"}}
    PackRegistry().register(manifest, definitions, grading)
    PACK.mkdir(parents=True, exist_ok=True)
    for name, data in (("manifest.json", manifest), ("exercises.json", definitions), ("grading.server.json", grading)):
        (PACK / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_mutants(PACK, {spec["id"]: spec["mutants"] for spec in EXERCISES})
    for spec in EXERCISES:
        print(f"== {spec['id']}")
        for fixture in grading[spec["id"]]["fixtures"]:
            print(f"   {fixture['id']:22s}", json.dumps(fixture["expected"])[:700])
    print("\ndbt Core cross-check:", "done" if dbt else "skipped (set DATAPASS_DBT_PYTHON)")
    if problems:
        print("\nPROBLEMS:\n  " + "\n  ".join(problems))


if __name__ == "__main__":
    main()
