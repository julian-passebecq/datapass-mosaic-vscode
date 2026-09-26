INSERT INTO orders_delta SELECT order_id, order_date, amount FROM read_csv('data/orders_april.csv');
INSERT INTO orders_delta SELECT order_id, order_date, amount FROM read_csv('data/orders_april.csv') WHERE order_id > 460;
