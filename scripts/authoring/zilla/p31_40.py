"""ZillaCode problems 31-40 as Datapass specs."""
from .common import code, problem, rows

# 31 ------------------------------------------------------------------------------------------------------------------
problem(
    n=31, slug="weekend-orders", title="Weekend orders from text dates", difficulty="medium",
    topics=["dates", "nulls", "joins"], industry="E-commerce",
    tables={"df_orders": {"order_id": "VARCHAR", "product_id": "VARCHAR", "user_id": "VARCHAR", "order_date": "VARCHAR"},
            "df_products": {"product_id": "VARCHAR", "product_name": "VARCHAR", "category": "VARCHAR"}},
    prompt="""
        Orders store their date as text in 'MM/DD/YYYY' format, and some dates are wrong. Return one row per order line
        with the user, the product's name and category, the original order_date text, and is_weekend: true for a
        Saturday or Sunday, false for another day, and NULL when order_date is not a valid 'MM/DD/YYYY' date (the order
        is kept). Order lines of unknown products are left out.
    """,
    output=["user_id", "product_name", "category", "order_date", "is_weekend"],
    grain="One row per order line with a known product.",
    pitfall="Day numbering differs: DuckDB and Snowflake's DAYOFWEEK give Sunday = 0 and Saturday = 6, pandas' "
            "dayofweek gives Monday = 0 and Sunday = 6, Polars' weekday() Monday = 1 and Sunday = 7. A failed parse is "
            "NULL (NaT), and comparing it must not turn into false.",
    hints=["Parse with a format and a safe function: try_strptime (DuckDB), TRY_TO_DATE(x, 'MM/DD/YYYY') (Snowflake).",
           "Keep order_date as the original text in the output."],
    explanation="""
        Parse the text date safely, then test the day of week with the engine's own numbering. An unparseable date
        stays NULL through the comparison, so is_weekend is NULL rather than false.
    """,
    changes=["An invalid date keeps its order line with a NULL is_weekend (the statement asked to handle wrong formats "
             "without a rule). order_id is text, as the statement says. is_weekend is a Boolean (CodeDELeet's "
             "correction of ZillaCode's 0/1)."],
    edges=[{"id": "weekdays-and-bad-dates", "tables": {
        "df_orders": rows("order_id product_id user_id order_date", ("1", "P1", "U1", "03/04/2023"),
                          ("2", "P1", "U1", "03/05/2023"), ("3", "P2", "U2", "03/03/2023"),
                          ("4", "P2", "U2", "02/30/2023"), ("5", "P1", "U3", "2023-03-04"), ("6", "P9", "U3", "03/04/2023")),
        "df_products": rows("product_id product_name category", ("P1", "Lamp", "Home"), ("P2", "Book", "Books")),
    }}],
    sql=code("""
        SELECT o.user_id, p.product_name, p.category, o.order_date,
               dayofweek(try_strptime(o.order_date, '%m/%d/%Y')) IN (0, 6) AS is_weekend
        FROM df_orders AS o
        JOIN df_products AS p ON o.product_id = p.product_id
    """),
    snowflake=code("""
        SELECT o.user_id, p.product_name, p.category, o.order_date,
               DAYOFWEEK(TRY_TO_DATE(o.order_date, 'MM/DD/YYYY')) IN (0, 6) AS is_weekend
        FROM df_orders AS o
        JOIN df_products AS p ON o.product_id = p.product_id
    """),
    dbt="auto",
    python=code("""
        def etl(df_orders, df_products):
            joined = df_orders.merge(df_products, on="product_id")
            dates = pd.to_datetime(joined["order_date"], format="%m/%d/%Y", errors="coerce")
            weekend = dates.dt.dayofweek.isin([5, 6]).astype(object)
            joined["is_weekend"] = weekend.where(dates.notna(), None)
            return joined[["user_id", "product_name", "category", "order_date", "is_weekend"]]
    """),
    polars=code("""
        def etl(df_orders, df_products):
            day = pl.col("order_date").str.to_date("%m/%d/%Y", strict=False).dt.weekday()
            return df_orders.join(df_products, on="product_id").select(
                "user_id", "product_name", "category", "order_date", (day >= 6).alias("is_weekend"))
    """),
    mutants={
        "sql": ["SELECT o.user_id, p.product_name, p.category, o.order_date, dayofweek(try_strptime(o.order_date, '%m/%d/%Y')) IN (5, 6) AS is_weekend FROM df_orders AS o JOIN df_products AS p ON o.product_id = p.product_id",
                "SELECT o.user_id, p.product_name, p.category, o.order_date, COALESCE(dayofweek(try_strptime(o.order_date, '%m/%d/%Y')) IN (0, 6), FALSE) AS is_weekend FROM df_orders AS o JOIN df_products AS p ON o.product_id = p.product_id"],
        "snowflake": ["SELECT o.user_id, p.product_name, p.category, o.order_date, DAYOFWEEKISO(TRY_TO_DATE(o.order_date, 'MM/DD/YYYY')) IN (0, 6) AS is_weekend FROM df_orders AS o JOIN df_products AS p ON o.product_id = p.product_id"],
        "python": [code("""
            def etl(df_orders, df_products):
                joined = df_orders.merge(df_products, on="product_id")
                dates = pd.to_datetime(joined["order_date"], format="%m/%d/%Y", errors="coerce")
                joined["is_weekend"] = dates.dt.dayofweek >= 5
                return joined[["user_id", "product_name", "category", "order_date", "is_weekend"]]
        """)],
    },
)

