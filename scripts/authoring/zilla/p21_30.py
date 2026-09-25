"""ZillaCode problems 21-30 as Datapass specs."""
from .common import code, problem, rows

# 21 ------------------------------------------------------------------------------------------------------------------
problem(
    n=21, slug="previous-product", title="Previous product of each customer", difficulty="medium",
    topics=["window-functions", "nulls", "strings"], industry="Retail",
    tables={"transactions": {"customer_id": "VARCHAR", "product_id": "VARCHAR", "quantity": "INTEGER", "date": "VARCHAR"}},
    prompt="""
        For each transaction, add previous_product: the product of the same customer's previous transaction in
        chronological order (date, then product_id for transactions on the same day), or NULL for their first one.
        Also add date_and_product: the date and the previous product separated by a space, with the text 'None' when
        there is no previous product. The date is ISO text ('YYYY-MM-DD').
    """,
    output=["customer_id", "product_id", "quantity", "date", "previous_product", "date_and_product"],
    grain="One row per transaction.",
    pitfall="previous_product stays NULL; only the display column shows 'None'. Concatenating the NULL directly makes "
            "date_and_product NULL (SQL, Snowflake CONCAT) or NaN (pandas).",
    hints=["LAG(product_id) OVER (PARTITION BY customer_id ORDER BY date, product_id).",
           "COALESCE(previous_product, 'None') only inside the concatenation."],
    explanation="""
        LAG reads the previous row of the same customer in the window order; the second sort key makes same-day
        transactions deterministic. The NULL is replaced only where it is displayed.
    """,
    changes=["previous_product stays NULL and only date_and_product shows 'None' (CodeDELeet's correction of "
             "ZillaCode). Same-day transactions are ordered by product_id. Output columns follow the statement's order."],
    edges=[{"id": "same-day", "tables": {"transactions": rows(
        "customer_id product_id quantity date",
        ("C1", "P9", 1, "2023-03-01"), ("C1", "P2", 4, "2023-03-01"), ("C1", "P5", 2, "2023-02-01"),
        ("C2", "P1", 1, "2023-03-02"),
    )}}],
    sql=code("""
        WITH ordered AS (
            SELECT customer_id, product_id, quantity, date,
                   LAG(product_id) OVER (PARTITION BY customer_id ORDER BY date, product_id) AS previous_product
            FROM transactions
        )
        SELECT customer_id, product_id, quantity, date, previous_product,
               date || ' ' || COALESCE(previous_product, 'None') AS date_and_product
        FROM ordered
    """),
    snowflake=code("""
        WITH ordered AS (
            SELECT customer_id, product_id, quantity, date,
                   LAG(product_id) OVER (PARTITION BY customer_id ORDER BY date, product_id) AS previous_product
            FROM transactions
        )
        SELECT customer_id, product_id, quantity, date, previous_product,
               CONCAT(date, ' ', NVL(previous_product, 'None')) AS date_and_product
        FROM ordered
    """),
    dbt="auto",
    python=code("""
        def etl(transactions):
            result = transactions.sort_values(["customer_id", "date", "product_id"]).copy()
            result["previous_product"] = result.groupby("customer_id")["product_id"].shift(1)
            result["date_and_product"] = result["date"] + " " + result["previous_product"].fillna("None")
            return result[["customer_id", "product_id", "quantity", "date", "previous_product", "date_and_product"]]
    """),
    polars=code("""
        def etl(transactions):
            ordered = transactions.sort("customer_id", "date", "product_id").with_columns(
                pl.col("product_id").shift(1).over("customer_id").alias("previous_product"))
            return ordered.with_columns(
                (pl.col("date") + " " + pl.col("previous_product").fill_null("None")).alias("date_and_product"))
    """),
    mutants={
        "sql": ["WITH o AS (SELECT customer_id, product_id, quantity, date, LAG(product_id) OVER (PARTITION BY customer_id ORDER BY date, product_id) AS previous_product FROM transactions) SELECT customer_id, product_id, quantity, date, COALESCE(previous_product, 'None') AS previous_product, date || ' ' || COALESCE(previous_product, 'None') AS date_and_product FROM o",
                "WITH o AS (SELECT customer_id, product_id, quantity, date, LAG(product_id) OVER (PARTITION BY customer_id ORDER BY date DESC, product_id) AS previous_product FROM transactions) SELECT customer_id, product_id, quantity, date, previous_product, date || ' ' || COALESCE(previous_product, 'None') AS date_and_product FROM o"],
        "snowflake": ["WITH o AS (SELECT customer_id, product_id, quantity, date, LAG(product_id) OVER (PARTITION BY customer_id ORDER BY date, product_id) AS previous_product FROM transactions) SELECT customer_id, product_id, quantity, date, previous_product, CONCAT(date, ' ', previous_product) AS date_and_product FROM o"],
    },
)

