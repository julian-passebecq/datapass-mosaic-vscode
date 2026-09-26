SELECT store, round(sum(amount), 2) AS revenue
FROM read_parquet('lake/sales/**/*.parquet', hive_partitioning = true)
WHERE year = 2025 AND month = 4
GROUP BY store;
