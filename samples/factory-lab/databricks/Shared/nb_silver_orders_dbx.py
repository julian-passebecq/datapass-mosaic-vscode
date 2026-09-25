# Databricks notebook source
# MAGIC %md
# MAGIC # Silver orders (Azure Databricks)
# MAGIC Called by the Azure Data Factory pipeline `pl_retail_daily_adf` (Azure Databricks notebook activity).
# MAGIC Parameters arrive as widgets (`baseParameters`), always as text. The value passed to
# MAGIC `dbutils.notebook.exit` becomes `@activity('Silver orders').output.runOutput`.
# MAGIC Runs on SparkLab, the Workbench's bounded fake Spark: nothing connects to Databricks.

# COMMAND ----------

dbutils.widgets.text("run_date", "2026-01-01")
dbutils.widgets.text("min_amount", "0")
run_date = dbutils.widgets.get("run_date")
min_amount = int(dbutils.widgets.get("min_amount"))

# COMMAND ----------

from pyspark.sql import functions as F

orders = spark.table("bronze.orders")
silver = (
    orders
    .filter(F.col("net_amount") > min_amount)
    .dropDuplicates(["order_id"])
    .withColumn("load_date", F.lit(run_date))
)
silver.write.mode("overwrite").saveAsTable("silver.orders")

# COMMAND ----------

dbutils.notebook.exit(str(silver.count()))
