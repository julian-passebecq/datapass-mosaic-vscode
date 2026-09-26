-- Write data/sales.csv as Parquet under lake/sales/, partitioned by year and month (Hive style).
-- Run it from the Lakehouse Lab (Run solution.sql); "Check my work" reads what it left on disk.
SELECT * FROM read_csv('data/sales.csv') LIMIT 5;