# 32 ------------------------------------------------------------------------------------------------------------------
problem(
    n=32, slug="anomalous-rides", title="Rides with anomalous ratings", difficulty="medium",
    topics=["aggregation", "cross-join", "conditional-logic"], industry="Amusement parks",
    tables={"rides": {"ride_id": "VARCHAR", "ride_name": "VARCHAR", "type": "VARCHAR", "capacity": "INTEGER"},
            "visitors": {"visitor_id": "VARCHAR", "ride_id": "VARCHAR", "timestamp": "VARCHAR", "rating": "INTEGER"}},
    prompt="""
        For each ride that has ratings, return its average rating and is_anomalous: true when that average is below
        half, or above one and a half times, the overall average. The overall average is the average of the rides'
        averages (each ride weighs the same), over the rides of the rides table. Ratings of unknown rides are ignored;
        a NULL rating is not a rating.
    """,
    output=["ride_id", "ride_name", "average_rating", "is_anomalous"],
    grain="One row per ride with at least one rating.",
    pitfall="The overall average is the mean of the ride averages, not AVG(rating) over all visits: a ride with many "
            "visits would otherwise dominate it.",
    hints=["Average per ride first, then average those averages.", "CROSS JOIN the one-row overall average to every ride."],
    explanation="""
        Two levels of aggregation: per ride, then over the per-ride results. A one-row result can be attached to every
        row with a CROSS JOIN (or a scalar subquery).
    """,
    changes=["The output keeps the statement's columns (ZillaCode also returned type and capacity). Ratings of rides "
             "missing from rides are ignored; is_anomalous is a Boolean (CodeDELeet's correction of 0/1)."],
    edges=[{"id": "weighted-average-trap", "tables": {
        "rides": rows("ride_id ride_name type capacity", ("r1", "Coaster", "Thrill", 20), ("r2", "Carousel", "Family", 30),
                      ("r3", "Swings", "Family", 16), ("r4", "Maze", "Walk", 50)),
        "visitors": rows("visitor_id ride_id timestamp rating",
                         ("v1", "r1", "2023-07-01 10:00:00", 5),
                         *[(f"v{i}", "r2", "2023-07-01 11:00:00", 2) for i in range(2, 10)],
                         ("v10", "r3", "2023-07-01 12:00:00", 4), ("v11", "r3", "2023-07-01 12:30:00", None),
                         ("v12", "r9", "2023-07-01 13:00:00", 1)),
    }}],
    sql=code("""
        WITH ride_avg AS (
            SELECT ride_id, AVG(rating) AS average_rating
            FROM visitors
            WHERE ride_id IN (SELECT ride_id FROM rides)
            GROUP BY ride_id
        ),
        overall AS (
            SELECT AVG(average_rating) AS overall_rating FROM ride_avg
        )
        SELECT r.ride_id, r.ride_name, a.average_rating,
               a.average_rating < 0.5 * o.overall_rating OR a.average_rating > 1.5 * o.overall_rating AS is_anomalous
        FROM rides AS r
        JOIN ride_avg AS a ON r.ride_id = a.ride_id
        CROSS JOIN overall AS o
    """),
    snowflake="same", dbt="auto",
    python=code("""
        def etl(rides, visitors):
            known = visitors[visitors["ride_id"].isin(rides["ride_id"])]
            ride_avg = known.groupby("ride_id", as_index=False).agg(average_rating=("rating", "mean"))
            ride_avg = ride_avg[ride_avg["average_rating"].notna()]
            overall = ride_avg["average_rating"].mean()
            ride_avg["is_anomalous"] = (ride_avg["average_rating"] < 0.5 * overall) | (ride_avg["average_rating"] > 1.5 * overall)
            return rides.merge(ride_avg, on="ride_id")[["ride_id", "ride_name", "average_rating", "is_anomalous"]]
    """),
    polars=code("""
        def etl(rides, visitors):
            ride_avg = (visitors.filter(pl.col("ride_id").is_in(rides["ride_id"].implode()))
                        .group_by("ride_id").agg(pl.col("rating").mean().alias("average_rating"))
                        .filter(pl.col("average_rating").is_not_null()))
            overall = pl.col("average_rating").mean()
            return rides.join(ride_avg, on="ride_id").select(
                "ride_id", "ride_name", "average_rating",
                ((pl.col("average_rating") < 0.5 * overall) | (pl.col("average_rating") > 1.5 * overall)).alias("is_anomalous"))
    """),
    mutants={
        "sql": ["WITH a AS (SELECT ride_id, AVG(rating) AS average_rating FROM visitors WHERE ride_id IN (SELECT ride_id FROM rides) GROUP BY ride_id), o AS (SELECT AVG(rating) AS overall_rating FROM visitors WHERE ride_id IN (SELECT ride_id FROM rides)) SELECT r.ride_id, r.ride_name, a.average_rating, a.average_rating < 0.5 * o.overall_rating OR a.average_rating > 1.5 * o.overall_rating AS is_anomalous FROM rides AS r JOIN a ON r.ride_id = a.ride_id CROSS JOIN o",
                "WITH a AS (SELECT ride_id, AVG(rating) AS average_rating FROM visitors GROUP BY ride_id), o AS (SELECT AVG(average_rating) AS overall_rating FROM a) SELECT r.ride_id, r.ride_name, a.average_rating, a.average_rating < 0.5 * o.overall_rating OR a.average_rating > 1.5 * o.overall_rating AS is_anomalous FROM rides AS r JOIN a ON r.ride_id = a.ride_id CROSS JOIN o"],
    },
)

