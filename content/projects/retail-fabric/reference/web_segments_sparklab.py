# Reference answer: web revenue by segment, the segments broadcast to every executor.
from pyspark.sql import functions as F

web = spark.table("silver.web_orders")
segments = spark.table("source.dim_customer_segment")

by_segment = (
    web.join(F.broadcast(segments), "segment_id")
    .groupBy("segment_name")
    .agg(F.count("order_id").alias("orders"), F.sum("net_amount").alias("revenue"))
)
