# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   }
# META }

# MARKDOWN ********************

# # Silver orders
# Called by the pipeline `pl_retail_daily` (Notebook activity). The pipeline passes
# `run_date` and `min_amount`; they replace the defaults of the parameters cell below.
# Runs on SparkLab, the Workbench's bounded fake Spark: results are computed on the local lakehouse.

# PARAMETERS CELL ********************

run_date = "2026-01-01"
min_amount = 0

# CELL ********************

from pyspark.sql import functions as F

orders = spark.table("bronze.orders")
silver = (
    orders
    .filter(F.col("net_amount") > min_amount)
    .dropDuplicates(["order_id"])
    .withColumn("load_date", F.lit(run_date))
)
silver.write.mode("overwrite").format("delta").saveAsTable("silver.orders")

# CELL ********************

# The exit value reaches the pipeline as text: @activity('Silver orders').output.result.exitValue
notebookutils.notebook.exit(str(silver.count()))