# 33 ------------------------------------------------------------------------------------------------------------------
problem(
    n=33, slug="status-labels", title="Status labels with unknown companies", difficulty="easy",
    topics=["conditional-logic", "left-join", "nulls"], industry="Aerospace",
    tables={"aerospace_df": {"id": "VARCHAR", "name": "VARCHAR", "type": "VARCHAR", "status": "VARCHAR",
                             "company_id": "VARCHAR"},
            "company_df": {"id": "VARCHAR", "name": "VARCHAR", "country": "VARCHAR"}},
    prompt="""
        Return every piece of equipment with its company's name and country and a status_label: 'Domestic Active' when
        the status is 'active' and the country is 'USA', 'Foreign Active' when the status is 'active' and the country
        is anything else (including unknown, when the company is missing), and 'Inactive' otherwise.
    """,
    output=["id", "equipment_name", "equipment_type", "equipment_status", "company_name", "country", "status_label"],
    grain="One row per piece of equipment.",
    pitfall="country != 'USA' is NULL, not true, when the company is unknown, so a CASE falls through to 'Inactive'. "
            "Test the USA case first and let every other active row be foreign.",
    hints=["LEFT JOIN company_df so equipment without a known company stays.",
           "CASE WHEN active AND country = 'USA' THEN ... WHEN active THEN 'Foreign Active' ELSE 'Inactive' END."],
    explanation="""
        Order the CASE branches so the NULL country needs no comparison of its own: the first branch tests the positive
        USA condition, the second catches every other active row. `country IS DISTINCT FROM 'USA'` expresses the same.
    """,
    changes=["Active equipment of an unknown company is 'Foreign Active', as the statement's 'not USA' reads (ZillaCode's "
             "SQL gave 'Inactive', its pandas answer 'Foreign Active')."],
    edges=[{"id": "unknown-company", "tables": {
        "aerospace_df": rows("id name type status company_id", ("E1", "Probe", "Probe", "active", "C9"),
                             ("E2", "Relay", "Satellite", "inactive", "C9"), ("E3", "Lander", "Rover", "active", "C1"),
                             ("E4", "Glider", "Plane", "Active", "C1")),
        "company_df": rows("id name country", ("C1", "NASA", "USA")),
    }}],
    sql=code("""
        SELECT a.id,
               a.name AS equipment_name,
               a.type AS equipment_type,
               a.status AS equipment_status,
               c.name AS company_name,
               c.country,
               CASE WHEN a.status = 'active' AND c.country = 'USA' THEN 'Domestic Active'
                    WHEN a.status = 'active' THEN 'Foreign Active'
                    ELSE 'Inactive'
               END AS status_label
        FROM aerospace_df AS a
        LEFT JOIN company_df AS c ON a.company_id = c.id
    """),
    snowflake="same", dbt="auto",
    python=code("""
        def etl(aerospace_df, company_df):
            companies = company_df.rename(columns={"id": "company_id", "name": "company_name"})
            joined = aerospace_df.merge(companies, on="company_id", how="left")
            active = joined["status"] == "active"
            joined["status_label"] = "Inactive"
            joined.loc[active, "status_label"] = "Foreign Active"
            joined.loc[active & (joined["country"] == "USA"), "status_label"] = "Domestic Active"
            joined = joined.rename(columns={"name": "equipment_name", "type": "equipment_type", "status": "equipment_status"})
            return joined[["id", "equipment_name", "equipment_type", "equipment_status", "company_name", "country", "status_label"]]
    """),
    polars=code("""
        def etl(aerospace_df, company_df):
            companies = company_df.rename({"id": "company_id", "name": "company_name"})
            active = pl.col("status") == "active"
            return aerospace_df.join(companies, on="company_id", how="left").select(
                "id",
                pl.col("name").alias("equipment_name"),
                pl.col("type").alias("equipment_type"),
                pl.col("status").alias("equipment_status"),
                "company_name",
                "country",
                pl.when(active & (pl.col("country") == "USA")).then(pl.lit("Domestic Active"))
                .when(active).then(pl.lit("Foreign Active"))
                .otherwise(pl.lit("Inactive")).alias("status_label"),
            )
    """),
    sparklab=code("""
        from pyspark.sql import functions as F

        equipment = spark.table("aerospace_df")
        companies = spark.table("company_df").withColumnRenamed("id", "company_id").withColumnRenamed("name", "company_name")
        active = F.col("status") == "active"
        equipment.join(companies, "company_id", "left").select(
            "id",
            F.col("name").alias("equipment_name"),
            F.col("type").alias("equipment_type"),
            F.col("status").alias("equipment_status"),
            "company_name",
            "country",
            F.when(active & (F.col("country") == "USA"), "Domestic Active")
            .when(active, "Foreign Active")
            .otherwise("Inactive").alias("status_label"),
        )
    """),
    mutants={
        "sql": ["SELECT a.id, a.name AS equipment_name, a.type AS equipment_type, a.status AS equipment_status, c.name AS company_name, c.country, CASE WHEN a.status = 'active' AND c.country = 'USA' THEN 'Domestic Active' WHEN a.status = 'active' AND c.country != 'USA' THEN 'Foreign Active' ELSE 'Inactive' END AS status_label FROM aerospace_df AS a LEFT JOIN company_df AS c ON a.company_id = c.id",
                "SELECT a.id, a.name AS equipment_name, a.type AS equipment_type, a.status AS equipment_status, c.name AS company_name, c.country, CASE WHEN a.status = 'active' AND c.country = 'USA' THEN 'Domestic Active' WHEN a.status = 'active' THEN 'Foreign Active' ELSE 'Inactive' END AS status_label FROM aerospace_df AS a JOIN company_df AS c ON a.company_id = c.id"],
    },
)

