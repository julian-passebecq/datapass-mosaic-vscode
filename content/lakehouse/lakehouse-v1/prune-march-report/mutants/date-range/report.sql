SELECT store, round(sum(amount), 2) AS revenue
FROM read_parquet('lake/sales/**/*.parquet', hive_partitioning = true)
WHERE sale_date BETWEEN DATE '2025-03-01' AND DATE '2025-03-31'
GROUP BY store;
