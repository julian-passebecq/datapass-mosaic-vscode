# Project "Databricks lakehouse and ML": explore the wind turbine readings in SparkLab.
# SparkLab > Run active SparkLab file. Parsed by a whitelist (AST) and compiled to local SQL:
# never executed as Python. Stages, shuffle and costs are simulated.
from pyspark.sql import functions as F

readings = spark.table("source.turbine_readings")

# TODO: add a wind_band column: "low" under 8 m/s, "medium" under 14 m/s, otherwise "high",
# then aggregate by wind_band:
#   readings  = number of readings (sample_id)
#   avg_power = average power (actual_power)
bands = readings.groupBy("turbine_id").agg(F.count("sample_id").alias("readings"))
