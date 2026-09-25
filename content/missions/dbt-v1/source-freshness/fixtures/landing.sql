-- The landing tables as they are right now. The shop export ran an hour ago; the ERP's weekly product export
-- has not arrived for 20 days (its job was disabled during a migration and nobody noticed).
CREATE OR REPLACE TABLE ${raw}.shop_orders AS
SELECT order_id, customer_id, order_date, channel, payment_type,
       CAST(timezone('UTC', now()) AS TIMESTAMP) - INTERVAL 1 HOUR AS loaded_at
FROM ${raw}.shop_orders;

CREATE OR REPLACE TABLE ${raw}.shop_order_lines AS
SELECT order_id, line_number, product_id, quantity, unit_price, discount_amount,
       CAST(timezone('UTC', now()) AS TIMESTAMP) - INTERVAL 1 HOUR AS loaded_at
FROM ${raw}.shop_order_lines;

CREATE OR REPLACE TABLE ${raw}.erp_products AS
SELECT product_id, product_name, subcategory_id, list_price,
       CAST(timezone('UTC', now()) AS TIMESTAMP) - INTERVAL 20 DAY AS loaded_at
FROM ${raw}.erp_products;
