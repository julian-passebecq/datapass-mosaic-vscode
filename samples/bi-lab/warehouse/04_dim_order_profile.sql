-- Junk dimension: the order's low-cardinality flags (channel, payment type, gift) combined in one small table,
-- instead of three tiny dimensions or three text columns repeated on every fact row. One row per combination seen.
CREATE OR REPLACE TABLE gold.dim_order_profile AS
SELECT CAST(ROW_NUMBER() OVER (ORDER BY channel, payment_type, is_gift) AS INTEGER) AS order_profile_key,
       channel,
       payment_type,
       is_gift
FROM (SELECT DISTINCT channel, payment_type, is_gift FROM source.shop_orders) AS combinations;
