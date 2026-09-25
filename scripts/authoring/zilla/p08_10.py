"""ZillaCode problems 8-10 as Datapass specs."""
from .common import code, problem, rows

# 8 -------------------------------------------------------------------------------------------------------------------
problem(
    n=8, slug="calls-per-day", title="Callers and call time per day", difficulty="easy",
    topics=["aggregation", "distinct"], industry="Telecommunications",
    tables={"calls_df": {"call_id": "INTEGER", "cust_id": "INTEGER", "date": "VARCHAR", "duration": "INTEGER"},
            "customers_df": {"cust_id": "INTEGER", "name": "VARCHAR", "state": "VARCHAR", "tenure": "INTEGER",
                             "occupation": "VARCHAR"}},
    prompt="""
        A telecom company logs calls (the date is text, 'yyyy-MM-dd') and keeps a customer list. For each date,
        return the number of distinct customers who called and the total call duration in seconds. Only calls from
        customers present in customers_df count.
    """,
    output=["date", "num_customers", "total_duration"],
    grain="One row per date with at least one call from a known customer.",
    pitfall="A customer who calls twice on the same day is one customer: COUNT(DISTINCT cust_id), not COUNT(*). "
            "Calls from unknown customers are dropped by the join, including their duration.",
    hints=["Join the calls to the customers first.", "Group by date."],
    explanation="""
        Inner join calls to customers (which drops unknown callers), then GROUP BY date with COUNT(DISTINCT cust_id)
        and SUM(duration).
    """,
    edges=[{"id": "repeat-and-unknown-callers", "tables": {
        "calls_df": rows("call_id cust_id date duration", (1, 1, "2022-02-01", 100), (2, 1, "2022-02-01", 50),
                         (3, 2, "2022-02-01", 30), (4, 9, "2022-02-01", 999), (5, 9, "2022-02-02", 10)),
        "customers_df": rows("cust_id name state tenure occupation", (1, "Alice", "NY", 10, "doctor"),
                             (2, "Bob", "CA", 12, "lawyer")),
    }}],
    sql=code("""
        SELECT c.date,
               COUNT(DISTINCT c.cust_id) AS num_customers,
               SUM(c.duration) AS total_duration
        FROM calls_df AS c
        JOIN customers_df AS cu ON c.cust_id = cu.cust_id
        GROUP BY c.date
    """),
    snowflake="same", dbt="auto",
    python=code("""
        def etl(calls_df, customers_df):
            known = calls_df.merge(customers_df[["cust_id"]], on="cust_id")
            return known.groupby("date", as_index=False).agg(
                num_customers=("cust_id", "nunique"), total_duration=("duration", "sum")
            )
    """),
    polars=code("""
        def etl(calls_df, customers_df):
            known = calls_df.join(customers_df.select("cust_id"), on="cust_id")
            return known.group_by("date").agg(
                pl.col("cust_id").n_unique().alias("num_customers"),
                pl.col("duration").sum().alias("total_duration"),
            )
    """),
    sparklab=code("""
        from pyspark.sql import functions as F

        calls = spark.table("calls_df")
        customers = spark.table("customers_df").select("cust_id")
        calls.join(customers, "cust_id").groupBy("date").agg(
            F.countDistinct("cust_id").alias("num_customers"), F.sum("duration").alias("total_duration")
        )
    """),
    mutants={
        "sql": ["SELECT c.date, COUNT(c.cust_id) AS num_customers, SUM(c.duration) AS total_duration FROM calls_df AS c JOIN customers_df AS cu ON c.cust_id = cu.cust_id GROUP BY c.date",
                "SELECT date, COUNT(DISTINCT cust_id) AS num_customers, SUM(duration) AS total_duration FROM calls_df GROUP BY date"],
    },
)

