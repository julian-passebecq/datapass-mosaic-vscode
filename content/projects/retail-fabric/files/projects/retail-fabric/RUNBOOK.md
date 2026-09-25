# Runbook: daily retail load

Complete this runbook for the on-call team. Answer each question in a few lines.

## Schedule

- When does the `retail_daily_load` DAG start, and what does it do if the web file does not arrive?
- How many times is the Fabric pipeline trigger retried, and how far apart?

## Fabric pipeline `pl_retail_daily`

- Which activity fails when `silver.orders` is empty, and who is told when the notebook fails?
- Is it safe to run the pipeline again the same day? Why (or why not)?

## Data quality

- Which checks protect `silver.web_orders` (Pipeline Lab), and what happens when they find rows?

## Warehouse

- How do you find a customer's city at the time of a past sale (type 2 SCD)?
