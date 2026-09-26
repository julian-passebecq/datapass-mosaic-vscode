-- Snapshot 1: the product dimension. The supplier's change file: inserts, updates and deletes.
CREATE TABLE dim_product AS
SELECT i + 1 AS product_id, 'Product ' || (i + 1) AS name, ['toys', 'garden', 'kitchen'][1 + (i % 3)] AS category,
       ROUND(5 + ((i * 17) % 200) / 4.0, 2) AS price
FROM range(30) t(i);
COPY (
  SELECT * FROM (VALUES
    ('U', 3, 'Product 3', 'kitchen', 12.5),
    ('U', 7, 'Product 7 XL', 'garden', 44.0),
    ('D', 11, NULL, NULL, NULL),
    ('I', 31, 'Product 31', 'toys', 9.99),
    ('I', 32, 'Product 32', 'garden', 19.99),
    ('D', 20, NULL, NULL, NULL),
    ('U', 25, 'Product 25', 'toys', 30.0)
  ) v(op, product_id, name, category, price)
) TO 'data/product_changes.csv' (HEADER);
