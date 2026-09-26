COPY (SELECT order_id, order_date, amount FROM read_csv('data/orders_april.csv')) TO 'lake/orders_delta/part-april.parquet' (FORMAT parquet);
