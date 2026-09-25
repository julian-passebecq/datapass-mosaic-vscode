-- Returns fact. Grain: one row per return. It shares dim_date, dim_customer and dim_product with fct_sales
-- (conformed dimensions), so sales and returns can be compared side by side (drill across). The customer and
-- product keys are the ones of the sale being returned.
CREATE OR REPLACE TABLE gold.fct_returns AS
SELECT r.return_id,
       r.order_id,
       CAST(strftime(r.return_date, '%Y%m%d') AS INTEGER) AS return_date_key,
       s.customer_key,
       s.product_key,
       r.quantity AS returned_quantity,
       r.refund_amount
FROM source.shop_returns AS r
JOIN gold.fct_sales AS s ON s.order_id = r.order_id AND s.line_number = r.line_number;
