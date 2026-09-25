"""Grade every installed exercise through the real shared worker.

For each exercise:
- the private reference solution must PASS a full submission (visible, hidden
  and edge fixtures);
- the public starter must NOT pass (a starter that already passes teaches nothing);
- every listed mutant (a plausible wrong answer) must NOT pass, which proves the
  hidden/edge fixtures actually discriminate the mistake the lesson is about.

Python/Polars exercises run in a trusted worker here on purpose: this smoke
executes only repository-authored reference code.
"""
from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.pop("DATAPASS_TRUSTED_PYTHON", None)

from datapass_runtime.exercises import definitions, solution
from datapass_runtime.kernels import KernelManager

SKIP_RUNTIMES = {"fastapispark-guided-v1"}  # requires an explicitly qualified remote connection
# Packs whose starters must run cleanly and fail only on their results, so a
# learner never starts from a parse error.
RUNNABLE_STARTER_PACKS = {"sql-lab-v1", "engine-lab-v1", "python-lab-v1", "de-patterns-v1", "airflow-lab-v1"}

# Plausible wrong answers per exercise id. Each must fail submission.
MUTANTS: dict[str, list[str]] = {
    "sql-lab-cross-size-brand": [
        "SELECT s.size_code, b.brand_name FROM sizes AS s JOIN brands AS b ON s.size_code = b.brand_name",
        "SELECT DISTINCT s.size_code, b.brand_name FROM sizes AS s CROSS JOIN brands AS b",
    ],
    "sql-lab-cross-time-grid": [
        "SELECT h.hour_value, q.minute_value FROM hours AS h CROSS JOIN quarters AS q ORDER BY q.minute_value, h.hour_value",
        "SELECT h.hour_value, q.minute_value FROM hours AS h CROSS JOIN quarters AS q",
    ],
    "sql-lab-inner-customer-orders": [
        "SELECT c.customer_id, c.customer_name, od.order_id, od.product_id, od.quantity FROM customers AS c LEFT JOIN order_detail AS od ON c.customer_id = od.customer_id",
        "SELECT c.customer_id, c.customer_name, od.order_id, od.product_id, od.quantity FROM customers AS c JOIN order_detail AS od ON c.customer_id = od.order_id",
    ],
    "sql-lab-inner-multi-key": [
        "SELECT a.store_id, a.product_id, a.amount, t.target_amount FROM actual_sales AS a JOIN product_targets AS t ON a.product_id = t.product_id",
    ],
    "sql-lab-left-preserve-customers": [
        "SELECT c.customer_id, c.customer_name, od.order_id, od.product_id, od.quantity FROM customers AS c JOIN order_detail AS od ON c.customer_id = od.customer_id",
        "SELECT c.customer_id, c.customer_name, od.order_id, od.product_id, od.quantity FROM order_detail AS od LEFT JOIN customers AS c ON c.customer_id = od.customer_id",
    ],
    "sql-lab-left-find-missing-universe": [
        "SELECT s.sale_id, s.product_id, pc.category_id, cu.universe_id FROM sales AS s JOIN product_category AS pc ON s.product_id = pc.product_id LEFT JOIN category_universe AS cu ON pc.category_id = cu.category_id WHERE cu.universe_id IS NULL",
        "SELECT s.sale_id, s.product_id, pc.category_id, cu.universe_id FROM sales AS s LEFT JOIN product_category AS pc ON s.product_id = pc.product_id LEFT JOIN category_universe AS cu ON pc.category_id = cu.category_id WHERE pc.category_id IS NULL",
    ],
    "sql-lab-left-filter-placement": [
        "SELECT c.customer_id, o.order_id, o.order_date FROM customers AS c LEFT JOIN orders AS o ON c.customer_id = o.customer_id WHERE o.status = 'COMPLETED' AND o.order_date >= DATE '2026-01-01' AND o.order_date < DATE '2027-01-01'",
        "SELECT c.customer_id, o.order_id, o.order_date FROM customers AS c LEFT JOIN orders AS o ON c.customer_id = o.customer_id AND o.status = 'COMPLETED'",
    ],
    "sql-lab-full-reconcile": [
        "SELECT s.customer_id, CASE WHEN t.customer_id IS NULL THEN 'SOURCE_ONLY' ELSE 'MATCHED' END AS reconciliation_status FROM source_customers AS s LEFT JOIN target_customers AS t ON s.customer_id = t.customer_id",
    ],
    "sql-lab-self-manager": [
        "SELECT e.employee_name, m.employee_name AS manager_name FROM employees AS e JOIN employees AS m ON e.manager_id = m.employee_id",
        "SELECT e.employee_name, m.employee_name AS manager_name FROM employees AS e LEFT JOIN employees AS m ON e.employee_id = m.manager_id",
    ],
    "sql-lab-self-consecutive-orders": [
        "SELECT a.customer_id, a.order_id AS first_order, a.order_date AS first_order_date, b.order_id AS second_order, b.order_date AS second_order_date FROM sales_orders AS a JOIN sales_orders AS b ON a.customer_id = b.customer_id AND b.order_date > a.order_date",
        "SELECT a.customer_id, a.order_id AS first_order, a.order_date AS first_order_date, b.order_id AS second_order, b.order_date AS second_order_date FROM sales_orders AS a JOIN sales_orders AS b ON b.order_date = a.order_date + INTERVAL 1 DAY",
    ],
    "sql-lab-groupby-basket": [
        "SELECT customer_id, SUM(amount) AS average_basket_amount FROM sales GROUP BY customer_id",
        "SELECT customer_id, AVG(COALESCE(amount, 0)) AS average_basket_amount FROM sales GROUP BY customer_id",
    ],
    "sql-lab-groupby-having": [
        "SELECT city, COUNT(*) AS sale_count, AVG(sale_value) AS avg_sale_value FROM property_sales GROUP BY city HAVING COUNT(*) >= 3 AND AVG(sale_value) < 250000",
        "SELECT city, COUNT(*) AS sale_count, AVG(sale_value) AS avg_sale_value FROM property_sales WHERE sale_value < 250000 GROUP BY city HAVING COUNT(*) > 3",
    ],
    "sql-lab-groupby-above-global": [
        "SELECT customer_id, AVG(amount) AS customer_avg FROM sales GROUP BY customer_id HAVING AVG(amount) >= (SELECT AVG(amount) FROM sales)",
        "SELECT customer_id, AVG(amount) AS customer_avg FROM sales GROUP BY customer_id HAVING AVG(amount) > (SELECT AVG(customer_avg) FROM (SELECT AVG(amount) AS customer_avg FROM sales GROUP BY customer_id))",
    ],
    "sql-lab-case-raises": [
        "SELECT employee_name, department, wage, CASE WHEN department = 'SALES' THEN wage * 1.10 WHEN department = 'HR' THEN wage * 1.05 WHEN department = 'IT' THEN wage * 1.03 END AS wage_after_raise FROM employees",
    ],
    "sql-lab-case-inside-sum": [
        "SELECT discount_code, SUM(quantity * price_per_unit) AS total_revenue FROM sales GROUP BY discount_code",
        "SELECT discount_code, SUM(CASE WHEN discount_code = 'DISCOUNT10' THEN quantity * price_per_unit * 0.90 WHEN discount_code = 'DISCOUNT20' THEN quantity * price_per_unit * 0.80 END) AS total_revenue FROM sales GROUP BY discount_code",
    ],
    "sql-lab-case-salary-bands": [
        "WITH banded AS (SELECT department, wage, CASE WHEN wage < 50000 THEN 'Low' WHEN wage < 90000 THEN 'Medium' ELSE 'High' END AS salary_band FROM employees) SELECT department, salary_band, COUNT(*) AS employee_count, AVG(wage) AS average_wage FROM banded GROUP BY department, salary_band",
        "WITH banded AS (SELECT department, wage, CASE WHEN wage < 90000 THEN 'Medium' WHEN wage <= 50000 THEN 'Low' ELSE 'High' END AS salary_band FROM employees) SELECT department, salary_band, COUNT(*) AS employee_count, AVG(wage) AS average_wage FROM banded GROUP BY department, salary_band",
    ],
    "sql-lab-case-football-wins": [
        "SELECT COUNT(CASE WHEN home_team = 'Lille' AND home_goals > away_goals THEN 1 ELSE 0 END) AS home_wins, COUNT(CASE WHEN away_team = 'Lille' AND away_goals > home_goals THEN 1 ELSE 0 END) AS away_wins FROM matches WHERE division = 'L1'",
        "SELECT COUNT(CASE WHEN home_team = 'Lille' AND home_goals > away_goals THEN 1 END) AS home_wins, COUNT(CASE WHEN away_team = 'Lille' AND away_goals > home_goals THEN 1 END) AS away_wins FROM matches",
    ],
    "sql-lab-grouping-two-sets": [
        "SELECT contract_type, act_type, SUM(amount_reimbursed) AS total_reimbursed FROM reimbursements GROUP BY GROUPING SETS ((contract_type, act_type))",
        "SELECT contract_type, act_type, SUM(amount_reimbursed) AS total_reimbursed FROM reimbursements GROUP BY ROLLUP (contract_type, act_type)",
    ],
    "sql-lab-grouping-label-subtotals": [
        "SELECT year_value, COALESCE(region, 'ALL REGIONS') AS region_label, SUM(population) AS population FROM regional_population GROUP BY GROUPING SETS ((year_value, region), (year_value))",
    ],
    "sql-lab-grouping-rollup": [
        "SELECT contract_type, act_type, SUM(amount_reimbursed) AS total_reimbursed FROM reimbursements GROUP BY ROLLUP (act_type, contract_type)",
        "SELECT contract_type, act_type, SUM(amount_reimbursed) AS total_reimbursed FROM reimbursements GROUP BY CUBE (contract_type, act_type)",
    ],
    "sql-lab-grouping-cube": [
        "SELECT contract_type, act_type, SUM(amount_reimbursed) AS total_reimbursed FROM reimbursements GROUP BY ROLLUP (contract_type, act_type)",
    ],
    "sql-lab-window-running-total": [
        "SELECT date_value, visitors_count, SUM(visitors_count) OVER () AS running_visitors FROM sensor_daily",
        "SELECT date_value, visitors_count, SUM(visitors_count) OVER (ORDER BY date_value DESC) AS running_visitors FROM sensor_daily",
    ],
    "sql-lab-window-centered-average": [
        "SELECT date_value, daily_sales, AVG(daily_sales) OVER (ORDER BY date_value ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS moving_average FROM store_daily_sales",
        "SELECT date_value, daily_sales, AVG(daily_sales) OVER (ORDER BY date_value RANGE BETWEEN INTERVAL 2 DAY PRECEDING AND INTERVAL 2 DAY FOLLOWING) AS moving_average FROM store_daily_sales",
    ],
    "sql-lab-window-dept-average": [
        "SELECT employee_name, department, wage, AVG(wage) OVER () AS department_avg_wage FROM employees",
    ],
    "sql-lab-window-top-earner-flag": [
        "WITH x AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY department ORDER BY wage DESC, employee_name) AS rn, MAX(wage) OVER (PARTITION BY department) AS department_max_wage FROM employees) SELECT employee_name, department, wage, department_max_wage, CASE WHEN rn = 1 THEN 1 ELSE 0 END AS is_top_earner FROM x",
    ],
    "sql-lab-window-second-highest": [
        "WITH r AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY department ORDER BY wage DESC, employee_name) AS wage_rank FROM employees) SELECT employee_name, department, wage FROM r WHERE wage_rank = 2",
        "WITH r AS (SELECT *, RANK() OVER (PARTITION BY department ORDER BY wage DESC) AS wage_rank FROM employees) SELECT employee_name, department, wage FROM r WHERE wage_rank = 2",
    ],
    "sql-lab-window-pct-change": [
        "WITH x AS (SELECT *, LAG(visitors_count) OVER (ORDER BY date_value) AS previous_visitors FROM sensor_daily) SELECT date_value, weekday_number, visitors_count, previous_visitors, (visitors_count - previous_visitors) * 1.0 / NULLIF(previous_visitors, 0) AS pct_change FROM x",
    ],
    "sql-lab-window-row-number-dept": [
        "SELECT employee_name, department, wage, RANK() OVER (PARTITION BY department ORDER BY wage DESC) AS wage_row_number FROM employees",
        "SELECT employee_name, department, wage, ROW_NUMBER() OVER (PARTITION BY department ORDER BY wage, employee_name) AS wage_row_number FROM employees",
    ],
    "sql-lab-window-dense-rank": [
        "SELECT employee_name, sex, wage, RANK() OVER (PARTITION BY sex ORDER BY wage DESC) AS wage_rank FROM employees",
        "SELECT employee_name, sex, wage, DENSE_RANK() OVER (ORDER BY wage DESC) AS wage_rank FROM employees",
    ],
    "sql-lab-window-rows-vs-range": [
        "SELECT event_id, event_date, amount, SUM(amount) OVER (ORDER BY event_date) AS running_total FROM sales_events",
    ],
    # --- sql-lab-v1 pack version 2 -------------------------------------------------
    "sql-lab-cross-retail-grid": [
        "SELECT DISTINCT s.store_id, m.market_id, mo.month_id, w.weekday_id, q.quarter_id FROM stores AS s CROSS JOIN markets AS m CROSS JOIN months AS mo CROSS JOIN weekdays AS w CROSS JOIN quarters AS q",
        "SELECT s.store_id, m.market_id, mo.month_id, w.weekday_id, q.quarter_id FROM stores AS s JOIN markets AS m ON s.store_id = m.market_id CROSS JOIN months AS mo CROSS JOIN weekdays AS w CROSS JOIN quarters AS q",
    ],
    "sql-lab-inner-add-products": [
        "SELECT co.order_id, co.customer_id, co.product_id, co.quantity, p.product_name, p.unit_price FROM customer_orders AS co LEFT JOIN products AS p ON co.product_id = p.product_id",
        "SELECT co.order_id, co.customer_id, co.product_id, co.quantity, p.product_name, p.unit_price FROM customer_orders AS co JOIN products AS p ON co.customer_id = p.product_id",
    ],
    "sql-lab-inner-retail-chain": [
        "SELECT s.sale_id, s.product_id, pc.category_id, cu.universe_id FROM sales AS s JOIN product_category AS pc ON s.product_id = pc.product_id LEFT JOIN category_universe AS cu ON pc.category_id = cu.category_id",
        "SELECT s.sale_id, s.product_id, pc.category_id, cu.universe_id FROM sales AS s LEFT JOIN product_category AS pc ON s.product_id = pc.product_id LEFT JOIN category_universe AS cu ON pc.category_id = cu.category_id",
    ],
    "sql-lab-inner-constant-key": [
        "SELECT b.beverage, f.food FROM beverages AS b JOIN food_items AS f ON b.beverage = f.food",
        "SELECT DISTINCT b.beverage, f.food FROM beverages AS b CROSS JOIN food_items AS f",
    ],
    "sql-lab-left-product-enrichment": [
        "SELECT co.order_id, co.product_id, co.quantity, p.product_name FROM customer_orders AS co JOIN products AS p ON co.product_id = p.product_id",
        "SELECT co.order_id, co.product_id, co.quantity, p.product_name FROM customer_orders AS co LEFT JOIN products AS p ON co.product_id = p.product_id WHERE p.product_name IS NOT NULL",
    ],
    "sql-lab-full-products": [
        "SELECT sp.store_id, sp.product_id, p.product_name FROM store_products AS sp FULL OUTER JOIN products AS p ON sp.product_id = p.product_id",
        "SELECT sp.store_id, sp.product_id, p.product_name FROM store_products AS sp LEFT JOIN products AS p ON sp.product_id = p.product_id",
    ],
    "sql-lab-self-meetings": [
        "SELECT a.meeting_id, b.person_name AS colleague, a.duration_minutes FROM meeting_participants AS a JOIN meeting_participants AS b ON a.meeting_id = b.meeting_id WHERE a.person_name = 'Benjamin'",
        "SELECT a.meeting_id, b.person_name AS colleague, a.duration_minutes FROM meeting_participants AS a JOIN meeting_participants AS b ON a.meeting_id = b.meeting_id WHERE b.person_name <> 'Benjamin'",
    ],
    "sql-lab-groupby-neighborhood": [
        "SELECT neighborhood, SUM(price) AS average_price FROM property_sales GROUP BY neighborhood",
        "SELECT neighborhood, AVG(price) AS average_price FROM property_sales GROUP BY neighborhood, price",
    ],
    "sql-lab-groupby-city": [
        "SELECT city, CAST(AVG(CAST(sale_value AS INTEGER)) AS INTEGER) AS avg_sale_value FROM property_sales GROUP BY city",
        "SELECT city, AVG(sale_value) AS avg_sale_value FROM property_sales GROUP BY city",
    ],
    "sql-lab-groupby-above-global-cte": [
        "WITH global_avg AS (SELECT AVG(amount) AS avg_amount FROM sales) SELECT s.customer_id, AVG(s.amount) AS customer_avg FROM sales AS s CROSS JOIN global_avg AS g GROUP BY s.customer_id, g.avg_amount HAVING AVG(s.amount) >= g.avg_amount",
        "WITH per_customer AS (SELECT customer_id, AVG(amount) AS customer_avg FROM sales GROUP BY customer_id) SELECT customer_id, customer_avg FROM per_customer WHERE customer_avg > (SELECT AVG(customer_avg) FROM per_customer)",
    ],
    "sql-lab-groupby-meeting-average": [
        "SELECT person_name AS colleague, AVG(duration_minutes) AS avg_meeting_duration FROM meeting_participants WHERE person_name <> 'Benjamin' GROUP BY person_name",
        "WITH m AS (SELECT a.meeting_id, b.person_name AS colleague, a.duration_minutes FROM meeting_participants AS a JOIN meeting_participants AS b ON a.meeting_id = b.meeting_id WHERE a.person_name = 'Benjamin') SELECT colleague, AVG(duration_minutes) AS avg_meeting_duration FROM m GROUP BY colleague",
    ],
    "sql-lab-case-discount-cte": [
        "WITH priced AS (SELECT discount_code, CASE WHEN discount_code = 'DISCOUNT10' THEN quantity * price_per_unit * 0.10 WHEN discount_code = 'DISCOUNT20' THEN quantity * price_per_unit * 0.20 ELSE quantity * price_per_unit END AS revenue_after_discount FROM sales) SELECT discount_code, SUM(revenue_after_discount) AS total_revenue FROM priced GROUP BY discount_code",
        "WITH priced AS (SELECT discount_code, CASE WHEN discount_code = 'DISCOUNT10' THEN quantity * price_per_unit * 0.90 WHEN discount_code = 'DISCOUNT20' THEN quantity * price_per_unit * 0.80 END AS revenue_after_discount FROM sales) SELECT discount_code, SUM(revenue_after_discount) AS total_revenue FROM priced GROUP BY discount_code",
    ],
    "sql-lab-grouping-contract": [
        "SELECT contract_type, SUM(amount_reimbursed) AS total_reimbursed FROM reimbursements GROUP BY contract_type, act_type",
        "SELECT contract_type, COUNT(amount_reimbursed) AS total_reimbursed FROM reimbursements GROUP BY contract_type",
    ],
    "sql-lab-grouping-contract-act": [
        "SELECT contract_type, act_type, SUM(DISTINCT amount_reimbursed) AS total_reimbursed FROM reimbursements GROUP BY contract_type, act_type",
        "SELECT contract_type, act_type, SUM(amount_reimbursed) AS total_reimbursed FROM reimbursements GROUP BY ROLLUP (contract_type, act_type)",
    ],
    "sql-lab-grouping-union": [
        "SELECT contract_type AS typology, SUM(amount_reimbursed) AS total_reimbursed FROM reimbursements GROUP BY contract_type UNION SELECT act_type AS typology, SUM(amount_reimbursed) AS total_reimbursed FROM reimbursements GROUP BY act_type",
        "SELECT contract_type AS typology, SUM(amount_reimbursed) AS total_reimbursed FROM reimbursements GROUP BY contract_type",
    ],
    "sql-lab-grouping-region-year": [
        "SELECT year_value, region, SUM(population) AS population FROM regional_population GROUP BY year_value, region",
        "SELECT year_value, region, SUM(population) AS population FROM regional_population GROUP BY ROLLUP (year_value, region)",
    ],
    "sql-lab-grouping-multilevel-rollup": [
        "SELECT contract_type, act_type, age_group, sex, year_value, SUM(amount_reimbursed) AS total_reimbursed FROM reimbursements GROUP BY CUBE (contract_type, act_type, age_group, sex, year_value)",
        "SELECT contract_type, act_type, age_group, sex, year_value, SUM(amount_reimbursed) AS total_reimbursed FROM reimbursements GROUP BY ROLLUP (contract_type, act_type, sex, age_group, year_value)",
    ],
    "sql-lab-grouping-store-share": [
        "SELECT store_id, SUM(CASE WHEN product_name = 'Red Bull' THEN amount END) AS red_bull_sales, SUM(amount) AS store_sales, SUM(CASE WHEN product_name = 'Red Bull' THEN amount END) * 1.0 / (SELECT SUM(amount) FROM sales) AS red_bull_share FROM sales GROUP BY store_id",
        "SELECT store_id, COALESCE(SUM(CASE WHEN product_name = 'Red Bull' THEN amount END), 0) AS red_bull_sales, SUM(amount) AS store_sales, COALESCE(SUM(CASE WHEN product_name = 'Red Bull' THEN amount END), 0) * 1.0 / SUM(amount) AS red_bull_share FROM sales GROUP BY store_id",
    ],
    "sql-lab-window-sum-over": [
        "SELECT date_value, visitors_count, SUM(visitors_count) OVER (ORDER BY date_value) AS total_visitors FROM sensor_daily",
    ],
    "sql-lab-window-progressive-average": [
        "SELECT date_value, visitors_count, AVG(visitors_count) OVER () AS avg_visitors_to_date FROM sensor_daily",
        "SELECT date_value, visitors_count, AVG(visitors_count) OVER (ORDER BY date_value DESC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS avg_visitors_to_date FROM sensor_daily",
    ],
    "sql-lab-window-seven-row-average": [
        "SELECT date_value, visitors_count, AVG(visitors_count) OVER (ORDER BY date_value ROWS BETWEEN 7 PRECEDING AND CURRENT ROW) AS seven_day_avg FROM sensor_daily",
        "SELECT date_value, visitors_count, AVG(visitors_count) OVER (ORDER BY date_value RANGE BETWEEN INTERVAL 6 DAY PRECEDING AND CURRENT ROW) AS seven_day_avg FROM sensor_daily",
    ],
    "sql-lab-window-verify-average": [
        "WITH w AS (SELECT *, SUM(visitors_count) OVER (ORDER BY date_value ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) AS window_sum, COUNT(*) OVER () AS window_count, AVG(visitors_count) OVER (ORDER BY date_value ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) AS window_avg FROM sensor_daily) SELECT date_value, visitors_count, window_sum, window_count, window_avg, window_sum * 1.0 / NULLIF(window_count, 0) AS manual_avg FROM w",
        "WITH w AS (SELECT *, SUM(visitors_count) OVER (ORDER BY date_value ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) AS window_sum, COUNT(*) OVER (ORDER BY date_value ROWS BETWEEN 7 PRECEDING AND CURRENT ROW) AS window_count, AVG(visitors_count) OVER (ORDER BY date_value ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) AS window_avg FROM sensor_daily) SELECT date_value, visitors_count, window_sum, window_count, window_avg, window_sum * 1.0 / NULLIF(window_count, 0) AS manual_avg FROM w",
    ],
    "sql-lab-window-dept-max": [
        "SELECT employee_name, department, wage, MAX(wage) OVER (PARTITION BY department ORDER BY wage) AS department_max_wage FROM employees",
        "SELECT employee_name, department, wage, MAX(wage) OVER () AS department_max_wage FROM employees",
    ],
    "sql-lab-window-weekday-partition": [
        "SELECT date_value, weekday_number, visitors_count, AVG(visitors_count) OVER (ORDER BY date_value ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) AS same_weekday_avg FROM sensor_daily",
        "SELECT date_value, weekday_number, visitors_count, AVG(visitors_count) OVER (PARTITION BY weekday_number ORDER BY date_value ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS same_weekday_avg FROM sensor_daily",
    ],
    "sql-lab-window-lag": [
        "SELECT date_value, weekday_number, visitors_count, LAG(visitors_count) OVER (ORDER BY date_value) AS previous_same_weekday_visitors FROM sensor_daily",
        "SELECT date_value, weekday_number, visitors_count, LEAD(visitors_count) OVER (PARTITION BY weekday_number ORDER BY date_value) AS previous_same_weekday_visitors FROM sensor_daily",
    ],
    "sql-lab-window-row-number-sex": [
        "SELECT employee_name, sex, wage, RANK() OVER (PARTITION BY sex ORDER BY wage DESC) AS wage_row_number FROM employees",
        "SELECT employee_name, sex, wage, ROW_NUMBER() OVER (PARTITION BY sex ORDER BY wage DESC, employee_name DESC) AS wage_row_number FROM employees",
    ],
    "sql-lab-window-sensor-running-avg": [
        "SELECT sensor_id, date_value, visitors_count, AVG(visitors_count) OVER (ORDER BY date_value, sensor_id ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running_avg_visitors FROM sensor_daily",
    ],
    "sql-lab-window-sensor-weekday": [
        "SELECT sensor_id, weekday_number, date_value, visitors_count, AVG(visitors_count) OVER (PARTITION BY sensor_id ORDER BY date_value ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running_avg_visitors FROM sensor_daily",
    ],
    "sql-lab-window-updated-ranking": [
        "WITH moving AS (SELECT *, AVG(visitors_count) OVER (PARTITION BY sensor_id, weekday_number ORDER BY date_value ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running_avg_visitors FROM sensor_daily) SELECT sensor_id, weekday_number, date_value, visitors_count, running_avg_visitors, RANK() OVER (PARTITION BY date_value ORDER BY running_avg_visitors DESC) AS sensor_rank FROM moving",
        "WITH moving AS (SELECT *, AVG(visitors_count) OVER (PARTITION BY sensor_id, weekday_number ORDER BY date_value ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running_avg_visitors FROM sensor_daily) SELECT sensor_id, weekday_number, date_value, visitors_count, running_avg_visitors, DENSE_RANK() OVER (PARTITION BY date_value ORDER BY visitors_count DESC) AS sensor_rank FROM moving",
    ],
    "sql-lab-window-top-one": [
        "WITH ranked AS (SELECT *, DENSE_RANK() OVER (PARTITION BY department ORDER BY wage DESC) AS rn FROM employees) SELECT employee_name, department, wage FROM ranked WHERE rn = 1",
        "WITH ranked AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY department ORDER BY wage DESC, employee_name DESC) AS rn FROM employees) SELECT employee_name, department, wage FROM ranked WHERE rn = 1",
    ],
    # --- engine-lab-v1 and python-lab-v1 (variant ids are <scenario>-<language>) ---
    'eng-filter-active-sql': [
        "SELECT order_id, customer_id, status, amount FROM orders WHERE upper(status) = 'ACTIVE'",
        "SELECT DISTINCT order_id, customer_id, status, amount FROM orders WHERE status = 'ACTIVE'",
    ],
    'eng-filter-active-python': [
        'import pandas as pd\norders_df = pd.DataFrame(orders)\nactive = orders_df[orders_df["status"].str.upper() == "ACTIVE"]\ndisplay(active[["order_id", "customer_id", "status", "amount"]])',
    ],
    'eng-derived-flag-sql': [
        'SELECT order_id, amount, CASE WHEN amount > 1000 THEN 1 ELSE 0 END AS is_high_value FROM orders',
    ],
    'eng-derived-flag-polars': [
        'import polars as pl\norders_df = pl.DataFrame(orders)\ndisplay(orders_df.with_columns(is_high_value=(pl.col("amount") >= 1000).cast(pl.Int64)).select("order_id", "amount", "is_high_value"))',
    ],
    'eng-group-sum-sql': [
        'SELECT customer_id, SUM(DISTINCT amount) AS total_amount FROM orders GROUP BY customer_id',
    ],
    'eng-group-sum-sparklab': [
        'from pyspark.sql import functions as F\norders = spark.table("orders")\norders.groupBy("customer_id").agg(F.max("amount").alias("total_amount"))',
    ],
    'eng-multi-agg-sql': [
        'SELECT customer_id, COUNT(order_id) AS order_count, SUM(amount) AS total_amount, SUM(amount) / COUNT(DISTINCT customer_id) AS avg_amount FROM orders GROUP BY customer_id',
    ],
    'eng-inner-join-sql': [
        'SELECT o.order_id, o.customer_id, o.amount, c.customer_name FROM orders AS o LEFT JOIN customers AS c ON o.customer_id = c.customer_id',
    ],
    'eng-inner-join-python': [
        'import pandas as pd\norders_df = pd.DataFrame(orders)\ncustomers_df = pd.DataFrame(customers)\nresult = orders_df.merge(customers_df, on="customer_id", how="left")\ndisplay(result[["order_id", "customer_id", "amount", "customer_name"]])',
    ],
    'eng-anti-join-sql': [
        'SELECT o.order_id, o.customer_id, o.amount FROM orders AS o WHERE o.customer_id NOT IN (SELECT customer_id FROM customers)',
    ],
    'eng-anti-join-sparklab': [
        'from pyspark.sql import functions as F\norders = spark.table("orders")\ncustomers = spark.table("customers")\norders.join(customers, on="customer_id", how="semi").select("order_id", "customer_id", "amount")',
    ],
    'eng-latest-row-sql': [
        'SELECT customer_id, updated_at, status FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY updated_at) AS rn FROM customer_history) WHERE rn = 1',
    ],
    'eng-latest-row-python': [
        'import pandas as pd\nhistory_df = pd.DataFrame(customer_history)\nlatest = history_df.drop_duplicates(subset=["customer_id"], keep="last")\ndisplay(latest[["customer_id", "updated_at", "status"]])',
    ],
    'eng-running-total-sql': [
        'SELECT customer_id, order_date, order_id, amount, SUM(amount) OVER (ORDER BY order_date, order_id ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running_amount FROM orders',
    ],
    'eng-running-total-python': [
        'import pandas as pd\norders_df = pd.DataFrame(orders)\norders_df["running_amount"] = orders_df.groupby("customer_id")["amount"].cumsum()\ndisplay(orders_df[["customer_id", "order_date", "order_id", "amount", "running_amount"]])',
    ],
    'eng-lag-delta-sql': [
        'WITH x AS (SELECT *, LAG(amount) OVER (ORDER BY order_date, order_id) AS previous_amount FROM orders) SELECT customer_id, order_date, order_id, amount, previous_amount, amount - previous_amount AS amount_delta FROM x',
    ],
    'eng-lag-delta-polars': [
        'import polars as pl\norders_df = pl.DataFrame(orders)\nresult = orders_df.sort("customer_id", "order_date", "order_id").with_columns(previous_amount=pl.col("amount").shift(1))\ndisplay(result.with_columns(amount_delta=pl.col("amount") - pl.col("previous_amount")))',
    ],
    'eng-top-n-sql': [
        'SELECT category, product_id, revenue FROM (SELECT *, DENSE_RANK() OVER (PARTITION BY category ORDER BY revenue DESC) AS rn FROM product_sales) WHERE rn <= 3',
        'SELECT category, product_id, revenue FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY category ORDER BY revenue DESC, product_id DESC) AS rn FROM product_sales) WHERE rn <= 3',
    ],
    'eng-null-fill-sql': [
        "SELECT customer_id, COALESCE(NULLIF(country, ''), 'UNKNOWN') AS country_clean FROM customers",
    ],
    'eng-null-fill-python': [
        'import pandas as pd\ncustomers_df = pd.DataFrame(customers)\ncustomers_df["country_clean"] = customers_df["country"].replace("", None).fillna("UNKNOWN")\ndisplay(customers_df[["customer_id", "country_clean"]])',
    ],
    'eng-union-sql': [
        'SELECT order_id, amount FROM historical_orders UNION SELECT order_id, amount FROM current_orders',
    ],
    'eng-union-python': [
        'import pandas as pd\nhistorical_orders_df = pd.DataFrame(historical_orders)\ncurrent_orders_df = pd.DataFrame(current_orders)\ndisplay(pd.concat([historical_orders_df, current_orders_df]).drop_duplicates()[["order_id", "amount"]])',
    ],
    'eng-transform-share-sql': [
        'SELECT customer_id, order_id, amount, SUM(amount) OVER () AS customer_total, amount / SUM(amount) OVER () AS amount_share FROM orders',
    ],
    'eng-transform-share-sparklab': [
        'from pyspark.sql import functions as F\nfrom pyspark.sql.window import Window\norders = spark.table("orders")\nw = Window.partitionBy("customer_id").orderBy("order_id")\nwith_total = orders.withColumn("customer_total", F.sum("amount").over(w))\nwith_total.withColumn("amount_share", F.col("amount") / F.col("customer_total"))',
    ],
    'eng-dense-rank-sql': [
        'SELECT employee_name, department, wage, RANK() OVER (PARTITION BY department ORDER BY wage DESC) AS wage_rank FROM employees',
    ],
    'eng-dense-rank-python': [
        'import pandas as pd\nemployees_df = pd.DataFrame(employees)\nemployees_df["wage_rank"] = employees_df.groupby("department")["wage"].rank(method="min", ascending=False).astype(int)\ndisplay(employees_df)',
    ],
    'eng-cross-merge-sql': [
        'SELECT DISTINCT s.size_code, b.brand_name FROM sizes AS s CROSS JOIN brands AS b',
    ],
    'eng-broadcast-join-sparklab': [
        'from pyspark.sql import functions as F\nsales = spark.table("sales")\nproducts = spark.table("products")\nsales.join(F.broadcast(products), on="product_id", how="left").select("sale_id", "product_id", "quantity", "product_name")',
    ],
    'eng-normalize-email-sql': [
        "SELECT customer_id, lower(replace(email, ' ', '')) AS email_normalized FROM customers",
    ],
    'eng-qualify-latest-sql': [
        'SELECT user_id, event_id, event_time FROM events QUALIFY ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY event_time DESC, event_id) = 1',
    ],
    'eng-ordered-string-agg-sql': [
        "SELECT user_id, string_agg(event_name, ',' ORDER BY event_time) AS recent_events FROM events GROUP BY user_id",
    ],
    'eng-split-explode-sql': [
        "SELECT DISTINCT order_id, CAST(unnest(string_split(item_ids, ',')) AS INTEGER) AS item_id FROM orders",
    ],
    'py-load-mode': [
        'result = []\nfor row in table_stats:\n    if row["row_count"] == 0:\n        mode = "full"\n    elif row["row_count"] >= 1_000_000:\n        mode = "large_incremental"\n    else:\n        mode = "incremental"\n    result.append({"table_name": row["table_name"], "row_count": row["row_count"], "mode": mode})\ndisplay(result)',
    ],
    'py-safe-int': [
        'result = []\nfor row in raw_values:\n    try:\n        parsed = int(float(row["raw_value"]))\n    except ValueError:\n        parsed = None\n    result.append({"raw_value": row["raw_value"], "parsed": parsed})\ndisplay(result)',
    ],
    'py-set-validate': [
        'allowed_status = {"NEW", "READY", "DONE"}\ndisplay([{"status": row["status"], "is_valid": row["status"].upper() in allowed_status} for row in statuses])',
    ],
    'py-frequency': [
        'display([{"status": status, "count": 1} for status in {row["status"] for row in events}])',
    ],
    'py-dedupe-order': [
        'display([{"id": value} for value in sorted({row["id"] for row in ids})])',
    ],
    'py-batching': [
        'values = [row["id"] for row in ids]\nresult = []\nfor number, start in enumerate(range(0, len(values) - 3 + 1, 3), start=1):\n    batch = values[start:start + 3]\n    result.append({"batch_number": number, "first_id": batch[0], "last_id": batch[-1], "size": len(batch)})\ndisplay(result)',
    ],
    'py-binary-search': [
        'from bisect import bisect_right\nvalues = [row["value"] for row in sorted_values]\nresult = []\nfor row in targets:\n    position = bisect_right(values, row["target"])\n    result.append({"target": row["target"], "position": position, "found": row["target"] in values})\ndisplay(result)',
    ],
    'py-hash-join': [
        'names = {c["customer_id"]: c["name"] for c in customers}\ndisplay([{"order_id": o["order_id"], "customer_id": o["customer_id"], "customer_name": names.get(o["customer_id"], "")} for o in orders])',
    ],
    'py-prefix-filter': [
        'display([{"table_name": row["table_name"]} for row in tables_list if "dim_" in row["table_name"].lower()], columns=["table_name"])',
    ],
    'py-sort-key': [
        'display([{"name": j["name"], "priority": j["priority"]} for j in sorted(jobs, key=lambda job: (job["priority"], job["name"]))])',
    ],
    'py-parse-timestamp': [
        'from datetime import datetime\nresult = []\nfor row in raw_times:\n    ts = datetime.strptime(row["raw"], "%Y-%m-%d %H:%M:%S")\n    result.append({"raw": row["raw"], "date": ts.date().isoformat(), "hour": ts.hour, "weekday": ts.isoweekday()})\ndisplay(result)',
    ],
    'py-numpy-vectorize': [
        'import numpy as np\nvalues = np.array([row["amount"] for row in amounts], dtype=float)\ndisplay([{"amount": float(a), "net_amount": float(a * 0.2)} for a in values])',
    ],
    # de-patterns-v1: data-engineering SQL patterns.
    "de-clean-imported-text": [
        "SELECT CAST(order_id AS INTEGER) AS order_id, TRY_CAST(amount AS DOUBLE) AS amount, LOWER(status) AS status FROM raw_orders",
        "SELECT CAST(order_id AS INTEGER) AS order_id, TRY_CAST(NULLIF(TRIM(amount), '') AS DOUBLE) AS amount, LOWER(TRIM(status)) AS status FROM raw_orders",
    ],
    "de-latest-cdc-record": [
        "SELECT customer_id, email, updated_at FROM customer_changes QUALIFY RANK() OVER (PARTITION BY customer_id ORDER BY updated_at DESC) = 1",
        "SELECT customer_id, email, updated_at FROM customer_changes QUALIFY ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY ingest_seq DESC) = 1",
        "SELECT c.customer_id, c.email, c.updated_at FROM customer_changes c JOIN (SELECT customer_id, MAX(updated_at) AS m FROM customer_changes GROUP BY customer_id) x ON x.customer_id = c.customer_id AND x.m = c.updated_at",
    ],
    "de-not-in-null-trap": [
        "SELECT customer_id, name FROM customers WHERE customer_id NOT IN (SELECT customer_id FROM orders)",
    ],
    "de-login-streaks": [
        "WITH g AS (SELECT user_id, CAST(login_at AS DATE) AS d, CAST(login_at AS DATE) - CAST(ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY login_at) AS INTEGER) AS island FROM logins) SELECT user_id, MIN(d) AS streak_start, MAX(d) AS streak_end, COUNT(*) AS days FROM g GROUP BY user_id, island",
        "WITH login_days AS (SELECT DISTINCT user_id, CAST(login_at AS DATE) AS d FROM logins), g AS (SELECT user_id, d, d - CAST(ROW_NUMBER() OVER (ORDER BY d, user_id) AS INTEGER) AS island FROM login_days) SELECT user_id, MIN(d) AS streak_start, MAX(d) AS streak_end, COUNT(*) AS days FROM g GROUP BY user_id, island",
    ],
    "de-sessionize-clicks": [
        "WITH f AS (SELECT user_id, event_at, CASE WHEN event_at - LAG(event_at) OVER (PARTITION BY user_id ORDER BY event_at) < INTERVAL 30 MINUTE THEN 0 ELSE 1 END AS s FROM clicks), n AS (SELECT user_id, event_at, SUM(s) OVER (PARTITION BY user_id ORDER BY event_at ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS session_no FROM f) SELECT user_id, session_no, MIN(event_at) AS session_start, MAX(event_at) AS session_end, COUNT(*) AS events FROM n GROUP BY user_id, session_no",
        "WITH f AS (SELECT user_id, event_at, CASE WHEN event_at - LAG(event_at) OVER (ORDER BY event_at) <= INTERVAL 30 MINUTE THEN 0 ELSE 1 END AS s FROM clicks), n AS (SELECT user_id, event_at, SUM(s) OVER (PARTITION BY user_id ORDER BY event_at ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS session_no FROM f) SELECT user_id, session_no, MIN(event_at) AS session_start, MAX(event_at) AS session_end, COUNT(*) AS events FROM n GROUP BY user_id, session_no",
    ],
    "de-asof-trade-prices": [
        "SELECT t.trade_id, t.symbol, t.traded_at, p.price FROM trades t ASOF JOIN prices p ON t.symbol = p.symbol AND t.traded_at >= p.quoted_at",
        "SELECT t.trade_id, t.symbol, t.traded_at, p.price FROM trades t ASOF LEFT JOIN prices p ON t.symbol = p.symbol AND t.traded_at > p.quoted_at",
        "SELECT t.trade_id, t.symbol, t.traded_at, p.price FROM trades t ASOF LEFT JOIN prices p ON t.traded_at >= p.quoted_at",
    ],
    "de-scd2-validity": [
        "SELECT customer_id, tier, changed_on AS valid_from, LEAD(changed_on) OVER (ORDER BY changed_on) AS valid_to, LEAD(changed_on) OVER (ORDER BY changed_on) IS NULL AS is_current FROM tier_changes",
        "SELECT customer_id, tier, changed_on AS valid_from, LAG(changed_on) OVER (PARTITION BY customer_id ORDER BY changed_on) AS valid_to, LAG(changed_on) OVER (PARTITION BY customer_id ORDER BY changed_on) IS NULL AS is_current FROM tier_changes",
    ],
    "de-upsert-result": [
        "SELECT COALESCE(u.id, t.id) AS id, COALESCE(u.name, t.name) AS name, COALESCE(u.city, t.city) AS city FROM target t FULL JOIN updates u ON u.id = t.id",
        "SELECT t.id, COALESCE(u.name, t.name) AS name, CASE WHEN u.id IS NULL THEN t.city ELSE u.city END AS city FROM target t LEFT JOIN updates u ON u.id = t.id",
    ],
    "de-dq-rule-violations": [
        "SELECT order_id, CASE WHEN email IS NULL OR TRIM(email) = '' THEN 'missing_email' WHEN amount < 0 THEN 'negative_amount' WHEN order_date > DATE '2026-09-30' THEN 'future_date' END AS rule FROM orders WHERE (email IS NULL OR TRIM(email) = '') OR amount < 0 OR order_date > DATE '2026-09-30'",
        "SELECT order_id, 'missing_email' AS rule FROM orders WHERE email IS NULL UNION ALL SELECT order_id, 'negative_amount' FROM orders WHERE amount < 0 UNION ALL SELECT order_id, 'future_date' FROM orders WHERE order_date > DATE '2026-09-30'",
        "SELECT order_id, 'missing_email' AS rule FROM orders WHERE email IS NULL OR TRIM(email) = '' UNION ALL SELECT order_id, 'negative_amount' FROM orders WHERE amount <= 0 UNION ALL SELECT order_id, 'future_date' FROM orders WHERE order_date >= DATE '2026-09-30'",
    ],
    "de-monthly-revenue-gaps": [
        "SELECT CAST(date_trunc('month', sold_on) AS DATE) AS month, SUM(amount) AS revenue FROM sales WHERE sold_on BETWEEN DATE '2026-01-01' AND DATE '2026-06-30' GROUP BY 1",
        "SELECT CAST(m.month AS DATE) AS month, SUM(s.amount) AS revenue FROM generate_series(DATE '2026-01-01', DATE '2026-06-01', INTERVAL 1 MONTH) AS m(month) LEFT JOIN sales s ON date_trunc('month', s.sold_on) = m.month GROUP BY m.month",
    ],
    "de-funnel-conversion": [
        "SELECT step, COUNT(*) AS users, ROUND(100.0 * COUNT(*) / NULLIF((SELECT COUNT(*) FROM events WHERE step = 'view'), 0), 1) AS pct_of_viewers FROM events GROUP BY step",
        "WITH t AS (SELECT COUNT(DISTINCT user_id) FILTER (WHERE step = 'view') AS v, COUNT(DISTINCT user_id) FILTER (WHERE step = 'cart') AS c, COUNT(DISTINCT user_id) FILTER (WHERE step = 'purchase') AS p FROM events) SELECT 'view' AS step, v AS users, ROUND(100.0 * v / NULLIF(v, 0), 1) AS pct_of_viewers FROM t UNION ALL SELECT 'cart', c, ROUND(100.0 * c / NULLIF(v, 0), 1) FROM t UNION ALL SELECT 'purchase', p, ROUND(100.0 * p / NULLIF(v, 0), 1) FROM t",
    ],
    "de-median-delivery": [
        "SELECT carrier, AVG(days) AS median_days FROM deliveries GROUP BY carrier",
        "SELECT carrier, CAST(quantile_disc(days, 0.5) AS DOUBLE) AS median_days FROM deliveries GROUP BY carrier",
    ],
    "de-cohort-retention": [
        "WITH monthly AS (SELECT customer_id, CAST(date_trunc('month', ordered_on) AS DATE) AS order_month FROM orders), cohorts AS (SELECT customer_id, MIN(order_month) AS cohort_month FROM monthly GROUP BY customer_id) SELECT c.cohort_month, CAST(date_diff('month', c.cohort_month, m.order_month) AS INTEGER) AS month_offset, COUNT(*) AS customers FROM monthly m JOIN cohorts c USING (customer_id) GROUP BY 1, 2",
        "SELECT CAST(date_trunc('month', ordered_on) AS DATE) AS cohort_month, 0 AS month_offset, COUNT(DISTINCT customer_id) AS customers FROM orders GROUP BY 1",
    ],
    "de-split-tags": [
        "WITH e AS (SELECT article_id, LOWER(raw_tag) AS tag FROM (SELECT article_id, UNNEST(string_split(tags, ',')) AS raw_tag FROM articles)) SELECT tag, COUNT(DISTINCT article_id) AS articles FROM e WHERE tag <> '' GROUP BY tag",
        "WITH e AS (SELECT article_id, LOWER(TRIM(raw_tag)) AS tag FROM (SELECT article_id, UNNEST(string_split(tags, ',')) AS raw_tag FROM articles)) SELECT tag, COUNT(*) AS articles FROM e WHERE tag <> '' GROUP BY tag",
    ],
    "de-incremental-watermark": [
        "SELECT s.id, s.updated_at FROM source_rows s WHERE s.updated_at >= COALESCE((SELECT MAX(last_loaded_at) FROM watermark WHERE table_name = 'source_rows'), TIMESTAMP '1900-01-01 00:00:00')",
        "SELECT s.id, s.updated_at FROM source_rows s WHERE s.updated_at > (SELECT MAX(last_loaded_at) FROM watermark WHERE table_name = 'source_rows')",
        "SELECT s.id, s.updated_at FROM source_rows s WHERE s.updated_at > COALESCE((SELECT MAX(last_loaded_at) FROM watermark), TIMESTAMP '1900-01-01 00:00:00')",
    ],
    "de-pivot-status-filter": [
        "SELECT opened_on, COUNT(status = 'open') AS open_count, COUNT(status = 'closed') AS closed_count, COUNT(*) AS total FROM tickets GROUP BY opened_on",
    ],
    'af-fan-in-fan-out': [
        'from datetime import datetime\n\nfrom airflow.sdk import DAG\nfrom airflow.providers.standard.operators.empty import EmptyOperator\n\nwith DAG(dag_id="customer_360", schedule="@daily", start_date=datetime(2026, 3, 1)) as dag:\n\n    extract_orders = EmptyOperator(task_id="extract_orders")\n    extract_customers = EmptyOperator(task_id="extract_customers")\n    transform = EmptyOperator(task_id="transform")\n    load_warehouse = EmptyOperator(task_id="load_warehouse")\n    load_search = EmptyOperator(task_id="load_search")\n    notify = EmptyOperator(task_id="notify")\n\n    extract_orders >> extract_customers >> transform >> [load_warehouse, load_search] >> notify\n',
        'from datetime import datetime\n\nfrom airflow.sdk import DAG\nfrom airflow.providers.standard.operators.empty import EmptyOperator\n\nwith DAG(dag_id="customer_360", schedule="@daily", start_date=datetime(2026, 3, 1)) as dag:\n\n    extract_orders = EmptyOperator(task_id="extract_orders")\n    extract_customers = EmptyOperator(task_id="extract_customers")\n    transform = EmptyOperator(task_id="transform")\n    load_warehouse = EmptyOperator(task_id="load_warehouse")\n    load_search = EmptyOperator(task_id="load_search")\n    notify = EmptyOperator(task_id="notify")\n\n    [extract_orders, extract_customers] >> transform >> [load_warehouse, load_search]\n    load_warehouse >> notify\n',
    ],
    'af-taskflow-data-dependencies': [
        'import pendulum\n\nfrom airflow.sdk import dag, task\n\n\n@dag(schedule="@daily", start_date=pendulum.datetime(2026, 3, 1, tz="UTC"))\ndef orders_taskflow():\n    @task\n    def extract():\n        return [{"order_id": 1, "amount": 10.0}]\n\n    @task\n    def transform(rows):\n        return [row for row in rows if row["amount"] > 0]\n\n    @task\n    def load(rows):\n        print(f"loading {len(rows)} rows")\n\n    @task\n    def audit():\n        print("audit done")\n\n    raw = extract()\n    clean = transform(raw)\n    load(clean)\n    audit()\n\n\norders_taskflow()\n',
        'import pendulum\n\nfrom airflow.sdk import dag, task\n\n\n@dag(schedule="@daily", start_date=pendulum.datetime(2026, 3, 1, tz="UTC"))\ndef orders_taskflow():\n    @task\n    def extract():\n        return [{"order_id": 1, "amount": 10.0}]\n\n    @task\n    def transform(rows):\n        return [row for row in rows if row["amount"] > 0]\n\n    @task\n    def load(rows):\n        print(f"loading {len(rows)} rows")\n\n    @task\n    def audit():\n        print("audit done")\n\n    raw = extract()\n    clean = transform(raw)\n    load(raw) >> audit()\n\n\norders_taskflow()\n',
    ],
    'af-catchup-backfill': [
        'from datetime import datetime\n\nfrom airflow.sdk import DAG\nfrom airflow.providers.standard.operators.bash import BashOperator\n\nwith DAG(\n    dag_id="daily_sales",\n    schedule="@daily",\n    start_date=datetime(2026, 3, 2),\n    catchup=True,\n) as dag:\n    BashOperator(task_id="load", bash_command="load_sales --day {{ ds }}")\n',
        'from datetime import datetime\n\nfrom airflow.sdk import DAG\nfrom airflow.providers.standard.operators.bash import BashOperator\n\nwith DAG(\n    dag_id="daily_sales",\n    schedule="0 6 * * *",\n    start_date=datetime(2026, 3, 1),\n    catchup=True,\n) as dag:\n    BashOperator(task_id="load", bash_command="load_sales --day {{ ds }}")\n',
    ],
    'af-no-accidental-backfill': [
        'from datetime import datetime\n\nfrom airflow.sdk import DAG\nfrom airflow.providers.standard.operators.bash import BashOperator\n\nwith DAG(\n    dag_id="inventory_snapshot",\n    schedule=None,\n    start_date=datetime(2025, 1, 1),\n) as dag:\n    BashOperator(task_id="snapshot", bash_command="snapshot_inventory --day {{ ds }}")\n',
        'from datetime import datetime\n\nfrom airflow.sdk import DAG\nfrom airflow.providers.standard.operators.bash import BashOperator\n\nwith DAG(\n    dag_id="inventory_snapshot",\n    schedule="@once",\n    start_date=datetime(2025, 1, 1),\n) as dag:\n    BashOperator(task_id="snapshot", bash_command="snapshot_inventory --day {{ ds }}")\n',
    ],
    'af-cron-weekdays': [
        'from datetime import datetime\n\nfrom airflow.sdk import DAG\nfrom airflow.providers.standard.operators.bash import BashOperator\n\nwith DAG(\n    dag_id="market_prices",\n    schedule="30 6 * * 0-4",\n    start_date=datetime(2026, 3, 2),\n    catchup=True,\n) as dag:\n    BashOperator(task_id="fetch", bash_command="fetch_prices --ts {{ ts }}")\n',
        'from datetime import datetime\n\nfrom airflow.sdk import DAG\nfrom airflow.providers.standard.operators.bash import BashOperator\n\nwith DAG(\n    dag_id="market_prices",\n    schedule="0 6 * * 1-5",\n    start_date=datetime(2026, 3, 2),\n    catchup=True,\n) as dag:\n    BashOperator(task_id="fetch", bash_command="fetch_prices --ts {{ ts }}")\n',
        'from datetime import datetime\n\nfrom airflow.sdk import DAG\nfrom airflow.providers.standard.operators.bash import BashOperator\n\nwith DAG(\n    dag_id="market_prices",\n    schedule="30 6 * * 1-6",\n    start_date=datetime(2026, 3, 2),\n    catchup=True,\n) as dag:\n    BashOperator(task_id="fetch", bash_command="fetch_prices --ts {{ ts }}")\n',
    ],
    'af-data-interval-timetable': [
        'from datetime import datetime\n\nfrom airflow.sdk import DAG\nfrom airflow.providers.common.sql.operators.sql import SQLExecuteQueryOperator\nfrom airflow.timetables.trigger import CronTriggerTimetable\n\nwith DAG(\n    dag_id="daily_sales_load",\n    schedule=CronTriggerTimetable("0 0 * * *", timezone="UTC"),\n    start_date=datetime(2026, 3, 1),\n    catchup=True,\n) as dag:\n    SQLExecuteQueryOperator(\n        task_id="load_day",\n        conn_id="warehouse",\n        sql=(\n            "INSERT INTO daily_sales SELECT * FROM sales "\n            "WHERE sold_at >= \'{{ data_interval_start | ds }}\' AND sold_at < \'{{ data_interval_end | ds }}\'"\n        ),\n    )\n',
        'from datetime import datetime\n\nfrom airflow.sdk import DAG\nfrom airflow.providers.common.sql.operators.sql import SQLExecuteQueryOperator\nfrom airflow.timetables.interval import CronDataIntervalTimetable\n\nwith DAG(\n    dag_id="daily_sales_load",\n    schedule=CronDataIntervalTimetable("0 0 * * *", timezone="UTC"),\n    start_date=datetime(2026, 3, 1),\n    catchup=True,\n) as dag:\n    SQLExecuteQueryOperator(\n        task_id="load_day",\n        conn_id="warehouse",\n        sql="INSERT INTO daily_sales SELECT * FROM sales WHERE sold_at >= \'{{ ds }}\' AND sold_at < \'{{ ds }}\'",\n    )\n',
    ],
    'af-airflow3-previous-day-partition': [
        'from datetime import datetime\n\nfrom airflow.sdk import DAG\nfrom airflow.providers.standard.operators.bash import BashOperator\n\nwith DAG(\n    dag_id="partition_loader",\n    schedule="@daily",\n    start_date=datetime(2026, 3, 1),\n    catchup=True,\n) as dag:\n    BashOperator(\n        task_id="load_partition",\n        bash_command="load_partition --table events --dt {{ macros.ds_add(ds, 1) }}",\n    )\n',
        'from datetime import datetime\n\nfrom airflow.sdk import DAG\nfrom airflow.providers.standard.operators.bash import BashOperator\n\nwith DAG(\n    dag_id="partition_loader",\n    schedule="@daily",\n    start_date=datetime(2026, 3, 1),\n    catchup=True,\n) as dag:\n    BashOperator(\n        task_id="load_partition",\n        bash_command="load_partition --table events --dt {{ data_interval_start | ds }}",\n    )\n',
    ],
    'af-retries-flaky-api': [
        'from datetime import datetime, timedelta\n\nfrom airflow.sdk import DAG\nfrom airflow.providers.standard.operators.bash import BashOperator\n\nwith DAG(dag_id="exchange_rates", schedule="@daily", start_date=datetime(2026, 3, 5)) as dag:\n    fetch = BashOperator(\n        task_id="fetch_rates",\n        bash_command="fetch_rates --day {{ ds }}",\n        retries=3,\n        retry_delay=timedelta(minutes=10),\n    )\n    publish = BashOperator(task_id="publish_rates", bash_command="publish_rates --day {{ ds }}")\n    fetch >> publish\n',
        'from datetime import datetime, timedelta\n\nfrom airflow.sdk import DAG\nfrom airflow.providers.standard.operators.bash import BashOperator\n\nwith DAG(dag_id="exchange_rates", schedule="@daily", start_date=datetime(2026, 3, 5)) as dag:\n    fetch = BashOperator(\n        task_id="fetch_rates",\n        bash_command="fetch_rates --day {{ ds }}",\n        retries=2,\n    )\n    publish = BashOperator(task_id="publish_rates", bash_command="publish_rates --day {{ ds }}")\n    fetch >> publish\n',
        'from datetime import datetime, timedelta\n\nfrom airflow.sdk import DAG\nfrom airflow.providers.standard.operators.bash import BashOperator\n\nwith DAG(dag_id="exchange_rates", schedule="@daily", start_date=datetime(2026, 3, 5)) as dag:\n    fetch = BashOperator(\n        task_id="fetch_rates",\n        bash_command="fetch_rates --day {{ ds }}",\n        retries=1,\n        retry_delay=timedelta(minutes=10),\n    )\n    publish = BashOperator(task_id="publish_rates", bash_command="publish_rates --day {{ ds }}")\n    fetch >> publish\n',
    ],
    'af-cleanup-trigger-rule': [
        'from datetime import datetime\n\nfrom airflow.sdk import DAG\nfrom airflow.providers.standard.operators.bash import BashOperator\n\nwith DAG(dag_id="staging_refresh", schedule="@daily", start_date=datetime(2026, 3, 5)) as dag:\n    create_tmp = BashOperator(task_id="create_tmp", bash_command="create_tmp_tables")\n    transform = BashOperator(task_id="transform", bash_command="run_transform --day {{ ds }}")\n    drop_tmp = BashOperator(task_id="drop_tmp", bash_command="drop_tmp_tables", trigger_rule="one_success")\n    create_tmp >> transform >> drop_tmp\n',
        'from datetime import datetime\n\nfrom airflow.sdk import DAG\nfrom airflow.providers.standard.operators.bash import BashOperator\n\nwith DAG(dag_id="staging_refresh", schedule="@daily", start_date=datetime(2026, 3, 5)) as dag:\n    create_tmp = BashOperator(task_id="create_tmp", bash_command="create_tmp_tables")\n    transform = BashOperator(task_id="transform", bash_command="run_transform --day {{ ds }}")\n    drop_tmp = BashOperator(task_id="drop_tmp", bash_command="drop_tmp_tables", trigger_rule="none_failed")\n    create_tmp >> transform >> drop_tmp\n',
        'from datetime import datetime\n\nfrom airflow.sdk import DAG\nfrom airflow.providers.standard.operators.bash import BashOperator\n\nwith DAG(dag_id="staging_refresh", schedule="@daily", start_date=datetime(2026, 3, 5)) as dag:\n    create_tmp = BashOperator(task_id="create_tmp", bash_command="create_tmp_tables")\n    transform = BashOperator(task_id="transform", bash_command="run_transform --day {{ ds }}")\n    drop_tmp = BashOperator(task_id="drop_tmp", bash_command="drop_tmp_tables", trigger_rule="one_failed")\n    create_tmp >> transform >> drop_tmp\n',
    ],
    'af-watcher-fails-the-run': [
        'from datetime import datetime\n\nfrom airflow.sdk import DAG, task\nfrom airflow.providers.standard.operators.bash import BashOperator\n\n\n@task\ndef watcher():\n    raise RuntimeError("An upstream task failed; failing the DAG run on purpose.")\n\n\nwith DAG(dag_id="staging_refresh", schedule="@daily", start_date=datetime(2026, 3, 5)) as dag:\n    create_tmp = BashOperator(task_id="create_tmp", bash_command="create_tmp_tables")\n    transform = BashOperator(task_id="transform", bash_command="run_transform --day {{ ds }}")\n    drop_tmp = BashOperator(task_id="drop_tmp", bash_command="drop_tmp_tables", trigger_rule="all_done")\n    create_tmp >> transform >> drop_tmp\n    [create_tmp, transform, drop_tmp] >> watcher.override(trigger_rule="all_failed")()\n',
        'from datetime import datetime\n\nfrom airflow.sdk import DAG, task\nfrom airflow.providers.standard.operators.bash import BashOperator\n\n\n@task\ndef watcher():\n    raise RuntimeError("An upstream task failed; failing the DAG run on purpose.")\n\n\nwith DAG(dag_id="staging_refresh", schedule="@daily", start_date=datetime(2026, 3, 5)) as dag:\n    create_tmp = BashOperator(task_id="create_tmp", bash_command="create_tmp_tables")\n    transform = BashOperator(task_id="transform", bash_command="run_transform --day {{ ds }}")\n    drop_tmp = BashOperator(task_id="drop_tmp", bash_command="drop_tmp_tables", trigger_rule="all_done")\n    create_tmp >> transform >> drop_tmp\n    drop_tmp >> watcher.override(trigger_rule="one_failed")()\n',
        'from datetime import datetime\n\nfrom airflow.sdk import DAG, task\nfrom airflow.providers.standard.operators.bash import BashOperator\n\n\n@task\ndef watcher():\n    raise RuntimeError("An upstream task failed; failing the DAG run on purpose.")\n\n\nwith DAG(dag_id="staging_refresh", schedule="@daily", start_date=datetime(2026, 3, 5)) as dag:\n    create_tmp = BashOperator(task_id="create_tmp", bash_command="create_tmp_tables")\n    transform = BashOperator(task_id="transform", bash_command="run_transform --day {{ ds }}")\n    drop_tmp = BashOperator(task_id="drop_tmp", bash_command="drop_tmp_tables", trigger_rule="all_done")\n    create_tmp >> transform >> drop_tmp\n    [create_tmp, transform, drop_tmp] >> watcher.override(trigger_rule="all_done")()\n',
    ],
    'af-branch-join': [
        'from datetime import datetime\n\nfrom airflow.sdk import DAG\nfrom airflow.providers.standard.operators.bash import BashOperator\nfrom airflow.providers.standard.operators.python import BranchPythonOperator\n\n\ndef choose_load(**context):\n    return "full_load" if context["logical_date"].day == 1 else "incremental_load"\n\n\nwith DAG(dag_id="warehouse_load", schedule="@daily", start_date=datetime(2026, 3, 5)) as dag:\n    choose = BranchPythonOperator(task_id="choose", python_callable=choose_load)\n    full = BashOperator(task_id="full_load", bash_command="load --full")\n    incremental = BashOperator(task_id="incremental_load", bash_command="load --since {{ ds }}")\n    publish = BashOperator(task_id="publish", bash_command="publish_marts", trigger_rule="all_done")\n    choose >> [full, incremental] >> publish\n',
        'from datetime import datetime\n\nfrom airflow.sdk import DAG\nfrom airflow.providers.standard.operators.bash import BashOperator\nfrom airflow.providers.standard.operators.python import BranchPythonOperator\n\n\ndef choose_load(**context):\n    return "full_load" if context["logical_date"].day == 1 else "incremental_load"\n\n\nwith DAG(dag_id="warehouse_load", schedule="@daily", start_date=datetime(2026, 3, 5)) as dag:\n    choose = BranchPythonOperator(task_id="choose", python_callable=choose_load)\n    full = BashOperator(task_id="full_load", bash_command="load --full")\n    incremental = BashOperator(task_id="incremental_load", bash_command="load --since {{ ds }}")\n    publish = BashOperator(task_id="publish", bash_command="publish_marts", trigger_rule="none_failed")\n    choose >> [full, incremental] >> publish\n',
        'from datetime import datetime\n\nfrom airflow.sdk import DAG\nfrom airflow.providers.standard.operators.bash import BashOperator\nfrom airflow.providers.standard.operators.python import BranchPythonOperator\n\n\ndef choose_load(**context):\n    return "full_load" if context["logical_date"].day == 1 else "incremental_load"\n\n\nwith DAG(dag_id="warehouse_load", schedule="@daily", start_date=datetime(2026, 3, 5)) as dag:\n    choose = BranchPythonOperator(task_id="choose", python_callable=choose_load)\n    full = BashOperator(task_id="full_load", bash_command="load --full")\n    incremental = BashOperator(task_id="incremental_load", bash_command="load --since {{ ds }}")\n    publish = BashOperator(task_id="publish", bash_command="publish_marts", trigger_rule="one_success")\n    choose >> [full, incremental] >> publish\n',
    ],
    'af-sensor-soft-fail': [
        'from datetime import datetime, timedelta\n\nfrom airflow.sdk import DAG\nfrom airflow.providers.standard.operators.bash import BashOperator\nfrom airflow.providers.standard.sensors.filesystem import FileSensor\n\nwith DAG(dag_id="partner_feed", schedule="0 6 * * *", start_date=datetime(2026, 3, 5)) as dag:\n    wait = FileSensor(\n        task_id="wait_for_feed",\n        filepath="/data/partner/{{ ds }}.csv",\n        poke_interval=timedelta(minutes=10),\n        timeout=timedelta(hours=2),\n        mode="reschedule",\n    )\n    load = BashOperator(task_id="load_feed", bash_command="load_feed --day {{ ds }}")\n    wait >> load\n',
        'from datetime import datetime, timedelta\n\nfrom airflow.sdk import DAG\nfrom airflow.providers.standard.operators.bash import BashOperator\nfrom airflow.providers.standard.sensors.filesystem import FileSensor\n\nwith DAG(dag_id="partner_feed", schedule="0 6 * * *", start_date=datetime(2026, 3, 5)) as dag:\n    wait = FileSensor(\n        task_id="wait_for_feed",\n        filepath="/data/partner/{{ ds }}.csv",\n        poke_interval=timedelta(minutes=5),\n        timeout=timedelta(hours=2),\n        mode="reschedule",\n        soft_fail=True,\n    )\n    load = BashOperator(task_id="load_feed", bash_command="load_feed --day {{ ds }}")\n    wait >> load\n',
        'from datetime import datetime, timedelta\n\nfrom airflow.sdk import DAG\nfrom airflow.providers.standard.operators.bash import BashOperator\nfrom airflow.providers.standard.sensors.filesystem import FileSensor\n\nwith DAG(dag_id="partner_feed", schedule="0 6 * * *", start_date=datetime(2026, 3, 5)) as dag:\n    wait = FileSensor(\n        task_id="wait_for_feed",\n        filepath="/data/partner/{{ ds }}.csv",\n        poke_interval=timedelta(minutes=10),\n        timeout=timedelta(hours=1),\n        mode="reschedule",\n        soft_fail=True,\n    )\n    load = BashOperator(task_id="load_feed", bash_command="load_feed --day {{ ds }}")\n    wait >> load\n',
    ],
    'af-default-args-override': [
        'from datetime import datetime, timedelta\n\nfrom airflow.sdk import DAG\nfrom airflow.providers.standard.operators.bash import BashOperator\n\nwith DAG(\n    dag_id="billing_export",\n    schedule="@daily",\n    start_date=datetime(2026, 3, 5),\n    default_args={"retries": 0, "retry_delay": timedelta(minutes=1)},\n) as dag:\n    extract = BashOperator(task_id="extract", bash_command="extract --day {{ ds }}")\n    transform = BashOperator(task_id="transform", bash_command="transform --day {{ ds }}")\n    send = BashOperator(task_id="send_invoices", bash_command="send_invoices --day {{ ds }}")\n    extract >> transform >> send\n',
        'from datetime import datetime, timedelta\n\nfrom airflow.sdk import DAG\nfrom airflow.providers.standard.operators.bash import BashOperator\n\nwith DAG(\n    dag_id="billing_export",\n    schedule="@daily",\n    start_date=datetime(2026, 3, 5),\n    default_args={"retries": 1, "retry_delay": timedelta(minutes=1)},\n) as dag:\n    extract = BashOperator(task_id="extract", bash_command="extract --day {{ ds }}")\n    transform = BashOperator(task_id="transform", bash_command="transform --day {{ ds }}")\n    send = BashOperator(task_id="send_invoices", bash_command="send_invoices --day {{ ds }}", retries=0)\n    extract >> transform >> send\n',
    ],
}


