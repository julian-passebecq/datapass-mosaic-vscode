-- Last night's landing tables. The shop's export job timed out and was retried: SO1003 and SO1006 were
-- exported twice. SO1006's payment changed between the two exports (the customer switched to PayPal).
CREATE OR REPLACE TABLE ${raw}.shop_orders AS
SELECT order_id, customer_id, CAST(order_date AS DATE) AS order_date, channel, payment_type,
       CAST(loaded_at AS TIMESTAMP) AS loaded_at
FROM (VALUES
    ('SO1001', 'C001', '2026-01-05', 'web',   'card',   '2026-03-13 02:00:00'),
    ('SO1002', 'C002', '2026-01-12', 'store', 'card',   '2026-03-13 02:00:00'),
    ('SO1003', 'C001', '2026-02-03', 'web',   'paypal', '2026-03-13 02:00:00'),
    ('SO1004', 'C003', '2026-02-10', 'web',   'card',   '2026-03-13 02:00:00'),
    ('SO1005', 'C004', '2026-02-18', 'store', 'cash',   '2026-03-13 02:00:00'),
    ('SO1006', 'C001', '2026-02-20', 'web',   'card',   '2026-03-13 02:00:00'),
    ('SO1007', 'C005', '2026-03-02', 'web',   'paypal', '2026-03-13 02:00:00'),
    ('SO1008', 'C003', '2026-03-12', 'store', 'card',   '2026-03-13 02:00:00'),
    ('SO1009', 'C006', '2026-03-15', 'web',   'card',   '2026-03-13 02:00:00'),
    ('SO1010', 'C009', '2026-03-20', 'web',   'card',   '2026-03-13 02:00:00'),
    ('SO1011', 'C002', '2026-03-25', 'store', 'card',   '2026-03-13 02:00:00'),
    ('SO1003', 'C001', '2026-02-03', 'web',   'paypal', '2026-03-13 02:41:00'),
    ('SO1006', 'C001', '2026-02-20', 'web',   'paypal', '2026-03-13 02:41:00')
) AS t(order_id, customer_id, order_date, channel, payment_type, loaded_at);
