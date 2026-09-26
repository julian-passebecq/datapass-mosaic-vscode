-- orders_delta is a Delta table (Parquet files + a _delta_log of JSON commits), attached by the lab as orders_delta.
SELECT count(*) AS orders FROM orders_delta;
SELECT * FROM read_csv('data/orders_april.csv') LIMIT 5;
