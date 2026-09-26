-- 3,000 sales from November 2024 to April 2025 (deterministic).
COPY (
  SELECT i + 1 AS sale_id,
         DATE '2024-11-01' + CAST((i * 37) % 181 AS INTEGER) AS sale_date,
         ['north', 'south', 'east', 'west'][1 + (i % 4)] AS store,
         ROUND(5 + ((i * 7919) % 20000) / 100.0, 2) AS amount
  FROM range(3000) t(i)
) TO 'data/sales.csv' (HEADER);
