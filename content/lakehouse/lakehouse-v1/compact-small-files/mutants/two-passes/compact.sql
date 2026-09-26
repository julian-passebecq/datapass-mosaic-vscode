COPY (SELECT * FROM read_parquet('lake/events/**/*.parquet', hive_partitioning = true) WHERE action = 'buy')
TO 'lake/events_compacted' (FORMAT parquet, PARTITION_BY (event_date));
COPY (SELECT * FROM read_parquet('lake/events/**/*.parquet', hive_partitioning = true) WHERE action <> 'buy')
TO 'lake/events_compacted' (FORMAT parquet, PARTITION_BY (event_date), APPEND);
