-- Project "Retail end to end": the web orders in silver.
-- Mosaic > Run active SQL runs this file on the local catalog (DuckDB).
--
-- bronze.web_orders comes from the CSV import: every column is text.
-- Build silver.web_orders with:
--   - order_id and customer_id as text;
--   - segment_id as INTEGER and net_amount as DOUBLE;
--   - ordered_at cast to TIMESTAMP and renamed loaded_at, as in the store orders
--     (the Fabric pipeline will append these rows to bronze.orders by column name);
--   - one row per order (the shop sometimes sends a line twice);
--   - only strictly positive amounts (no refund, no free sample).

CREATE OR REPLACE TABLE silver.web_orders AS
SELECT order_id,
       customer_id,
       segment_id,
       net_amount,
       ordered_at
FROM bronze.web_orders;
