-- 16 March: the ERP's weekly export replaces erp_products, as every week. Every row carries the new landing time.
-- Merchandising cut two list prices (P02, P07), the trekking poles were discontinued (no longer exported) and a chalk
-- bag was added.
CREATE OR REPLACE TABLE ${raw}.erp_products AS
SELECT product_id, product_name, subcategory_id, CAST(list_price AS DECIMAL(10,2)) AS list_price,
       CAST(loaded_at AS TIMESTAMP) AS loaded_at
FROM (VALUES
    ('P01', 'Trail Tent 2P',    10, 199.00, '2026-03-16 03:00:00'),
    ('P02', 'Summit Tent 4P',   10, 329.00, '2026-03-16 03:00:00'),
    ('P03', 'Down Bag -5',      11, 159.00, '2026-03-16 03:00:00'),
    ('P04', 'Dynamic Rope 60m', 20, 139.00, '2026-03-16 03:00:00'),
    ('P05', 'Alpine Harness',   21,  69.00, '2026-03-16 03:00:00'),
    ('P06', 'Rain Jacket',      30,  99.00, '2026-03-16 03:00:00'),
    ('P07', 'Insulated Jacket', 30, 129.00, '2026-03-16 03:00:00'),
    ('P08', 'Gift Card',        NULL, 50.00, '2026-03-16 03:00:00'),
    ('P09', 'Chalk Bag',        21,  19.00, '2026-03-16 03:00:00')
) AS t(product_id, product_name, subcategory_id, list_price, loaded_at);