# 22 ------------------------------------------------------------------------------------------------------------------
problem(
    n=22, slug="active-watch-time", title="Watch time during active subscriptions", difficulty="hard",
    topics=["semi-join", "dates", "aggregation"], industry="Video streaming",
    tables={"user_behavior_df": {"user_id": "VARCHAR", "watch_duration": "INTEGER", "date": "DATE"},
            "subscription_df": {"user_id": "VARCHAR", "subscription_start": "DATE", "subscription_end": "VARCHAR"}},
    rename={"userId": "user_id", "watchDuration": "watch_duration", "subscriptionStart": "subscription_start",
            "subscriptionEnd": "subscription_end"},
    zilla_output={"total_watch_time": "totalWatchTime"},
    prompt="""
        A streaming service wants the minutes each user watched while subscribed. A viewing counts if its date falls
        inside one of the user's subscriptions, start and end days included; subscription_end is a date as text, or
        'ongoing' for an open subscription. A viewing covered by two overlapping subscriptions counts once. Return
        the users with at least one counted viewing and their total minutes.
    """,
    output=["user_id", "total_watch_time"],
    grain="One row per user with at least one viewing during a subscription.",
    pitfall="Joining viewings to subscriptions counts a viewing once per matching subscription, so overlapping "
            "subscriptions double it: test coverage with EXISTS (a semi-join) instead. 'ongoing' is not a date: "
            "TRY_CAST (TRY_TO_DATE in Snowflake) turns it into NULL instead of failing.",
    hints=["WHERE EXISTS (SELECT 1 FROM subscription_df ... ) keeps each viewing once.",
           "Compare dates as dates; handle 'ongoing' explicitly."],
    explanation="""
        The question is whether a covering subscription exists, not how many there are: a correlated EXISTS (or a
        semi-join) keeps each viewing row once. The end date needs a safe conversion because of 'ongoing'.
    """,
    changes=["Columns are snake_case (ZillaCode used userId, watchDuration, ...). A viewing covered by overlapping "
             "subscriptions counts once (ZillaCode's join would count it twice); an edge check covers it."],
    edges=[{"id": "overlap-and-bounds", "tables": {
        "user_behavior_df": rows("user_id watch_duration date", ("U1", 10, "2023-01-06"), ("U1", 20, "2023-01-10"),
                                 ("U1", 40, "2022-12-31"), ("U2", 5, "2023-02-01"), ("U3", 7, "2023-01-01"),
                                 ("U1", 10, "2023-01-06"), ("U2", 3, "2023-03-01")),
        "subscription_df": rows("user_id subscription_start subscription_end", ("U1", "2023-01-01", "2023-01-10"),
                                ("U1", "2023-01-05", "ongoing"), ("U2", "2023-02-02", "2023-03-01")),
    }}],
    sql=code("""
        SELECT b.user_id, SUM(b.watch_duration) AS total_watch_time
        FROM user_behavior_df AS b
        WHERE EXISTS (
            SELECT 1
            FROM subscription_df AS s
            WHERE s.user_id = b.user_id
              AND b.date >= s.subscription_start
              AND (s.subscription_end = 'ongoing' OR b.date <= TRY_CAST(s.subscription_end AS DATE))
        )
        GROUP BY b.user_id
    """),
    snowflake=code("""
        SELECT b.user_id, SUM(b.watch_duration) AS total_watch_time
        FROM user_behavior_df AS b
        WHERE EXISTS (
            SELECT 1
            FROM subscription_df AS s
            WHERE s.user_id = b.user_id
              AND b.date >= s.subscription_start
              AND (s.subscription_end = 'ongoing' OR b.date <= TRY_TO_DATE(s.subscription_end))
        )
        GROUP BY b.user_id
    """),
    dbt="auto",
    python=code("""
        def etl(user_behavior_df, subscription_df):
            views = user_behavior_df.reset_index(names="view").assign(day=pd.to_datetime(user_behavior_df["date"]))
            subs = subscription_df.assign(start=pd.to_datetime(subscription_df["subscription_start"]),
                                          end=pd.to_datetime(subscription_df["subscription_end"], errors="coerce"))
            pairs = views.merge(subs, on="user_id")
            covered = pairs[(pairs["day"] >= pairs["start"])
                            & ((pairs["subscription_end"] == "ongoing") | (pairs["day"] <= pairs["end"]))]
            counted = views[views["view"].isin(covered["view"])]
            return (counted.groupby("user_id", as_index=False)["watch_duration"].sum()
                    .rename(columns={"watch_duration": "total_watch_time"}))
    """),
    polars=code("""
        def etl(user_behavior_df, subscription_df):
            views = user_behavior_df.with_row_index("view").with_columns(pl.col("date").str.to_date().alias("day"))
            subs = subscription_df.with_columns(
                pl.col("subscription_start").str.to_date().alias("start"),
                pl.col("subscription_end").str.to_date(strict=False).alias("end"))
            covered = views.join(subs, on="user_id").filter(
                (pl.col("day") >= pl.col("start"))
                & ((pl.col("subscription_end") == "ongoing") | (pl.col("day") <= pl.col("end"))))
            counted = views.filter(pl.col("view").is_in(covered["view"].implode()))
            return counted.group_by("user_id").agg(pl.col("watch_duration").sum().alias("total_watch_time"))
    """),
    mutants={
        "sql": ["SELECT b.user_id, SUM(b.watch_duration) AS total_watch_time FROM user_behavior_df AS b JOIN subscription_df AS s ON s.user_id = b.user_id WHERE b.date >= s.subscription_start AND (s.subscription_end = 'ongoing' OR b.date <= TRY_CAST(s.subscription_end AS DATE)) GROUP BY b.user_id",
                "SELECT b.user_id, SUM(b.watch_duration) AS total_watch_time FROM user_behavior_df AS b WHERE EXISTS (SELECT 1 FROM subscription_df AS s WHERE s.user_id = b.user_id AND b.date >= s.subscription_start AND (s.subscription_end = 'ongoing' OR b.date < TRY_CAST(s.subscription_end AS DATE))) GROUP BY b.user_id"],
    },
)