# 9 -------------------------------------------------------------------------------------------------------------------
problem(
    n=9, slug="author-numbers", title="Number the authors of each paper", difficulty="easy",
    topics=["window-functions", "semi-join"], industry="AI research",
    tables={"research_papers": {"paper_id": "VARCHAR", "title": "VARCHAR", "year": "INTEGER"},
            "authors": {"paper_id": "VARCHAR", "author_id": "VARCHAR", "name": "VARCHAR"}},
    prompt="""
        A lab tracks its research papers and their authors. For the authors of papers listed in research_papers,
        number the authors within each paper by author_id in ascending order, starting at 1. author_id is text.
    """,
    output=["paper_id", "author_id", "name", "row_number"],
    grain="One row per author row of a known paper.",
    pitfall="author_id is text, so 'A10' sorts before 'A2'. research_papers may list a paper twice: filter with "
            "IN or EXISTS (a semi-join) instead of joining, or every author is duplicated.",
    hints=["ROW_NUMBER() OVER (PARTITION BY paper_id ORDER BY author_id).",
           "Keep the authors whose paper_id appears in research_papers without joining its rows."],
    explanation="""
        A semi-join keeps each author at most once however many times the paper is listed; ROW_NUMBER numbers the
        authors of each paper in text order. ZillaCode's reference ignored research_papers; Datapass uses it as the
        list of known papers.
    """,
    changes=["Only authors of papers present in research_papers are numbered (a semi-join); ZillaCode's reference did "
             "not read research_papers."],
    edges=[{"id": "text-order-and-duplicate-paper", "tables": {
        "research_papers": rows("paper_id title year", ("P1", "Attention", 2020), ("P1", "Attention", 2020),
                                ("P2", "Graphs", 2021)),
        "authors": rows("paper_id author_id name", ("P1", "A2", "Bea"), ("P1", "A10", "Cal"), ("P1", "A1", "Ada"),
                        ("P2", "B1", "Dov"), ("P9", "Z1", "Zed")),
    }}],
    sql=code("""
        SELECT paper_id, author_id, name,
               ROW_NUMBER() OVER (PARTITION BY paper_id ORDER BY author_id) AS row_number
        FROM authors
        WHERE paper_id IN (SELECT paper_id FROM research_papers)
    """),
    snowflake="same", dbt="auto",
    python=code("""
        def etl(research_papers, authors):
            known = authors[authors["paper_id"].isin(research_papers["paper_id"])]
            known = known.sort_values(["paper_id", "author_id"]).copy()
            known["row_number"] = known.groupby("paper_id").cumcount() + 1
            return known[["paper_id", "author_id", "name", "row_number"]]
    """),
    polars=code("""
        def etl(research_papers, authors):
            known = authors.filter(pl.col("paper_id").is_in(research_papers["paper_id"].implode())).sort("paper_id", "author_id")
            return known.with_columns((pl.int_range(pl.len()).over("paper_id") + 1).alias("row_number"))
    """),
    sparklab=code("""
        from pyspark.sql import functions as F
        from pyspark.sql import Window

        authors = spark.table("authors")
        papers = spark.table("research_papers").select("paper_id")
        by_paper = Window.partitionBy("paper_id").orderBy("author_id")
        authors.join(papers, "paper_id", "semi").withColumn("row_number", F.row_number().over(by_paper))
    """),
    mutants={
        "sql": ["SELECT a.paper_id, a.author_id, a.name, ROW_NUMBER() OVER (PARTITION BY a.paper_id ORDER BY a.author_id) AS row_number FROM authors AS a JOIN research_papers AS p ON a.paper_id = p.paper_id",
                "SELECT paper_id, author_id, name, ROW_NUMBER() OVER (PARTITION BY paper_id ORDER BY name) AS row_number FROM authors WHERE paper_id IN (SELECT paper_id FROM research_papers)"],
    },
)