def grade(manager, workspace: Path, spec: dict, code: str) -> dict:
    return manager.call("packs", workspace / ".datapass" / "data", {
        "op": "exercise",
        "exercise_id": spec["id"],
        "exercise_version": spec["version"],
        "language": spec["language"],
        "code": code,
        "mode": "submit",
        "notebook_id": "packs-smoke",
        "cell_id": "solution",
        "source_revision": 1,
        "profile": "generic_8x8",
        "aqe": True,
    }, cwd=workspace)


def summary(result: dict) -> str:
    return ", ".join(f"{c['id']}={c['status']}" for c in result.get("checks", [])) or str(result.get("status"))


def main() -> None:
    specs = [spec for spec in definitions() if spec.get("runtime") not in SKIP_RUNTIMES]
    unknown = set(MUTANTS) - {spec["id"] for spec in specs}
    assert not unknown, f"Mutants reference unknown exercises: {sorted(unknown)}"
    failures: list[str] = []
    counts = {"solutions": 0, "starters": 0, "mutants": 0}
    with TemporaryDirectory(prefix="datapass-packs-smoke-") as temp:
        workspace = Path(temp)
        manager = KernelManager(mode="duckdb", trusted=True, timeout=60.0, max_workers=1)
        try:
            for spec in specs:
                reference = solution(spec["id"])["source"]
                result = grade(manager, workspace, spec, reference)
                counts["solutions"] += 1
                if result["status"] != "passed":
                    failures.append(f"{spec['id']}: reference solution {result['status']} ({summary(result)})")
                starter = spec.get("starter_source", "")
                if starter.strip():
                    counts["starters"] += 1
                    graded = grade(manager, workspace, spec, starter)
                    if graded["status"] == "passed":
                        failures.append(f"{spec['id']}: starter already passes")
                    elif spec.get("pack", {}).get("id") in RUNNABLE_STARTER_PACKS and any(
                            check["execution_status"] != "success" for check in graded["checks"]):
                        failures.append(f"{spec['id']}: starter does not execute ({summary(graded)})")
                for index, mutant in enumerate(MUTANTS.get(spec["id"], [])):
                    counts["mutants"] += 1
                    graded = grade(manager, workspace, spec, mutant)
                    if graded["status"] == "passed":
                        failures.append(f"{spec['id']}: mutant #{index} passed; fixtures do not discriminate it")
                    elif any(check["execution_status"] != "success" for check in graded["checks"]):
                        # A mutant must be a runnable wrong answer, not a typo that errors.
                        failures.append(f"{spec['id']}: mutant #{index} does not execute ({summary(graded)})")
        finally:
            manager.close()
    if failures:
        raise SystemExit("Exercise pack smoke failed:\n  " + "\n  ".join(failures))
    print(f"Exercise pack smoke passed: {counts['solutions']} reference solutions, "
          f"{counts['starters']} starters rejected, {counts['mutants']} mutants rejected.")


if __name__ == "__main__":
    main()
