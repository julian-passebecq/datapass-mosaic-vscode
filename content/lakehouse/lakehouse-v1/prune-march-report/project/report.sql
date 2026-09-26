-- March 2025 revenue per store, from the partitioned files in lake/sales/.
SELECT store, round(sum(amount), 2) AS revenue
FROM read_parquet('lake/sales/**/*.parquet', hive_partitioning = true)
WHERE strftime(sale_date, '%Y-%m') = '2025-03'
GROUP BY store
ORDER BY store;
