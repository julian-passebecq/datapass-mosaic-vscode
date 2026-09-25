# Projet « Lakehouse Databricks et ML » : contrôler les prédictions avec Polars (Python local de confiance).
# Mosaic > Run active Python. Ce fichier s'exécute comme du VRAI Python local, seulement après avoir activé
# le Python de confiance pour ce workspace. query(sql) lit le catalogue ; publish(nom, table) y écrit.
import polars as pl

scored = pl.DataFrame(query(
    "SELECT turbine_id, wind_speed, actual_power, prediction FROM gold.turbine_power_scored"
))

# TODO : calculez l'erreur absolue (actual_power - prediction), puis par turbine_id :
#   readings      = nombre de mesures
#   max_abs_error = plus grande erreur absolue
# et publiez le résultat dans metrics.turbine_residuals.
summary = scored.group_by("turbine_id").agg(pl.len().alias("readings"))
summary
