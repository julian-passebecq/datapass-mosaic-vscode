# Databricks notebook source
# MAGIC %md
# MAGIC # One segment's report
# MAGIC Run once per segment by the `for_each_task` of `segment_reports`: `{{input}}` becomes the
# MAGIC `segment_id` widget.

# COMMAND ----------

from pyspark.sql import functions as F

dbutils.widgets.text("segment_id", "1")
segment_id = int(dbutils.widgets.get("segment_id"))

orders = spark.table("main.silver.orders").filter(F.col("segment_id") == segment_id)
report = orders.groupBy("segment_id").agg(F.count("order_id").alias("orders"), F.sum("net_amount").alias("revenue"))
report.write.mode("overwrite").saveAsTable("main.gold.segment_report_" + str(segment_id))
