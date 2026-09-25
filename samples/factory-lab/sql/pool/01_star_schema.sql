-- flavor: synapse
-- Cloud Lab > SQL pool: a small star schema in a simulated Azure Synapse dedicated SQL pool.
-- Run it from the SQL pool tab (Cloud Lab), then open the tables panel and the plans of the last queries.
-- Each lab row stands for many real rows (the tab's scale), so the design choices matter.

-- Dimensions are small and joined by every query: keep a full copy on every compute node.
IF OBJECT_ID('dbo.dim_segment') IS NOT NULL DROP TABLE dbo.dim_segment;

CREATE TABLE dbo.dim_segment
WITH ( DISTRIBUTION = REPLICATE, CLUSTERED INDEX (segment_id) )
AS
SELECT segment_id, segment_name
FROM source.dim_customer_segment;

-- Facts are large: hash distribute them on a column with many distinct values and no NULLs.
IF OBJECT_ID('dbo.fact_orders') IS NOT NULL DROP TABLE dbo.fact_orders;

CREATE TABLE dbo.fact_orders
WITH ( DISTRIBUTION = HASH(order_id), CLUSTERED COLUMNSTORE INDEX )
AS
SELECT order_id, customer_id, segment_id, net_amount, CAST(LEFT(loaded_at, 10) AS DATE) AS order_date
FROM source.orders
WHERE net_amount > 0
OPTION (LABEL = 'CTAS : fact_orders');

-- Revenue by segment: the join to a replicated dimension runs locally; only the GROUP BY moves rows.
SELECT s.segment_name, COUNT_BIG(*) AS orders, SUM(f.net_amount) AS revenue
FROM dbo.fact_orders AS f
JOIN dbo.dim_segment AS s ON f.segment_id = s.segment_id
GROUP BY s.segment_name;

-- The same fact distributed on customer_id: the tables panel shows its skew (one corporate account dominates).
IF OBJECT_ID('dbo.fact_orders_by_customer') IS NOT NULL DROP TABLE dbo.fact_orders_by_customer;

CREATE TABLE dbo.fact_orders_by_customer
WITH ( DISTRIBUTION = HASH(customer_id), CLUSTERED COLUMNSTORE INDEX )
AS
SELECT order_id, customer_id, segment_id, net_amount, order_date
FROM dbo.fact_orders;

-- Grouping on the distribution column needs no shuffle.
SELECT customer_id, SUM(net_amount) AS revenue
FROM dbo.fact_orders_by_customer
GROUP BY customer_id;

-- Joining the two facts on order_id: only the table distributed on order_id stays in place.
EXPLAIN
SELECT a.order_id, a.net_amount, b.customer_id
FROM dbo.fact_orders AS a
JOIN dbo.fact_orders_by_customer AS b ON a.order_id = b.order_id;
