# Retail dbt sample

A small dbt project for the Datapass dbt Lab: two seeds (`raw_customers`, `raw_orders`), a staging view, two marts and
tests. It runs with real dbt Core and dbt-duckdb on the local catalog.

In the dbt Lab: **Install dbt tools** once, pick this project, then run `dbt build` in its terminal. The lab generates
the `datapass_retail` profile in `.datapass/dbt/profiles.yml` (a local DuckDB file, no secrets) and lends the catalog
file to dbt while the command runs. Review SQL, macros and hooks before running a project you did not write: dbt runs
them as your user.

`charts/revenue.yml` and `dbt_charts.yml` describe a dbt Charts board on `fct_sales`.
