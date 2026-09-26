UPDATE dim_product t SET name = c.name, category = c.category, price = c.price
FROM read_csv('data/product_changes.csv') c WHERE c.product_id = t.product_id AND c.op = 'U';
DELETE FROM dim_product WHERE product_id IN (SELECT product_id FROM read_csv('data/product_changes.csv') WHERE op = 'D');
INSERT INTO dim_product SELECT product_id, name, category, price FROM read_csv('data/product_changes.csv') WHERE op = 'I';
