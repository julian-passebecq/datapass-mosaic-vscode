BEGIN;
DELETE FROM customers;
INSERT INTO customers SELECT * FROM customers AT (VERSION => 2);
COMMIT;
