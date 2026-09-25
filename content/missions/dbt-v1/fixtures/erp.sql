-- The ERP export (products in a snowflaked hierarchy), as in the BI Lab's warehouse sources.
CREATE OR REPLACE TABLE ${raw}.erp_categories AS
SELECT * FROM (VALUES (1, 'Camping'), (2, 'Climbing'), (3, 'Apparel')) AS t(category_id, category_name);

CREATE OR REPLACE TABLE ${raw}.erp_subcategories AS
SELECT * FROM (VALUES
    (10, 'Tents', 1), (11, 'Sleeping bags', 1), (20, 'Ropes', 2), (21, 'Harnesses', 2), (30, 'Jackets', 3)
) AS t(subcategory_id, subcategory_name, category_id);

CREATE OR REPLACE TABLE ${raw}.erp_products AS
SELECT product_id, product_name, subcategory_id, CAST(list_price AS DECIMAL(10,2)) AS list_price,
       CAST(loaded_at AS TIMESTAMP) AS loaded_at
FROM (VALUES
    ('P01', 'Trail Tent 2P',    10, 199.00, '2026-03-09 03:00:00'),
    ('P02', 'Summit Tent 4P',   10, 349.00, '2026-03-09 03:00:00'),
    ('P03', 'Down Bag -5',      11, 159.00, '2026-03-09 03:00:00'),
    ('P04', 'Dynamic Rope 60m', 20, 139.00, '2026-03-09 03:00:00'),
    ('P05', 'Alpine Harness',   21,  69.00, '2026-03-09 03:00:00'),
    ('P06', 'Rain Jacket',      30,  99.00, '2026-03-09 03:00:00'),
    ('P07', 'Insulated Jacket', 30, 149.00, '2026-03-09 03:00:00'),
    ('P08', 'Gift Card',        NULL, 50.00, '2026-03-09 03:00:00')
) AS t(product_id, product_name, subcategory_id, list_price, loaded_at);
