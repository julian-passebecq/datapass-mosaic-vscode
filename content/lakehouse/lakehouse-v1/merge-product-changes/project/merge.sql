-- dim_product is a DuckLake table (the lake is attached as `lake`). The supplier's changes:
SELECT * FROM read_csv('data/product_changes.csv');