# 34 ------------------------------------------------------------------------------------------------------------------
problem(
    n=34, slug="interaction-log", title="One log of visits, likes and comments", difficulty="easy",
    topics=["union"], industry="Web analytics",
    tables={"page_visits": {"user_id": "VARCHAR", "page_id": "VARCHAR", "visit_time": "VARCHAR"},
            "page_likes": {"user_id": "VARCHAR", "page_id": "VARCHAR", "like_time": "VARCHAR"},
            "page_comments": {"user_id": "VARCHAR", "page_id": "VARCHAR", "comment_time": "VARCHAR"}},
    prompt="""
        Combine visits, likes and comments into one interaction log: user_id, page_id, interaction_time (the event's
        timestamp, as ISO text) and interaction_type ('visit', 'like' or 'comment'). Every event is kept, including
        identical events.
    """,
    output=["user_id", "page_id", "interaction_time", "interaction_type"],
    grain="One row per event of any of the three tables.",
    pitfall="UNION would merge identical events; UNION ALL keeps them. Each branch renames its own time column.",
    hints=["Three SELECTs with a literal interaction_type, glued with UNION ALL.",
           "Alias the time column to interaction_time in every branch."],
    explanation="Align the three schemas by renaming and add the event type as a literal before appending with UNION ALL.",
    changes=["Timestamps are ISO text, which sorts chronologically in every engine. Row order is not graded (ZillaCode's "
             "references sorted by time without the statement asking for it)."],
    edges=[{"id": "identical-events", "tables": {
        "page_visits": rows("user_id page_id visit_time", ("U1", "P1", "2023-01-01 09:00:00"), ("U1", "P1", "2023-01-01 09:00:00")),
        "page_likes": rows("user_id page_id like_time", ("U1", "P1", "2023-01-01 09:00:00")),
        "page_comments": rows("user_id page_id comment_time", ("U2", "P3", "2023-01-02 10:00:00")),
    }}],
    sql=code("""
        SELECT user_id, page_id, visit_time AS interaction_time, 'visit' AS interaction_type FROM page_visits
        UNION ALL
        SELECT user_id, page_id, like_time AS interaction_time, 'like' AS interaction_type FROM page_likes
        UNION ALL
        SELECT user_id, page_id, comment_time AS interaction_time, 'comment' AS interaction_type FROM page_comments
    """),
    snowflake="same", dbt="auto",
    python=code("""
        def etl(page_visits, page_likes, page_comments):
            parts = [
                page_visits.rename(columns={"visit_time": "interaction_time"}).assign(interaction_type="visit"),
                page_likes.rename(columns={"like_time": "interaction_time"}).assign(interaction_type="like"),
                page_comments.rename(columns={"comment_time": "interaction_time"}).assign(interaction_type="comment"),
            ]
            return pd.concat(parts, ignore_index=True)[["user_id", "page_id", "interaction_time", "interaction_type"]]
    """),
    polars=code("""
        def etl(page_visits, page_likes, page_comments):
            return pl.concat([
                page_visits.rename({"visit_time": "interaction_time"}).with_columns(pl.lit("visit").alias("interaction_type")),
                page_likes.rename({"like_time": "interaction_time"}).with_columns(pl.lit("like").alias("interaction_type")),
                page_comments.rename({"comment_time": "interaction_time"}).with_columns(pl.lit("comment").alias("interaction_type")),
            ])
    """),
    mutants={
        "sql": ["SELECT user_id, page_id, visit_time AS interaction_time, 'visit' AS interaction_type FROM page_visits UNION SELECT user_id, page_id, like_time, 'like' FROM page_likes UNION SELECT user_id, page_id, comment_time, 'comment' FROM page_comments"],
    },
)

# 35 ------------------------------------------------------------------------------------------------------------------
problem(
    n=35, slug="daily-category-sales", title="Daily quantity per category", difficulty="easy",
    topics=["aggregation", "joins"], industry="Outdoor retail",
    tables={"df_sales": {"sales_id": "VARCHAR", "product_id": "VARCHAR", "date": "DATE", "quantity_sold": "INTEGER"},
            "df_products": {"product_id": "VARCHAR", "product_name": "VARCHAR", "product_category": "VARCHAR"}},
    prompt="""
        Return the total quantity sold for each product category on each day. Sales of unknown products are ignored.
    """,
    output=["date", "product_category", "total_quantity"],
    grain="One row per (date, product_category) with sales.",
    pitfall="Group by the category, not the product: two products of one category sold on the same day add up.",
    hints=["Join sales to products, then GROUP BY date, product_category.", "SUM(quantity_sold)."],
    explanation="Join to find each sale's category and aggregate at the (date, category) grain.",
    edges=[{"id": "same-category-same-day", "tables": {
        "df_sales": rows("sales_id product_id date quantity_sold", ("S1", "P1", "2023-06-01", 2), ("S2", "P2", "2023-06-01", 3),
                         ("S3", "P3", "2023-06-01", 4), ("S4", "P9", "2023-06-01", 50), ("S5", "P1", "2023-06-02", 1)),
        "df_products": rows("product_id product_name product_category", ("P1", "Tent", "Camping"),
                            ("P2", "Stove", "Camping"), ("P3", "Rod", "Fishing")),
    }}],
    sql=code("""
        SELECT s.date, p.product_category, SUM(s.quantity_sold) AS total_quantity
        FROM df_sales AS s
        JOIN df_products AS p ON s.product_id = p.product_id
        GROUP BY s.date, p.product_category
    """),
    snowflake="same", dbt="auto",
    python=code("""
        def etl(df_sales, df_products):
            joined = df_sales.merge(df_products, on="product_id")
            return joined.groupby(["date", "product_category"], as_index=False).agg(total_quantity=("quantity_sold", "sum"))
    """),
    polars=code("""
        def etl(df_sales, df_products):
            return df_sales.join(df_products, on="product_id").group_by("date", "product_category").agg(
                pl.col("quantity_sold").sum().alias("total_quantity"))
    """),
    sparklab=code("""
        from pyspark.sql import functions as F

        sales = spark.table("df_sales")
        products = spark.table("df_products")
        sales.join(products, "product_id").groupBy("date", "product_category").agg(
            F.sum("quantity_sold").alias("total_quantity"))
    """),
    mutants={
        "sql": ["SELECT s.date, p.product_category, SUM(s.quantity_sold) AS total_quantity FROM df_sales AS s JOIN df_products AS p ON s.product_id = p.product_id GROUP BY s.date, p.product_category, p.product_id",
                "SELECT s.date, p.product_category, SUM(s.quantity_sold) AS total_quantity FROM df_sales AS s LEFT JOIN df_products AS p ON s.product_id = p.product_id GROUP BY s.date, p.product_category"],
    },
)

