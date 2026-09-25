-- flavor: synapse
-- Cloud Lab > SQL pool: a stored procedure that rebuilds a table with CTAS and swaps it in with RENAME OBJECT.
-- A procedure takes its own batch: GO lines separate the batches.

CREATE OR ALTER PROCEDURE dbo.usp_segment_revenue @min_amount DECIMAL(10, 2) = 0
AS
BEGIN
    IF OBJECT_ID('dbo.segment_revenue_new') IS NOT NULL DROP TABLE dbo.segment_revenue_new;

    -- Build the new version next to the old one: readers keep the old table meanwhile.
    CREATE TABLE dbo.segment_revenue_new
    WITH ( DISTRIBUTION = REPLICATE, CLUSTERED INDEX (segment_id) )
    AS
    SELECT o.segment_id, s.segment_name, COUNT_BIG(*) AS orders, SUM(o.net_amount) AS revenue
    FROM source.orders AS o
    JOIN source.dim_customer_segment AS s ON o.segment_id = s.segment_id
    WHERE o.net_amount >= @min_amount
    GROUP BY o.segment_id, s.segment_name;

    IF OBJECT_ID('dbo.segment_revenue') IS NOT NULL DROP TABLE dbo.segment_revenue;
    RENAME OBJECT dbo.segment_revenue_new TO segment_revenue;
END
GO

-- Running it twice is safe: each run rebuilds the table from scratch.
EXEC dbo.usp_segment_revenue;
EXEC dbo.usp_segment_revenue @min_amount = 100;

SELECT segment_name, orders, revenue
FROM dbo.segment_revenue
ORDER BY revenue DESC;

-- Variables: DECLARE with a query, then use them in statements.
DECLARE @top_segment VARCHAR(40) = (SELECT TOP 1 segment_name FROM dbo.segment_revenue ORDER BY revenue DESC);
PRINT CONCAT('Top segment: ', @top_segment);
