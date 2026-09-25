"""ZillaCode problems 1-7 as Datapass specs."""
from .common import code, problem, rows

# 1 -------------------------------------------------------------------------------------------------------------------
VIDEOS = {"video_id": "INTEGER", "title": "VARCHAR", "genre": "VARCHAR", "release_year": "INTEGER",
          "duration": "INTEGER", "view_count": "BIGINT"}
problem(
    n=1, slug="popular-videos", title="Popular recent videos", difficulty="easy", topics=["filtering"],
    industry="Video streaming",
    tables={"input_df": VIDEOS},
    prompt="""
        A video streaming platform keeps one row per video in `input_df`. Return the videos that have more than
        1,000,000 views and were released in the last five years, taking 2024 as the current year: release years
        2019 to 2024. Keep the input's columns.
    """,
    output=list(VIDEOS), grain="One row per qualifying video; duplicate input rows stay duplicated.",
    pitfall="The view threshold is strict (exactly 1,000,000 views does not qualify) while 2019 is inside the window. "
            "A NULL view count is never above the threshold.",
    hints=["Filter rows; there is nothing to aggregate.", "Write the window as release_year >= 2024 - 5."],
    explanation="""
        A row filter with two conditions. The boundaries are the lesson: `view_count > 1000000` is strict and
        `release_year >= 2019` is inclusive. Comparisons with NULL are unknown, so a video without a view count is
        filtered out in every engine.
    """,
    changes=["Output columns keep the input order (ZillaCode's printed sample sorted them alphabetically)."],
    edges=[{"id": "boundaries", "tables": {"input_df": rows(
        "video_id title genre release_year duration view_count",
        (21, "Exactly a million", "Drama", 2023, 100, 1000000),
        (22, "Just above", "Drama", 2019, 101, 1000001),
        (23, "Too old", "Action", 2018, 102, 9000000),
        (24, "No count", "Action", 2022, 103, None),
        (22, "Just above", "Drama", 2019, 101, 1000001),
    )}}],
    sql=code("""
        SELECT video_id, title, genre, release_year, duration, view_count
        FROM input_df
        WHERE view_count > 1000000
          AND release_year >= 2024 - 5
    """),
    snowflake="same", dbt="auto",
    python=code("""
        def etl(input_df):
            recent = input_df[(input_df["view_count"] > 1_000_000) & (input_df["release_year"] >= 2024 - 5)]
            return recent[["video_id", "title", "genre", "release_year", "duration", "view_count"]]
    """),
    polars=code("""
        def etl(input_df):
            return input_df.filter(
                (pl.col("view_count") > 1_000_000) & (pl.col("release_year") >= 2024 - 5)
            ).select("video_id", "title", "genre", "release_year", "duration", "view_count")
    """),
    sparklab=code("""
        from pyspark.sql import functions as F

        videos = spark.table("input_df")
        videos.filter((F.col("view_count") > 1000000) & (F.col("release_year") >= 2019)).select(
            "video_id", "title", "genre", "release_year", "duration", "view_count"
        )
    """),
    mutants={
        "sql": ["SELECT video_id, title, genre, release_year, duration, view_count FROM input_df WHERE view_count >= 1000000 AND release_year >= 2019",
                "SELECT video_id, title, genre, release_year, duration, view_count FROM input_df WHERE view_count > 1000000 AND release_year > 2019"],
        "sparklab": ["from pyspark.sql import functions as F\nvideos = spark.table(\"input_df\")\nvideos.filter((F.col(\"view_count\") > 1000000) & (F.col(\"release_year\") >= 2019)).select(\"video_id\", \"title\", \"genre\", \"release_year\", \"duration\", \"view_count\").distinct()\n"],
    },
)