# 10 ------------------------------------------------------------------------------------------------------------------
problem(
    n=10, slug="product-summary", title="Sales and stock per product", difficulty="medium",
    topics=["aggregation", "left-join", "nulls"], industry="Food and beverage",
    tables={"products": {"product_id": "INTEGER", "name": "VARCHAR", "category": "VARCHAR"},
            "sales": {"sale_id": "INTEGER", "product_id": "INTEGER", "quantity": "INTEGER", "revenue": "DOUBLE"},
            "inventory": {"product_id": "INTEGER", "stock": "INTEGER", "warehouse": "VARCHAR"}},
    prompt="""
        For every product, return its name and category, the total quantity sold and revenue (over all its sales), and
        the total stock across all warehouses. A product without sales or without stock gets 0 in those columns.
    """,
    output=["product_id", "name", "category", "total_quantity", "total_revenue", "total_stock"],
    grain="One row per product.",
    pitfall="Aggregate sales and inventory separately before joining them: joining both to the product first "
            "multiplies each sale by the number of warehouses (fan-out).",
    hints=["Two aggregations (sales per product, stock per product), then two LEFT JOINs.",
           "COALESCE the missing totals to 0."],
    explanation="""
        Sales and inventory are both one-to-many from products. Pre-aggregate each to one row per product, LEFT JOIN
        both to products, and replace missing totals with 0 (COALESCE, or ZEROIFNULL in Snowflake).
    """,
    changes=["total_revenue stays a DOUBLE: the revenue data has decimals."],
    edges=[{"id": "fan-out", "tables": {
        "products": rows("product_id name category", (1, "Cola", "Beverages"), (2, "Crisps", "Snacks"),
                         (3, "Kiwi", "Fruits")),
        "sales": rows("sale_id product_id quantity revenue", (1, 1, 2, 4.0), (2, 1, 3, 6.0), (3, 2, 1, 1.5)),
        "inventory": rows("product_id stock warehouse", (1, 10, "North"), (1, 5, "South"), (3, 7, "North")),
    }}],
    sql=code("""
        WITH sold AS (
            SELECT product_id, SUM(quantity) AS total_quantity, SUM(revenue) AS total_revenue
            FROM sales
            GROUP BY product_id
        ),
        stocked AS (
            SELECT product_id, SUM(stock) AS total_stock
            FROM inventory
            GROUP BY product_id
        )
        SELECT p.product_id, p.name, p.category,
               COALESCE(s.total_quantity, 0) AS total_quantity,
               COALESCE(s.total_revenue, 0) AS total_revenue,
               COALESCE(i.total_stock, 0) AS total_stock
        FROM products AS p
        LEFT JOIN sold AS s ON p.product_id = s.product_id
        LEFT JOIN stocked AS i ON p.product_id = i.product_id
    """),
    snowflake=code("""
        WITH sold AS (
            SELECT product_id, SUM(quantity) AS total_quantity, SUM(revenue) AS total_revenue
            FROM sales
            GROUP BY product_id
        ),
        stocked AS (
            SELECT product_id, SUM(stock) AS total_stock
            FROM inventory
            GROUP BY product_id
        )
        SELECT p.product_id, p.name, p.category,
               ZEROIFNULL(s.total_quantity) AS total_quantity,
               ZEROIFNULL(s.total_revenue) AS total_revenue,
               ZEROIFNULL(i.total_stock) AS total_stock
        FROM products AS p
        LEFT JOIN sold AS s ON p.product_id = s.product_id
        LEFT JOIN stocked AS i ON p.product_id = i.product_id
    """),
    dbt="auto",
    python=code("""
        def etl(products, sales, inventory):
            sold = sales.groupby("product_id", as_index=False).agg(
                total_quantity=("quantity", "sum"), total_revenue=("revenue", "sum"))
            stocked = inventory.groupby("product_id", as_index=False).agg(total_stock=("stock", "sum"))
            result = products.merge(sold, on="product_id", how="left").merge(stocked, on="product_id", how="left")
            return result.fillna({"total_quantity": 0, "total_revenue": 0, "total_stock": 0})
    """),
    polars=code("""
        def etl(products, sales, inventory):
            sold = sales.group_by("product_id").agg(
                pl.col("quantity").sum().alias("total_quantity"), pl.col("revenue").sum().alias("total_revenue"))
            stocked = inventory.group_by("product_id").agg(pl.col("stock").sum().alias("total_stock"))
            result = products.join(sold, on="product_id", how="left").join(stocked, on="product_id", how="left")
            return result.with_columns(pl.col("total_quantity", "total_revenue", "total_stock").fill_null(0))
    """),
    sparklab=code("""
        from pyspark.sql import functions as F

        products = spark.table("products")
        sold = spark.table("sales").groupBy("product_id").agg(
            F.sum("quantity").alias("total_quantity"), F.sum("revenue").alias("total_revenue"))
        stocked = spark.table("inventory").groupBy("product_id").agg(F.sum("stock").alias("total_stock"))
        products.join(sold, "product_id", "left").join(stocked, "product_id", "left").select(
            "product_id", "name", "category",
            F.coalesce(F.col("total_quantity"), F.lit(0)).alias("total_quantity"),
            F.coalesce(F.col("total_revenue"), F.lit(0)).alias("total_revenue"),
            F.coalesce(F.col("total_stock"), F.lit(0)).alias("total_stock"),
        )
    """),
    mutants={
        "sql": ["SELECT p.product_id, p.name, p.category, COALESCE(SUM(s.quantity), 0) AS total_quantity, COALESCE(SUM(s.revenue), 0) AS total_revenue, COALESCE(SUM(i.stock), 0) AS total_stock FROM products AS p LEFT JOIN sales AS s ON p.product_id = s.product_id LEFT JOIN inventory AS i ON p.product_id = i.product_id GROUP BY p.product_id, p.name, p.category",
                "WITH sold AS (SELECT product_id, SUM(quantity) AS total_quantity, SUM(revenue) AS total_revenue FROM sales GROUP BY product_id), stocked AS (SELECT product_id, SUM(stock) AS total_stock FROM inventory GROUP BY product_id) SELECT p.product_id, p.name, p.category, s.total_quantity, s.total_revenue, i.total_stock FROM products AS p LEFT JOIN sold AS s ON p.product_id = s.product_id LEFT JOIN stocked AS i ON p.product_id = i.product_id"],
    },
)
