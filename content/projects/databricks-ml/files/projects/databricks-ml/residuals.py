# Project "Databricks lakehouse and ML": check the predictions with Polars (trusted local Python).
# Mosaic > Run active Python. This file runs as REAL local Python, only after you enable trusted
# Python for this workspace. query(sql) reads the catalog; publish(name, table) writes to it.
import polars as pl

scored = pl.DataFrame(query(
    "SELECT turbine_id, wind_speed, actual_power, prediction FROM gold.turbine_power_scored"
))

# TODO: compute the absolute error (actual_power - prediction), then per turbine_id:
#   readings      = number of readings
#   max_abs_error = largest absolute error
# and publish the result to metrics.turbine_residuals.
summary = scored.group_by("turbine_id").agg(pl.len().alias("readings"))
summary
