# Databricks notebook source
# MAGIC %md
# MAGIC # Failure alert
# MAGIC Runs only when an upstream task failed (`run_if: AT_LEAST_ONE_FAILED`). A real job would call a
# MAGIC webhook or rely on job notifications; the lab records the message as a task value.

# COMMAND ----------

run_date = dbutils.widgets.get("run_date")
dbutils.jobs.taskValues.set(key="alert", value="retail_daily_dbx failed for " + run_date)