# 2 -------------------------------------------------------------------------------------------------------------------
problem(
    n=2, slug="crm-orders", title="CRM order report", difficulty="easy", topics=["joins", "strings"],
    industry="CRM software",
    tables={"customers": {"customer_id": "INTEGER", "first_name": "VARCHAR", "last_name": "VARCHAR", "email": "VARCHAR"},
            "orders": {"order_id": "INTEGER", "customer_id": "INTEGER", "product_id": "INTEGER", "order_date": "DATE"},
            "products": {"product_id": "INTEGER", "product_name": "VARCHAR", "category": "VARCHAR"}},
    prompt="""
        A CRM application stores customers, orders and products. Return one row per order with the customer's name
        (first and last name separated by a space), the customer's email, the product's name and category, and the
        order date. Orders whose customer or product is unknown are left out.
    """,
    output=["order_id", "customer_name", "customer_email", "product_name", "product_category", "order_date"],
    grain="One row per order that matches a customer and a product.",
    pitfall="If a name part is NULL, customer_name is NULL: string concatenation propagates NULL in SQL, pandas and "
            "Polars, but DuckDB's concat_ws (and Spark's) silently skip NULL arguments and would return 'Bo'.",
    hints=["Join orders to customers and to products with inner joins.",
           "Rename email and category to the requested output names."],
    explanation="""
        Two inner joins keyed on customer_id and product_id, then a projection that builds customer_name with `||`
        (NULL-propagating) and renames the columns to the output contract.
    """,
    changes=["The output uses the statement's names customer_email and product_category; ZillaCode's reference had "
             "kept email and category."],
    zilla_output={"customer_email": "email", "product_category": "category"},
    edges=[{"id": "missing-keys-and-null-name", "tables": {
        "customers": rows("customer_id first_name last_name email", (1, "Ann", "Lee", "ann@example.com"),
                          (2, "Bo", None, "bo@example.com")),
        "orders": rows("order_id customer_id product_id order_date", (10, 1, 100, "2024-01-02"),
                       (11, 2, 100, "2024-01-03"), (12, 1, 999, "2024-01-04"), (13, 3, 100, "2024-01-05")),
        "products": rows("product_id product_name category", (100, "Mop", "Cleaning")),
    }}],
    sql=code("""
        SELECT o.order_id,
               c.first_name || ' ' || c.last_name AS customer_name,
               c.email AS customer_email,
               p.product_name,
               p.category AS product_category,
               o.order_date
        FROM orders AS o
        JOIN customers AS c ON o.customer_id = c.customer_id
        JOIN products AS p ON o.product_id = p.product_id
    """),
    snowflake="same", dbt="auto",
    python=code("""
        def etl(customers, orders, products):
            joined = orders.merge(customers, on="customer_id").merge(products, on="product_id")
            joined["customer_name"] = joined["first_name"] + " " + joined["last_name"]
            joined = joined.rename(columns={"email": "customer_email", "category": "product_category"})
            return joined[["order_id", "customer_name", "customer_email", "product_name", "product_category", "order_date"]]
    """),
    polars=code("""
        def etl(customers, orders, products):
            joined = orders.join(customers, on="customer_id").join(products, on="product_id")
            return joined.select(
                "order_id",
                (pl.col("first_name") + " " + pl.col("last_name")).alias("customer_name"),
                pl.col("email").alias("customer_email"),
                "product_name",
                pl.col("category").alias("product_category"),
                "order_date",
            )
    """),
    mutants={
        "sql": ["SELECT o.order_id, concat_ws(' ', c.first_name, c.last_name) AS customer_name, c.email AS customer_email, p.product_name, p.category AS product_category, o.order_date FROM orders AS o JOIN customers AS c ON o.customer_id = c.customer_id JOIN products AS p ON o.product_id = p.product_id",
                "SELECT o.order_id, c.first_name || ' ' || c.last_name AS customer_name, c.email AS customer_email, p.product_name, p.category AS product_category, o.order_date FROM orders AS o JOIN customers AS c ON o.customer_id = c.customer_id LEFT JOIN products AS p ON o.product_id = p.product_id"],
    },
)

