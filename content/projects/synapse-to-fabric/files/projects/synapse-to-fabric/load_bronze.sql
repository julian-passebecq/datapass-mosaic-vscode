-- Project "Synapse warehouse to Fabric Warehouse": load bronze.
-- Mosaic > Run active SQL runs this file on the local catalog (DuckDB).
--
-- The Synapse pipeline pl_sqlpool_daily starts from bronze.orders. In the service, a Copy activity or a
-- COPY INTO would load it from the data lake; here, the raw source is copied as is.
CREATE OR REPLACE TABLE bronze.orders AS
SELECT order_id, customer_id, segment_id, net_amount, loaded_at
FROM source.orders;

SELECT COUNT(*) AS orders, SUM(net_amount) AS net_amount FROM bronze.orders;
