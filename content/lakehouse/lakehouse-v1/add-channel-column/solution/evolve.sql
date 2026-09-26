ALTER TABLE orders ADD COLUMN channel VARCHAR;
INSERT INTO orders BY NAME SELECT * FROM read_csv('data/orders_april.csv');
