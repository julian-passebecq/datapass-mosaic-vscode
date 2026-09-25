# Databricks notebook source
# MAGIC %md
# MAGIC # Batch scoring with the champion
# MAGIC Loads whichever version holds the `champion` alias, so promoting a new version needs no code change.

# COMMAND ----------

import mlflow

model = mlflow.spark.load_model("models:/main.ml.power_model@champion")
readings = spark.table("main.source.turbine_readings")
scored = model.transform(readings).select("sample_id", "turbine_id", "wind_speed", "actual_power", "prediction")
scored.write.mode("overwrite").saveAsTable("main.gold.turbine_power_scored")
