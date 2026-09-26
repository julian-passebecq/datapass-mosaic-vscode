-- Snapshot 1: the first load. Snapshot 2: five new customers. Snapshot 3: the bad UPDATE (every country became FR).
CREATE TABLE customers AS
SELECT i + 1 AS customer_id, 'Customer ' || (i + 1) AS name, 'c' || (i + 1) || '@example.com' AS email,
       ['FR', 'DE', 'BE', 'NL', 'ES'][1 + (i % 5)] AS country
FROM range(20) t(i);
INSERT INTO customers
SELECT i + 21, 'Customer ' || (i + 21), 'c' || (i + 21) || '@example.com', ['IT', 'FR', 'DE', 'PT', 'FR'][1 + (i % 5)]
FROM range(5) t(i);
UPDATE customers SET country = 'FR';
