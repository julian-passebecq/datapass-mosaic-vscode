ALTER TABLE orders ADD COLUMN channel VARCHAR;
INSERT INTO orders (order_id, order_date, amount) SELECT order_id, order_date, amount FROM read_csv('data/orders_april.csv');
