pipeline("web_orders_quality", schedule="0 7 * * *")
no_duplicates = quality("no_duplicates", "SELECT order_id FROM silver.web_orders GROUP BY order_id HAVING COUNT(*) > 1")
positive_amounts = quality("positive_amounts", "SELECT order_id FROM silver.web_orders WHERE net_amount <= 0")
known_segments = quality("known_segments", "SELECT w.order_id FROM silver.web_orders AS w LEFT JOIN source.dim_customer_segment AS s ON s.segment_id = w.segment_id WHERE s.segment_id IS NULL")
publish = sql("publish", "CREATE OR REPLACE TABLE gold.web_orders_daily AS SELECT CAST(loaded_at AS DATE) AS order_date, COUNT(*) AS orders, SUM(net_amount) AS revenue FROM silver.web_orders GROUP BY 1")
[no_duplicates, positive_amounts, known_segments] >> publish