# 3 -------------------------------------------------------------------------------------------------------------------
problem(
    n=3, slug="landlord-income", title="Rental income per landlord", difficulty="medium",
    topics=["aggregation", "deduplication", "joins"], industry="Property management",
    tables={"properties_df": {"property_id": "INTEGER", "landlord_id": "INTEGER", "property_type": "VARCHAR",
                              "rent": "DOUBLE", "square_feet": "INTEGER", "city": "VARCHAR"},
            "landlords_df": {"landlord_id": "INTEGER", "first_name": "VARCHAR", "last_name": "VARCHAR",
                             "email": "VARCHAR", "phone": "VARCHAR"}},
    prompt="""
        A property manager keeps the properties it manages and their landlords. Return, for each landlord who owns at
        least one property, the landlord's full name (first and last name separated by a space) and the total monthly
        rent of their properties. The feeds may contain exact duplicate rows (the same record loaded twice): count each
        property and each landlord once. Properties whose landlord is not in landlords_df are left out.
    """,
    output=["landlord_id", "landlord_name", "total_rental_income"],
    grain="One row per landlord with at least one property.",
    pitfall="Joining before removing duplicate rows multiplies the rent: a landlord listed twice doubles its income. "
            "A NULL rent is ignored by SUM, not treated as a missing total.",
    hints=["Remove exact duplicate rows from both tables first (DISTINCT, drop_duplicates, unique).",
           "Aggregate the rent per landlord before joining the names."],
    explanation="""
        Deduplicate each feed, sum the rent per landlord, then join the landlord names. Summing after the join would
        count every property once per matching landlord row. ZillaCode's reference pivoted the rent by property type
        first; the total is the same, so Datapass sums directly.
    """,
    changes=["The statement's warning about duplicates became a contract: exact duplicate rows count once (ZillaCode's "
             "reference summed them)."],
    edges=[{"id": "duplicates-and-null-rent", "tables": {
        "properties_df": rows("property_id landlord_id property_type rent square_feet city",
                              (1, 101, "Apartment", 1000.0, 700, "Seattle"), (1, 101, "Apartment", 1000.0, 700, "Seattle"),
                              (2, 101, "Condo", None, 500, "Seattle"), (3, 102, "House", 2000.0, 1500, "Tacoma"),
                              (4, 103, "House", 500.0, 900, "Everett")),
        "landlords_df": rows("landlord_id first_name last_name email phone",
                             (101, "John", "Smith", "john@example.com", "555-0101"),
                             (101, "John", "Smith", "john@example.com", "555-0101"),
                             (102, "Jane", "Doe", "jane@example.com", "555-0102"),
                             (104, "Mary", "Major", "mary@example.com", "555-0104")),
    }}],
    sql=code("""
        WITH properties AS (SELECT DISTINCT * FROM properties_df),
             landlords AS (SELECT DISTINCT * FROM landlords_df),
             income AS (
                 SELECT landlord_id, SUM(rent) AS total_rental_income
                 FROM properties
                 GROUP BY landlord_id
             )
        SELECT l.landlord_id,
               l.first_name || ' ' || l.last_name AS landlord_name,
               i.total_rental_income
        FROM income AS i
        JOIN landlords AS l ON i.landlord_id = l.landlord_id
    """),
    snowflake="same", dbt="auto",
    python=code("""
        def etl(properties_df, landlords_df):
            income = (properties_df.drop_duplicates()
                      .groupby("landlord_id", as_index=False)["rent"].sum()
                      .rename(columns={"rent": "total_rental_income"}))
            result = income.merge(landlords_df.drop_duplicates(), on="landlord_id")
            result["landlord_name"] = result["first_name"] + " " + result["last_name"]
            return result[["landlord_id", "landlord_name", "total_rental_income"]]
    """),
    polars=code("""
        def etl(properties_df, landlords_df):
            income = properties_df.unique().group_by("landlord_id").agg(pl.col("rent").sum().alias("total_rental_income"))
            return income.join(landlords_df.unique(), on="landlord_id").select(
                "landlord_id",
                (pl.col("first_name") + " " + pl.col("last_name")).alias("landlord_name"),
                "total_rental_income",
            )
    """),
    mutants={
        "sql": ["SELECT l.landlord_id, l.first_name || ' ' || l.last_name AS landlord_name, SUM(p.rent) AS total_rental_income FROM properties_df AS p JOIN landlords_df AS l ON p.landlord_id = l.landlord_id GROUP BY l.landlord_id, l.first_name, l.last_name"],
        "python": [code("""
            def etl(properties_df, landlords_df):
                income = properties_df.groupby("landlord_id", as_index=False)["rent"].sum().rename(columns={"rent": "total_rental_income"})
                result = income.merge(landlords_df.drop_duplicates(), on="landlord_id")
                result["landlord_name"] = result["first_name"] + " " + result["last_name"]
                return result[["landlord_id", "landlord_name", "total_rental_income"]]
        """)],
    },
)

