# Polars (trusted local Python): compact lake/events/ into lake/events_compacted/, one file per event_date.
import polars as pl

events = pl.scan_parquet("lake/events/**/*.parquet", hive_partitioning=True)
print(events.group_by("event_date").len().sort("event_date").collect())
