CREATE OR REPLACE TABLE orders AS
SELECT *, CAST(NULL AS VARCHAR) AS channel FROM orders
UNION ALL BY NAME SELECT * FROM read_csv('data/orders_april.csv');
