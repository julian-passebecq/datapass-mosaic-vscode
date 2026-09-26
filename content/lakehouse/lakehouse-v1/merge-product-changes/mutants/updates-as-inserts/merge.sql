BEGIN;
DELETE FROM dim_product WHERE product_id IN (SELECT product_id FROM read_csv('data/product_changes.csv') WHERE op = 'D');
INSERT INTO dim_product SELECT product_id, name, category, price FROM read_csv('data/product_changes.csv') WHERE op IN ('I', 'U');
COMMIT;
