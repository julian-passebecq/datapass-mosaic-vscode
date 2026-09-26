-- A streaming job wrote one small file per partition every micro-batch: 7 days x 30 batches = 210 files.
CREATE TEMP TABLE ev AS
SELECT i + 1 AS event_id,
       DATE '2025-04-01' + CAST(i % 7 AS INTEGER) AS event_date,
       'user-' || ((i * 13) % 200) AS user_id,
       ['view', 'click', 'buy'][1 + (i % 3)] AS action,
       CAST((i * 31) % 1000 AS INTEGER) AS value_cents,
       (i // 7) % 30 AS batch
FROM range(4200) t(i);
COPY (SELECT * EXCLUDE (batch) FROM ev WHERE batch = 0) TO 'lake/events' (FORMAT parquet, PARTITION_BY (event_date), APPEND, FILENAME_PATTERN 'part-{uuid}');
COPY (SELECT * EXCLUDE (batch) FROM ev WHERE batch = 1) TO 'lake/events' (FORMAT parquet, PARTITION_BY (event_date), APPEND, FILENAME_PATTERN 'part-{uuid}');
COPY (SELECT * EXCLUDE (batch) FROM ev WHERE batch = 2) TO 'lake/events' (FORMAT parquet, PARTITION_BY (event_date), APPEND, FILENAME_PATTERN 'part-{uuid}');
COPY (SELECT * EXCLUDE (batch) FROM ev WHERE batch = 3) TO 'lake/events' (FORMAT parquet, PARTITION_BY (event_date), APPEND, FILENAME_PATTERN 'part-{uuid}');
COPY (SELECT * EXCLUDE (batch) FROM ev WHERE batch = 4) TO 'lake/events' (FORMAT parquet, PARTITION_BY (event_date), APPEND, FILENAME_PATTERN 'part-{uuid}');
COPY (SELECT * EXCLUDE (batch) FROM ev WHERE batch = 5) TO 'lake/events' (FORMAT parquet, PARTITION_BY (event_date), APPEND, FILENAME_PATTERN 'part-{uuid}');
COPY (SELECT * EXCLUDE (batch) FROM ev WHERE batch = 6) TO 'lake/events' (FORMAT parquet, PARTITION_BY (event_date), APPEND, FILENAME_PATTERN 'part-{uuid}');
COPY (SELECT * EXCLUDE (batch) FROM ev WHERE batch = 7) TO 'lake/events' (FORMAT parquet, PARTITION_BY (event_date), APPEND, FILENAME_PATTERN 'part-{uuid}');
COPY (SELECT * EXCLUDE (batch) FROM ev WHERE batch = 8) TO 'lake/events' (FORMAT parquet, PARTITION_BY (event_date), APPEND, FILENAME_PATTERN 'part-{uuid}');
COPY (SELECT * EXCLUDE (batch) FROM ev WHERE batch = 9) TO 'lake/events' (FORMAT parquet, PARTITION_BY (event_date), APPEND, FILENAME_PATTERN 'part-{uuid}');
COPY (SELECT * EXCLUDE (batch) FROM ev WHERE batch = 10) TO 'lake/events' (FORMAT parquet, PARTITION_BY (event_date), APPEND, FILENAME_PATTERN 'part-{uuid}');
COPY (SELECT * EXCLUDE (batch) FROM ev WHERE batch = 11) TO 'lake/events' (FORMAT parquet, PARTITION_BY (event_date), APPEND, FILENAME_PATTERN 'part-{uuid}');
COPY (SELECT * EXCLUDE (batch) FROM ev WHERE batch = 12) TO 'lake/events' (FORMAT parquet, PARTITION_BY (event_date), APPEND, FILENAME_PATTERN 'part-{uuid}');
COPY (SELECT * EXCLUDE (batch) FROM ev WHERE batch = 13) TO 'lake/events' (FORMAT parquet, PARTITION_BY (event_date), APPEND, FILENAME_PATTERN 'part-{uuid}');
COPY (SELECT * EXCLUDE (batch) FROM ev WHERE batch = 14) TO 'lake/events' (FORMAT parquet, PARTITION_BY (event_date), APPEND, FILENAME_PATTERN 'part-{uuid}');
COPY (SELECT * EXCLUDE (batch) FROM ev WHERE batch = 15) TO 'lake/events' (FORMAT parquet, PARTITION_BY (event_date), APPEND, FILENAME_PATTERN 'part-{uuid}');
COPY (SELECT * EXCLUDE (batch) FROM ev WHERE batch = 16) TO 'lake/events' (FORMAT parquet, PARTITION_BY (event_date), APPEND, FILENAME_PATTERN 'part-{uuid}');
COPY (SELECT * EXCLUDE (batch) FROM ev WHERE batch = 17) TO 'lake/events' (FORMAT parquet, PARTITION_BY (event_date), APPEND, FILENAME_PATTERN 'part-{uuid}');
COPY (SELECT * EXCLUDE (batch) FROM ev WHERE batch = 18) TO 'lake/events' (FORMAT parquet, PARTITION_BY (event_date), APPEND, FILENAME_PATTERN 'part-{uuid}');
COPY (SELECT * EXCLUDE (batch) FROM ev WHERE batch = 19) TO 'lake/events' (FORMAT parquet, PARTITION_BY (event_date), APPEND, FILENAME_PATTERN 'part-{uuid}');
COPY (SELECT * EXCLUDE (batch) FROM ev WHERE batch = 20) TO 'lake/events' (FORMAT parquet, PARTITION_BY (event_date), APPEND, FILENAME_PATTERN 'part-{uuid}');
COPY (SELECT * EXCLUDE (batch) FROM ev WHERE batch = 21) TO 'lake/events' (FORMAT parquet, PARTITION_BY (event_date), APPEND, FILENAME_PATTERN 'part-{uuid}');
COPY (SELECT * EXCLUDE (batch) FROM ev WHERE batch = 22) TO 'lake/events' (FORMAT parquet, PARTITION_BY (event_date), APPEND, FILENAME_PATTERN 'part-{uuid}');
COPY (SELECT * EXCLUDE (batch) FROM ev WHERE batch = 23) TO 'lake/events' (FORMAT parquet, PARTITION_BY (event_date), APPEND, FILENAME_PATTERN 'part-{uuid}');
COPY (SELECT * EXCLUDE (batch) FROM ev WHERE batch = 24) TO 'lake/events' (FORMAT parquet, PARTITION_BY (event_date), APPEND, FILENAME_PATTERN 'part-{uuid}');
COPY (SELECT * EXCLUDE (batch) FROM ev WHERE batch = 25) TO 'lake/events' (FORMAT parquet, PARTITION_BY (event_date), APPEND, FILENAME_PATTERN 'part-{uuid}');
COPY (SELECT * EXCLUDE (batch) FROM ev WHERE batch = 26) TO 'lake/events' (FORMAT parquet, PARTITION_BY (event_date), APPEND, FILENAME_PATTERN 'part-{uuid}');
COPY (SELECT * EXCLUDE (batch) FROM ev WHERE batch = 27) TO 'lake/events' (FORMAT parquet, PARTITION_BY (event_date), APPEND, FILENAME_PATTERN 'part-{uuid}');
COPY (SELECT * EXCLUDE (batch) FROM ev WHERE batch = 28) TO 'lake/events' (FORMAT parquet, PARTITION_BY (event_date), APPEND, FILENAME_PATTERN 'part-{uuid}');
COPY (SELECT * EXCLUDE (batch) FROM ev WHERE batch = 29) TO 'lake/events' (FORMAT parquet, PARTITION_BY (event_date), APPEND, FILENAME_PATTERN 'part-{uuid}');
