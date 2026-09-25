-- Date dimension: one row per calendar day of 2026, with a "smart" integer key (yyyymmdd) and the attributes
-- reports slice by. The -1 row is the unknown date: facts point to it when a date is missing (an order that is
-- not shipped yet), so no fact row ever has a NULL key. The fiscal year starts on 1 July.
CREATE OR REPLACE TABLE gold.dim_date AS
SELECT CAST(strftime(d, '%Y%m%d') AS INTEGER) AS date_key,
       CAST(d AS DATE) AS full_date,
       year(d) AS calendar_year,
       quarter(d) AS calendar_quarter,
       month(d) AS month_number,
       monthname(d) AS month_name,
       strftime(d, '%Y-%m') AS year_month,
       isodow(d) AS day_of_week,
       dayname(d) AS day_name,
       isodow(d) >= 6 AS is_weekend,
       CASE WHEN month(d) >= 7 THEN year(d) + 1 ELSE year(d) END AS fiscal_year
FROM generate_series(TIMESTAMP '2026-01-01', TIMESTAMP '2026-12-31', INTERVAL 1 DAY) AS days(d)
UNION ALL
SELECT -1, NULL, NULL, NULL, NULL, 'Unknown', 'Unknown', NULL, 'Unknown', NULL, NULL;
