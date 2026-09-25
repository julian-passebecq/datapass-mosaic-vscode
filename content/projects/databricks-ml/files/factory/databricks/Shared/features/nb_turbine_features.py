# Databricks notebook source
# MAGIC %md
# MAGIC # Turbine features
# MAGIC Run by the job `turbine_features` as the service principal `sp-feature-eng`. It reads the raw readings
# MAGIC and writes the features the power model will use. Runs on SparkLab, the Workbench's bounded fake Spark:
# MAGIC results are computed on the local lakehouse, under the lab's Unity Catalog rules.

# COMMAND ----------

from pyspark.sql import functions as F

readings = spark.table("main.source.turbine_readings")

# TODO: keep the readings with a positive wind speed and add two columns:
#   power_per_wind = actual_power / wind_speed
#   wind_band      = "low" under 8 m/s, "medium" under 14 m/s, otherwise "high"
features = readings

features.write.mode("overwrite").saveAsTable("main.silver.turbine_features")

# COMMAND ----------

dbutils.jobs.taskValues.set(key="rows", value=features.count())
