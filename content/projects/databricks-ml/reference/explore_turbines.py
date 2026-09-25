# Reference answer: readings and average power by wind band.
from pyspark.sql import functions as F

readings = spark.table("source.turbine_readings")

bands = (
    readings
    .withColumn("wind_band", F.when(F.col("wind_speed") < 8, "low").when(F.col("wind_speed") < 14, "medium").otherwise("high"))
    .groupBy("wind_band")
    .agg(F.count("sample_id").alias("readings"), F.avg("actual_power").alias("avg_power"))
)
