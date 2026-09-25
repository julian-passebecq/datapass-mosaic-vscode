-- flavor: fabric
-- Project "Synapse warehouse to Fabric Warehouse": port a dedicated pool table to Fabric Warehouse.
--
-- This script comes from the Synapse pool. Run it with the Fabric Warehouse product (Cloud Lab > SQL pool,
-- choose Fabric Warehouse, then Run active .sql): Fabric refuses the options it manages itself and some
-- types. Fix the script until it runs, without changing the data it produces.

IF OBJECT_ID('dbo.fact_daily_revenue_fw') IS NOT NULL DROP TABLE dbo.fact_daily_revenue_fw;

CREATE TABLE dbo.fact_daily_revenue_fw
WITH ( DISTRIBUTION = HASH(segment_id), CLUSTERED COLUMNSTORE INDEX )
AS
SELECT CAST(LEFT(o.loaded_at, 10) AS DATE) AS order_date,
       o.segment_id,
       CAST(s.segment_name AS NVARCHAR(40)) AS segment_name,
       COUNT_BIG(*) AS orders,
       CAST(SUM(o.net_amount) AS MONEY) AS revenue
FROM source.orders AS o
JOIN source.dim_customer_segment AS s ON s.segment_id = o.segment_id
WHERE o.net_amount > 0
GROUP BY CAST(LEFT(o.loaded_at, 10) AS DATE), o.segment_id, s.segment_name;

SELECT segment_name, SUM(revenue) AS revenue
FROM dbo.fact_daily_revenue_fw
GROUP BY segment_name
ORDER BY revenue DESC;
