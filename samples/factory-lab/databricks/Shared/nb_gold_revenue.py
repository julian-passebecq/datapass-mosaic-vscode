# Databricks notebook source
# MAGIC %md
# MAGIC # Gold revenue by segment
# MAGIC Joins silver orders to the segment dimension and writes `main.gold.revenue_by_segment`.

# COMMAND ----------

from pyspark.sql import functions as F

silver = spark.table("main.silver.orders")
segments = spark.table("main.source.dim_customer_segment")
gold = (
    silver.join(segments, "segment_id")
    .groupBy("segment_name")
    .agg(F.count("order_id").alias("orders"), F.sum("net_amount").alias("revenue"))
)
gold.write.mode("overwrite").saveAsTable("main.gold.revenue_by_segment")

# COMMAND ----------

dbutils.jobs.taskValues.set(key="segments", value=gold.count())
