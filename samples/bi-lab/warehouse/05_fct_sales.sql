-- Sales fact. Grain: one row per order line.
-- order_id stays on the fact as a degenerate dimension (it has no dimension table of its own).
-- The order date and the ship date play two roles against the same dim_date (a role-playing dimension).
-- The customer version is the one valid on the order date: a point-in-time join on the type 2 dimension.
-- Unknown or missing references point to the -1 members, never to NULL, so no sale disappears from a report.
-- shipping_fee is an order-level amount and is not on this line-level fact: repeating it on every line would
-- count it once per line.
CREATE OR REPLACE TABLE gold.fct_sales AS
SELECT l.order_id,
       l.line_number,
       CAST(strftime(o.order_date, '%Y%m%d') AS INTEGER) AS order_date_key,
       COALESCE(CAST(strftime(o.ship_date, '%Y%m%d') AS INTEGER), -1) AS ship_date_key,
       COALESCE(dc.customer_key, -1) AS customer_key,
       COALESCE(dp.product_key, -1) AS product_key,
       op.order_profile_key,
       l.quantity,
       l.quantity * l.unit_price AS gross_amount,
       l.discount_amount,
       l.quantity * l.unit_price - l.discount_amount AS net_amount,
       l.quantity * dp.unit_cost AS cost_amount
FROM source.shop_order_lines AS l
JOIN source.shop_orders AS o ON o.order_id = l.order_id
LEFT JOIN gold.dim_customer AS dc
       ON dc.customer_id = o.customer_id
      AND o.order_date >= dc.valid_from
      AND o.order_date < dc.valid_to
LEFT JOIN gold.dim_product AS dp ON dp.product_id = l.product_id
JOIN gold.dim_order_profile AS op
  ON op.channel = o.channel AND op.payment_type = o.payment_type AND op.is_gift = o.is_gift;