# 36 ------------------------------------------------------------------------------------------------------------------
problem(
    n=36, slug="vc-above-limit", title="Investors above their funding limit", difficulty="easy",
    topics=["aggregation", "having", "joins"], industry="Venture capital",
    tables={"venture_capitalist_df": {"vc_id": "VARCHAR", "vc_name": "VARCHAR", "funding_limit": "DOUBLE"},
            "funded_startups_df": {"startup_id": "VARCHAR", "startup_name": "VARCHAR", "vc_id": "VARCHAR", "funding": "DOUBLE"}},
    prompt="""
        Each venture capitalist has a funding limit. Return the investors whose funded start-ups have an average funding
        strictly above their limit, with that average. A NULL funding amount is not part of the average.
    """,
    output=["vc_id", "vc_name", "avg_funding"],
    grain="One row per investor whose average funding is above their limit.",
    pitfall="The limit differs per investor, so compare after aggregating; an average equal to the limit is not above it.",
    hints=["AVG(funding) per vc_id, join the investors, keep avg_funding > funding_limit.",
           "Or GROUP BY the investor columns and use HAVING."],
    explanation="Aggregate per investor, then filter on the aggregate (HAVING, or a WHERE on the aggregated subquery).",
    changes=["The output keeps the statement's columns (ZillaCode's reference also returned funding_limit)."],
    edges=[{"id": "equal-to-limit", "tables": {
        "venture_capitalist_df": rows("vc_id vc_name funding_limit", ("V1", "Equal", 2.0), ("V2", "Above", 2.0),
                                      ("V3", "Idle", 0.5)),
        "funded_startups_df": rows("startup_id startup_name vc_id funding", ("S1", "A", "V1", 1.0), ("S2", "B", "V1", 3.0),
                                   ("S3", "C", "V2", 3.0), ("S4", "D", "V2", None), ("S5", "E", "V9", 9.0)),
    }}],
    sql=code("""
        SELECT v.vc_id, v.vc_name, AVG(s.funding) AS avg_funding
        FROM venture_capitalist_df AS v
        JOIN funded_startups_df AS s ON v.vc_id = s.vc_id
        GROUP BY v.vc_id, v.vc_name, v.funding_limit
        HAVING AVG(s.funding) > v.funding_limit
    """),
    snowflake="same", dbt="auto",
    python=code("""
        def etl(venture_capitalist_df, funded_startups_df):
            averages = funded_startups_df.groupby("vc_id", as_index=False).agg(avg_funding=("funding", "mean"))
            joined = venture_capitalist_df.merge(averages, on="vc_id")
            return joined[joined["avg_funding"] > joined["funding_limit"]][["vc_id", "vc_name", "avg_funding"]]
    """),
    polars=code("""
        def etl(venture_capitalist_df, funded_startups_df):
            averages = funded_startups_df.group_by("vc_id").agg(pl.col("funding").mean().alias("avg_funding"))
            return venture_capitalist_df.join(averages, on="vc_id").filter(
                pl.col("avg_funding") > pl.col("funding_limit")).select("vc_id", "vc_name", "avg_funding")
    """),
    sparklab=code("""
        from pyspark.sql import functions as F

        investors = spark.table("venture_capitalist_df")
        averages = spark.table("funded_startups_df").groupBy("vc_id").agg(F.avg("funding").alias("avg_funding"))
        investors.join(averages, "vc_id").filter(F.col("avg_funding") > F.col("funding_limit")).select(
            "vc_id", "vc_name", "avg_funding")
    """),
    mutants={
        "sql": ["SELECT v.vc_id, v.vc_name, AVG(s.funding) AS avg_funding FROM venture_capitalist_df AS v JOIN funded_startups_df AS s ON v.vc_id = s.vc_id GROUP BY v.vc_id, v.vc_name, v.funding_limit HAVING AVG(s.funding) >= v.funding_limit",
                "SELECT v.vc_id, v.vc_name, SUM(s.funding) / COUNT(*) AS avg_funding FROM venture_capitalist_df AS v JOIN funded_startups_df AS s ON v.vc_id = s.vc_id GROUP BY v.vc_id, v.vc_name, v.funding_limit HAVING SUM(s.funding) / COUNT(*) > v.funding_limit"],
    },
)

