# Databricks notebook source
# MAGIC %md
# MAGIC # Ingest orders (bronze)
# MAGIC First task of the `retail_daily_dbx` job. Tables use Unity Catalog three-level names:
# MAGIC `main.source.orders` is the lab table `source.orders`. The number of rows is passed to the next
# MAGIC tasks as a task value (`{{tasks.ingest_orders.values.new_rows}}`).

# COMMAND ----------

orders = spark.table("main.source.orders")
orders.write.mode("overwrite").saveAsTable("main.bronze.orders")

# COMMAND ----------

new_rows = orders.count()
dbutils.jobs.taskValues.set(key="new_rows", value=new_rows)
dbutils.notebook.exit(str(new_rows))
