-- 12 March, first export of the new shop platform: every order and every line so far.
CREATE OR REPLACE TABLE ${raw}.shop_orders AS
SELECT order_id, customer_id, CAST(order_date AS DATE) AS order_date, channel, payment_type,
       CAST(loaded_at AS TIMESTAMP) AS loaded_at
FROM (VALUES
    ('SO1001', 'C001', '2026-01-05', 'web',   'card',   '2026-03-12 02:00:00'),
    ('SO1002', 'C002', '2026-01-12', 'store', 'card',   '2026-03-12 02:00:00'),
    ('SO1003', 'C001', '2026-02-03', 'web',   'paypal', '2026-03-12 02:00:00'),
    ('SO1004', 'C003', '2026-02-10', 'web',   'card',   '2026-03-12 02:00:00'),
    ('SO1005', 'C004', '2026-02-18', 'store', 'cash',   '2026-03-12 02:00:00'),
    ('SO1006', 'C001', '2026-02-20', 'web',   'card',   '2026-03-12 02:00:00'),
    ('SO1007', 'C005', '2026-03-02', 'web',   'paypal', '2026-03-12 02:00:00'),
    ('SO1008', 'C003', '2026-03-11', 'store', 'card',   '2026-03-12 02:00:00')
) AS t(order_id, customer_id, order_date, channel, payment_type, loaded_at);

CREATE OR REPLACE TABLE ${raw}.shop_order_lines AS
SELECT order_id, line_number, product_id, quantity, CAST(unit_price AS DECIMAL(10,2)) AS unit_price,
       CAST(discount_amount AS DECIMAL(10,2)) AS discount_amount, CAST(loaded_at AS TIMESTAMP) AS loaded_at
FROM (VALUES
    ('SO1001', 1, 'P01', 1, 199.00,  0.00, '2026-03-12 02:00:00'),
    ('SO1001', 2, 'P06', 2,  99.00, 10.00, '2026-03-12 02:00:00'),
    ('SO1002', 1, 'P04', 1, 139.00,  0.00, '2026-03-12 02:00:00'),
    ('SO1002', 2, 'P05', 2,  69.00,  0.00, '2026-03-12 02:00:00'),
    ('SO1003', 1, 'P03', 1, 159.00, 15.00, '2026-03-12 02:00:00'),
    ('SO1004', 1, 'P02', 1, 349.00,  0.00, '2026-03-12 02:00:00'),
    ('SO1004', 2, 'P07', 1, 149.00,  0.00, '2026-03-12 02:00:00'),
    ('SO1005', 1, 'P06', 3,  99.00, 20.00, '2026-03-12 02:00:00'),
    ('SO1006', 1, 'P05', 1,  69.00,  0.00, '2026-03-12 02:00:00'),
    ('SO1006', 2, 'P08', 1,  50.00,  0.00, '2026-03-12 02:00:00'),
    ('SO1007', 1, 'P07', 2, 149.00,  0.00, '2026-03-12 02:00:00'),
    ('SO1008', 1, 'P01', 2, 199.00, 30.00, '2026-03-12 02:00:00'),
    ('SO1008', 2, 'P04', 1, 139.00,  0.00, '2026-03-12 02:00:00')
) AS t(order_id, line_number, product_id, quantity, unit_price, discount_amount, loaded_at);
