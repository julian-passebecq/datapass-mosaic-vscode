import polars as pl

(pl.scan_parquet("lake/events/**/*.parquet", hive_partitioning=True)
 .collect()
 .unique(subset=["user_id", "event_date"])
 .write_parquet("lake/events_compacted", partition_by="event_date"))