# 23 ------------------------------------------------------------------------------------------------------------------
problem(
    n=23, slug="model-metrics", title="Model usage and accuracy per type", difficulty="medium",
    topics=["aggregation", "window-functions", "joins"], industry="Machine learning",
    tables={"df_models": {"model_id": "VARCHAR", "model_name": "VARCHAR", "model_type": "VARCHAR", "accuracy": "DOUBLE"},
            "df_usage": {"model_id": "VARCHAR", "date": "DATE", "uses": "INTEGER"}},
    rename={"Model_ID": "model_id", "Model_Name": "model_name", "Model_Type": "model_type", "Accuracy": "accuracy",
            "Date": "date", "Uses": "uses", "Total_Uses": "total_uses", "Average_Accuracy": "average_accuracy"},
    prompt="""
        For every model that has usage records, return its attributes, its total number of uses, and the average
        accuracy of all the models of its type in df_models (models without usage included in that average). Usage of
        unknown models is ignored.
    """,
    output=["model_id", "model_name", "model_type", "accuracy", "total_uses", "average_accuracy"],
    grain="One row per model with at least one usage record.",
    pitfall="Average the accuracy over df_models, one row per model: averaging after the join with usage weighs a "
            "model by its number of usage days, and drops the unused models from the average.",
    hints=["Sum uses per model in one aggregation, average accuracy per type in another.",
           "Or AVG(accuracy) OVER (PARTITION BY model_type) on df_models before joining."],
    explanation="""
        The two measures live at different grains (model and model type) and must be computed before joining, or the
        usage rows repeat the models. A window function over df_models gives the type average on every model row.
    """,
    changes=["Columns are snake_case (ZillaCode used Model_ID, Total_Uses, ...)."],
    edges=[{"id": "unused-and-weighted", "tables": {
        "df_models": rows("model_id model_name model_type accuracy", ("M1", "Alpha", "T1", 0.8), ("M2", "Beta", "T1", 0.6),
                          ("M3", "Gamma", "T2", 0.9), ("M4", "Delta", "T2", 0.5)),
        "df_usage": rows("model_id date uses", ("M1", "2023-01-01", 10), ("M3", "2023-01-01", 5),
                         ("M3", "2023-01-02", 7), ("M4", "2023-01-01", 1), ("M9", "2023-01-01", 99)),
    }}],
    sql=code("""
        WITH model_usage AS (
            SELECT model_id, SUM(uses) AS total_uses
            FROM df_usage
            GROUP BY model_id
        ),
        type_accuracy AS (
            SELECT model_type, AVG(accuracy) AS average_accuracy
            FROM df_models
            GROUP BY model_type
        )
        SELECT m.model_id, m.model_name, m.model_type, m.accuracy, u.total_uses, t.average_accuracy
        FROM df_models AS m
        JOIN model_usage AS u ON m.model_id = u.model_id
        JOIN type_accuracy AS t ON m.model_type = t.model_type
    """),
    snowflake=code("""
        WITH models AS (
            SELECT model_id, model_name, model_type, accuracy,
                   AVG(accuracy) OVER (PARTITION BY model_type) AS average_accuracy
            FROM df_models
        ),
        model_usage AS (
            SELECT model_id, SUM(uses) AS total_uses
            FROM df_usage
            GROUP BY model_id
        )
        SELECT m.model_id, m.model_name, m.model_type, m.accuracy, u.total_uses, m.average_accuracy
        FROM models AS m
        JOIN model_usage AS u ON m.model_id = u.model_id
    """),
    dbt="auto",
    python=code("""
        def etl(df_models, df_usage):
            usage = df_usage.groupby("model_id", as_index=False).agg(total_uses=("uses", "sum"))
            models = df_models.assign(average_accuracy=df_models.groupby("model_type")["accuracy"].transform("mean"))
            result = models.merge(usage, on="model_id")
            return result[["model_id", "model_name", "model_type", "accuracy", "total_uses", "average_accuracy"]]
    """),
    polars=code("""
        def etl(df_models, df_usage):
            usage = df_usage.group_by("model_id").agg(pl.col("uses").sum().alias("total_uses"))
            models = df_models.with_columns(pl.col("accuracy").mean().over("model_type").alias("average_accuracy"))
            return models.join(usage, on="model_id").select(
                "model_id", "model_name", "model_type", "accuracy", "total_uses", "average_accuracy")
    """),
    sparklab=code("""
        from pyspark.sql import functions as F

        models = spark.table("df_models")
        usage = spark.table("df_usage").groupBy("model_id").agg(F.sum("uses").alias("total_uses"))
        type_accuracy = models.groupBy("model_type").agg(F.avg("accuracy").alias("average_accuracy"))
        models.join(usage, "model_id").join(type_accuracy, "model_type").select(
            "model_id", "model_name", "model_type", "accuracy", "total_uses", "average_accuracy")
    """),
    mutants={
        "sql": ["WITH j AS (SELECT m.model_id, m.model_name, m.model_type, m.accuracy, u.uses FROM df_models AS m JOIN df_usage AS u ON m.model_id = u.model_id) SELECT model_id, model_name, model_type, accuracy, SUM(uses) OVER (PARTITION BY model_id) AS total_uses, AVG(accuracy) OVER (PARTITION BY model_type) AS average_accuracy FROM j QUALIFY ROW_NUMBER() OVER (PARTITION BY model_id ORDER BY uses) = 1"],
        "python": [code("""
            def etl(df_models, df_usage):
                joined = df_models.merge(df_usage, on="model_id")
                joined["total_uses"] = joined.groupby("model_id")["uses"].transform("sum")
                joined["average_accuracy"] = joined.groupby("model_type")["accuracy"].transform("mean")
                return joined.drop_duplicates("model_id")[["model_id", "model_name", "model_type", "accuracy", "total_uses", "average_accuracy"]]
        """)],
    },
)

