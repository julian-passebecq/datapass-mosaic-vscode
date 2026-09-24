export const sqlChallengeTopics = [
  { id: 'lab-cross', name: 'Cross Joins', short: 'Cross Join', icon: '×', description: 'Cartesian products, time grids, and dimensional scaffolding.' },
  { id: 'lab-inner', name: 'Inner Joins', short: 'Inner Join', icon: '⋂', description: 'Match related rows and chain joins across normalized tables.' },
  { id: 'lab-left', name: 'Left Joins', short: 'Left Join', icon: '←', description: 'Preserve the left side, enrich data, and detect missing matches.' },
  { id: 'lab-full', name: 'Full Outer Joins', short: 'Full Join', icon: '↔', description: 'Reconcile two datasets while preserving unmatched rows from both sides.' },
  { id: 'lab-self', name: 'Self Joins', short: 'Self Join', icon: '↻', description: 'Join a table to itself for hierarchies, sequences, and pairwise relationships.' },
  { id: 'lab-groupby', name: 'GROUP BY + HAVING', short: 'GROUP BY', icon: 'Σ', description: 'Aggregate by business keys, filter groups, and reason about granularity.' },
  { id: 'lab-case', name: 'CASE WHEN', short: 'CASE', icon: '?', description: 'Conditional columns, conditional aggregation, and business-rule bucketing.' },
  { id: 'lab-grouping', name: 'Grouping Sets / ROLLUP / CUBE', short: 'Grouping Sets', icon: '▦', description: 'Multiple aggregation levels in one query for reporting and OLAP-style summaries.' },
  { id: 'lab-window', name: 'Window Functions', short: 'Windows', icon: '▤', description: 'OVER, PARTITION BY, frames, LAG, ROW_NUMBER, RANK, DENSE_RANK, and running metrics.' },
]

const C = (x) => ({ collection: 'sql-lab', language: 'sql', why: 'This pattern appears in data transformation, reconciliation, quality checks, reporting queries, and data-engineering interviews.', ...x })

