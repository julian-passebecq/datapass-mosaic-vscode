BEGIN;
DELETE FROM dim_product
WHERE product_id IN (SELECT product_id FROM read_csv('data/product_changes.csv') WHERE op = 'D');
MERGE INTO dim_product AS t
USING (SELECT * FROM read_csv('data/product_changes.csv') WHERE op IN ('I', 'U')) AS c
ON t.product_id = c.product_id
WHEN MATCHED THEN UPDATE SET name = c.name, category = c.category, price = c.price
WHEN NOT MATCHED THEN INSERT (product_id, name, category, price) VALUES (c.product_id, c.name, c.category, c.price);
COMMIT;
