COPY (SELECT *, year(sale_date) AS year FROM read_csv('data/sales.csv')) TO 'lake/sales' (FORMAT parquet, PARTITION_BY (year));