# 24 ------------------------------------------------------------------------------------------------------------------
CHURN = ["user_id", "account_created_date", "location", "activity_date", "activity_type", "exit_date", "exit_reason"]
problem(
    n=24, slug="churn-timeline", title="Churn timeline without duplicate activities", difficulty="hard",
    topics=["full-outer-join", "deduplication", "ordering", "nulls"], industry="Software",
    tables={"df_accounts": {"user_id": "VARCHAR", "account_created_date": "DATE", "location": "VARCHAR"},
            "df_activities": {"user_id": "VARCHAR", "activity_date": "DATE", "activity_type": "VARCHAR"},
            "df_exit_surveys": {"user_id": "VARCHAR", "exit_date": "DATE", "exit_reason": "VARCHAR"}},
    prompt="""
        Combine user accounts, activities and exit surveys into one timeline: one row per distinct activity of a user
        (activities logged twice with the same user, date and type count once), with the account and exit survey
        columns repeated. A user present in only some of the tables still appears, with NULLs for the missing columns.
        Sort by user_id ascending, then activity_date descending with a missing activity date last, then activity_type
        ascending.
    """,
    output=CHURN, ordered=True,
    order_text="Row order is graded: user_id ascending, activity_date descending with NULLs last, activity_type ascending.",
    grain="One row per distinct activity, or one row for a user without activities.",
    pitfall="Descending sorts disagree on NULLs: Snowflake puts them first, DuckDB, pandas and Spark last, and Polars "
            "first unless nulls_last=True. Say NULLS LAST explicitly.",
    hints=["SELECT DISTINCT from the activities, then FULL OUTER JOIN the three tables on user_id.",
           "ORDER BY user_id, activity_date DESC NULLS LAST, activity_type."],
    explanation="""
        Deduplicate the activities, full-outer-join the three tables on the user (COALESCE the key), and sort with an
        explicit NULL placement so the order means the same thing on every engine.
    """,
    changes=["Every user of any table appears (the statement's rule; ZillaCode's SQL started from accounts). The sort "
             "places a missing activity date last and breaks same-day ties by activity_type; row order is graded."],
    edges=[{"id": "null-date-and-orphans", "tables": {
        "df_accounts": rows("user_id account_created_date location", ("U1", "2023-01-01", "Paris"),
                            ("U3", "2023-01-03", "Rome")),
        "df_activities": rows("user_id activity_date activity_type", ("U1", "2023-02-01", "Login"),
                              ("U1", None, "Import"), ("U1", "2023-02-05", "Upload"), ("U1", "2023-02-05", "Export"),
                              ("U1", "2023-02-01", "Login"), ("U2", "2023-02-02", "Login")),
        "df_exit_surveys": rows("user_id exit_date exit_reason", ("U1", "2023-03-01", "Price"), ("U4", "2023-03-04", "Bugs")),
    }}],
    sql=code("""
        WITH activities AS (
            SELECT DISTINCT user_id, activity_date, activity_type FROM df_activities
        )
        SELECT COALESCE(a.user_id, act.user_id, e.user_id) AS user_id,
               a.account_created_date, a.location, act.activity_date, act.activity_type, e.exit_date, e.exit_reason
        FROM df_accounts AS a
        FULL OUTER JOIN activities AS act ON a.user_id = act.user_id
        FULL OUTER JOIN df_exit_surveys AS e ON COALESCE(a.user_id, act.user_id) = e.user_id
        ORDER BY user_id, act.activity_date DESC NULLS LAST, act.activity_type
    """),
    snowflake="same",
    python=code("""
        def etl(df_accounts, df_activities, df_exit_surveys):
            combined = (df_accounts.merge(df_activities.drop_duplicates(), on="user_id", how="outer")
                        .merge(df_exit_surveys, on="user_id", how="outer"))
            combined = combined.sort_values(["user_id", "activity_date", "activity_type"],
                                            ascending=[True, False, True], na_position="last")
            return combined[["user_id", "account_created_date", "location", "activity_date", "activity_type",
                             "exit_date", "exit_reason"]]
    """),
    polars=code("""
        def etl(df_accounts, df_activities, df_exit_surveys):
            combined = (df_accounts.join(df_activities.unique(), on="user_id", how="full", coalesce=True)
                        .join(df_exit_surveys, on="user_id", how="full", coalesce=True))
            return combined.sort(["user_id", "activity_date", "activity_type"], descending=[False, True, False],
                                 nulls_last=True).select("user_id", "account_created_date", "location", "activity_date",
                                                         "activity_type", "exit_date", "exit_reason")
    """),
    sparklab=code("""
        from pyspark.sql import functions as F

        accounts = spark.table("df_accounts")
        activities = spark.table("df_activities").distinct()
        exits = spark.table("df_exit_surveys")
        accounts.join(activities, "user_id", "full").join(exits, "user_id", "full").select(
            "user_id", "account_created_date", "location", "activity_date", "activity_type", "exit_date", "exit_reason"
        ).orderBy(F.col("user_id"), F.col("activity_date").desc(), F.col("activity_type"))
    """),
    mutants={
        "sql": ["WITH act AS (SELECT DISTINCT user_id, activity_date, activity_type FROM df_activities) SELECT a.user_id, a.account_created_date, a.location, act.activity_date, act.activity_type, e.exit_date, e.exit_reason FROM df_accounts AS a LEFT JOIN act ON a.user_id = act.user_id LEFT JOIN df_exit_surveys AS e ON a.user_id = e.user_id ORDER BY a.user_id, act.activity_date DESC NULLS LAST, act.activity_type",
                "SELECT COALESCE(a.user_id, act.user_id, e.user_id) AS user_id, a.account_created_date, a.location, act.activity_date, act.activity_type, e.exit_date, e.exit_reason FROM df_accounts AS a FULL OUTER JOIN df_activities AS act ON a.user_id = act.user_id FULL OUTER JOIN df_exit_surveys AS e ON COALESCE(a.user_id, act.user_id) = e.user_id ORDER BY user_id, act.activity_date DESC NULLS LAST, act.activity_type"],
        "snowflake": ["WITH activities AS (SELECT DISTINCT user_id, activity_date, activity_type FROM df_activities) SELECT COALESCE(a.user_id, act.user_id, e.user_id) AS user_id, a.account_created_date, a.location, act.activity_date, act.activity_type, e.exit_date, e.exit_reason FROM df_accounts AS a FULL OUTER JOIN activities AS act ON a.user_id = act.user_id FULL OUTER JOIN df_exit_surveys AS e ON COALESCE(a.user_id, act.user_id) = e.user_id ORDER BY user_id, act.activity_date DESC, act.activity_type"],
        "polars": [code("""
            def etl(df_accounts, df_activities, df_exit_surveys):
                combined = (df_accounts.join(df_activities.unique(), on="user_id", how="full", coalesce=True)
                            .join(df_exit_surveys, on="user_id", how="full", coalesce=True))
                return combined.sort(["user_id", "activity_date", "activity_type"], descending=[False, True, False]).select(
                    "user_id", "account_created_date", "location", "activity_date", "activity_type", "exit_date", "exit_reason")
        """)],
    },
)

# 25 ------------------------------------------------------------------------------------------------------------------
problem(
    n=25, slug="minerals-per-location", title="Mineral output per location", difficulty="easy",
    topics=["aggregation", "joins", "ordering"], industry="Mining",
    tables={"mines": {"id": "INTEGER", "name": "VARCHAR", "location": "VARCHAR"},
            "extraction": {"mine_id": "INTEGER", "date": "DATE", "mineral": "VARCHAR", "quantity": "DOUBLE"}},
    prompt="""
        A mining company records extractions per mine. Return the total quantity of each mineral extracted in each
        location (several mines can share a location), sorted by location and then by mineral. Extractions from
        unknown mines are ignored.
    """,
    output=["location", "mineral", "total_quantity"], ordered=True,
    order_text="Row order is graded: location ascending, then mineral ascending.",
    grain="One row per (location, mineral).",
    pitfall="Group by location, not by mine: two mines in the same location must add up. The join keys have "
            "different names (mines.id, extraction.mine_id).",
    hints=["JOIN extraction ON mines.id = extraction.mine_id.", "GROUP BY location, mineral ORDER BY location, mineral."],
    explanation="Join on the differently named keys, aggregate at the (location, mineral) grain and sort by both.",
    edges=[{"id": "shared-location", "tables": {
        "mines": rows("id name location", (1, "Alpha", "Chile"), (2, "Beta", "Chile"), (3, "Gamma", "Peru")),
        "extraction": rows("mine_id date mineral quantity", (1, "2023-06-01", "Copper", 10.0),
                           (2, "2023-06-01", "Copper", 5.0), (2, "2023-06-02", "Gold", None), (2, "2023-06-03", "Gold", 1.5),
                           (3, "2023-06-01", "Copper", 2.0), (9, "2023-06-01", "Copper", 99.0)),
    }}],
    sql=code("""
        SELECT m.location, e.mineral, SUM(e.quantity) AS total_quantity
        FROM mines AS m
        JOIN extraction AS e ON m.id = e.mine_id
        GROUP BY m.location, e.mineral
        ORDER BY m.location, e.mineral
    """),
    snowflake="same",
    python=code("""
        def etl(mines, extraction):
            joined = mines.merge(extraction, left_on="id", right_on="mine_id")
            totals = joined.groupby(["location", "mineral"], as_index=False)["quantity"].sum()
            return totals.rename(columns={"quantity": "total_quantity"}).sort_values(["location", "mineral"])
    """),
    polars=code("""
        def etl(mines, extraction):
            joined = mines.join(extraction, left_on="id", right_on="mine_id")
            return joined.group_by("location", "mineral").agg(
                pl.col("quantity").sum().alias("total_quantity")).sort("location", "mineral")
    """),
    sparklab=code("""
        from pyspark.sql import functions as F

        mines = spark.table("mines").withColumnRenamed("id", "mine_id").select("mine_id", "location")
        extraction = spark.table("extraction")
        extraction.join(mines, "mine_id").groupBy("location", "mineral").agg(
            F.sum("quantity").alias("total_quantity")
        ).orderBy("location", "mineral")
    """),
    mutants={
        "sql": ["SELECT m.location, e.mineral, SUM(e.quantity) AS total_quantity FROM mines AS m JOIN extraction AS e ON m.id = e.mine_id GROUP BY m.location, e.mineral ORDER BY e.mineral, m.location",
                "SELECT m.location, e.mineral, SUM(e.quantity) AS total_quantity FROM mines AS m JOIN extraction AS e ON m.id = e.mine_id GROUP BY m.id, m.location, e.mineral ORDER BY m.location, e.mineral"],
    },
)

