-- Runs as a SQL task on a SQL warehouse. :min_segments is a task parameter (a named parameter marker).
SELECT COUNT(*) AS segments,
       SUM(revenue) AS revenue,
       COUNT(*) >= CAST(:min_segments AS INTEGER) AS enough_segments
FROM main.gold.revenue_by_segment;
