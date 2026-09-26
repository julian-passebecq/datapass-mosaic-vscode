COPY (SELECT * FROM read_parquet('lake/events/**/*.parquet', hive_partitioning = true))
TO 'lake/events_compacted' (FORMAT parquet, PARTITION_BY (event_date));
