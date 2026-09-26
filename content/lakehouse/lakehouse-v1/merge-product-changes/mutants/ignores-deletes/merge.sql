MERGE INTO dim_product AS t
USING read_csv('data/product_changes.csv') AS c
ON t.product_id = c.product_id
WHEN MATCHED AND c.op = 'U' THEN UPDATE SET name = c.name, category = c.category, price = c.price
WHEN NOT MATCHED AND c.op = 'I' THEN INSERT (product_id, name, category, price) VALUES (c.product_id, c.name, c.category, c.price);
