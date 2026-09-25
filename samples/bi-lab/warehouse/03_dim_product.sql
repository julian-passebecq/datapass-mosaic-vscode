-- Product dimension: the ERP's snowflaked hierarchy (product -> subcategory -> category) flattened into one
-- table, so the star has a single join per dimension. LEFT JOINs keep products without a subcategory (the gift
-- card); they report under 'Unassigned'. Type 1: cost and price are the current ERP values.
CREATE OR REPLACE TABLE gold.dim_product AS
SELECT CAST(ROW_NUMBER() OVER (ORDER BY p.product_id) AS INTEGER) AS product_key,
       p.product_id,
       p.product_name,
       COALESCE(s.subcategory_name, 'Unassigned') AS subcategory,
       COALESCE(c.category_name, 'Unassigned') AS category,
       p.unit_cost,
       p.list_price
FROM source.erp_products AS p
LEFT JOIN source.erp_subcategories AS s ON s.subcategory_id = p.subcategory_id
LEFT JOIN source.erp_categories AS c ON c.category_id = s.category_id
UNION ALL
SELECT -1, 'UNKNOWN', 'Unknown product', 'Unknown', 'Unknown', NULL, NULL;