export const sqlChallenges = [
  // CROSS JOINS
  C({ id:'lab-cross-size-brand', track:'lab-cross', level:'Beginner', title:'Build every size × brand combination', sourcePack:'Cross Joins',
    concept:'CROSS JOIN returns the Cartesian product: every row from the first input paired with every row from the second.',
    context:'Tables: dbo.sizes(size_code) with XS, M, L, XL; dbo.brands(brand_name) with Nike, Asphalte, Abercrombie, Lewis.',
    task:'Return every possible size and brand combination. Before revealing the solution, predict the output row count.',
    starter:'SELECT\n    -- columns\nFROM dbo.sizes AS s\n-- join dbo.brands\n',
    solution:`SELECT
    s.size_code,
    b.brand_name
FROM dbo.sizes AS s
CROSS JOIN dbo.brands AS b;`,
    solutionExplanation:'There is no join predicate because a cross join intentionally creates all combinations. With 4 sizes and 4 brands, the result has 16 rows.',
    hints:['Start with both table aliases.','A CROSS JOIN has no ON clause.','Output size is left-row-count × right-row-count.'], pitfall:'Adding an ON condition changes the problem into a conditional join rather than a Cartesian product.' }),
  C({ id:'lab-cross-time-grid', track:'lab-cross', level:'Beginner', title:'Generate quarter-hour time slots', sourcePack:'Cross Joins',
    concept:'A small Cartesian product is useful for generating complete dimensional combinations.',
    context:'Tables: dbo.hours(hour_value) contains 08–12; dbo.quarters(minute_value) contains 00, 15, 30, 45.',
    task:'Generate every hour/minute pair and sort chronologically.',
    starter:'SELECT\n    h.hour_value,\n    q.minute_value\nFROM dbo.hours AS h\n-- complete the join\n-- order the result\n',
    solution:`SELECT
    h.hour_value,
    q.minute_value
FROM dbo.hours AS h
CROSS JOIN dbo.quarters AS q
ORDER BY h.hour_value, q.minute_value;`,
    solutionExplanation:'The two tiny dimensions are independent, so CROSS JOIN creates the full grid. ORDER BY makes the generated combinations readable as time slots.',
    hints:['No matching key is needed.','Join every hour to every quarter.','Sort by hour first, then minute.'], pitfall:'Do not use INNER JOIN unless you invent a key; that obscures the intent.' }),
  C({ id:'lab-cross-retail-grid', track:'lab-cross', level:'Intermediate', title:'Build a complete retail reporting grid', sourcePack:'Cross Joins',
    concept:'Cross joins can generate a scaffold containing combinations that do not yet exist in fact data.',
    context:'Dimensions: dbo.stores(store_id), dbo.markets(market_id), dbo.months(month_id), dbo.weekdays(weekday_id), dbo.quarters(quarter_id).',
    task:'Create every store × market × month × weekday × quarter combination.',
    starter:'SELECT\n    s.store_id, m.market_id, mo.month_id, w.weekday_id, q.quarter_id\nFROM dbo.stores AS s\n-- add the remaining dimensions\n',
    solution:`SELECT
    s.store_id,
    m.market_id,
    mo.month_id,
    w.weekday_id,
    q.quarter_id
FROM dbo.stores AS s
CROSS JOIN dbo.markets AS m
CROSS JOIN dbo.months AS mo
CROSS JOIN dbo.weekdays AS w
CROSS JOIN dbo.quarters AS q;`,
    solutionExplanation:'Each additional CROSS JOIN multiplies the current row count by the size of the next dimension. This pattern is useful for gap detection, but the cardinality must be estimated first.',
    hints:['Chain CROSS JOIN clauses.','There is still no ON predicate.','Estimate the row count before running this in production.'], pitfall:'Cartesian products can explode in size very quickly; use them intentionally and with small dimensions.' }),

  // INNER JOINS
  C({ id:'lab-inner-customer-orders', track:'lab-inner', level:'Beginner', title:'Match customers to detailed orders', sourcePack:'Inner Joins',
    concept:'INNER JOIN keeps only rows that satisfy the join predicate on both sides.',
    context:'dbo.customers(customer_id, customer_name); dbo.order_detail(order_id, customer_id, product_id, quantity).',
    task:'Return customer_id, customer_name, order_id, product_id, and quantity for customers that have matching order details.',
    starter:'SELECT\n    -- requested columns\nFROM dbo.customers AS c\nINNER JOIN dbo.order_detail AS od\n    ON -- matching key\n',
    solution:`SELECT
    c.customer_id,
    c.customer_name,
    od.order_id,
    od.product_id,
    od.quantity
FROM dbo.customers AS c
INNER JOIN dbo.order_detail AS od
    ON c.customer_id = od.customer_id;`,
    solutionExplanation:'The equality predicate connects the customer business key to the foreign key in the order details. Customers without matching details disappear by design.',
    hints:['Find the common key.','Qualify customer_id because it exists in both tables.'], pitfall:'Joining on unrelated columns can produce plausible-looking but incorrect data.' }),
  C({ id:'lab-inner-add-products', track:'lab-inner', level:'Beginner', title:'Enrich order rows with product data', sourcePack:'Inner Joins',
    concept:'Joins are often chained: first establish the transaction grain, then enrich it with dimensions.',
    context:'dbo.customer_orders already contains product_id; dbo.products(product_id, product_name, unit_price).',
    task:'Return all matched order rows enriched with the product name and unit price.',
    starter:'SELECT\n    co.*,\n    -- product columns\nFROM dbo.customer_orders AS co\n-- join products\n',
    solution:`SELECT
    co.*,
    p.product_name,
    p.unit_price
FROM dbo.customer_orders AS co
INNER JOIN dbo.products AS p
    ON co.product_id = p.product_id;`,
    solutionExplanation:'The product_id is the relationship key. INNER JOIN assumes rows without a known product should not appear in this result.',
    hints:['Join on product_id.','Use table aliases to make the key origin obvious.'], pitfall:'If unknown products must remain visible for data-quality analysis, LEFT JOIN would be the better choice.' }),
  C({ id:'lab-inner-retail-chain', track:'lab-inner', level:'Intermediate', title:'Map each sale to its retail universe', sourcePack:'Inner Joins retail case',
    concept:'A normalized model may require several joins to move from a fact table to a higher-level business category.',
    context:'dbo.sales(product_id,...); dbo.product_category(product_id, category_id); dbo.category_universe(category_id, universe_id).',
    task:'Return sales with the category_id and universe_id by chaining two inner joins.',
    starter:'SELECT\n    s.*,\n    pc.category_id,\n    cu.universe_id\nFROM dbo.sales AS s\n-- join product_category\n-- join category_universe\n',
    solution:`SELECT
    s.*,
    pc.category_id,
    cu.universe_id
FROM dbo.sales AS s
INNER JOIN dbo.product_category AS pc
    ON s.product_id = pc.product_id
INNER JOIN dbo.category_universe AS cu
    ON pc.category_id = cu.category_id;`,
    solutionExplanation:'The first join resolves product → category; the second resolves category → universe. Each predicate follows a declared relationship rather than guessing from names.',
    hints:['First get category_id from product_id.','Then use category_id to reach the universe.'], pitfall:'Do not join sales directly to category_universe unless a legitimate key exists between them.' }),
  C({ id:'lab-inner-multi-key', track:'lab-inner', level:'Intermediate', title:'Join on two business keys', sourcePack:'Inner Join extension',
    concept:'A join predicate may require multiple columns when one column alone does not uniquely identify the relationship.',
    context:'dbo.actual_sales(store_id, product_id, amount); dbo.product_targets(store_id, product_id, target_amount).',
    task:'Match actual sales to targets using both store_id and product_id.',
    starter:'SELECT\n    a.store_id, a.product_id, a.amount, t.target_amount\nFROM dbo.actual_sales AS a\nINNER JOIN dbo.product_targets AS t\n    ON -- first key\n   AND -- second key\n',
    solution:`SELECT
    a.store_id,
    a.product_id,
    a.amount,
    t.target_amount
FROM dbo.actual_sales AS a
INNER JOIN dbo.product_targets AS t
    ON a.store_id = t.store_id
   AND a.product_id = t.product_id;`,
    solutionExplanation:'The relationship grain is store + product. Using only product_id could incorrectly match one product across multiple stores.',
    hints:['Ask what uniquely identifies a target row.','Use AND inside the ON predicate.'], pitfall:'A partial join key often creates duplicate or cross-store matches.' }),
  C({ id:'lab-inner-constant-key', track:'lab-inner', level:'Expert', title:'Understand a cross join simulated with an inner join', sourcePack:'Cross join with inner join',
    concept:'If every row on both sides has the same artificial key, an inner join on that key creates a Cartesian product.',
    context:'dbo.beverages(id, beverage) and dbo.food_items(id, food) both have id = 1 for every row.',
    task:'Write the inner join that produces every beverage × food pair. Then identify why CROSS JOIN would express the intention more clearly.',
    starter:'SELECT b.beverage, f.food\nFROM dbo.beverages AS b\nINNER JOIN dbo.food_items AS f\n    ON -- constant key match\n',
    solution:`SELECT
    b.beverage,
    f.food
FROM dbo.beverages AS b
INNER JOIN dbo.food_items AS f
    ON b.id = f.id;`,
    solutionExplanation:'Because every id is 1, every beverage matches every food. It works, but CROSS JOIN is clearer because it states that the Cartesian product is intentional.',
    hints:['Every row has the same id.','Think about how many rows match each left row.'], pitfall:'Do not use this artificial-key trick in real code when CROSS JOIN expresses the intent directly.' }),

  // LEFT JOINS
  C({ id:'lab-left-preserve-customers', track:'lab-left', level:'Beginner', title:'Keep customers even when they have no orders', sourcePack:'Left Joins',
    concept:'LEFT JOIN keeps every row from the left table and fills unmatched right-side columns with NULL.',
    context:'dbo.customers(customer_id, customer_name); dbo.order_detail(order_id, customer_id, product_id, quantity).',
    task:'Return all customers and any matching order detail. Customers without orders must remain in the result.',
    starter:'SELECT c.customer_id, c.customer_name, od.order_id, od.product_id, od.quantity\nFROM dbo.customers AS c\n-- complete the left join\n',
    solution:`SELECT
    c.customer_id,
    c.customer_name,
    od.order_id,
    od.product_id,
    od.quantity
FROM dbo.customers AS c
LEFT JOIN dbo.order_detail AS od
    ON c.customer_id = od.customer_id;`,
    solutionExplanation:'The preserved side is dbo.customers because it appears before LEFT JOIN. Missing orders show as NULL rather than removing the customer.',
    hints:['Put the dataset you must preserve on the left.','Join on customer_id.'], pitfall:'Reversing the table order changes which records are guaranteed to survive.' }),
  C({ id:'lab-left-product-enrichment', track:'lab-left', level:'Beginner', title:'Preserve order lines with unknown products', sourcePack:'Left Joins',
    concept:'LEFT JOIN is a standard enrichment pattern when missing dimension matches should remain visible.',
    context:'dbo.customer_orders(product_id,...); dbo.products(product_id, product_name).',
    task:'Add product_name while retaining every row from customer_orders.',
    starter:'SELECT co.*, p.product_name\nFROM dbo.customer_orders AS co\n-- join products while preserving co\n',
    solution:`SELECT
    co.*,
    p.product_name
FROM dbo.customer_orders AS co
LEFT JOIN dbo.products AS p
    ON co.product_id = p.product_id;`,
    solutionExplanation:'Unknown product IDs remain in the output, with product_name = NULL. That makes downstream quality checks possible.',
    hints:['The transactional rows are the preserved side.','Use LEFT JOIN, not INNER JOIN.'], pitfall:'A WHERE condition on p.product_name after the join can accidentally remove the NULL rows and behave like an inner join.' }),
  C({ id:'lab-left-find-missing-universe', track:'lab-left', level:'Intermediate', title:'Find sales with no mapped universe', sourcePack:'Left Join retail case',
    concept:'LEFT JOIN plus an IS NULL filter is an anti-join pattern for detecting unmatched keys.',
    context:'dbo.sales(product_id,...); dbo.product_category(product_id, category_id); dbo.category_universe(category_id, universe_id).',
    task:'Find sales that cannot be mapped to a universe. Preserve sales through both joins, then keep rows where universe_id is NULL.',
    starter:'SELECT s.*, pc.category_id, cu.universe_id\nFROM dbo.sales AS s\n-- left join mappings\nWHERE -- missing universe\n',
    solution:`SELECT
    s.*,
    pc.category_id,
    cu.universe_id
FROM dbo.sales AS s
LEFT JOIN dbo.product_category AS pc
    ON s.product_id = pc.product_id
LEFT JOIN dbo.category_universe AS cu
    ON pc.category_id = cu.category_id
WHERE cu.universe_id IS NULL;`,
    solutionExplanation:'Both enrichment steps are left joins so unmapped sales survive. The final IS NULL test isolates the failures.',
    hints:['Use LEFT JOIN twice.','The missing value appears on the right-most dimension.','Filter with IS NULL, not = NULL.'], pitfall:'`= NULL` never behaves like an ordinary equality comparison; use IS NULL.' }),
  C({ id:'lab-left-filter-placement', track:'lab-left', level:'Intermediate', title:'Keep the left join while filtering the right table', sourcePack:'Left Join extension',
    concept:'A predicate in ON controls matching; the same predicate in WHERE can remove NULL-extended rows after the join.',
    context:'dbo.customers; dbo.orders(customer_id, order_date, status).',
    task:'Return every customer and only their 2026 completed orders. Customers with no matching completed 2026 order must still appear.',
    starter:'SELECT c.customer_id, o.order_id, o.order_date\nFROM dbo.customers AS c\nLEFT JOIN dbo.orders AS o\n    ON c.customer_id = o.customer_id\n   AND -- put right-side filters here\n',
    solution:`SELECT
    c.customer_id,
    o.order_id,
    o.order_date
FROM dbo.customers AS c
LEFT JOIN dbo.orders AS o
    ON c.customer_id = o.customer_id
   AND o.status = 'COMPLETED'
   AND o.order_date >= '20260101'
   AND o.order_date < '20270101';`,
    solutionExplanation:'The order filters are part of the matching rule, so unmatched customers still produce one NULL-extended row.',
    hints:['Do not put the right-table filter in WHERE.','Keep all right-side restrictions inside ON.'], pitfall:'`WHERE o.status = ...` rejects NULL and effectively removes customers with no matching order.' }),

  // FULL OUTER
  C({ id:'lab-full-products', track:'lab-full', level:'Intermediate', title:'Preserve store products and catalog products', sourcePack:'Full Outer Joins',
    concept:'FULL OUTER JOIN preserves unmatched rows from both inputs.',
    context:'dbo.store_products(product_id, store_id); dbo.products(product_id, product_name).',
    task:'Return every store-product mapping and every catalog product, including products missing on either side.',
    starter:'SELECT sp.store_id, COALESCE(sp.product_id, p.product_id) AS product_id, p.product_name\nFROM dbo.store_products AS sp\n-- full join products\n',
    solution:`SELECT
    sp.store_id,
    COALESCE(sp.product_id, p.product_id) AS product_id,
    p.product_name
FROM dbo.store_products AS sp
FULL OUTER JOIN dbo.products AS p
    ON sp.product_id = p.product_id;`,
    solutionExplanation:'Matched products appear once; unmatched store mappings and unmatched catalog products are both preserved. COALESCE provides whichever product_id exists.',
    hints:['Use FULL OUTER JOIN.','The key can be NULL on either side after the join.'], pitfall:'SELECTing only one side’s key can hide the identifier for rows that exist only on the other side.' }),
  C({ id:'lab-full-reconcile', track:'lab-full', level:'Intermediate', title:'Reconcile source and target customer IDs', sourcePack:'Full Outer Join reconciliation',
    concept:'FULL OUTER JOIN is useful for reconciliation: matched, source-only, and target-only records can be classified in one result.',
    context:'dbo.source_customers(customer_id); dbo.target_customers(customer_id).',
    task:'Return customer_id and a status of MATCHED, SOURCE_ONLY, or TARGET_ONLY.',
    starter:'SELECT\n    COALESCE(s.customer_id, t.customer_id) AS customer_id,\n    CASE\n        -- classify the row\n    END AS reconciliation_status\nFROM dbo.source_customers AS s\nFULL OUTER JOIN dbo.target_customers AS t\n    ON s.customer_id = t.customer_id;\n',
    solution:`SELECT
    COALESCE(s.customer_id, t.customer_id) AS customer_id,
    CASE
        WHEN s.customer_id IS NULL THEN 'TARGET_ONLY'
        WHEN t.customer_id IS NULL THEN 'SOURCE_ONLY'
        ELSE 'MATCHED'
    END AS reconciliation_status
FROM dbo.source_customers AS s
FULL OUTER JOIN dbo.target_customers AS t
    ON s.customer_id = t.customer_id;`,
    solutionExplanation:'The NULL pattern tells you which side was missing. This is a common migration and pipeline validation query.',
    hints:['FULL JOIN first.','Check which side is NULL.','COALESCE returns the available key.'], pitfall:'Do not filter out NULLs before classifying them; those NULLs are the signal you need.' }),

  // SELF JOINS
  C({ id:'lab-self-manager', track:'lab-self', level:'Beginner', title:'Resolve employee → manager names', sourcePack:'Self Joins',
    concept:'A self join uses two aliases for the same table so rows can play different roles.',
    context:'dbo.employees(employee_id, employee_name, manager_id).',
    task:'Return each employee with their manager name. Keep top-level employees who have no manager.',
    starter:'SELECT e.employee_name, m.employee_name AS manager_name\nFROM dbo.employees AS e\n-- join dbo.employees again as m\n',
    solution:`SELECT
    e.employee_name,
    m.employee_name AS manager_name
FROM dbo.employees AS e
LEFT JOIN dbo.employees AS m
    ON e.manager_id = m.employee_id;`,
    solutionExplanation:'Alias e represents the employee row; alias m represents the manager row. LEFT JOIN keeps executives whose manager_id is NULL.',
    hints:['Use the same table twice with different aliases.','Employee.manager_id points to Manager.employee_id.'], pitfall:'Without aliases, the column references are ambiguous and the relationship is hard to read.' }),
  C({ id:'lab-self-consecutive-orders', track:'lab-self', level:'Intermediate', title:'Find customers ordering on consecutive days', sourcePack:'Self Join order-delay exercise',
    concept:'Self joins can compare different rows belonging to the same entity.',
    context:'dbo.sales_orders(order_id, customer_id, order_date).',
    task:'Return pairs of different orders for the same customer where the second order occurs exactly one day after the first.',
    starter:'SELECT a.customer_id, a.order_id AS first_order, b.order_id AS second_order\nFROM dbo.sales_orders AS a\nINNER JOIN dbo.sales_orders AS b\n    ON -- same customer\n   AND -- next day relationship\n',
    solution:`SELECT
    a.customer_id,
    a.order_id AS first_order,
    a.order_date AS first_order_date,
    b.order_id AS second_order,
    b.order_date AS second_order_date
FROM dbo.sales_orders AS a
INNER JOIN dbo.sales_orders AS b
    ON a.customer_id = b.customer_id
   AND b.order_date = DATEADD(day, 1, a.order_date);`,
    solutionExplanation:'The date relationship itself guarantees the rows are different, so a separate order_id inequality is usually unnecessary. DATEADD is idiomatic T-SQL.',
    hints:['Join rows for the same customer.','Use DATEADD(day, 1, first_date).'], pitfall:'Joining only on customer_id creates every order pair for that customer and can become quadratic.' }),
  C({ id:'lab-self-meetings', track:'lab-self', level:'Intermediate', title:'Find Benjamin’s meeting partners', sourcePack:'Self Join meetings exercise',
    concept:'A many-participant event table can be self-joined on event ID to build participant pairs.',
    context:'dbo.meeting_participants(meeting_id, person_name, duration_minutes).',
    task:'Return Benjamin’s meetings paired with every other participant in the same meeting.',
    starter:'SELECT a.meeting_id, b.person_name AS colleague, a.duration_minutes\nFROM dbo.meeting_participants AS a\nINNER JOIN dbo.meeting_participants AS b\n    ON -- same meeting\nWHERE -- Benjamin on left, someone else on right\n',
    solution:`SELECT
    a.meeting_id,
    b.person_name AS colleague,
    a.duration_minutes
FROM dbo.meeting_participants AS a
INNER JOIN dbo.meeting_participants AS b
    ON a.meeting_id = b.meeting_id
WHERE a.person_name = 'Benjamin'
  AND b.person_name <> 'Benjamin';`,
    solutionExplanation:'The self join expands each Benjamin event row to the other participants in that event. A later GROUP BY can summarize time by colleague.',
    hints:['Join on meeting_id.','Filter the left alias to Benjamin.','Exclude Benjamin from the right alias.'], pitfall:'Forgetting the right-side exclusion pairs Benjamin with himself.' }),

  // GROUP BY
  C({ id:'lab-groupby-neighborhood', track:'lab-groupby', level:'Beginner', title:'Average property price by neighborhood', sourcePack:'GROUP BY intro',
    concept:'GROUP BY changes the grain of the result to one row per grouping key.',
    context:'dbo.property_sales(neighborhood, price).',
    task:'Return one row per neighborhood with its average price.',
    starter:'SELECT neighborhood,\n       -- average price\nFROM dbo.property_sales\n-- group correctly\n',
    solution:`SELECT
    neighborhood,
    AVG(price) AS average_price
FROM dbo.property_sales
GROUP BY neighborhood;`,
    solutionExplanation:'Every selected column that is not aggregated must be part of the GROUP BY. AVG then summarizes all property rows inside each neighborhood.',
    hints:['Use AVG(price).','Group by the non-aggregated selected column.'], pitfall:'Selecting extra detail columns would either error or change the intended grain.' }),
  C({ id:'lab-groupby-city', track:'lab-groupby', level:'Beginner', title:'Average sale value by city', sourcePack:'Real-estate GROUP BY exercise',
    concept:'Aggregation is often combined with an explicit numeric conversion for reporting output.',
    context:'dbo.property_sales(city, sale_value).',
    task:'Return each city and its average sale_value, cast to an integer.',
    starter:'SELECT city,\n       CAST(-- average AS int) AS avg_sale_value\nFROM dbo.property_sales\nGROUP BY --\n',
    solution:`SELECT
    city,
    CAST(AVG(sale_value) AS int) AS avg_sale_value
FROM dbo.property_sales
GROUP BY city;`,
    solutionExplanation:'AVG computes at city grain; CAST only changes the returned representation, not the grouping.',
    hints:['Aggregate first, cast the aggregate.','Group by city.'], pitfall:'Casting each source row before AVG can change precision and therefore the result.' }),
  C({ id:'lab-groupby-basket', track:'lab-groupby', level:'Beginner', title:'Average basket amount per customer', sourcePack:'GROUP BY exercises',
    concept:'The grouping key determines the business entity you are summarizing.',
    context:'dbo.sales(customer_id, amount).',
    task:'Return each customer_id with their average transaction amount.',
    starter:'SELECT customer_id,\n       -- aggregate\nFROM dbo.sales\nGROUP BY --\n',
    solution:`SELECT
    customer_id,
    AVG(amount) AS average_basket_amount
FROM dbo.sales
GROUP BY customer_id;`,
    solutionExplanation:'Rows are partitioned by customer_id and AVG summarizes amounts within each customer.',
    hints:['One output row per customer.','Use AVG(amount).'], pitfall:'SUM(amount) answers total spend, which is a different metric from average basket.' }),
  C({ id:'lab-groupby-having', track:'lab-groupby', level:'Intermediate', title:'Filter aggregated cities with HAVING', sourcePack:'WHERE / CTE / HAVING lesson',
    concept:'WHERE filters input rows before aggregation; HAVING filters groups after aggregation.',
    context:'dbo.property_sales(city, sale_value).',
    task:'Return cities with more than 10 sales and average sale value below 250000.',
    starter:'SELECT city, COUNT(*) AS sale_count, AVG(sale_value) AS avg_sale_value\nFROM dbo.property_sales\nGROUP BY city\n-- filter the groups\n',
    solution:`SELECT
    city,
    COUNT(*) AS sale_count,
    AVG(sale_value) AS avg_sale_value
FROM dbo.property_sales
GROUP BY city
HAVING COUNT(*) > 10
   AND AVG(sale_value) < 250000;`,
    solutionExplanation:'The conditions depend on COUNT and AVG, which do not exist until after grouping. HAVING is therefore the correct filter stage.',
    hints:['You are filtering groups, not raw rows.','Use aggregate expressions in HAVING.'], pitfall:'Trying to use aggregate aliases in WHERE is logically too early.' }),
  C({ id:'lab-groupby-above-global', track:'lab-groupby', level:'Intermediate', title:'Customers above the global average transaction value', sourcePack:'GROUP BY + subquery exercise',
    concept:'A grouped aggregate can be compared with a scalar aggregate computed by a subquery.',
    context:'dbo.sales(customer_id, amount).',
    task:'Return customers whose average transaction amount is greater than the average amount across all transactions.',
    starter:'SELECT customer_id, AVG(amount) AS customer_avg\nFROM dbo.sales\nGROUP BY customer_id\nHAVING AVG(amount) > (\n    -- global average\n);\n',
    solution:`SELECT
    customer_id,
    AVG(amount) AS customer_avg
FROM dbo.sales
GROUP BY customer_id
HAVING AVG(amount) > (
    SELECT AVG(amount)
    FROM dbo.sales
);`,
    solutionExplanation:'The inner query returns one scalar global benchmark. HAVING compares each customer-level aggregate to that benchmark.',
    hints:['The subquery should return exactly one value.','The outer query groups by customer_id.'], pitfall:'Grouping the inner query would return multiple values and break the scalar comparison.' }),
  C({ id:'lab-groupby-above-global-cte', track:'lab-groupby', level:'Intermediate', title:'Rewrite the global-average filter with a CTE', sourcePack:'GROUP BY + CTE exercise',
    concept:'A CTE can give a named intermediate result to a benchmark or complex aggregation.',
    context:'dbo.sales(customer_id, amount).',
    task:'Compute the global average in a CTE, then return customers whose average transaction amount is above it.',
    starter:'WITH global_avg AS (\n    -- one-row benchmark\n)\nSELECT customer_id, AVG(amount) AS customer_avg\nFROM dbo.sales\n-- bring benchmark into scope\nGROUP BY customer_id, -- benchmark column\nHAVING -- compare averages\n',
    solution:`WITH global_avg AS (
    SELECT AVG(amount) AS avg_amount
    FROM dbo.sales
)
SELECT
    s.customer_id,
    AVG(s.amount) AS customer_avg
FROM dbo.sales AS s
CROSS JOIN global_avg AS g
GROUP BY s.customer_id, g.avg_amount
HAVING AVG(s.amount) > g.avg_amount;`,
    solutionExplanation:'The one-row CTE is cross joined so its scalar benchmark is available to the grouped query. Because g.avg_amount appears as a non-aggregated selected/reference value at group scope, it is included in GROUP BY.',
    hints:['Make the CTE one row.','A one-row CTE can be CROSS JOINed safely.','Compare AVG(s.amount) to the benchmark.'], pitfall:'A CTE does not automatically expose its columns; it must be referenced in FROM/JOIN.' }),
  C({ id:'lab-groupby-meeting-average', track:'lab-groupby', level:'Intermediate', title:'Average meeting duration by colleague', sourcePack:'GROUP BY meetings solution',
    concept:'A CTE can first construct the correct row grain, then a GROUP BY can summarize it.',
    context:'dbo.meeting_participants(meeting_id, person_name, duration_minutes).',
    task:'Using a self-join CTE, calculate Benjamin’s average meeting duration with each colleague.',
    starter:'WITH benjamin_meetings AS (\n    -- self join participant pairs\n)\nSELECT colleague, AVG(duration_minutes) AS avg_meeting_duration\nFROM benjamin_meetings\nGROUP BY colleague;\n',
    solution:`WITH benjamin_meetings AS (
    SELECT
        a.meeting_id,
        b.person_name AS colleague,
        a.duration_minutes
    FROM dbo.meeting_participants AS a
    INNER JOIN dbo.meeting_participants AS b
        ON a.meeting_id = b.meeting_id
    WHERE a.person_name = 'Benjamin'
      AND b.person_name <> 'Benjamin'
)
SELECT
    colleague,
    AVG(duration_minutes) AS avg_meeting_duration
FROM benjamin_meetings
GROUP BY colleague;`,
    solutionExplanation:'The CTE creates one Benjamin-colleague row per shared meeting; the outer query changes the grain to one row per colleague.',
    hints:['Solve the self join first.','Aggregate only after the colleague rows exist.'], pitfall:'Aggregating before forming participant pairs loses the relationship you need.' }),

  // CASE WHEN
  C({ id:'lab-case-raises', track:'lab-case', level:'Beginner', title:'Apply salary raises by department', sourcePack:'CASE WHEN simple use cases',
    concept:'Searched CASE evaluates conditions in order and returns the result for the first matching branch.',
    context:'dbo.employees(employee_name, department, wage). SALES +10%, HR +5%, IT +3%, everyone else unchanged.',
    task:'Return employee_name, department, wage, and wage_after_raise.',
    starter:'SELECT employee_name, department, wage,\n       CASE\n           -- department rules\n           ELSE wage\n       END AS wage_after_raise\nFROM dbo.employees;\n',
    solution:`SELECT
    employee_name,
    department,
    wage,
    CASE
        WHEN department = 'SALES' THEN wage * 1.10
        WHEN department = 'HR' THEN wage * 1.05
        WHEN department = 'IT' THEN wage * 1.03
        ELSE wage
    END AS wage_after_raise
FROM dbo.employees;`,
    solutionExplanation:'CASE creates a derived value per row. ELSE preserves the original wage for departments without a special rule.',
    hints:['Use a searched CASE.','Each WHEN returns a numeric expression.','Finish with END AS alias.'], pitfall:'Forgetting ELSE returns NULL for unmatched departments.' }),
  C({ id:'lab-case-discount-cte', track:'lab-case', level:'Intermediate', title:'Calculate discounted revenue with a CTE', sourcePack:'CASE inside aggregation',
    concept:'A CTE can make row-level business rules explicit before aggregation.',
    context:'dbo.sales(discount_code, quantity, price_per_unit). DISCOUNT10 = 10% off; DISCOUNT20 = 20% off.',
    task:'In a CTE, compute revenue_after_discount for every row, then return total revenue by discount_code.',
    starter:'WITH priced AS (\n    SELECT discount_code,\n           CASE\n               -- discount rules\n           END AS revenue_after_discount\n    FROM dbo.sales\n)\nSELECT discount_code, SUM(revenue_after_discount) AS total_revenue\nFROM priced\nGROUP BY discount_code;\n',
    solution:`WITH priced AS (
    SELECT
        discount_code,
        CASE
            WHEN discount_code = 'DISCOUNT10' THEN quantity * price_per_unit * 0.90
            WHEN discount_code = 'DISCOUNT20' THEN quantity * price_per_unit * 0.80
            ELSE quantity * price_per_unit
        END AS revenue_after_discount
    FROM dbo.sales
)
SELECT
    discount_code,
    SUM(revenue_after_discount) AS total_revenue
FROM priced
GROUP BY discount_code;`,
    solutionExplanation:'The CTE separates row-level pricing rules from the group-level SUM, which makes the logic easier to debug.',
    hints:['CASE belongs in the CTE.','SUM belongs in the outer query.'], pitfall:'Multiplying by 0.10 would keep only 10% of revenue; a 10% discount means multiply by 0.90.' }),
  C({ id:'lab-case-inside-sum', track:'lab-case', level:'Intermediate', title:'Put CASE directly inside SUM', sourcePack:'CASE inside aggregation',
    concept:'Conditional aggregation applies a CASE expression inside SUM, COUNT, AVG, or another aggregate.',
    context:'dbo.sales(discount_code, quantity, price_per_unit).',
    task:'Return total revenue by discount_code after applying the discount, without a CTE.',
    starter:'SELECT discount_code,\n       SUM(\n           CASE\n               -- row-level value\n           END\n       ) AS total_revenue\nFROM dbo.sales\nGROUP BY discount_code;\n',
    solution:`SELECT
    discount_code,
    SUM(
        CASE
            WHEN discount_code = 'DISCOUNT10' THEN quantity * price_per_unit * 0.90
            WHEN discount_code = 'DISCOUNT20' THEN quantity * price_per_unit * 0.80
            ELSE quantity * price_per_unit
        END
    ) AS total_revenue
FROM dbo.sales
GROUP BY discount_code;`,
    solutionExplanation:'CASE returns the revenue value for each row; SUM aggregates those returned values at discount_code grain.',
    hints:['Think: CASE per row, SUM across rows.','Keep the CASE entirely inside SUM(...).'], pitfall:'CASE controls the value being aggregated; it does not replace GROUP BY.' }),
  C({ id:'lab-case-salary-bands', track:'lab-case', level:'Intermediate', title:'Bucket salaries then aggregate', sourcePack:'CASE + GROUP BY CTE exercise',
    concept:'CASE can create a categorical dimension that is then used in a GROUP BY.',
    context:'dbo.employees(department, wage). Low ≤ 50000; Medium < 90000; otherwise High.',
    task:'Create salary_band in a CTE, then return department, salary_band, employee_count, and average_wage.',
    starter:'WITH banded AS (\n    SELECT department, wage,\n           CASE\n               -- bands\n           END AS salary_band\n    FROM dbo.employees\n)\nSELECT department, salary_band,\n       -- count and average\nFROM banded\nGROUP BY department, salary_band;\n',
    solution:`WITH banded AS (
    SELECT
        department,
        wage,
        CASE
            WHEN wage <= 50000 THEN 'Low'
            WHEN wage < 90000 THEN 'Medium'
            ELSE 'High'
        END AS salary_band
    FROM dbo.employees
)
SELECT
    department,
    salary_band,
    COUNT(*) AS employee_count,
    AVG(wage) AS average_wage
FROM banded
GROUP BY department, salary_band;`,
    solutionExplanation:'The CTE materializes the business classification logically; the outer query aggregates at department + band grain.',
    hints:['Order the thresholds from low to high.','COUNT(*) gives the number of employees in each group.'], pitfall:'Overlapping or incorrectly ordered WHEN conditions can classify rows into the wrong bucket.' }),
  C({ id:'lab-case-football-wins', track:'lab-case', level:'Intermediate', title:'Count home and away wins conditionally', sourcePack:'CASE football exercise',
    concept:'COUNT(CASE WHEN ... THEN 1 END) counts only rows where CASE returns a non-NULL value.',
    context:'dbo.matches(division, home_team, away_team, home_goals, away_goals). Count Lille wins in division L1.',
    task:'Return the number of Lille home wins and away wins for L1 in one query.',
    starter:'SELECT\n    COUNT(CASE WHEN -- home win THEN 1 END) AS home_wins,\n    COUNT(CASE WHEN -- away win THEN 1 END) AS away_wins\nFROM dbo.matches\nWHERE division = \'L1\';\n',
    solution:`SELECT
    COUNT(CASE
        WHEN home_team = 'Lille' AND home_goals > away_goals THEN 1
    END) AS home_wins,
    COUNT(CASE
        WHEN away_team = 'Lille' AND away_goals > home_goals THEN 1
    END) AS away_wins
FROM dbo.matches
WHERE division = 'L1';`,
    solutionExplanation:'COUNT ignores NULL. The CASE returns 1 only for a qualifying win, so each aggregate counts its own condition.',
    hints:['COUNT ignores NULL values.','Home win: Lille is home and home_goals > away_goals.','Filter the division separately in WHERE.'], pitfall:'`ELSE 0` inside COUNT would count zeros too, because zero is non-NULL. Use no ELSE, or use SUM with ELSE 0.' }),

  // GROUPING SETS
  C({ id:'lab-grouping-contract', track:'lab-grouping', level:'Beginner', title:'Baseline: reimbursements by contract type', sourcePack:'Grouping Sets',
    concept:'Before advanced grouping, be clear about the ordinary GROUP BY grain.',
    context:'dbo.reimbursements(contract_type, act_type, amount_reimbursed).',
    task:'Return total amount_reimbursed by contract_type.',
    starter:'SELECT contract_type, SUM(amount_reimbursed) AS total_reimbursed\nFROM dbo.reimbursements\nGROUP BY --\n',
    solution:`SELECT
    contract_type,
    SUM(amount_reimbursed) AS total_reimbursed
FROM dbo.reimbursements
GROUP BY contract_type;`,
    solutionExplanation:'This is the baseline aggregation that later GROUPING SETS queries will combine with other grains.',
    hints:['One output row per contract_type.'], pitfall:'Do not include act_type unless you want a finer grain.' }),
  C({ id:'lab-grouping-contract-act', track:'lab-grouping', level:'Beginner', title:'Baseline: reimbursements by contract and act', sourcePack:'Grouping Sets',
    concept:'Adding a grouping key makes the result grain more detailed.',
    context:'dbo.reimbursements(contract_type, act_type, amount_reimbursed).',
    task:'Return total amount_reimbursed for each contract_type + act_type combination.',
    starter:'SELECT contract_type, act_type, SUM(amount_reimbursed) AS total_reimbursed\nFROM dbo.reimbursements\nGROUP BY --\n',
    solution:`SELECT
    contract_type,
    act_type,
    SUM(amount_reimbursed) AS total_reimbursed
FROM dbo.reimbursements
GROUP BY contract_type, act_type;`,
    solutionExplanation:'The result now has one row per unique pair instead of one row per contract type.',
    hints:['Group by both non-aggregated columns.'], pitfall:'Changing grouping keys changes the grain and therefore the meaning of every aggregate.' }),
  C({ id:'lab-grouping-union', track:'lab-grouping', level:'Intermediate', title:'Combine two separate summaries with UNION ALL', sourcePack:'Grouping Sets precursor',
    concept:'GROUPING SETS can replace patterns that otherwise require multiple grouped queries combined with UNION ALL.',
    context:'dbo.reimbursements(contract_type, act_type, amount_reimbursed).',
    task:'Return totals by contract_type and totals by act_type as a single two-column result named typology, total_reimbursed. Use UNION ALL.',
    starter:'SELECT contract_type AS typology, SUM(amount_reimbursed) AS total_reimbursed\nFROM dbo.reimbursements\nGROUP BY contract_type\n\nUNION ALL\n\n-- second aggregation\n',
    solution:`SELECT
    contract_type AS typology,
    SUM(amount_reimbursed) AS total_reimbursed
FROM dbo.reimbursements
GROUP BY contract_type

UNION ALL

SELECT
    act_type AS typology,
    SUM(amount_reimbursed) AS total_reimbursed
FROM dbo.reimbursements
GROUP BY act_type;`,
    solutionExplanation:'Two independent groupings are computed separately and stacked. The next challenge replaces this with GROUPING SETS in one grouped query.',
    hints:['Both SELECTs must return compatible columns.','Use UNION ALL so rows are not unnecessarily deduplicated.'], pitfall:'UNION performs duplicate elimination; UNION ALL is usually the intended operation for combining grouping results.' }),
  C({ id:'lab-grouping-two-sets', track:'lab-grouping', level:'Intermediate', title:'Replace two GROUP BY queries with GROUPING SETS', sourcePack:'Grouping Sets',
    concept:'GROUPING SETS computes explicitly requested aggregation grains in one GROUP BY.',
    context:'dbo.reimbursements(contract_type, act_type, amount_reimbursed).',
    task:'Return totals by contract_type and totals by act_type using GROUPING SETS.',
    starter:'SELECT contract_type, act_type, SUM(amount_reimbursed) AS total_reimbursed\nFROM dbo.reimbursements\nGROUP BY GROUPING SETS (\n    -- two grouping sets\n);\n',
    solution:`SELECT
    contract_type,
    act_type,
    SUM(amount_reimbursed) AS total_reimbursed
FROM dbo.reimbursements
GROUP BY GROUPING SETS (
    (contract_type),
    (act_type)
);`,
    solutionExplanation:'The engine computes two grains: one where contract_type is grouped and one where act_type is grouped. The other grouping column is NULL in each subtotal row.',
    hints:['Each grouping set is written in parentheses.','You need one set for each desired grain.'], pitfall:'`(contract_type, act_type)` is one combined grain; `(contract_type), (act_type)` are two separate grains.' }),
  C({ id:'lab-grouping-region-year', track:'lab-grouping', level:'Intermediate', title:'Region/year detail plus yearly totals', sourcePack:'Grouping Sets population exercise',
    concept:'Grouping sets can produce detail and subtotal levels together.',
    context:'dbo.population(year_value, region, population).',
    task:'Return population by year + region and also total population by year.',
    starter:'SELECT year_value, region, SUM(population) AS population\nFROM dbo.population\nGROUP BY GROUPING SETS (\n    -- detail grain, yearly subtotal\n);\n',
    solution:`SELECT
    year_value,
    region,
    SUM(population) AS population
FROM dbo.population
GROUP BY GROUPING SETS (
    (year_value, region),
    (year_value)
);`,
    solutionExplanation:'The first grouping set gives regional detail; the second collapses region to produce one subtotal per year.',
    hints:['Write the most detailed grain first.','The subtotal removes region.'], pitfall:'A NULL region in subtotal rows represents “all regions,” not necessarily missing source data.' }),
  C({ id:'lab-grouping-label-subtotals', track:'lab-grouping', level:'Intermediate', title:'Label subtotal rows with GROUPING()', sourcePack:'Grouping Sets adaptation',
    concept:'GROUPING(column) distinguishes subtotal NULL placeholders from real NULL values in source data.',
    context:'dbo.population(year_value, region, population).',
    task:'Use GROUPING SETS for region/year detail and yearly totals. Return region_label = ALL REGIONS for subtotal rows.',
    starter:'SELECT year_value,\n       CASE WHEN GROUPING(region) = 1 THEN \'ALL REGIONS\' ELSE region END AS region_label,\n       SUM(population) AS population\nFROM dbo.population\nGROUP BY GROUPING SETS ((year_value, region), (year_value));\n',
    solution:`SELECT
    year_value,
    CASE
        WHEN GROUPING(region) = 1 THEN 'ALL REGIONS'
        ELSE region
    END AS region_label,
    SUM(population) AS population
FROM dbo.population
GROUP BY GROUPING SETS (
    (year_value, region),
    (year_value)
);`,
    solutionExplanation:'GROUPING(region) returns 1 when region was aggregated away by the grouping operation, so you can safely label subtotal rows.',
    hints:['Use GROUPING(region), not region IS NULL.','A real NULL region and a subtotal NULL are not the same thing.'], pitfall:'COALESCE(region, \'ALL REGIONS\') cannot distinguish a genuine source NULL from a subtotal placeholder.' }),
  C({ id:'lab-grouping-rollup', track:'lab-grouping', level:'Intermediate', title:'Create hierarchical subtotals with ROLLUP', sourcePack:'ROLLUP exercise',
    concept:'ROLLUP creates hierarchical subtotals from right to left plus a grand total.',
    context:'dbo.reimbursements(contract_type, act_type, amount_reimbursed).',
    task:'Return contract + act detail, contract subtotals, and a grand total using ROLLUP.',
    starter:'SELECT contract_type, act_type, SUM(amount_reimbursed) AS total_reimbursed\nFROM dbo.reimbursements\nGROUP BY -- rollup\n',
    solution:`SELECT
    contract_type,
    act_type,
    SUM(amount_reimbursed) AS total_reimbursed
FROM dbo.reimbursements
GROUP BY ROLLUP (contract_type, act_type);`,
    solutionExplanation:'ROLLUP(contract_type, act_type) produces (contract_type, act_type), then (contract_type), then the grand total (). Column order defines the hierarchy.',
    hints:['Use GROUP BY ROLLUP(...).','Think hierarchy: contract → act.'], pitfall:'ROLLUP column order matters; reversing it changes which subtotal hierarchy is produced.' }),
  C({ id:'lab-grouping-cube', track:'lab-grouping', level:'Intermediate', title:'Generate every subtotal combination with CUBE', sourcePack:'CUBE exercise',
    concept:'CUBE produces all combinations of the listed dimensions plus the grand total.',
    context:'dbo.reimbursements(contract_type, act_type, amount_reimbursed).',
    task:'Return contract + act detail, contract totals, act totals, and the grand total.',
    starter:'SELECT contract_type, act_type, SUM(amount_reimbursed) AS total_reimbursed\nFROM dbo.reimbursements\nGROUP BY -- cube\n',
    solution:`SELECT
    contract_type,
    act_type,
    SUM(amount_reimbursed) AS total_reimbursed
FROM dbo.reimbursements
GROUP BY CUBE (contract_type, act_type);`,
    solutionExplanation:'For two dimensions, CUBE yields four grains: (contract, act), (contract), (act), and (). It is broader than ROLLUP.',
    hints:['Use GROUP BY CUBE(...).','CUBE includes both one-dimensional subtotals.'], pitfall:'CUBE grows as 2^n grouping combinations, so many dimensions can create a large result.' }),
  C({ id:'lab-grouping-multilevel-rollup', track:'lab-grouping', level:'Expert', title:'Roll up a five-level reporting hierarchy', sourcePack:'ROLLUP real-data exercise',
    concept:'ROLLUP is efficient for a strict reporting hierarchy where each level rolls into the one to its left.',
    context:'dbo.reimbursements(contract_type, act_type, age_group, sex, year_value, amount_reimbursed).',
    task:'Produce subtotals across contract_type → act_type → age_group → sex → year_value and a grand total.',
    starter:'SELECT contract_type, act_type, age_group, sex, year_value,\n       SUM(amount_reimbursed) AS total_reimbursed\nFROM dbo.reimbursements\nGROUP BY ROLLUP (\n    -- hierarchy in order\n);\n',
    solution:`SELECT
    contract_type,
    act_type,
    age_group,
    sex,
    year_value,
    SUM(amount_reimbursed) AS total_reimbursed
FROM dbo.reimbursements
GROUP BY ROLLUP (
    contract_type,
    act_type,
    age_group,
    sex,
    year_value
);`,
    solutionExplanation:'ROLLUP progressively removes dimensions from the right, generating hierarchical totals up to the grand total. This is very different from generating every possible combination.',
    hints:['List dimensions from highest to lowest hierarchy.','ROLLUP moves from right to left.'], pitfall:'Use CUBE only if every cross-dimensional subtotal is genuinely needed; it can explode the number of groups.' }),
  C({ id:'lab-grouping-store-share', track:'lab-grouping', level:'Expert', title:'Product share of store sales with grouping sets', sourcePack:'Red Bull grouping sets exercise',
    concept:'Grouping sets can compute detail and total rows in one aggregation, then those rows can be joined or conditionally aggregated to calculate shares.',
    context:'dbo.sales(store_id, product_name, amount). Compute Red Bull sales divided by total store sales.',
    task:'Use GROUPING SETS to compute product-level and store-level totals, then return Red Bull share for each store.',
    starter:'WITH totals AS (\n    SELECT store_id, product_name, SUM(amount) AS amount\n    FROM dbo.sales\n    GROUP BY GROUPING SETS (\n        -- product detail and store total\n    )\n)\n-- join/aggregate totals to calculate Red Bull share\n',
    solution:`WITH totals AS (
    SELECT
        store_id,
        product_name,
        SUM(amount) AS amount
    FROM dbo.sales
    GROUP BY GROUPING SETS (
        (store_id, product_name),
        (store_id)
    )
), store_rollup AS (
    SELECT
        store_id,
        MAX(CASE WHEN product_name = 'Red Bull' THEN amount END) AS red_bull_sales,
        MAX(CASE WHEN product_name IS NULL THEN amount END) AS store_sales
    FROM totals
    GROUP BY store_id
)
SELECT
    store_id,
    red_bull_sales,
    store_sales,
    red_bull_sales * 1.0 / NULLIF(store_sales, 0) AS red_bull_share
FROM store_rollup;`,
    solutionExplanation:'The first CTE emits both product rows and store-total rows. The second CTE pivots the two required values into one row per store before dividing.',
    hints:['Your grouping sets are (store_id, product_name) and (store_id).','The store subtotal has product_name = NULL.','Use NULLIF to guard division by zero.'], pitfall:'Treat subtotal NULLs carefully if product_name can genuinely be NULL in source data; GROUPING(product_name) is safer in that case.' }),

  // WINDOW FUNCTIONS
  C({ id:'lab-window-sum-over', track:'lab-window', level:'Beginner', title:'Repeat a grand total on every row with OVER()', sourcePack:'Window Functions — OVER',
    concept:'An aggregate used with OVER() becomes a window aggregate: rows are retained while the aggregate is calculated across the window.',
    context:'dbo.sensor_daily(date_value, visitors_count).',
    task:'Return every row and add total_visitors containing the grand total visitors across the full table.',
    starter:'SELECT *,\n       SUM(visitors_count) -- add window\nFROM dbo.sensor_daily;\n',
    solution:`SELECT
    *,
    SUM(visitors_count) OVER () AS total_visitors
FROM dbo.sensor_daily;`,
    solutionExplanation:'Without GROUP BY, the detail rows remain. OVER() tells SQL Server to calculate the SUM over the complete result window and repeat it on each row.',
    hints:['Keep SUM.','Add OVER() after the aggregate.'], pitfall:'`SUM(visitors_count)` without OVER and without GROUP BY collapses the result to a single aggregate row.' }),
  C({ id:'lab-window-running-total', track:'lab-window', level:'Beginner', title:'Running total by date', sourcePack:'Window Functions — OVER ORDER BY',
    concept:'ORDER BY inside OVER defines the logical sequence for a running calculation.',
    context:'dbo.sensor_daily(date_value, visitors_count), one row per date.',
    task:'Add running_visitors: cumulative visitors from the first date through the current row.',
    starter:'SELECT date_value, visitors_count,\n       SUM(visitors_count) OVER (\n           -- order\n       ) AS running_visitors\nFROM dbo.sensor_daily;\n',
    solution:`SELECT
    date_value,
    visitors_count,
    SUM(visitors_count) OVER (
        ORDER BY date_value
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS running_visitors
FROM dbo.sensor_daily;`,
    solutionExplanation:'The explicit ROWS frame makes the running-total behavior deterministic by row position from the beginning through the current row.',
    hints:['Order the window by date_value.','Use UNBOUNDED PRECEDING to start at the first row.'], pitfall:'Relying on an implicit frame can be confusing when ORDER BY values contain ties; explicit ROWS is clearer.' }),
  C({ id:'lab-window-progressive-average', track:'lab-window', level:'Beginner', title:'Progressive average by date', sourcePack:'Window Functions — OVER ORDER BY',
    concept:'The same running-window structure works with AVG as well as SUM.',
    context:'dbo.sensor_daily(date_value, visitors_count).',
    task:'Add avg_visitors_to_date: average visitors from the first date through the current date.',
    starter:'SELECT date_value, visitors_count,\n       AVG(visitors_count) OVER (\n           ORDER BY date_value\n           -- frame\n       ) AS avg_visitors_to_date\nFROM dbo.sensor_daily;\n',
    solution:`SELECT
    date_value,
    visitors_count,
    AVG(visitors_count * 1.0) OVER (
        ORDER BY date_value
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS avg_visitors_to_date
FROM dbo.sensor_daily;`,
    solutionExplanation:'The frame grows one row at a time. Multiplying by 1.0 avoids integer-only averaging when the underlying type is integer.',
    hints:['Same frame as a running total.','Change SUM to AVG.'], pitfall:'The window ORDER BY is separate from the final presentation ORDER BY, although using the same key is common.' }),
  C({ id:'lab-window-centered-average', track:'lab-window', level:'Intermediate', title:'Centered five-row moving average', sourcePack:'ROWS BETWEEN exercise',
    concept:'A ROWS frame can include rows before and after the current row.',
    context:'dbo.daily_sales(date_value, daily_sales).',
    task:'Compute a five-row moving average: two rows before, current row, and two rows after.',
    starter:'SELECT date_value, daily_sales,\n       AVG(daily_sales * 1.0) OVER (\n           ORDER BY date_value\n           ROWS BETWEEN -- and --\n       ) AS moving_average\nFROM dbo.daily_sales;\n',
    solution:`SELECT
    date_value,
    daily_sales,
    AVG(daily_sales * 1.0) OVER (
        ORDER BY date_value
        ROWS BETWEEN 2 PRECEDING AND 2 FOLLOWING
    ) AS moving_average
FROM dbo.daily_sales;`,
    solutionExplanation:'The frame contains at most five physical rows centered on the current row. At the edges, SQL uses only the rows that exist.',
    hints:['Start 2 PRECEDING.','End 2 FOLLOWING.'], pitfall:'ROWS counts physical rows, not “days.” Missing dates change the business meaning unless the data is calendar-complete.' }),
  C({ id:'lab-window-seven-row-average', track:'lab-window', level:'Intermediate', title:'Trailing seven-row moving average', sourcePack:'Window Functions sensor exercise',
    concept:'A trailing frame includes a fixed number of preceding rows plus the current row.',
    context:'dbo.sensor_daily(date_value, visitors_count), one row per calendar day.',
    task:'Compute the average visitors across the current day and previous six rows.',
    starter:'SELECT *,\n       AVG(visitors_count * 1.0) OVER (\n           ORDER BY date_value\n           ROWS BETWEEN --\n       ) AS seven_day_avg\nFROM dbo.sensor_daily;\n',
    solution:`SELECT
    *,
    AVG(visitors_count * 1.0) OVER (
        ORDER BY date_value
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ) AS seven_day_avg
FROM dbo.sensor_daily;`,
    solutionExplanation:'Six preceding rows plus the current row gives a maximum frame size of seven. This corresponds to seven days only when the table has exactly one row per day.',
    hints:['Six before + current = seven rows.','Use CURRENT ROW as the end boundary.'], pitfall:'A seven-row window is not automatically a seven-day window if dates are missing or duplicated.' }),
  C({ id:'lab-window-verify-average', track:'lab-window', level:'Intermediate', title:'Verify a moving average with SUM / COUNT', sourcePack:'Window Functions verification exercise',
    concept:'AVG over a frame can be validated by calculating SUM and COUNT over the exact same frame.',
    context:'dbo.sensor_daily(date_value, visitors_count).',
    task:'Return trailing-seven-row SUM, COUNT, manual_average = SUM/COUNT, and AVG using identical frames.',
    starter:'SELECT *,\n       -- SUM window\n       -- COUNT window\n       -- manual division\n       -- AVG window\nFROM dbo.sensor_daily;\n',
    solution:`WITH w AS (
    SELECT
        *,
        SUM(visitors_count) OVER (
            ORDER BY date_value
            ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
        ) AS window_sum,
        COUNT(*) OVER (
            ORDER BY date_value
            ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
        ) AS window_count,
        AVG(visitors_count * 1.0) OVER (
            ORDER BY date_value
            ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
        ) AS window_avg
    FROM dbo.sensor_daily
)
SELECT
    *,
    window_sum * 1.0 / NULLIF(window_count, 0) AS manual_avg
FROM w;`,
    solutionExplanation:'All three functions use the same frame. The outer SELECT makes the manual calculation readable and avoids repeating the window expressions.',
    hints:['Every window must use the same ORDER BY and frame.','Use a CTE so aliases can be reused.'], pitfall:'SQL Server generally does not let you reference a SELECT-list alias in another expression in the same SELECT list.' }),
  C({ id:'lab-window-dept-average', track:'lab-window', level:'Beginner', title:'Department average without collapsing employees', sourcePack:'PARTITION BY exercise',
    concept:'PARTITION BY splits rows into independent windows while preserving every detail row.',
    context:'dbo.employees(employee_name, department, wage).',
    task:'Return every employee and add department_avg_wage.',
    starter:'SELECT *,\n       AVG(wage * 1.0) OVER (\n           PARTITION BY --\n       ) AS department_avg_wage\nFROM dbo.employees;\n',
    solution:`SELECT
    *,
    AVG(wage * 1.0) OVER (
        PARTITION BY department
    ) AS department_avg_wage
FROM dbo.employees;`,
    solutionExplanation:'Each department is its own window. Unlike GROUP BY, employees are not collapsed into one row per department.',
    hints:['Partition on department.','No window ORDER BY is required for a plain department average.'], pitfall:'GROUP BY would remove employee-level detail, which is not the requested output.' }),
  C({ id:'lab-window-dept-max', track:'lab-window', level:'Beginner', title:'Department maximum on every employee row', sourcePack:'PARTITION BY exercise',
    concept:'Window aggregates are useful for comparing each row to its group benchmark.',
    context:'dbo.employees(employee_name, department, wage).',
    task:'Add department_max_wage to every employee row.',
    starter:'SELECT *,\n       -- window MAX\nFROM dbo.employees;\n',
    solution:`SELECT
    *,
    MAX(wage) OVER (
        PARTITION BY department
    ) AS department_max_wage
FROM dbo.employees;`,
    solutionExplanation:'MAX is calculated independently in each department partition and repeated on every row in that partition.',
    hints:['Use MAX(wage).','Partition by department.'], pitfall:'No ORDER BY is needed because this is not a running maximum.' }),
  C({ id:'lab-window-top-earner-flag', track:'lab-window', level:'Intermediate', title:'Flag the highest-paid employee in each department', sourcePack:'PARTITION BY max exercise',
    concept:'A group benchmark from a window function can be compared to the current row in an outer query.',
    context:'dbo.employees(employee_name, department, wage).',
    task:'Add department_max_wage and is_top_earner (1/0).',
    starter:'WITH x AS (\n    SELECT *,\n           MAX(wage) OVER (PARTITION BY department) AS department_max_wage\n    FROM dbo.employees\n)\nSELECT *,\n       CASE WHEN -- compare wage to max -- END AS is_top_earner\nFROM x;\n',
    solution:`WITH x AS (
    SELECT
        *,
        MAX(wage) OVER (PARTITION BY department) AS department_max_wage
    FROM dbo.employees
)
SELECT
    *,
    CASE WHEN wage = department_max_wage THEN 1 ELSE 0 END AS is_top_earner
FROM x;`,
    solutionExplanation:'The CTE calculates the partition benchmark first; the outer query can then reference the alias cleanly.',
    hints:['Compute the max first.','Compare current wage to the window result in an outer query.'], pitfall:'If two employees tie for maximum wage, both should be flagged; ROW_NUMBER would arbitrarily choose one unless you add a tie-breaker.' }),
  C({ id:'lab-window-second-highest', track:'lab-window', level:'Expert', title:'Second distinct highest wage per department', sourcePack:'Window Functions second max extension',
    concept:'Ranking functions are usually clearer than repeated max-filter-max logic for nth-highest problems.',
    context:'dbo.employees(employee_name, department, wage).',
    task:'Return employees whose wage is the second distinct highest wage in their department.',
    starter:'WITH ranked AS (\n    SELECT *,\n           DENSE_RANK() OVER (\n               PARTITION BY department\n               ORDER BY wage DESC\n           ) AS wage_rank\n    FROM dbo.employees\n)\nSELECT *\nFROM ranked\nWHERE -- second rank\n',
    solution:`WITH ranked AS (
    SELECT
        *,
        DENSE_RANK() OVER (
            PARTITION BY department
            ORDER BY wage DESC
        ) AS wage_rank
    FROM dbo.employees
)
SELECT *
FROM ranked
WHERE wage_rank = 2;`,
    solutionExplanation:'DENSE_RANK assigns the same rank to equal wages and does not leave gaps, so rank 2 means the second distinct wage level.',
    hints:['Use DENSE_RANK for distinct wage levels.','Sort wages descending.','Filter in an outer query.'], pitfall:'ROW_NUMBER gives unique row positions, not distinct wage levels, so ties can change which row is “second.”' }),
  C({ id:'lab-window-weekday-partition', track:'lab-window', level:'Intermediate', title:'Compare each weekday with previous occurrences', sourcePack:'PARTITION BY weekday exercise',
    concept:'PARTITION BY can separate Mondays from Tuesdays while ORDER BY sequences occurrences inside each weekday.',
    context:'dbo.sensor_daily(date_value, weekday_number, visitors_count).',
    task:'For each row, compute the average of the current and previous six occurrences of the same weekday.',
    starter:'SELECT *,\n       AVG(visitors_count * 1.0) OVER (\n           PARTITION BY weekday_number\n           ORDER BY date_value\n           ROWS BETWEEN --\n       ) AS same_weekday_avg\nFROM dbo.sensor_daily;\n',
    solution:`SELECT
    *,
    AVG(visitors_count * 1.0) OVER (
        PARTITION BY weekday_number
        ORDER BY date_value
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ) AS same_weekday_avg
FROM dbo.sensor_daily;`,
    solutionExplanation:'Each weekday is isolated into its own time series, then the frame looks back across the previous six occurrences of that weekday.',
    hints:['Partition by weekday_number.','Order each partition by date.','Use 6 PRECEDING and CURRENT ROW.'], pitfall:'Without ORDER BY, “previous six” has no defined sequence.' }),
  C({ id:'lab-window-lag', track:'lab-window', level:'Intermediate', title:'Bring the previous same-weekday value onto the row', sourcePack:'LAG exercise',
    concept:'LAG reads a value from an earlier row in the window without a self join.',
    context:'dbo.sensor_daily(date_value, weekday_number, visitors_count).',
    task:'Add previous_same_weekday_visitors using LAG.',
    starter:'SELECT *,\n       LAG(visitors_count) OVER (\n           PARTITION BY --\n           ORDER BY --\n       ) AS previous_same_weekday_visitors\nFROM dbo.sensor_daily;\n',
    solution:`SELECT
    *,
    LAG(visitors_count) OVER (
        PARTITION BY weekday_number
        ORDER BY date_value
    ) AS previous_same_weekday_visitors
FROM dbo.sensor_daily;`,
    solutionExplanation:'Within each weekday partition, LAG returns the visitors_count from the immediately preceding date.',
    hints:['Partition by weekday.','Order by date.','LAG defaults to one row back.'], pitfall:'If you filter rows before computing LAG, you change which row is considered previous.' }),
  C({ id:'lab-window-pct-change', track:'lab-window', level:'Intermediate', title:'Week-over-week percentage change', sourcePack:'LAG percentage-change exercise',
    concept:'LAG can supply the denominator for a change calculation on the current row.',
    context:'dbo.sensor_daily(date_value, weekday_number, visitors_count).',
    task:'Compute percentage change versus the previous occurrence of the same weekday.',
    starter:'WITH x AS (\n    SELECT *,\n           LAG(visitors_count) OVER (\n               PARTITION BY weekday_number\n               ORDER BY date_value\n           ) AS previous_visitors\n    FROM dbo.sensor_daily\n)\nSELECT *,\n       -- percentage change\nFROM x;\n',
    solution:`WITH x AS (
    SELECT
        *,
        LAG(visitors_count) OVER (
            PARTITION BY weekday_number
            ORDER BY date_value
        ) AS previous_visitors
    FROM dbo.sensor_daily
)
SELECT
    *,
    (visitors_count - previous_visitors) * 1.0
        / NULLIF(previous_visitors, 0) AS pct_change
FROM x;`,
    solutionExplanation:'The CTE exposes the prior value once. The outer query calculates (current - previous) / previous and protects against division by zero.',
    hints:['Calculate LAG first.','Use NULLIF(previous_visitors, 0).','Force decimal division.'], pitfall:'The first row in each partition has no previous value, so pct_change is naturally NULL.' }),
  C({ id:'lab-window-row-number-dept', track:'lab-window', level:'Beginner', title:'Number salaries inside each department', sourcePack:'ROW_NUMBER exercise',
    concept:'ROW_NUMBER assigns a unique sequential position inside each partition according to the window ORDER BY.',
    context:'dbo.employees(employee_name, department, wage).',
    task:'Number employees from highest to lowest wage inside each department.',
    starter:'SELECT *,\n       ROW_NUMBER() OVER (\n           PARTITION BY department\n           ORDER BY --\n       ) AS wage_row_number\nFROM dbo.employees;\n',
    solution:`SELECT
    *,
    ROW_NUMBER() OVER (
        PARTITION BY department
        ORDER BY wage DESC, employee_name
    ) AS wage_row_number
FROM dbo.employees;`,
    solutionExplanation:'The numbering restarts in each department. employee_name is added as a tie-breaker so tied wages still have stable ordering.',
    hints:['Partition by department.','Highest wage should be number 1.','Add a deterministic tie-breaker if possible.'], pitfall:'ROW_NUMBER always produces unique numbers even when wages tie.' }),
  C({ id:'lab-window-row-number-sex', track:'lab-window', level:'Beginner', title:'Rank salaries separately by sex', sourcePack:'ROW_NUMBER by sex exercise',
    concept:'Changing the partition key changes where ranking restarts.',
    context:'dbo.employees(employee_name, sex, wage).',
    task:'Assign ROW_NUMBER from highest wage to lowest separately for each sex.',
    starter:'SELECT *,\n       ROW_NUMBER() OVER (\n           PARTITION BY --\n           ORDER BY wage DESC\n       ) AS wage_row_number\nFROM dbo.employees;\n',
    solution:`SELECT
    *,
    ROW_NUMBER() OVER (
        PARTITION BY sex
        ORDER BY wage DESC, employee_name
    ) AS wage_row_number
FROM dbo.employees;`,
    solutionExplanation:'PARTITION BY sex creates independent ranking sequences. The ordering then determines row position inside each sequence.',
    hints:['Ranking restarts per sex.','Sort wage descending.'], pitfall:'If no ORDER BY is provided, ROW_NUMBER is not meaningful; SQL Server requires an order_by_clause for ROW_NUMBER.' }),
  C({ id:'lab-window-dense-rank', track:'lab-window', level:'Intermediate', title:'Handle salary ties with DENSE_RANK', sourcePack:'RANK vs DENSE_RANK exercise',
    concept:'DENSE_RANK gives ties the same rank and does not leave gaps after ties.',
    context:'dbo.employees(employee_name, sex, wage).',
    task:'Return salary rank by sex so employees with equal wage share the same rank.',
    starter:'SELECT *,\n       DENSE_RANK() OVER (\n           PARTITION BY sex\n           ORDER BY wage DESC\n       ) AS wage_rank\nFROM dbo.employees;\n',
    solution:`SELECT
    *,
    DENSE_RANK() OVER (
        PARTITION BY sex
        ORDER BY wage DESC
    ) AS wage_rank
FROM dbo.employees;`,
    solutionExplanation:'If wages are 100, 90, 90, 80, DENSE_RANK returns 1, 2, 2, 3. RANK would return 1, 2, 2, 4.',
    hints:['Use DENSE_RANK, not ROW_NUMBER.','Order wage descending.'], pitfall:'Choose RANK vs DENSE_RANK based on business semantics, not personal preference.' }),
  C({ id:'lab-window-sensor-running-avg', track:'lab-window', level:'Intermediate', title:'Running average per sensor', sourcePack:'Window Functions retail sensor case',
    concept:'Multiple sensor streams should be partitioned before running calculations are ordered in time.',
    context:'dbo.sensor_daily(sensor_id, date_value, visitors_count).',
    task:'Compute running_avg_visitors independently for each sensor.',
    starter:'SELECT *,\n       AVG(visitors_count * 1.0) OVER (\n           PARTITION BY --\n           ORDER BY --\n           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW\n       ) AS running_avg_visitors\nFROM dbo.sensor_daily;\n',
    solution:`SELECT
    *,
    AVG(visitors_count * 1.0) OVER (
        PARTITION BY sensor_id
        ORDER BY date_value
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS running_avg_visitors
FROM dbo.sensor_daily;`,
    solutionExplanation:'PARTITION BY prevents one sensor’s history from contaminating another sensor’s running average.',
    hints:['Partition by sensor_id.','Order by date_value.'], pitfall:'Omitting sensor_id mixes independent time series into one calculation.' }),
  C({ id:'lab-window-sensor-weekday', track:'lab-window', level:'Intermediate', title:'Running average per sensor and weekday', sourcePack:'Correct sensor-window exercise',
    concept:'Windows can partition on multiple columns when the business series is defined by a composite key.',
    context:'dbo.sensor_daily(sensor_id, weekday_number, date_value, visitors_count).',
    task:'Compute running average visitors for each sensor + weekday series.',
    starter:'SELECT *,\n       AVG(visitors_count * 1.0) OVER (\n           PARTITION BY -- two keys\n           ORDER BY date_value\n           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW\n       ) AS running_avg_visitors\nFROM dbo.sensor_daily;\n',
    solution:`SELECT
    *,
    AVG(visitors_count * 1.0) OVER (
        PARTITION BY sensor_id, weekday_number
        ORDER BY date_value
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS running_avg_visitors
FROM dbo.sensor_daily;`,
    solutionExplanation:'Each sensor-weekday pair becomes an independent sequence, which is appropriate when comparing Saturdays only with previous Saturdays for the same sensor.',
    hints:['Use both sensor_id and weekday_number in PARTITION BY.'], pitfall:'Filtering to one weekday after computing the window is not equivalent to partitioning by weekday if the calculation itself must ignore other weekdays.' }),
  C({ id:'lab-window-updated-ranking', track:'lab-window', level:'Expert', title:'Rank sensors by their updated running average', sourcePack:'Window Functions final ranking exercise',
    concept:'Complex analytics often layer window functions: one query computes a metric, then an outer query ranks that metric.',
    context:'dbo.sensor_daily(sensor_id, weekday_number, date_value, visitors_count).',
    task:'Compute running average per sensor + weekday, then DENSE_RANK sensors for each date by that running average descending.',
    starter:'WITH moving AS (\n    -- running average per sensor + weekday\n)\nSELECT *,\n       DENSE_RANK() OVER (\n           PARTITION BY date_value\n           ORDER BY running_avg_visitors DESC\n       ) AS sensor_rank\nFROM moving;\n',
    solution:`WITH moving AS (
    SELECT
        *,
        AVG(visitors_count * 1.0) OVER (
            PARTITION BY sensor_id, weekday_number
            ORDER BY date_value
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS running_avg_visitors
    FROM dbo.sensor_daily
)
SELECT
    *,
    DENSE_RANK() OVER (
        PARTITION BY date_value
        ORDER BY running_avg_visitors DESC
    ) AS sensor_rank
FROM moving;`,
    solutionExplanation:'Window results cannot be nested directly inside another window function in the same SELECT. The CTE establishes the first window result, and the outer query performs the second window calculation.',
    hints:['First window: sensor + weekday over time.','Second window: rank sensors within each date.','Use a CTE between the two stages.'], pitfall:'Trying to nest one window function directly inside another window function is not valid T-SQL.' }),
  C({ id:'lab-window-top-one', track:'lab-window', level:'Intermediate', title:'Top-paid employee per department', sourcePack:'Window Functions ranking adaptation',
    concept:'T-SQL commonly filters ranking results in an outer query because the window value is produced after WHERE.',
    context:'dbo.employees(employee_name, department, wage).',
    task:'Return exactly one top-paid employee per department using ROW_NUMBER and a CTE.',
    starter:'WITH ranked AS (\n    SELECT *,\n           ROW_NUMBER() OVER (\n               PARTITION BY department\n               ORDER BY wage DESC, employee_name\n           ) AS rn\n    FROM dbo.employees\n)\nSELECT *\nFROM ranked\nWHERE --\n',
    solution:`WITH ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY department
            ORDER BY wage DESC, employee_name
        ) AS rn
    FROM dbo.employees
)
SELECT *
FROM ranked
WHERE rn = 1;`,
    solutionExplanation:'The ranking must be computed before it can be filtered. The CTE provides that logical stage. A tie-breaker makes the single selected row deterministic.',
    hints:['Compute rn in the CTE.','Filter rn = 1 outside.'], pitfall:'ROW_NUMBER intentionally returns one row even for tied maximum wages; use RANK/DENSE_RANK if all ties should survive.' }),
  C({ id:'lab-window-rows-vs-range', track:'lab-window', level:'Expert', title:'Understand ROWS vs RANGE with duplicate dates', sourcePack:'Window frame extension',
    concept:'ROWS frames are based on physical row positions; RANGE frames can treat peer rows with equal ORDER BY values together.',
    context:'dbo.sales_events(event_id, event_date, amount) may contain multiple rows for the same event_date.',
    task:'Write a deterministic row-by-row running total using ROWS, even when event_date is duplicated.',
    starter:'SELECT *,\n       SUM(amount) OVER (\n           ORDER BY event_date, -- tie breaker needed\n           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW\n       ) AS running_total\nFROM dbo.sales_events;\n',
    solution:`SELECT
    *,
    SUM(amount) OVER (
        ORDER BY event_date, event_id
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS running_total
FROM dbo.sales_events;`,
    solutionExplanation:'ROWS advances one physical row at a time. Adding a unique event_id tie-breaker makes the ordering deterministic when multiple rows share a date.',
    hints:['Use ROWS explicitly.','Add a unique ordering column such as event_id.'], pitfall:'Ordering only by a non-unique date leaves tied row ordering nondeterministic for row-by-row calculations.' }),
]