# 4 -------------------------------------------------------------------------------------------------------------------
problem(
    n=4, slug="pii-masking", title="Mask personal data", difficulty="easy", topics=["strings", "nulls"],
    industry="Social media",
    tables={"input_df": {"user_id": "INTEGER", "email": "VARCHAR", "phone": "BIGINT"}},
    prompt="""
        A social media company must stop exposing personal data. For every user, return the domain of the email
        address (the text after '@') and the phone number as text with its first six digits replaced by six asterisks
        (phone numbers have ten digits, so 5551234567 becomes ******4567). A missing email or phone stays missing.
    """,
    output=["user_id", "email_domain", "anon_phone"],
    grain="One row per input row.",
    pitfall="A missing phone must give a NULL anon_phone. DuckDB's concat() skips NULL arguments and returns "
            "'******', and in pandas a NULL turns the integer column into floats, so str() gives '5551234567.0'.",
    hints=["Cast the phone to text before cutting it.", "Split the email on '@' and keep the second part."],
    explanation="""
        Two string transformations. The phone is an integer, so convert it to text first; keep NULL-propagating
        concatenation (`||` in SQL) so an unknown phone stays unknown.
    """,
    changes=["A NULL email or phone now has a defined result (NULL); ZillaCode's references did not handle NULLs."],
    edges=[{"id": "missing-values", "tables": {"input_df": rows(
        "user_id email phone", (7, "gus@example.org", None), (8, None, 5550001111), (9, "ivy@mail.example.com", 5559990000),
    )}}],
    sql=code("""
        SELECT user_id,
               split_part(email, '@', 2) AS email_domain,
               '******' || substr(CAST(phone AS VARCHAR), 7) AS anon_phone
        FROM input_df
    """),
    snowflake="same", dbt="auto",
    python=code("""
        def etl(input_df):
            def mask(phone):
                return None if pd.isna(phone) else "******" + str(int(phone))[6:]

            return pd.DataFrame({
                "user_id": input_df["user_id"],
                "email_domain": input_df["email"].str.split("@").str[1],
                "anon_phone": input_df["phone"].map(mask),
            })
    """),
    polars=code("""
        def etl(input_df):
            return input_df.select(
                "user_id",
                pl.col("email").str.split("@").list.get(1).alias("email_domain"),
                (pl.lit("******") + pl.col("phone").cast(pl.Utf8).str.slice(6)).alias("anon_phone"),
            )
    """),
    mutants={
        "sql": ["SELECT user_id, split_part(email, '@', 2) AS email_domain, concat('******', substr(CAST(phone AS VARCHAR), 7)) AS anon_phone FROM input_df"],
        "python": [code("""
            def etl(input_df):
                return pd.DataFrame({
                    "user_id": input_df["user_id"],
                    "email_domain": input_df["email"].str.split("@").str[1],
                    "anon_phone": "******" + input_df["phone"].astype(str).str[6:],
                })
        """)],
    },
)

