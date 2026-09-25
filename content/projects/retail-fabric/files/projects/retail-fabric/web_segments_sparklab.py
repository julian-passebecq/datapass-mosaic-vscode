# Projet « Retail de bout en bout » : prototype SparkLab.
# SparkLab > Run active SparkLab file. Ce fichier est analysé par une liste blanche (AST) et compilé
# en SQL local : il n'est jamais exécuté comme du Python. Les étapes, le shuffle et les coûts sont simulés.
#
# But : le chiffre d'affaires web par segment, avec la petite dimension des segments diffusée (broadcast)
# pour éviter de redistribuer les commandes.
from pyspark.sql import functions as F

web = spark.table("silver.web_orders")
segments = spark.table("source.dim_customer_segment")

# TODO : joignez les segments (en broadcast) sur segment_id, puis agrégez par segment_name :
#   orders  = nombre de commandes (order_id)
#   revenue = somme de net_amount
by_segment = web.groupBy("segment_id").agg(F.count("order_id").alias("orders"))
