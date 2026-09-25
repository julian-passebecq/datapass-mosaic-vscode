-- Source systems of a small outdoor retailer, as the warehouse receives them.
-- CRM: customers (current state) and the history of the attributes the business tracks.
-- ERP: products in a snowflaked hierarchy (product -> subcategory -> category).
-- Shop: orders, order lines and returns.
-- Rerunning this script resets the sources.

CREATE OR REPLACE TABLE source.crm_customers AS
SELECT * FROM (VALUES
    ('C001', 'Alice Martin',  'alice.martin@example.com', 'Lyon',   'Consumer',       DATE '2026-02-15'),
    ('C002', 'Bruno Keller',  'bruno.keller@example.com', 'Geneva', 'Small Business', DATE '2026-01-01'),
    ('C003', 'Chloe Diaz',    'chloe.diaz@example.com',   'Madrid', 'Corporate',      DATE '2026-03-10'),
    ('C004', 'David Okafor',  'd.okafor@example.com',     'Lagos',  'Corporate',      DATE '2026-01-01'),
    ('C005', 'Emma Rossi',    'emma.r@example.com',       'Milan',  'Consumer',       DATE '2026-01-20'),
    ('C006', 'Farid Haddad',  'farid.h@example.com',      'Tunis',  'Small Business', DATE '2026-03-05')
) AS t(customer_id, customer_name, email, city, segment, updated_at);

-- One row per change of a tracked attribute (city, segment), with the date it took effect.
CREATE OR REPLACE TABLE source.crm_customer_history AS
SELECT * FROM (VALUES
    ('C001', DATE '2026-01-01', 'Paris',  'Consumer'),
    ('C001', DATE '2026-02-15', 'Lyon',   'Consumer'),
    ('C002', DATE '2026-01-01', 'Geneva', 'Small Business'),
    ('C003', DATE '2026-01-01', 'Madrid', 'Consumer'),
    ('C003', DATE '2026-03-10', 'Madrid', 'Corporate'),
    ('C004', DATE '2026-01-01', 'Lagos',  'Corporate'),
    ('C005', DATE '2026-01-01', 'Milan',  'Consumer'),
    ('C006', DATE '2026-03-05', 'Tunis',  'Small Business')
) AS t(customer_id, effective_date, city, segment);

CREATE OR REPLACE TABLE source.erp_categories AS
SELECT * FROM (VALUES (1, 'Camping'), (2, 'Climbing'), (3, 'Apparel')) AS t(category_id, category_name);

CREATE OR REPLACE TABLE source.erp_subcategories AS
SELECT * FROM (VALUES
    (10, 'Tents', 1), (11, 'Sleeping bags', 1), (20, 'Ropes', 2), (21, 'Harnesses', 2), (30, 'Jackets', 3)
) AS t(subcategory_id, subcategory_name, category_id);

-- P08 (a gift card) has no subcategory: an inner join through the hierarchy would lose it.
CREATE OR REPLACE TABLE source.erp_products AS
SELECT product_id, product_name, subcategory_id, CAST(unit_cost AS DECIMAL(10,2)) AS unit_cost,
       CAST(list_price AS DECIMAL(10,2)) AS list_price
FROM (VALUES
    ('P01', 'Trail Tent 2P',      10,   120.00, 199.00),
    ('P02', 'Summit Tent 4P',     10,   210.00, 349.00),
    ('P03', 'Down Bag -5',        11,    90.00, 159.00),
    ('P04', 'Dynamic Rope 60m',   20,    80.00, 139.00),
    ('P05', 'Alpine Harness',     21,    35.00,  69.00),
    ('P06', 'Rain Jacket',        30,    45.00,  99.00),
    ('P07', 'Insulated Jacket',   30,    70.00, 149.00),
    ('P08', 'Gift Card',          NULL,   0.00,  50.00)
) AS t(product_id, product_name, subcategory_id, unit_cost, list_price);

