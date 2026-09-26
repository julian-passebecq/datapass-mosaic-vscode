-- orders is a DuckLake table (the lake is attached as `lake`). The April export has one more column:
DESCRIBE orders;
SELECT * FROM read_csv('data/orders_april.csv') LIMIT 5;
