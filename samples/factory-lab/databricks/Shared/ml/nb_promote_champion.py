# Databricks notebook source
# MAGIC %md
# MAGIC # Promote the new version
# MAGIC Unity Catalog models have no stages: the `champion` alias marks the version to serve.

# COMMAND ----------

from mlflow import MlflowClient

dbutils.widgets.text("version", "1")
version = int(dbutils.widgets.get("version"))
MlflowClient().set_registered_model_alias("main.ml.power_model", "champion", version)