# 26 ------------------------------------------------------------------------------------------------------------------
problem(
    n=26, slug="discount-tags", title="Discounts hidden in descriptions", difficulty="medium",
    topics=["regular-expressions", "strings", "nulls"], industry="Consumer goods",
    tables={"df": {"store_id": "VARCHAR", "product_name": "VARCHAR", "category": "VARCHAR", "sold_units": "INTEGER",
                   "description": "VARCHAR"}},
    rename={"StoreID": "store_id", "ProductName": "product_name", "Category": "category", "SoldUnits": "sold_units",
            "Description": "description", "Discount": "discount"},
    prompt="""
        Product descriptions may carry a discount tag such as '[10% off]': a percentage of one to three digits, '%',
        optional spaces, then 'off', in square brackets, in lower case. Add a column discount with the first tag's
        percentage as a decimal (0.10 for 10%), or 0 when the description has no tag. Other numbers in the text are
        not discounts.
    """,
    output=["store_id", "product_name", "category", "sold_units", "description", "discount"],
    grain="One row per input row.",
    pitfall="Extract the digits of the tag, not the first number of the description ('Pack of 6 [10% off]' is 10%). "
            "Snowflake's REGEXP_SUBSTR has no capture group in this subset: extract the tag, then its digits.",
    hints=["The pattern \\[([0-9]{1,3})%\\s*off\\] captures the percentage.",
           "Divide by 100 and turn a missing match into 0."],
    explanation="""
        A regular expression locates the tag and a capture group (or a second extraction) keeps its digits. A missing
        match is NULL (Snowflake), '' (DuckDB) or NaN (pandas), so the conversion must be safe (TRY_CAST) and the
        result defaulted to 0.
    """,
    changes=["Columns are snake_case (ZillaCode used StoreID, Discount, ...). ZillaCode had no SQL answer for this "
             "problem; CodeDELeet authored one, and Datapass's references follow the statement."],
    edges=[{"id": "tag-variants", "tables": {"df": rows(
        "store_id product_name category sold_units description",
        ("S201", "Cans", "Food", 12, "Pack of 6 [10% off]"), ("S202", "Soap", "Hygiene", 3, "Gentle soap [5%off]"),
        ("S203", "Hat", "Clothes", 4, "Wool hat [25% OFF]"), ("S204", "Cups", "Home", 8, "Set of 4 cups"),
        ("S205", "Pens", "Office", 9, "Blue pens [15% off] [30% off]"),
    )}}],
    sql=code(r"""
        SELECT store_id, product_name, category, sold_units, description,
               COALESCE(TRY_CAST(regexp_extract(description, '\[([0-9]{1,3})%\s*off\]', 1) AS DOUBLE) / 100, 0) AS discount
        FROM df
    """),
    snowflake=code(r"""
        SELECT store_id, product_name, category, sold_units, description,
               ZEROIFNULL(TRY_CAST(REGEXP_SUBSTR(REGEXP_SUBSTR(description, '\\[[0-9]{1,3}%\\s*off\\]'), '[0-9]+') AS FLOAT) / 100) AS discount
        FROM df
    """),
    dbt="auto",
    python=code(r"""
        def etl(df):
            percent = df["description"].str.extract(r"\[([0-9]{1,3})%\s*off\]", expand=False).astype(float)
            return df.assign(discount=(percent / 100).fillna(0))
    """),
    polars=code(r"""
        def etl(df):
            percent = pl.col("description").str.extract(r"\[([0-9]{1,3})%\s*off\]", 1).cast(pl.Float64)
            return df.with_columns((percent / 100).fill_null(0).alias("discount"))
    """),
    mutants={
        "sql": [r"SELECT store_id, product_name, category, sold_units, description, COALESCE(TRY_CAST(regexp_extract(description, '([0-9]+)', 1) AS DOUBLE) / 100, 0) AS discount FROM df",
                r"SELECT store_id, product_name, category, sold_units, description, COALESCE(TRY_CAST(regexp_extract(description, '\[([0-9]{1,3})% off\]', 1) AS DOUBLE) / 100, 0) AS discount FROM df"],
        "snowflake": [r"SELECT store_id, product_name, category, sold_units, description, ZEROIFNULL(TRY_CAST(REGEXP_SUBSTR(description, '[0-9]+') AS FLOAT) / 100) AS discount FROM df"],
    },
)

