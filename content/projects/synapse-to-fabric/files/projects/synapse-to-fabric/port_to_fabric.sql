-- flavor: fabric
-- Projet « Entrepôt Synapse vers Fabric Warehouse » : porter une table du pool dédié vers Fabric Warehouse.
--
-- Ce script vient du pool Synapse. Exécutez-le avec le produit Fabric Warehouse (Cloud Lab > SQL pool,
-- choisissez Fabric Warehouse, puis Run active .sql) : Fabric refuse les options qu'il gère lui-même et
-- certains types. Corrigez le script jusqu'à ce qu'il passe, sans changer les données produites.

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
