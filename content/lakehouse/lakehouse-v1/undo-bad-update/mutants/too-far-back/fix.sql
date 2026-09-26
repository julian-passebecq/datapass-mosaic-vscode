BEGIN;
DELETE FROM customers;
INSERT INTO customers SELECT * FROM customers AT (VERSION => 1);
COMMIT;
