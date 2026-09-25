-- flavor: synapse
-- Cloud Lab > SQL pool: monthly partitions, partition elimination and loading a month with a partition switch.

-- One partition per month of 2026. RANGE RIGHT: each boundary is the first day of its month.
IF OBJECT_ID('dbo.fact_sales_2026') IS NOT NULL DROP TABLE dbo.fact_sales_2026;

CREATE TABLE dbo.fact_sales_2026
WITH
(   DISTRIBUTION = HASH(order_id)
,   CLUSTERED COLUMNSTORE INDEX
,   PARTITION ( order_date RANGE RIGHT FOR VALUES
        ( '2026-02-01', '2026-03-01', '2026-04-01', '2026-05-01', '2026-06-01', '2026-07-01'
        , '2026-08-01', '2026-09-01', '2026-10-01', '2026-11-01', '2026-12-01' ) )
)
AS
SELECT order_id, customer_id, segment_id, net_amount,
       -- Spread the sample orders over the year: order O-00n is placed 25 * n days after January 1st.
       CAST(DATEADD(day, 25 * CAST(RIGHT(order_id, 3) AS INT), '2026-01-01') AS DATE) AS order_date
FROM source.orders;

-- Scans all 12 partitions: the partition column is hidden inside functions.
SELECT COUNT(*) AS orders, SUM(net_amount) AS revenue
FROM dbo.fact_sales_2026
WHERE YEAR(order_date) = 2026 AND MONTH(order_date) = 3;

-- Scans one partition: the partition column itself is compared with constants.
SELECT COUNT(*) AS orders, SUM(net_amount) AS revenue
FROM dbo.fact_sales_2026
WHERE order_date >= '2026-03-01' AND order_date < '2026-04-01';

-- Load December: stage it in a table with exactly the same design, then switch the partition in.
IF OBJECT_ID('dbo.fact_sales_2026_stage') IS NOT NULL DROP TABLE dbo.fact_sales_2026_stage;

CREATE TABLE dbo.fact_sales_2026_stage
WITH
(   DISTRIBUTION = HASH(order_id)
,   CLUSTERED COLUMNSTORE INDEX
,   PARTITION ( order_date RANGE RIGHT FOR VALUES
        ( '2026-02-01', '2026-03-01', '2026-04-01', '2026-05-01', '2026-06-01', '2026-07-01'
        , '2026-08-01', '2026-09-01', '2026-10-01', '2026-11-01', '2026-12-01' ) )
)
AS
SELECT * FROM dbo.fact_sales_2026 WHERE 1 = 2;

INSERT INTO dbo.fact_sales_2026_stage (order_id, customer_id, segment_id, net_amount, order_date)
VALUES ('O-101', 'C007', 1, 80.0, '2026-12-03'), ('O-102', 'C008', 2, 120.0, '2026-12-15');

-- A metadata operation: no row is copied. TRUNCATE_TARGET replaces what December held.
ALTER TABLE dbo.fact_sales_2026_stage SWITCH PARTITION 12 TO dbo.fact_sales_2026 PARTITION 12
WITH (TRUNCATE_TARGET = ON);

SELECT MONTH(order_date) AS month, COUNT(*) AS orders, SUM(net_amount) AS revenue
FROM dbo.fact_sales_2026
GROUP BY MONTH(order_date)
ORDER BY month;