# 37 ------------------------------------------------------------------------------------------------------------------
problem(
    n=37, slug="latest-maintenance", title="Latest maintenance and its cost rank", difficulty="hard",
    topics=["window-functions", "ranking", "nulls"], industry="Pharmaceuticals",
    tables={"df1": {"equipment_id": "VARCHAR", "equipment_name": "VARCHAR", "purchase_date": "DATE"},
            "df2": {"equipment_id": "VARCHAR", "maintenance_date": "DATE", "maintenance_cost": "DOUBLE"}},
    prompt="""
        For each piece of equipment with at least one maintenance record, return its latest maintenance date and
        maintenance_cost_rank: rank all of that equipment's maintenance records by cost, highest first, with a dense
        rank (a NULL cost ranks last), and report the rank of the latest record. When several records share the latest
        date, report the best (smallest) of their ranks. Maintenance of unknown equipment is ignored.
    """,
    output=["equipment_id", "equipment_name", "purchase_date", "latest_maintenance_date", "maintenance_cost_rank"],
    grain="One row per equipment with at least one maintenance record.",
    pitfall="Rank within each piece of equipment (PARTITION BY equipment_id) and before keeping the latest records. "
            "Snowflake ranks a NULL cost first in a descending order: write NULLS LAST.",
    hints=["MAX(maintenance_date) and DENSE_RANK() over PARTITION BY equipment_id, in the same pass.",
           "Keep the rows on the latest date, then take MIN(rank) per equipment."],
    explanation="""
        Window functions compute both facts over the equipment's full history; filtering to the latest date must come
        after ranking, or every record would rank 1. CodeDELeet clarified this contract from ZillaCode's examples,
        where ranks are per equipment rather than global.
    """,
    changes=["The rank is per equipment, as CodeDELeet's correction established (ZillaCode's pandas answer hard-coded 1). "
             "Several records on the latest date give one row with the best rank; a NULL cost ranks last."],
    edges=[{"id": "tie-and-null-cost", "tables": {
        "df1": rows("equipment_id equipment_name purchase_date", ("EQ1", "Mixer", "2020-01-01"), ("EQ2", "Press", "2020-02-01"),
                    ("EQ3", "Scale", "2020-03-01")),
        "df2": rows("equipment_id maintenance_date maintenance_cost", ("EQ1", "2021-01-01", 500.0),
                    ("EQ1", "2021-03-01", 300.0), ("EQ1", "2021-03-01", 700.0), ("EQ2", "2021-01-01", 200.0),
                    ("EQ2", "2021-02-01", None), ("EQ9", "2021-05-01", 50.0)),
    }}],
    sql=code("""
        WITH ranked AS (
            SELECT e.equipment_id, e.equipment_name, e.purchase_date, m.maintenance_date,
                   MAX(m.maintenance_date) OVER (PARTITION BY m.equipment_id) AS latest_maintenance_date,
                   DENSE_RANK() OVER (PARTITION BY m.equipment_id ORDER BY m.maintenance_cost DESC NULLS LAST) AS cost_rank
            FROM df1 AS e
            JOIN df2 AS m ON e.equipment_id = m.equipment_id
        )
        SELECT equipment_id, equipment_name, purchase_date, latest_maintenance_date,
               MIN(cost_rank) AS maintenance_cost_rank
        FROM ranked
        WHERE maintenance_date = latest_maintenance_date
        GROUP BY equipment_id, equipment_name, purchase_date, latest_maintenance_date
    """),
    snowflake="same", dbt="auto",
    python=code("""
        def etl(df1, df2):
            joined = df1.merge(df2, on="equipment_id")
            joined["cost_rank"] = joined.groupby("equipment_id")["maintenance_cost"].rank(
                method="dense", ascending=False, na_option="bottom")
            joined["latest_maintenance_date"] = joined.groupby("equipment_id")["maintenance_date"].transform("max")
            latest = joined[joined["maintenance_date"] == joined["latest_maintenance_date"]]
            result = latest.groupby(["equipment_id", "equipment_name", "purchase_date", "latest_maintenance_date"],
                                    as_index=False).agg(maintenance_cost_rank=("cost_rank", "min"))
            result["maintenance_cost_rank"] = result["maintenance_cost_rank"].astype(int)
            return result
    """),
    polars=code("""
        def etl(df1, df2):
            cost = pl.col("maintenance_cost").fill_null(float("-inf"))
            joined = df1.join(df2, on="equipment_id").with_columns(
                cost.rank("dense", descending=True).over("equipment_id").alias("cost_rank"),
                pl.col("maintenance_date").max().over("equipment_id").alias("latest_maintenance_date"))
            latest = joined.filter(pl.col("maintenance_date") == pl.col("latest_maintenance_date"))
            return latest.group_by("equipment_id", "equipment_name", "purchase_date", "latest_maintenance_date").agg(
                pl.col("cost_rank").min().alias("maintenance_cost_rank"))
    """),
    mutants={
        "sql": ["WITH r AS (SELECT e.equipment_id, e.equipment_name, e.purchase_date, m.maintenance_date, MAX(m.maintenance_date) OVER () AS latest_maintenance_date, DENSE_RANK() OVER (ORDER BY m.maintenance_cost DESC NULLS LAST) AS cost_rank FROM df1 AS e JOIN df2 AS m ON e.equipment_id = m.equipment_id) SELECT equipment_id, equipment_name, purchase_date, latest_maintenance_date, MIN(cost_rank) AS maintenance_cost_rank FROM r WHERE maintenance_date = latest_maintenance_date GROUP BY equipment_id, equipment_name, purchase_date, latest_maintenance_date",
                "WITH latest AS (SELECT e.equipment_id, e.equipment_name, e.purchase_date, m.maintenance_date, m.maintenance_cost FROM df1 AS e JOIN df2 AS m ON e.equipment_id = m.equipment_id QUALIFY m.maintenance_date = MAX(m.maintenance_date) OVER (PARTITION BY m.equipment_id)) SELECT equipment_id, equipment_name, purchase_date, maintenance_date AS latest_maintenance_date, MIN(r) AS maintenance_cost_rank FROM (SELECT *, DENSE_RANK() OVER (PARTITION BY equipment_id ORDER BY maintenance_cost DESC NULLS LAST) AS r FROM latest) GROUP BY equipment_id, equipment_name, purchase_date, maintenance_date"],
        "snowflake": ["WITH ranked AS (SELECT e.equipment_id, e.equipment_name, e.purchase_date, m.maintenance_date, MAX(m.maintenance_date) OVER (PARTITION BY m.equipment_id) AS latest_maintenance_date, DENSE_RANK() OVER (PARTITION BY m.equipment_id ORDER BY m.maintenance_cost DESC) AS cost_rank FROM df1 AS e JOIN df2 AS m ON e.equipment_id = m.equipment_id) SELECT equipment_id, equipment_name, purchase_date, latest_maintenance_date, MIN(cost_rank) AS maintenance_cost_rank FROM ranked WHERE maintenance_date = latest_maintenance_date GROUP BY equipment_id, equipment_name, purchase_date, latest_maintenance_date"],
    },
)

