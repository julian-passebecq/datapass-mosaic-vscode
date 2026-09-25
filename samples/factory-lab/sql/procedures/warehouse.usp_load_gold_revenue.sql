-- Called by the Stored procedure activities of pl_retail_daily (Fabric), pl_retail_daily_adf (Azure Data Factory)
-- and pl_sqlpool_daily (Synapse, SQL pool stored procedure).
-- Lab note: the body runs as DuckDB SQL on the local catalog. The @parameters are replaced by the values the
-- pipeline passes, and the header is checked like SQL Server checks a call (missing or unknown parameters fail).
CREATE PROCEDURE warehouse.usp_load_gold_revenue
    @run_date VARCHAR(10),
    @min_orders INT = 1
AS
BEGIN
    DROP TABLE IF EXISTS gold.revenue_by_segment;
    CREATE TABLE gold.revenue_by_segment AS
    SELECT s.segment_name,
           COUNT(*) AS orders,
           SUM(o.net_amount) AS revenue,
           @run_date AS load_date
    FROM silver.orders AS o
    JOIN source.dim_customer_segment AS s ON s.segment_id = o.segment_id
    GROUP BY s.segment_name
    HAVING COUNT(*) >= @min_orders;
END
