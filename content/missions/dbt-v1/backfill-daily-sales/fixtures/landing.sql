-- The shop export, 9 to 13 March (13 March is today: still partial). The scheduler was down 10 to 12 March.
CREATE OR REPLACE TABLE ${raw}.shop_orders AS
SELECT order_id, customer_id, CAST(order_date AS DATE) AS order_date, channel, payment_type,
       CAST(loaded_at AS TIMESTAMP) AS loaded_at
FROM (VALUES
    ('SO2001', 'C001', '2026-03-09', 'web',   'card',   '2026-03-13 06:00:00'),
    ('SO2002', 'C004', '2026-03-09', 'store', 'cash',   '2026-03-13 06:00:00'),
    ('SO2003', 'C002', '2026-03-10', 'web',   'card',   '2026-03-13 06:00:00'),
    ('SO2004', 'C003', '2026-03-10', 'web',   'paypal', '2026-03-13 06:00:00'),
    ('SO2005', 'C005', '2026-03-10', 'store', 'card',   '2026-03-13 06:00:00'),
    ('SO2006', 'C006', '2026-03-11', 'web',   'card',   '2026-03-13 06:00:00'),
    ('SO2007', 'C001', '2026-03-12', 'web',   'card',   '2026-03-13 06:00:00'),
    ('SO2008', 'C002', '2026-03-12', 'store', 'card',   '2026-03-13 06:00:00'),
    ('SO2009', 'C003', '2026-03-13', 'web',   'card',   '2026-03-13 06:00:00')
) AS t(order_id, customer_id, order_date, channel, payment_type, loaded_at);

CREATE OR REPLACE TABLE ${raw}.shop_order_lines AS
SELECT order_id, line_number, product_id, quantity, CAST(unit_price AS DECIMAL(10,2)) AS unit_price,
       CAST(discount_amount AS DECIMAL(10,2)) AS discount_amount, CAST(loaded_at AS TIMESTAMP) AS loaded_at
FROM (VALUES
    ('SO2001', 1, 'P01', 1, 199.00,  0.00, '2026-03-13 06:00:00'),
    ('SO2002', 1, 'P06', 2,  99.00,  0.00, '2026-03-13 06:00:00'),
    ('SO2003', 1, 'P04', 1, 139.00,  0.00, '2026-03-13 06:00:00'),
    ('SO2003', 2, 'P05', 1,  69.00,  0.00, '2026-03-13 06:00:00'),
    ('SO2004', 1, 'P02', 1, 349.00, 49.00, '2026-03-13 06:00:00'),
    ('SO2005', 1, 'P07', 1, 149.00,  0.00, '2026-03-13 06:00:00'),
    ('SO2006', 1, 'P03', 2, 159.00, 18.00, '2026-03-13 06:00:00'),
    ('SO2006', 2, 'P08', 1,  50.00,  0.00, '2026-03-13 06:00:00'),
    ('SO2007', 1, 'P06', 1,  99.00,  0.00, '2026-03-13 06:00:00'),
    ('SO2008', 1, 'P01', 1, 199.00, 20.00, '2026-03-13 06:00:00'),
    ('SO2008', 2, 'P05', 2,  69.00,  0.00, '2026-03-13 06:00:00'),
    ('SO2009', 1, 'P02', 1, 349.00,  0.00, '2026-03-13 06:00:00')
) AS t(order_id, line_number, product_id, quantity, unit_price, discount_amount, loaded_at);

-- What the nightly job built on 9 March, before the scheduler went down.
CREATE SCHEMA IF NOT EXISTS dbt_dev_bkfl;
CREATE OR REPLACE TABLE dbt_dev_bkfl.fct_daily_sales AS
SELECT CAST(sales_date AS DATE) AS sales_date, category, CAST(orders AS BIGINT) AS orders,
       CAST(net_sales AS DECIMAL(38,2)) AS net_sales
FROM (VALUES
    ('2026-03-09', 'Apparel', 1, 198.00),
    ('2026-03-09', 'Camping', 1, 199.00)
) AS t(sales_date, category, orders, net_sales);
