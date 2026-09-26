COPY (SELECT * FROM read_csv('data/sales.csv')) TO 'lake/sales' (FORMAT parquet, PARTITION_BY (sale_date));