# 5 -------------------------------------------------------------------------------------------------------------------
problem(
    n=5, slug="category-orders", title="Average price and orders per category", difficulty="easy",
    topics=["aggregation", "joins"], industry="E-commerce",
    tables={"products_df": {"product_id": "INTEGER", "category": "VARCHAR", "price": "DOUBLE"},
            "orders_df": {"order_id": "INTEGER", "product_id": "INTEGER", "quantity": "INTEGER"}},
    prompt="""
        An e-commerce platform has products (with a category and a price) and orders (one product per order). For
        each category that has at least one order, return the average price over the category's orders (a product
        ordered twice counts twice) and the number of orders. Orders for unknown products are ignored.
    """,
    output=["category", "avg_price", "total_orders_count"],
    grain="One row per category with at least one order.",
    pitfall="avg_price is averaged over the joined order rows, not over the catalog: a product nobody ordered does "
            "not count, and a product ordered twice weighs twice.",
    hints=["Join orders to products first, then group by category.", "Count orders, not products."],
    explanation="""
        Inner join orders to products, then one GROUP BY category with AVG(price) and COUNT(order_id). Averaging the
        products table instead gives a different number as soon as order counts differ between products.
    """,
    edges=[{"id": "unordered-and-unknown", "tables": {
        "products_df": rows("product_id category price", (1, "Garden", 10.0), (2, "Garden", 30.0), (3, "Kitchen", 99.0)),
        "orders_df": rows("order_id product_id quantity", (1, 1, 1), (2, 1, 5), (3, 1, 2), (4, 2, 1), (5, 42, 1)),
    }}],
    sql=code("""
        SELECT p.category,
               AVG(p.price) AS avg_price,
               COUNT(o.order_id) AS total_orders_count
        FROM orders_df AS o
        JOIN products_df AS p ON o.product_id = p.product_id
        GROUP BY p.category
    """),
    snowflake="same", dbt="auto",
    python=code("""
        def etl(products_df, orders_df):
            joined = orders_df.merge(products_df, on="product_id")
            return joined.groupby("category", as_index=False).agg(
                avg_price=("price", "mean"), total_orders_count=("order_id", "count")
            )
    """),
    polars=code("""
        def etl(products_df, orders_df):
            joined = orders_df.join(products_df, on="product_id")
            return joined.group_by("category").agg(
                pl.col("price").mean().alias("avg_price"),
                pl.col("order_id").count().alias("total_orders_count"),
            )
    """),
    sparklab=code("""
        from pyspark.sql import functions as F

        orders = spark.table("orders_df")
        products = spark.table("products_df")
        orders.join(products, "product_id").groupBy("category").agg(
            F.avg("price").alias("avg_price"), F.count("order_id").alias("total_orders_count")
        )
    """),
    mutants={
        "sql": ["SELECT p.category, AVG(p.price) AS avg_price, COUNT(o.order_id) AS total_orders_count FROM products_df AS p LEFT JOIN orders_df AS o ON o.product_id = p.product_id GROUP BY p.category"],
        "sparklab": ["from pyspark.sql import functions as F\norders = spark.table(\"orders_df\")\nproducts = spark.table(\"products_df\")\nproducts.join(orders, \"product_id\", \"left\").groupBy(\"category\").agg(F.avg(\"price\").alias(\"avg_price\"), F.count(\"order_id\").alias(\"total_orders_count\"))\n"],
    },
)

# 6 -------------------------------------------------------------------------------------------------------------------
POSTS = {"id": "INTEGER", "text": "VARCHAR", "date": "VARCHAR", "likes": "INTEGER", "comments": "INTEGER",
         "shares": "INTEGER", "platform": "VARCHAR"}
