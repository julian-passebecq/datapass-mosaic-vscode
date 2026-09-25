# Reference answer: prediction errors per turbine, published to the metrics layer.
import polars as pl

scored = pl.DataFrame(query(
    "SELECT turbine_id, wind_speed, actual_power, prediction FROM gold.turbine_power_scored"
))

summary = (
    scored
    .with_columns((pl.col("actual_power") - pl.col("prediction")).abs().alias("abs_error"))
    .group_by("turbine_id")
    .agg(pl.len().alias("readings"), pl.col("abs_error").max().alias("max_abs_error"))
)
publish("metrics.turbine_residuals", summary)
summary