# 27 ------------------------------------------------------------------------------------------------------------------
problem(
    n=27, slug="mortgage-rate", title="Rate of each mortgage type", difficulty="easy",
    topics=["aggregation", "distinct"], industry="Mortgages",
    tables={"mortgage_details": {"mortgage_id": "VARCHAR", "mortgage_type": "VARCHAR", "interest_rate": "DOUBLE"},
            "user_mortgages": {"user_id": "VARCHAR", "mortgage_id": "VARCHAR"}},
    rename_tables={"MortgageDetails": "mortgage_details", "UserMortgages": "user_mortgages"},
    rename={"MortgageID": "mortgage_id", "MortgageType": "mortgage_type", "InterestRate": "interest_rate",
            "UserID": "user_id", "RateOfMortgage": "rate_of_mortgage"},
    prompt="""
        For each mortgage type held by at least one user, return rate_of_mortgage, defined by the lender as the sum of
        the interest rates of the users' mortgages of that type divided by the number of distinct users holding that
        type. A user holding two mortgages of the same type adds both rates but counts once.
    """,
    output=["mortgage_type", "rate_of_mortgage"],
    grain="One row per mortgage type held by at least one user.",
    pitfall="This is not AVG(interest_rate): the denominator counts distinct users, not mortgages.",
    hints=["Join user_mortgages to mortgage_details, then group by mortgage_type.",
           "SUM(interest_rate) / COUNT(DISTINCT user_id)."],
    explanation="""
        Implement the business definition exactly: a sum over the joined rows divided by a distinct count. It equals
        the average only when no user holds two mortgages of the same type.
    """,
    changes=["Tables and columns are snake_case (ZillaCode used MortgageDetails, RateOfMortgage, ...)."],
    edges=[{"id": "two-mortgages-one-user", "tables": {
        "mortgage_details": rows("mortgage_id mortgage_type interest_rate", ("M1", "Fixed", 4.0), ("M2", "Fixed", 5.0),
                                 ("M3", "Variable", 3.0), ("M4", "Balloon", 9.0)),
        "user_mortgages": rows("user_id mortgage_id", ("U1", "M1"), ("U1", "M2"), ("U2", "M1"), ("U3", "M3"), ("U4", "M9")),
    }}],
    sql=code("""
        SELECT d.mortgage_type,
               SUM(d.interest_rate) / COUNT(DISTINCT u.user_id) AS rate_of_mortgage
        FROM user_mortgages AS u
        JOIN mortgage_details AS d ON u.mortgage_id = d.mortgage_id
        GROUP BY d.mortgage_type
    """),
    snowflake="same", dbt="auto",
    python=code("""
        def etl(mortgage_details, user_mortgages):
            joined = user_mortgages.merge(mortgage_details, on="mortgage_id")
            per_type = joined.groupby("mortgage_type").agg(total=("interest_rate", "sum"), users=("user_id", "nunique"))
            per_type["rate_of_mortgage"] = per_type["total"] / per_type["users"]
            return per_type.reset_index()[["mortgage_type", "rate_of_mortgage"]]
    """),
    polars=code("""
        def etl(mortgage_details, user_mortgages):
            joined = user_mortgages.join(mortgage_details, on="mortgage_id")
            return joined.group_by("mortgage_type").agg(
                (pl.col("interest_rate").sum() / pl.col("user_id").n_unique()).alias("rate_of_mortgage"))
    """),
    sparklab=code("""
        from pyspark.sql import functions as F

        users = spark.table("user_mortgages")
        details = spark.table("mortgage_details")
        per_type = users.join(details, "mortgage_id").groupBy("mortgage_type").agg(
            F.sum("interest_rate").alias("total_rate"), F.countDistinct("user_id").alias("users"))
        per_type.select("mortgage_type", (F.col("total_rate") / F.col("users")).alias("rate_of_mortgage"))
    """),
    mutants={
        "sql": ["SELECT d.mortgage_type, AVG(d.interest_rate) AS rate_of_mortgage FROM user_mortgages AS u JOIN mortgage_details AS d ON u.mortgage_id = d.mortgage_id GROUP BY d.mortgage_type",
                "SELECT d.mortgage_type, SUM(d.interest_rate) / COUNT(u.user_id) AS rate_of_mortgage FROM user_mortgages AS u JOIN mortgage_details AS d ON u.mortgage_id = d.mortgage_id GROUP BY d.mortgage_type"],
    },
)

# 28 ------------------------------------------------------------------------------------------------------------------
problem(
    n=28, slug="serial-numbers", title="Serial numbers by manufacturing date", difficulty="easy",
    topics=["window-functions", "joins"], industry="Manufacturing",
    tables={"df1": {"product_id": "VARCHAR", "manufacturing_date": "DATE", "manufacturing_location": "VARCHAR"},
            "df2": {"product_id": "VARCHAR", "product_name": "VARCHAR", "product_type": "VARCHAR"}},
    prompt="""
        Join the manufacturing records (df1) to the product details (df2) on product_id and number the joined rows
        1, 2, 3, ... by manufacturing_date ascending; rows with the same date are numbered in product_id order.
        Records without product details are left out.
    """,
    output=["product_id", "manufacturing_date", "manufacturing_location", "product_name", "product_type", "row_number"],
    grain="One row per manufacturing record with product details.",
    pitfall="The numbering is global (no PARTITION BY) and needs a tie-breaker for equal dates to be deterministic.",
    hints=["ROW_NUMBER() OVER (ORDER BY manufacturing_date, product_id).", "Number after the join, not before."],
    explanation="""
        ROW_NUMBER over the whole joined result, ordered by the date and the product id. Numbering df1 before the
        join would leave gaps where records have no product details.
    """,
    changes=["Same-date rows are numbered in product_id order (ZillaCode left ties to the engine)."],
    edges=[{"id": "same-date-and-missing-details", "tables": {
        "df1": rows("product_id manufacturing_date manufacturing_location", ("P3", "2023-05-02", "Lyon"),
                    ("P1", "2023-05-02", "Lille"), ("P9", "2023-05-01", "Nice"), ("P2", "2023-05-03", "Pau")),
        "df2": rows("product_id product_name product_type", ("P1", "Bolt", "Hardware"), ("P2", "Nut", "Hardware"),
                    ("P3", "Gear", "Parts")),
    }}],
    sql=code("""
        SELECT a.product_id, a.manufacturing_date, a.manufacturing_location, b.product_name, b.product_type,
               ROW_NUMBER() OVER (ORDER BY a.manufacturing_date, a.product_id) AS row_number
        FROM df1 AS a
        JOIN df2 AS b ON a.product_id = b.product_id
    """),
    snowflake="same", dbt="auto",
    python=code("""
        def etl(df1, df2):
            joined = df1.merge(df2, on="product_id").sort_values(["manufacturing_date", "product_id"])
            joined["row_number"] = range(1, len(joined) + 1)
            return joined
    """),
    polars=code("""
        def etl(df1, df2):
            joined = df1.join(df2, on="product_id").sort("manufacturing_date", "product_id")
            return joined.with_columns(pl.int_range(1, pl.len() + 1).alias("row_number"))
    """),
    sparklab=code("""
        from pyspark.sql import functions as F
        from pyspark.sql import Window

        details = spark.table("df2")
        records = spark.table("df1")
        by_date = Window.orderBy("manufacturing_date", "product_id")
        records.join(details, "product_id").withColumn("row_number", F.row_number().over(by_date))
    """),
    mutants={
        "sql": ["SELECT a.product_id, a.manufacturing_date, a.manufacturing_location, b.product_name, b.product_type, ROW_NUMBER() OVER (ORDER BY a.manufacturing_date, a.product_id DESC) AS row_number FROM df1 AS a JOIN df2 AS b ON a.product_id = b.product_id",
                "WITH n AS (SELECT *, ROW_NUMBER() OVER (ORDER BY manufacturing_date, product_id) AS row_number FROM df1) SELECT n.product_id, n.manufacturing_date, n.manufacturing_location, b.product_name, b.product_type, n.row_number FROM n JOIN df2 AS b ON n.product_id = b.product_id"],
    },
)