problem(
    n=6, slug="replace-word", title="Replace a word in posts", difficulty="easy", topics=["strings"],
    industry="Social media",
    tables={"social_media": POSTS},
    prompt="""
        Return the social media posts unchanged except for their text, where every occurrence of the word
        "Python" is replaced by "PySpark". The replacement is case-sensitive: "python" stays as it is.
    """,
    output=list(POSTS), grain="One row per post.",
    pitfall="Replace every occurrence: DuckDB's regexp_replace without the 'g' flag and Polars' str.replace change only "
            "the first one. (Snowflake's REGEXP_REPLACE replaces all by default.)",
    hints=["A plain string replace is enough; no regular expression is needed.",
           "Keep the other columns and their order."],
    explanation="""
        replace(text, 'Python', 'PySpark') replaces all occurrences in DuckDB and Snowflake. Regex functions differ:
        DuckDB's regexp_replace needs the 'g' flag and Polars needs str.replace_all.
    """,
    changes=["The date stays text, as in the statement."],
    edges=[{"id": "twice-and-lowercase", "tables": {"social_media": rows(
        "id text date likes comments shares platform",
        (31, "Python and Python again", "2022-04-01", 5, 1, 0, "Twitter"),
        (32, "python in lower case", "2022-04-02", 6, 2, 1, "Facebook"),
        (33, None, "2022-04-03", 7, 0, 0, "Instagram"),
    )}}],
    sql=code("""
        SELECT id, replace(text, 'Python', 'PySpark') AS text, date, likes, comments, shares, platform
        FROM social_media
    """),
    snowflake="same", dbt="auto",
    python=code("""
        def etl(social_media):
            return social_media.assign(text=social_media["text"].str.replace("Python", "PySpark", regex=False))
    """),
    polars=code("""
        def etl(social_media):
            return social_media.with_columns(pl.col("text").str.replace_all("Python", "PySpark", literal=True))
    """),
    mutants={
        "sql": ["SELECT id, regexp_replace(text, 'Python', 'PySpark') AS text, date, likes, comments, shares, platform FROM social_media"],
        "polars": [code("""
            def etl(social_media):
                return social_media.with_columns(pl.col("text").str.replace("Python", "PySpark", literal=True))
        """)],
    },
)

