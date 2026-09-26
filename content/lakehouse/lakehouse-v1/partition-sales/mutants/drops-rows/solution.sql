COPY (SELECT *, year(sale_date) AS year, month(sale_date) AS month FROM read_csv('data/sales.csv') WHERE amount > 10)
TO 'lake/sales' (FORMAT parquet, PARTITION_BY (year, month));
