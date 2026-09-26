COPY (SELECT * FROM read_parquet('lake/events/**/*.parquet', hive_partitioning = true) WHERE event_date < DATE '2025-04-07')
TO 'lake/events_compacted' (FORMAT parquet, PARTITION_BY (event_date));
