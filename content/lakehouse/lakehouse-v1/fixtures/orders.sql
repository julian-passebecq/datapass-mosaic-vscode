-- Snapshot 1: March orders. The April export has a new column, channel.
CREATE TABLE orders AS
SELECT i + 1 AS order_id, DATE '2025-03-01' + CAST(i % 31 AS INTEGER) AS order_date,
       ROUND(10 + ((i * 37) % 900) / 10.0, 2) AS amount
FROM range(300) t(i);
COPY (
  SELECT i + 301 AS order_id, DATE '2025-04-01' + CAST(i % 30 AS INTEGER) AS order_date,
         ROUND(10 + ((i * 53) % 900) / 10.0, 2) AS amount, ['web', 'store', 'app'][1 + (i % 3)] AS channel
  FROM range(240) t(i)
) TO 'data/orders_april.csv' (HEADER);