# 38 ------------------------------------------------------------------------------------------------------------------
problem(
    n=38, slug="cross-join", title="Every transaction with every customer", difficulty="easy",
    topics=["cross-join"], industry="Banking",
    tables={"transactions": {"trans_id": "INTEGER", "trans_amt": "DOUBLE", "date": "VARCHAR", "cust_id": "INTEGER"},
            "customers": {"cust_id": "INTEGER", "first_name": "VARCHAR", "last_name": "VARCHAR", "age": "INTEGER"}},
    prompt="""
        For an analysis grid, pair every transaction with every customer (a cross join). Return the transaction's
        columns followed by the customer's; the cust_id column is the customer's, not the transaction's.
    """,
    output=["trans_id", "trans_amt", "date", "cust_id", "first_name", "last_name", "age"],
    grain="One row per (transaction, customer) pair.",
    pitfall="Both tables have cust_id: select the customer's one explicitly. Joining on cust_id is not a cross join.",
    hints=["CROSS JOIN (pandas merge(how='cross'), Polars join(how='cross')).",
           "Drop or rename the transaction's cust_id before combining."],
    explanation="A cross join produces n x m rows without a condition; the duplicate column name must be resolved explicitly.",
    changes=["The customer-side cust_id is kept explicitly (CodeDELeet's correction of duplicate keys)."],
    edges=[{"id": "duplicate-customer-row", "tables": {
        "transactions": rows("trans_id trans_amt date cust_id", (1, 10.0, "2023-07-01", 100), (2, 20.0, "2023-07-02", 200)),
        "customers": rows("cust_id first_name last_name age", (100, "Ann", "Lee", 30), (100, "Ann", "Lee", 30)),
    }}],
    sql=code("""
        SELECT t.trans_id, t.trans_amt, t.date, c.cust_id, c.first_name, c.last_name, c.age
        FROM transactions AS t
        CROSS JOIN customers AS c
    """),
    snowflake="same", dbt="auto",
    python=code("""
        def etl(transactions, customers):
            return transactions.drop(columns="cust_id").merge(customers, how="cross")
    """),
    polars=code("""
        def etl(transactions, customers):
            return transactions.drop("cust_id").join(customers, how="cross")
    """),
    mutants={
        "sql": ["SELECT t.trans_id, t.trans_amt, t.date, c.cust_id, c.first_name, c.last_name, c.age FROM transactions AS t JOIN customers AS c ON t.cust_id = c.cust_id",
                "SELECT t.trans_id, t.trans_amt, t.date, t.cust_id, c.first_name, c.last_name, c.age FROM transactions AS t CROSS JOIN customers AS c"],
    },
)

# 39 ------------------------------------------------------------------------------------------------------------------
problem(
    n=39, slug="self-interactions", title="Users who interact with themselves", difficulty="easy",
    topics=["filtering", "aggregation", "nulls"], industry="Social media",
    tables={"input_df": {"interaction_id": "INTEGER", "user1_id": "INTEGER", "user2_id": "INTEGER",
                         "interaction_type": "VARCHAR", "timestamp": "VARCHAR"}},
    zilla_output={"user_id": "user1_id"},
    prompt="""
        An interaction links user1_id to user2_id. A self-interaction has the same user on both sides. Return each user
        with at least one self-interaction and their number of self-interactions. An interaction with a missing user is
        not a self-interaction.
    """,
    output=["user_id", "self_interaction_count"],
    grain="One row per user with at least one self-interaction.",
    pitfall="NULL = NULL is not true: two missing users are not the same user (IS NOT DISTINCT FROM would count them). "
            "pandas and Polars agree with SQL here.",
    hints=["WHERE user1_id = user2_id, then GROUP BY user1_id.", "Alias user1_id to user_id."],
    explanation="A filter comparing two columns of the same row, then a count per user. Equality with NULL is unknown, "
                "so rows with a missing user drop out.",
    changes=["The output column is user_id, as the statement says (ZillaCode's reference kept user1_id)."],
    edges=[{"id": "missing-users", "tables": {"input_df": rows(
        "interaction_id user1_id user2_id interaction_type timestamp",
        (1, 7, 7, "like", "2023-01-01 10:00:00"), (2, 7, 7, "like", "2023-01-01 11:00:00"),
        (3, None, None, "like", "2023-01-01 12:00:00"), (4, 8, None, "comment", "2023-01-01 13:00:00"),
        (5, 9, 10, "like", "2023-01-01 14:00:00"),
    )}}],
    sql=code("""
        SELECT user1_id AS user_id, COUNT(*) AS self_interaction_count
        FROM input_df
        WHERE user1_id = user2_id
        GROUP BY user1_id
    """),
    snowflake="same", dbt="auto",
    python=code("""
        def etl(input_df):
            own = input_df[input_df["user1_id"] == input_df["user2_id"]]
            counts = own.groupby("user1_id", as_index=False).size()
            return counts.rename(columns={"user1_id": "user_id", "size": "self_interaction_count"})
    """),
    polars=code("""
        def etl(input_df):
            own = input_df.filter(pl.col("user1_id") == pl.col("user2_id"))
            return own.group_by(pl.col("user1_id").alias("user_id")).agg(pl.len().alias("self_interaction_count"))
    """),
    sparklab=code("""
        from pyspark.sql import functions as F

        interactions = spark.table("input_df")
        interactions.filter(F.col("user1_id") == F.col("user2_id")).groupBy("user1_id").agg(
            F.count("*").alias("self_interaction_count")
        ).withColumnRenamed("user1_id", "user_id")
    """),
    mutants={
        "sql": ["SELECT user1_id AS user_id, COUNT(*) AS self_interaction_count FROM input_df WHERE user1_id IS NOT DISTINCT FROM user2_id GROUP BY user1_id",
                "SELECT user1_id AS user_id, COUNT(DISTINCT interaction_type) AS self_interaction_count FROM input_df WHERE user1_id = user2_id GROUP BY user1_id"],
    },
)

