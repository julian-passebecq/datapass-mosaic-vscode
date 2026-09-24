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
                    if grade(manager, workspace, spec, starter)["status"] == "passed":
                        failures.append(f"{spec['id']}: starter already passes")
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
