# Databricks notebook source
# MAGIC %md
# MAGIC # Turbine features (reference answer)

# COMMAND ----------

from pyspark.sql import functions as F

readings = spark.table("main.source.turbine_readings")

features = (
    readings
    .filter(F.col("wind_speed") > 0)
    .withColumn("power_per_wind", F.col("actual_power") / F.col("wind_speed"))
    .withColumn("wind_band", F.when(F.col("wind_speed") < 8, "low").when(F.col("wind_speed") < 14, "medium").otherwise("high"))
)

features.write.mode("overwrite").saveAsTable("main.silver.turbine_features")

# COMMAND ----------

dbutils.jobs.taskValues.set(key="rows", value=features.count())