# 7 -------------------------------------------------------------------------------------------------------------------
problem(
    n=7, slug="top-products", title="Top products per category without gaps", difficulty="medium",
    topics=["window-functions", "ranking", "aggregation"], industry="Manufacturing",
    tables={"products": {"product_id": "INTEGER", "category": "VARCHAR", "product_name": "VARCHAR"},
            "sales": {"sale_id": "INTEGER", "product_id": "INTEGER", "quantity": "INTEGER", "revenue": "DOUBLE"}},
    prompt="""
        A manufacturer wants its best products. Compute each product's revenue (the sum of its sales), rank products
        within their category by revenue, highest first, with no gaps in the ranking (tied products share a rank and
        the next rank follows immediately), and return the products ranked 1 to 3 in each category. Products without
        sales are not ranked.
    """,
    output=["category", "product_name", "revenue", "rank"],
    grain="One row per product with a rank of 3 or better; ties can return more than three products per category.",
    pitfall="Without gaps means DENSE_RANK: with RANK, two products tied at the top push the next one to rank 3; "
            "ROW_NUMBER breaks ties arbitrarily and drops tied products.",
    hints=["Sum the revenue per product before ranking.", "Rank within the category: PARTITION BY category."],
    explanation="""
        Aggregate sales per product, join the product attributes, then DENSE_RANK() OVER (PARTITION BY category
        ORDER BY revenue DESC) and keep ranks up to 3. Snowflake can filter the window in the same SELECT with
        QUALIFY.
    """,
    changes=["revenue stays a DOUBLE (the statement said integer, the data has decimals); ties are part of the "
             "hidden checks."],
    edges=[{"id": "ties", "tables": {
        "products": rows("product_id category product_name", (1, "A", "Anvil"), (2, "A", "Bolt"), (3, "A", "Clamp"),
                         (4, "A", "Drill"), (5, "A", "Easel"), (6, "B", "File"), (7, "B", "Gauge")),
        "sales": rows("sale_id product_id quantity revenue", (1, 1, 1, 100.0), (2, 2, 1, 60.0), (3, 2, 1, 40.0),
                      (4, 3, 1, 80.0), (5, 4, 1, 70.0), (6, 5, 1, 10.0), (7, 6, 1, 5.0), (8, 7, 1, 5.0)),
    }}],
    sql=code("""
        WITH product_revenue AS (
            SELECT p.category, p.product_name, SUM(s.revenue) AS revenue
            FROM products AS p
            JOIN sales AS s ON p.product_id = s.product_id
            GROUP BY p.product_id, p.category, p.product_name
        ),
        ranked AS (
            SELECT category, product_name, revenue,
                   DENSE_RANK() OVER (PARTITION BY category ORDER BY revenue DESC) AS rank
            FROM product_revenue
        )
        SELECT category, product_name, revenue, rank
        FROM ranked
        WHERE rank <= 3
    """),
    snowflake=code("""
        SELECT p.category,
               p.product_name,
               SUM(s.revenue) AS revenue,
               DENSE_RANK() OVER (PARTITION BY p.category ORDER BY SUM(s.revenue) DESC) AS rank
        FROM products AS p
        JOIN sales AS s ON p.product_id = s.product_id
        GROUP BY p.product_id, p.category, p.product_name
        QUALIFY rank <= 3
    """),
    dbt="auto",
    python=code("""
        def etl(products, sales):
            revenue = sales.groupby("product_id", as_index=False)["revenue"].sum()
            ranked = products.merge(revenue, on="product_id")
            ranked["rank"] = ranked.groupby("category")["revenue"].rank(method="dense", ascending=False).astype(int)
            return ranked[ranked["rank"] <= 3][["category", "product_name", "revenue", "rank"]]
    """),
    polars=code("""
        def etl(products, sales):
            revenue = sales.group_by("product_id").agg(pl.col("revenue").sum())
            ranked = products.join(revenue, on="product_id").with_columns(
                pl.col("revenue").rank("dense", descending=True).over("category").alias("rank")
            )
            return ranked.filter(pl.col("rank") <= 3).select("category", "product_name", "revenue", "rank")
    """),
    mutants={
        "sql": ["WITH r AS (SELECT p.category, p.product_name, SUM(s.revenue) AS revenue FROM products AS p JOIN sales AS s ON p.product_id = s.product_id GROUP BY p.product_id, p.category, p.product_name), k AS (SELECT category, product_name, revenue, RANK() OVER (PARTITION BY category ORDER BY revenue DESC) AS rank FROM r) SELECT category, product_name, revenue, rank FROM k WHERE rank <= 3",
                "WITH r AS (SELECT p.category, p.product_name, SUM(s.revenue) AS revenue FROM products AS p JOIN sales AS s ON p.product_id = s.product_id GROUP BY p.product_id, p.category, p.product_name), k AS (SELECT category, product_name, revenue, ROW_NUMBER() OVER (PARTITION BY category ORDER BY revenue DESC) AS rank FROM r) SELECT category, product_name, revenue, rank FROM k WHERE rank <= 3"],
        "snowflake": ["SELECT p.category, p.product_name, SUM(s.revenue) AS revenue, RANK() OVER (PARTITION BY p.category ORDER BY SUM(s.revenue) DESC) AS rank FROM products AS p JOIN sales AS s ON p.product_id = s.product_id GROUP BY p.product_id, p.category, p.product_name QUALIFY rank <= 3"],
    },
)
