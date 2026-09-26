-- Compact lake/events/ (210 small files) into lake/events_compacted/: one Parquet file per event_date.
SELECT event_date, count(*) AS events
FROM read_parquet('lake/events/**/*.parquet', hive_partitioning = true)
GROUP BY event_date ORDER BY event_date;
