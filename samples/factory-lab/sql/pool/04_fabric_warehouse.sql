-- flavor: fabric
-- Cloud Lab > SQL pool: the same kind of tables in a simulated Microsoft Fabric Data Warehouse.
-- Fabric manages distribution, files and indexing itself: no DISTRIBUTION, index or PARTITION options.
-- Try running 01_star_schema.sql with the Fabric flavor to see which Synapse options Fabric refuses.

IF OBJECT_ID('dbo.dim_segment_fw') IS NOT NULL DROP TABLE dbo.dim_segment_fw;

CREATE TABLE dbo.dim_segment_fw
(   segment_id INT NOT NULL
,   segment_name VARCHAR(40) NOT NULL          -- nvarchar is not a Fabric type: strings are UTF-8 varchar
,   CONSTRAINT pk_dim_segment_fw PRIMARY KEY NONCLUSTERED (segment_id) NOT ENFORCED
);

INSERT INTO dbo.dim_segment_fw (segment_id, segment_name)
SELECT segment_id, segment_name FROM source.dim_customer_segment;

-- CTAS takes no distribution; CLUSTER BY co-locates rows with close values of the columns you filter on.
IF OBJECT_ID('dbo.fact_orders_fw') IS NOT NULL DROP TABLE dbo.fact_orders_fw;

CREATE TABLE dbo.fact_orders_fw
WITH ( CLUSTER BY (order_date) )
AS
SELECT order_id, customer_id, segment_id,
       CAST(net_amount AS DECIMAL(19, 4)) AS net_amount,      -- money becomes decimal(19,4)
       CAST(LEFT(loaded_at, 10) AS DATE) AS order_date
FROM source.orders;

-- Foreign keys exist in Fabric Warehouse, but only NOT ENFORCED, like primary keys.
ALTER TABLE dbo.fact_orders_fw ADD CONSTRAINT fk_orders_segment
    FOREIGN KEY (segment_id) REFERENCES dbo.dim_segment_fw (segment_id) NOT ENFORCED;

SELECT s.segment_name, SUM(f.net_amount) AS revenue
FROM dbo.fact_orders_fw AS f
JOIN dbo.dim_segment_fw AS s ON f.segment_id = s.segment_id
GROUP BY s.segment_name
ORDER BY revenue DESC;
