-- The Delta table's data files (its _delta_log ships with the mission: two commits of March orders).
COPY (SELECT i + 1 AS order_id, DATE '2025-03-01' + CAST(i % 15 AS INTEGER) AS order_date,
             ROUND(10 + ((i * 37) % 900) / 10.0, 2) AS amount FROM range(150) t(i))
TO 'lake/orders_delta/part-00000.parquet' (FORMAT parquet);
COPY (SELECT i + 151 AS order_id, DATE '2025-03-16' + CAST(i % 16 AS INTEGER) AS order_date,
             ROUND(10 + ((i * 41) % 900) / 10.0, 2) AS amount FROM range(120) t(i))
TO 'lake/orders_delta/part-00001.parquet' (FORMAT parquet);
COPY (SELECT i + 271 AS order_id, DATE '2025-04-01' + CAST(i % 30 AS INTEGER) AS order_date,
             ROUND(10 + ((i * 53) % 900) / 10.0, 2) AS amount FROM range(200) t(i))
TO 'data/orders_april.csv' (HEADER);
