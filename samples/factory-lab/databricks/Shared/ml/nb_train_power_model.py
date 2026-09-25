# Databricks notebook source
# MAGIC %md
# MAGIC # Train the turbine power model
# MAGIC Linear regression of `actual_power` on `wind_speed`, tracked with MLflow and registered in
# MAGIC Unity Catalog as `main.ml.power_model`. Runs on the lab's bounded Spark ML (real least squares
# MAGIC on the lab rows); the job runs it as the service principal `sp-ml-training`.

# COMMAND ----------

import mlflow
from pyspark.ml.feature import VectorAssembler
from pyspark.ml.regression import LinearRegression
from pyspark.ml.evaluation import RegressionEvaluator

mlflow.set_registry_uri("databricks-uc")
mlflow.set_experiment("/Shared/power-forecast")

readings = spark.table("main.source.turbine_readings")
train, test = readings.randomSplit([0.8, 0.2], seed=42)
assembler = VectorAssembler(inputCols=["wind_speed"], outputCol="features")
lr = LinearRegression(featuresCol="features", labelCol="actual_power")

# COMMAND ----------

with mlflow.start_run(run_name="linear-wind-speed") as run:
    model = lr.fit(assembler.transform(train))
    predictions = model.transform(assembler.transform(test))
    rmse = RegressionEvaluator(labelCol="actual_power", predictionCol="prediction", metricName="rmse").evaluate(predictions)
    mlflow.log_param("features", "wind_speed")
    mlflow.log_metric("rmse", rmse)
    info = mlflow.spark.log_model(model, "model", input_example=test.select("wind_speed"),
                                  registered_model_name="main.ml.power_model")

# COMMAND ----------

dbutils.jobs.taskValues.set(key="rmse", value=rmse)
dbutils.jobs.taskValues.set(key="model_version", value=info.registered_model_version)
