# Projet « Lakehouse Databricks et ML » : explorer les mesures des éoliennes dans SparkLab.
# SparkLab > Run active SparkLab file. Analysé par une liste blanche (AST) et compilé en SQL local :
# jamais exécuté comme du Python. Les étapes, le shuffle et les coûts sont simulés.
from pyspark.sql import functions as F

readings = spark.table("source.turbine_readings")

# TODO : ajoutez une colonne wind_band : "low" sous 8 m/s, "medium" sous 14 m/s, sinon "high",
# puis agrégez par wind_band :
#   readings  = nombre de mesures (sample_id)
#   avg_power = puissance moyenne (actual_power)
bands = readings.groupBy("turbine_id").agg(F.count("sample_id").alias("readings"))