-- SO1009 is not shipped yet (no ship_date). SO1010 belongs to C009, a customer the CRM has not sent yet.
CREATE OR REPLACE TABLE source.shop_orders AS
SELECT order_id, customer_id, order_date, ship_date, channel, payment_type, is_gift,
       CAST(shipping_fee AS DECIMAL(10,2)) AS shipping_fee
FROM (VALUES
    ('SO1001', 'C001', DATE '2026-01-05', DATE '2026-01-07', 'web',   'card',   FALSE, 5.00),
    ('SO1002', 'C002', DATE '2026-01-12', DATE '2026-01-13', 'store', 'card',   FALSE, 0.00),
    ('SO1003', 'C001', DATE '2026-02-03', DATE '2026-02-05', 'web',   'paypal', TRUE,  5.00),
    ('SO1004', 'C003', DATE '2026-02-10', DATE '2026-02-12', 'web',   'card',   FALSE, 5.00),
    ('SO1005', 'C004', DATE '2026-02-18', DATE '2026-02-20', 'store', 'cash',   FALSE, 0.00),
    ('SO1006', 'C001', DATE '2026-02-20', DATE '2026-02-23', 'web',   'card',   FALSE, 5.00),
    ('SO1007', 'C005', DATE '2026-03-02', DATE '2026-03-04', 'web',   'paypal', TRUE,  5.00),
    ('SO1008', 'C003', DATE '2026-03-12', DATE '2026-03-14', 'store', 'card',   FALSE, 0.00),
    ('SO1009', 'C006', DATE '2026-03-15', NULL,              'web',   'card',   FALSE, 5.00),
    ('SO1010', 'C009', DATE '2026-03-20', DATE '2026-03-22', 'web',   'card',   FALSE, 5.00),
    ('SO1011', 'C002', DATE '2026-03-25', DATE '2026-03-26', 'store', 'card',   TRUE,  0.00)
) AS t(order_id, customer_id, order_date, ship_date, channel, payment_type, is_gift, shipping_fee);

CREATE OR REPLACE TABLE source.shop_order_lines AS
SELECT order_id, line_number, product_id, quantity, CAST(unit_price AS DECIMAL(10,2)) AS unit_price,
       CAST(discount_amount AS DECIMAL(10,2)) AS discount_amount
FROM (VALUES
    ('SO1001', 1, 'P01', 1, 199.00,  0.00),
    ('SO1001', 2, 'P06', 2,  99.00, 10.00),
    ('SO1002', 1, 'P04', 1, 139.00,  0.00),
    ('SO1002', 2, 'P05', 2,  69.00,  0.00),
    ('SO1003', 1, 'P03', 1, 159.00, 15.00),
    ('SO1004', 1, 'P02', 1, 349.00,  0.00),
    ('SO1004', 2, 'P07', 1, 149.00,  0.00),
    ('SO1005', 1, 'P06', 3,  99.00, 20.00),
    ('SO1006', 1, 'P05', 1,  69.00,  0.00),
    ('SO1006', 2, 'P08', 1,  50.00,  0.00),
    ('SO1007', 1, 'P07', 2, 149.00,  0.00),
    ('SO1008', 1, 'P01', 2, 199.00, 30.00),
    ('SO1008', 2, 'P04', 1, 139.00,  0.00),
    ('SO1009', 1, 'P03', 1, 159.00,  0.00),
    ('SO1010', 1, 'P06', 1,  99.00,  0.00),
    ('SO1011', 1, 'P02', 1, 349.00, 50.00)
) AS t(order_id, line_number, product_id, quantity, unit_price, discount_amount);

CREATE OR REPLACE TABLE source.shop_returns AS
SELECT return_id, order_id, line_number, return_date, quantity, CAST(refund_amount AS DECIMAL(10,2)) AS refund_amount
FROM (VALUES
    ('R01', 'SO1001', 2, DATE '2026-01-20', 1,  94.00),
    ('R02', 'SO1004', 2, DATE '2026-02-25', 1, 149.00),
    ('R03', 'SO1008', 1, DATE '2026-03-20', 1, 184.00)
) AS t(return_id, order_id, line_number, return_date, quantity, refund_amount);
