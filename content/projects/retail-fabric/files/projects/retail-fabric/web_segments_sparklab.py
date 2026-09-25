# Project "Retail end to end": SparkLab prototype.
# SparkLab > Run active SparkLab file. This file is parsed by a whitelist (AST) and compiled to local
# SQL: it is never executed as Python. Stages, shuffle and costs are simulated.
#
# Goal: web revenue by segment, with the small segment dimension broadcast so that the orders are
# not redistributed.
from pyspark.sql import functions as F

web = spark.table("silver.web_orders")
segments = spark.table("source.dim_customer_segment")

# TODO: join the segments (broadcast) on segment_id, then aggregate by segment_name:
#   orders  = number of orders (order_id)
#   revenue = sum of net_amount
by_segment = web.groupBy("segment_id").agg(F.count("order_id").alias("orders"))