# 29 ------------------------------------------------------------------------------------------------------------------
problem(
    n=29, slug="budget-variance", title="Variance of budgets and spending", difficulty="medium",
    topics=["aggregation", "statistics", "nulls"], industry="Public sector",
    tables={"budget_df": {"department": "VARCHAR", "year": "INTEGER", "budget": "DOUBLE"},
            "spending_df": {"department": "VARCHAR", "year": "INTEGER", "spending": "DOUBLE"}},
    rename={"Department": "department", "Year": "year", "Budget": "budget", "Spending": "spending",
            "Budget_Variance": "budget_variance", "Spending_Variance": "spending_variance"},
    prompt="""
        For each department present in both tables, return the sample variance of its yearly budget and of its yearly
        spending, each truncated toward zero to an integer. A department with a single year has no sample variance
        (NULL).
    """,
    output=["department", "budget_variance", "spending_variance"],
    grain="One row per department present in both tables.",
    pitfall="Sample variance divides by n - 1 (VAR_SAMP, pandas' var(), Polars' var()); VAR_POP divides by n. With one "
            "value it is undefined, and truncating is not rounding.",
    hints=["VAR_SAMP per department in each table, then an inner join.", "TRUNC then cast to an integer."],
    explanation="""
        Aggregate each table per department with the sample variance, truncate, and join the two results. The NULL for
        single-year departments must survive the truncation (pandas' astype(int) would fail on NaN).
    """,
    changes=["Both variances are truncated integers, as the statement's schema says (ZillaCode truncated only the "
             "spending variance). Columns are snake_case."],
    edges=[{"id": "single-year-and-truncation", "tables": {
        "budget_df": rows("department year budget", ("Arts", 2020, 10.0), ("Arts", 2021, 13.0), ("Parks", 2021, 50.0),
                          ("Roads", 2020, 1.0), ("Roads", 2021, 2.0)),
        "spending_df": rows("department year spending", ("Arts", 2020, 1.0), ("Arts", 2021, 2.0), ("Arts", 2022, 4.0),
                            ("Parks", 2021, 40.0), ("Water", 2021, 7.0), ("Water", 2022, 9.0)),
    }}],
    sql=code("""
        WITH budgets AS (
            SELECT department, CAST(TRUNC(VAR_SAMP(budget)) AS BIGINT) AS budget_variance
            FROM budget_df
            GROUP BY department
        ),
        spendings AS (
            SELECT department, CAST(TRUNC(VAR_SAMP(spending)) AS BIGINT) AS spending_variance
            FROM spending_df
            GROUP BY department
        )
        SELECT b.department, b.budget_variance, s.spending_variance
        FROM budgets AS b
        JOIN spendings AS s ON b.department = s.department
    """),
    snowflake=code("""
        WITH budgets AS (
            SELECT department, TRUNC(VAR_SAMP(budget))::INT AS budget_variance
            FROM budget_df
            GROUP BY department
        ),
        spendings AS (
            SELECT department, TRUNC(VAR_SAMP(spending))::INT AS spending_variance
            FROM spending_df
            GROUP BY department
        )
        SELECT b.department, b.budget_variance, s.spending_variance
        FROM budgets AS b
        JOIN spendings AS s ON b.department = s.department
    """),
    dbt="auto",
    python=code("""
        def etl(budget_df, spending_df):
            def truncated(values):
                variance = values.var()
                return None if pd.isna(variance) else int(variance)

            budgets = budget_df.groupby("department")["budget"].apply(truncated).rename("budget_variance")
            spendings = spending_df.groupby("department")["spending"].apply(truncated).rename("spending_variance")
            return pd.concat([budgets, spendings], axis=1, join="inner").reset_index()
    """),
    polars=code("""
        def etl(budget_df, spending_df):
            budgets = budget_df.group_by("department").agg(
                pl.col("budget").var().floor().cast(pl.Int64).alias("budget_variance"))
            spendings = spending_df.group_by("department").agg(
                pl.col("spending").var().floor().cast(pl.Int64).alias("spending_variance"))
            return budgets.join(spendings, on="department")
    """),
    mutants={
        "sql": ["WITH b AS (SELECT department, CAST(TRUNC(VAR_POP(budget)) AS BIGINT) AS budget_variance FROM budget_df GROUP BY department), s AS (SELECT department, CAST(TRUNC(VAR_POP(spending)) AS BIGINT) AS spending_variance FROM spending_df GROUP BY department) SELECT b.department, b.budget_variance, s.spending_variance FROM b JOIN s ON b.department = s.department",
                "WITH b AS (SELECT department, CAST(ROUND(VAR_SAMP(budget)) AS BIGINT) AS budget_variance FROM budget_df GROUP BY department), s AS (SELECT department, CAST(ROUND(VAR_SAMP(spending)) AS BIGINT) AS spending_variance FROM spending_df GROUP BY department) SELECT b.department, b.budget_variance, s.spending_variance FROM b JOIN s ON b.department = s.department"],
    },
)

