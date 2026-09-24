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
