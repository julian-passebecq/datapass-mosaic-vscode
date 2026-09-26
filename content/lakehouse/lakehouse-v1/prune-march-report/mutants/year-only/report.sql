SELECT store, round(sum(amount), 2) AS revenue
FROM read_parquet('lake/sales/**/*.parquet', hive_partitioning = true)
WHERE year = 2025 AND month(sale_date) = 3
GROUP BY store;
