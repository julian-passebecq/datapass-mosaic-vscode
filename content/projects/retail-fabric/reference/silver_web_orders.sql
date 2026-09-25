-- Reference answer: silver.web_orders, typed, one row per order, positive amounts only.
CREATE OR REPLACE TABLE silver.web_orders AS
SELECT DISTINCT order_id,
       customer_id,
       CAST(segment_id AS INTEGER) AS segment_id,
       CAST(net_amount AS DOUBLE) AS net_amount,
       CAST(ordered_at AS TIMESTAMP) AS loaded_at
FROM bronze.web_orders
WHERE CAST(net_amount AS DOUBLE) > 0;