# 40 ------------------------------------------------------------------------------------------------------------------
LISTS = ["criminal_record", "employment_history", "education_history", "address"]
problem(
    n=40, slug="count-list-items", title="Count items in comma-separated fields", difficulty="easy",
    topics=["strings", "nulls"], industry="Background checks",
    tables={"background_checks": {"check_id": "INTEGER", "full_name": "VARCHAR", "dob": "DATE",
                                  "criminal_record": "VARCHAR", "employment_history": "VARCHAR",
                                  "education_history": "VARCHAR", "address": "VARCHAR"}},
    prompt="""
        Four text fields hold comma-separated lists (crimes, jobs, degrees, addresses). Return each check with the
        number of items in each list: the number of commas plus one, or 0 when the field is NULL or empty.
    """,
    output=["check_id", "full_name", "dob", "crime_count", "jobs_count", "degrees_count", "places_lived_count"],
    grain="One row per check.",
    pitfall="Splitting '' gives one empty item and splitting NULL gives NULL: both must count as 0.",
    hints=["LENGTH(x) - LENGTH(REPLACE(x, ',', '')) + 1 counts the items.", "Handle NULL and '' first."],
    explanation="""
        Counting separators works in every engine (Snowflake's subset has no arrays): the item count is the number of
        commas plus one, with NULL and the empty string defined as 0 items.
    """,
    changes=["NULL and empty fields count 0 items explicitly (ZillaCode's references differed on them)."],
    edges=[{"id": "null-and-empty", "tables": {"background_checks": rows(
        "check_id full_name dob criminal_record employment_history education_history address",
        (21, "Ada Park", "1990-01-01", None, "", "B.A.", "1 Main St, 2 Oak St, 3 Elm St"),
        (22, "Bo Chan", "1985-05-05", "Theft", None, "", "9 Pine St"),
    )}}],
    sql=code("""
        SELECT check_id, full_name, dob,
               CASE WHEN COALESCE(criminal_record, '') = '' THEN 0
                    ELSE length(criminal_record) - length(replace(criminal_record, ',', '')) + 1 END AS crime_count,
               CASE WHEN COALESCE(employment_history, '') = '' THEN 0
                    ELSE length(employment_history) - length(replace(employment_history, ',', '')) + 1 END AS jobs_count,
               CASE WHEN COALESCE(education_history, '') = '' THEN 0
                    ELSE length(education_history) - length(replace(education_history, ',', '')) + 1 END AS degrees_count,
               CASE WHEN COALESCE(address, '') = '' THEN 0
                    ELSE length(address) - length(replace(address, ',', '')) + 1 END AS places_lived_count
        FROM background_checks
    """),
    snowflake=code("""
        SELECT check_id, full_name, dob,
               IFF(NVL(criminal_record, '') = '', 0, LENGTH(criminal_record) - LENGTH(REPLACE(criminal_record, ',', '')) + 1) AS crime_count,
               IFF(NVL(employment_history, '') = '', 0, LENGTH(employment_history) - LENGTH(REPLACE(employment_history, ',', '')) + 1) AS jobs_count,
               IFF(NVL(education_history, '') = '', 0, LENGTH(education_history) - LENGTH(REPLACE(education_history, ',', '')) + 1) AS degrees_count,
               IFF(NVL(address, '') = '', 0, LENGTH(address) - LENGTH(REPLACE(address, ',', '')) + 1) AS places_lived_count
        FROM background_checks
    """),
    dbt="auto",
    python=code("""
        def etl(background_checks):
            def count(value):
                return 0 if pd.isna(value) or value == "" else value.count(",") + 1

            result = background_checks[["check_id", "full_name", "dob"]].copy()
            for source, target in [("criminal_record", "crime_count"), ("employment_history", "jobs_count"),
                                   ("education_history", "degrees_count"), ("address", "places_lived_count")]:
                result[target] = background_checks[source].map(count)
            return result
    """),
    polars=code("""
        def etl(background_checks):
            def count(name):
                field = pl.col(name)
                return pl.when(field.is_null() | (field == "")).then(0).otherwise(field.str.count_matches(",") + 1)

            return background_checks.select(
                "check_id", "full_name", "dob",
                count("criminal_record").alias("crime_count"),
                count("employment_history").alias("jobs_count"),
                count("education_history").alias("degrees_count"),
                count("address").alias("places_lived_count"),
            )
    """),
    mutants={
        "sql": ["SELECT check_id, full_name, dob, len(string_split(criminal_record, ',')) AS crime_count, len(string_split(employment_history, ',')) AS jobs_count, len(string_split(education_history, ',')) AS degrees_count, len(string_split(address, ',')) AS places_lived_count FROM background_checks"],
        "snowflake": ["SELECT check_id, full_name, dob, LENGTH(criminal_record) - LENGTH(REPLACE(criminal_record, ',', '')) + 1 AS crime_count, LENGTH(employment_history) - LENGTH(REPLACE(employment_history, ',', '')) + 1 AS jobs_count, LENGTH(education_history) - LENGTH(REPLACE(education_history, ',', '')) + 1 AS degrees_count, LENGTH(address) - LENGTH(REPLACE(address, ',', '')) + 1 AS places_lived_count FROM background_checks"],
    },
)