# 30 ------------------------------------------------------------------------------------------------------------------
problem(
    n=30, slug="valid-keys", title="Drop invalid and duplicate keys", difficulty="hard",
    topics=["data-quality", "window-functions", "dates"], industry="Accounting",
    tables={"df_transactions": {"transaction_id": "INTEGER", "client_id": "INTEGER", "date": "VARCHAR", "amount": "DOUBLE"},
            "df_clients": {"client_id": "INTEGER", "client_name": "VARCHAR", "industry": "VARCHAR"}},
    rename={"TransactionID": "transaction_id", "ClientID": "client_id", "Date": "date", "Amount": "amount",
            "ClientName": "client_name", "Industry": "industry"},
    prompt="""
        Clean two feeds before combining them. A transaction is valid when its transaction_id is greater than 0 and
        appears only once in df_transactions (every copy of a duplicated id is dropped), and its date is a real
        calendar date written 'YYYY-MM-DD'. A client is valid when its client_id is greater than 0 and appears only
        once in df_clients. Return the valid transactions of valid clients with the client's name and industry.
    """,
    output=["transaction_id", "client_id", "date", "amount", "client_name", "industry"],
    grain="One row per valid transaction of a valid client.",
    pitfall="A duplicated key is ambiguous: keeping 'the first' copy depends on the engine's row order. Count the "
            "copies over the whole feed (COUNT(*) OVER (PARTITION BY key)) before filtering. '2023-25-01' has the "
            "right shape but is not a date.",
    hints=["COUNT(*) OVER (PARTITION BY transaction_id) = 1 marks unique ids.",
           "Check the shape with a regular expression and the calendar with TRY_CAST (TRY_TO_DATE in Snowflake)."],
    explanation="""
        Data quality rules as filters: key positivity, key uniqueness over the whole feed (a window count), and a date
        that both matches the text format and parses to a real date. Then an inner join keeps transactions of valid
        clients only.
    """,
    changes=["Every copy of a duplicated key is dropped, as the statement says (ZillaCode kept an arbitrary first copy), "
             "and a date must be a real calendar date (ZillaCode kept '2023-25-01'). amount stays a DOUBLE. Columns "
             "are snake_case."],
    edges=[{"id": "duplicates-and-bad-dates", "tables": {
        "df_transactions": rows("transaction_id client_id date amount", (1, 1, "2023-02-28", 10.0),
                                (2, 1, "2023-02-30", 20.0), (3, 1, "2023-7-01", 30.0), (4, 2, "2023-03-01", 40.0),
                                (4, 1, "not a date", 41.0), (5, 3, "2023-03-02", 50.0), (0, 1, "2023-03-03", 60.0),
                                (6, 1, "2024-02-29", 70.0)),
        "df_clients": rows("client_id client_name industry", (1, "Acme", "Tech"), (2, "Bolt", "Energy"),
                           (3, "Core", "Retail"), (3, "Core", "Retail"), (0, "Zero", "None")),
    }}],
    sql=code("""
        WITH transactions AS (
            SELECT transaction_id, client_id, date, amount
            FROM (SELECT *, COUNT(*) OVER (PARTITION BY transaction_id) AS copies FROM df_transactions)
            WHERE copies = 1
              AND transaction_id > 0
              AND regexp_full_match(date, '[0-9]{4}-[0-9]{2}-[0-9]{2}')
              AND TRY_CAST(date AS DATE) IS NOT NULL
        ),
        clients AS (
            SELECT client_id, client_name, industry
            FROM (SELECT *, COUNT(*) OVER (PARTITION BY client_id) AS copies FROM df_clients)
            WHERE copies = 1 AND client_id > 0
        )
        SELECT t.transaction_id, t.client_id, t.date, t.amount, c.client_name, c.industry
        FROM transactions AS t
        JOIN clients AS c ON t.client_id = c.client_id
    """),
    snowflake=code("""
        WITH transactions AS (
            SELECT transaction_id, client_id, date, amount
            FROM df_transactions
            QUALIFY COUNT(*) OVER (PARTITION BY transaction_id) = 1
        ),
        clients AS (
            SELECT client_id, client_name, industry
            FROM df_clients
            QUALIFY COUNT(*) OVER (PARTITION BY client_id) = 1
        )
        SELECT t.transaction_id, t.client_id, t.date, t.amount, c.client_name, c.industry
        FROM transactions AS t
        JOIN clients AS c ON t.client_id = c.client_id
        WHERE t.transaction_id > 0
          AND c.client_id > 0
          AND REGEXP_LIKE(t.date, '[0-9]{4}-[0-9]{2}-[0-9]{2}')
          AND TRY_TO_DATE(t.date, 'YYYY-MM-DD') IS NOT NULL
    """),
    dbt="auto",
    python=code("""
        def etl(df_transactions, df_clients):
            transactions = df_transactions[~df_transactions["transaction_id"].duplicated(keep=False)]
            shaped = transactions["date"].str.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
            real = pd.to_datetime(transactions["date"], format="%Y-%m-%d", errors="coerce").notna()
            transactions = transactions[(transactions["transaction_id"] > 0) & shaped & real]
            clients = df_clients[~df_clients["client_id"].duplicated(keep=False) & (df_clients["client_id"] > 0)]
            return transactions.merge(clients, on="client_id")[
                ["transaction_id", "client_id", "date", "amount", "client_name", "industry"]]
    """),
    polars=code("""
        def etl(df_transactions, df_clients):
            transactions = df_transactions.filter(
                (pl.len().over("transaction_id") == 1)
                & (pl.col("transaction_id") > 0)
                & pl.col("date").str.contains(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
                & pl.col("date").str.to_date("%Y-%m-%d", strict=False).is_not_null())
            clients = df_clients.filter((pl.len().over("client_id") == 1) & (pl.col("client_id") > 0))
            return transactions.join(clients, on="client_id").select(
                "transaction_id", "client_id", "date", "amount", "client_name", "industry")
    """),
    mutants={
        "sql": ["WITH t AS (SELECT transaction_id, client_id, date, amount FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY transaction_id ORDER BY date) AS n FROM df_transactions) WHERE n = 1 AND transaction_id > 0 AND regexp_full_match(date, '[0-9]{4}-[0-9]{2}-[0-9]{2}') AND TRY_CAST(date AS DATE) IS NOT NULL), c AS (SELECT client_id, client_name, industry FROM (SELECT *, COUNT(*) OVER (PARTITION BY client_id) AS copies FROM df_clients) WHERE copies = 1 AND client_id > 0) SELECT t.transaction_id, t.client_id, t.date, t.amount, c.client_name, c.industry FROM t JOIN c ON t.client_id = c.client_id",
                "WITH t AS (SELECT transaction_id, client_id, date, amount FROM (SELECT *, COUNT(*) OVER (PARTITION BY transaction_id) AS copies FROM df_transactions) WHERE copies = 1 AND transaction_id > 0 AND regexp_full_match(date, '[0-9]{4}-[0-9]{2}-[0-9]{2}')), c AS (SELECT client_id, client_name, industry FROM (SELECT *, COUNT(*) OVER (PARTITION BY client_id) AS copies FROM df_clients) WHERE copies = 1 AND client_id > 0) SELECT t.transaction_id, t.client_id, t.date, t.amount, c.client_name, c.industry FROM t JOIN c ON t.client_id = c.client_id"],
        "snowflake": ["WITH t AS (SELECT transaction_id, client_id, date, amount FROM df_transactions WHERE transaction_id > 0 AND REGEXP_LIKE(date, '[0-9]{4}-[0-9]{2}-[0-9]{2}') AND TRY_TO_DATE(date, 'YYYY-MM-DD') IS NOT NULL QUALIFY COUNT(*) OVER (PARTITION BY transaction_id) = 1), c AS (SELECT client_id, client_name, industry FROM df_clients QUALIFY COUNT(*) OVER (PARTITION BY client_id) = 1) SELECT t.transaction_id, t.client_id, t.date, t.amount, c.client_name, c.industry FROM t JOIN c ON t.client_id = c.client_id WHERE c.client_id > 0"],
    },
)
