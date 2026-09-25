-- flavor: fabric
-- Reference answer: Fabric Warehouse manages distribution, files and indexes itself; strings are UTF-8 varchar
-- and money becomes decimal(19,4). CLUSTER BY keeps rows with close order dates together.

IF OBJECT_ID('dbo.fact_daily_revenue_fw') IS NOT NULL DROP TABLE dbo.fact_daily_revenue_fw;

CREATE TABLE dbo.fact_daily_revenue_fw
WITH ( CLUSTER BY (order_date) )
AS
SELECT CAST(LEFT(o.loaded_at, 10) AS DATE) AS order_date,
       o.segment_id,
       CAST(s.segment_name AS VARCHAR(40)) AS segment_name,
       COUNT_BIG(*) AS orders,
       CAST(SUM(o.net_amount) AS DECIMAL(19, 4)) AS revenue
FROM source.orders AS o
JOIN source.dim_customer_segment AS s ON s.segment_id = o.segment_id
WHERE o.net_amount > 0
GROUP BY CAST(LEFT(o.loaded_at, 10) AS DATE), o.segment_id, s.segment_name;

SELECT segment_name, SUM(revenue) AS revenue
FROM dbo.fact_daily_revenue_fw
GROUP BY segment_name
ORDER BY revenue DESC;
