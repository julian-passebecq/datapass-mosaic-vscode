"""ZillaCode problems 11-20 as Datapass specs."""
from .common import code, problem, rows

# 11 ------------------------------------------------------------------------------------------------------------------
MOVIES = {"movie_id": "INTEGER", "movie_title": "VARCHAR", "director_name": "VARCHAR", "release_date": "DATE",
          "box_office_collection": "DOUBLE", "genre": "VARCHAR"}
problem(
    n=11, slug="missing-box-office", title="Movies without box office figures", difficulty="easy",
    topics=["filtering", "nulls"], industry="Film",
    tables={"movies_df": MOVIES},
    prompt="""
        A film database has one row per movie released in 2022. Return the movies whose box office collection is
        missing (NULL), with all their columns. A collection of 0 is a known value, not a missing one.
    """,
    output=list(MOVIES), grain="One row per movie without a box office figure.",
    pitfall="`= NULL` is never true: test with IS NULL (isna() in pandas, is_null() in Polars). Zero is not NULL.",
    hints=["Use IS NULL, not = NULL.", "Keep every column in its input order."],
    explanation="""
        NULL means unknown, so a comparison with NULL is unknown too and a WHERE clause drops it. IS NULL is the
        predicate that asks the question.
    """,
    changes=["The hidden check is authored: ZillaCode's second test gave box office figures as text ('1.327B'), which "
             "does not fit the numeric column; its lesson (no missing figure, empty result) is kept."],
    hidden={"movies_df": rows(
        "movie_id movie_title director_name release_date box_office_collection genre",
        (11, "Dune", "Denis Villeneuve", "2021-09-03", 406.6, "Sci-Fi"),
        (12, "Eternals", "Chloe Zhao", "2021-11-05", 391.1, "Action"),
    )},
    edges=[{"id": "zero-is-not-null", "tables": {"movies_df": rows(
        "movie_id movie_title director_name release_date box_office_collection genre",
        (21, "Festival Cut", "A. Director", "2022-01-14", 0.0, "Drama"),
        (22, "Lost Reel", "B. Director", "2022-02-11", None, "Drama"),
        (22, "Lost Reel", "B. Director", "2022-02-11", None, "Drama"),
        (23, "Blockbuster", "C. Director", "2022-07-01", 999.9, "Action"),
    )}}],
    sql=code("""
        SELECT movie_id, movie_title, director_name, release_date, box_office_collection, genre
        FROM movies_df
        WHERE box_office_collection IS NULL
    """),
    snowflake="same", dbt="auto",
    python=code("""
        def etl(movies_df):
            return movies_df[movies_df["box_office_collection"].isna()]
    """),
    polars=code("""
        def etl(movies_df):
            return movies_df.filter(pl.col("box_office_collection").is_null())
    """),
    sparklab=code("""
        from pyspark.sql import functions as F

        movies = spark.table("movies_df")
        movies.filter(F.col("box_office_collection").isNull())
    """),
    mutants={
        "sql": ["SELECT * FROM movies_df WHERE box_office_collection = NULL",
                "SELECT * FROM movies_df WHERE box_office_collection IS NULL OR box_office_collection = 0"],
        "python": [code("""
            def etl(movies_df):
                return movies_df[(movies_df["box_office_collection"].isna()) | (movies_df["box_office_collection"] == 0)]
        """)],
    },
)

# 12 ------------------------------------------------------------------------------------------------------------------
POLICY = {"customer_id": "INTEGER", "first_name": "VARCHAR", "last_name": "VARCHAR", "age": "INTEGER",
          "policy_type": "VARCHAR"}
problem(
    n=12, slug="append-customers", title="Append two customer files", difficulty="easy",
    topics=["union"], industry="Insurance",
    tables={"input_df1": POLICY, "input_df2": POLICY},
    prompt="""
        An insurance agency keeps its customers in two files with the same columns. Return every row of both files.
        A customer present in both files appears twice: this is an append, not a deduplication.
    """,
    output=list(POLICY), grain="One row per input row of either file.",
    pitfall="UNION removes duplicate rows; appending needs UNION ALL (pd.concat, pl.concat).",
    hints=["UNION ALL keeps every row.", "Both files have the same columns in the same order."],
    explanation="UNION ALL appends result sets without comparing rows; UNION also deduplicates, which loses rows here.",
    edges=[{"id": "shared-rows", "tables": {
        "input_df1": rows("customer_id first_name last_name age policy_type", (1, "Alice", "Smith", 30, "auto"),
                          (1, "Alice", "Smith", 30, "auto")),
        "input_df2": rows("customer_id first_name last_name age policy_type", (1, "Alice", "Smith", 30, "auto"),
                          (2, "Bob", "Stone", 41, "home")),
    }}],
    sql=code("""
        SELECT customer_id, first_name, last_name, age, policy_type FROM input_df1
        UNION ALL
        SELECT customer_id, first_name, last_name, age, policy_type FROM input_df2
    """),
    snowflake="same", dbt="auto",
    python=code("""
        def etl(input_df1, input_df2):
            return pd.concat([input_df1, input_df2], ignore_index=True)
    """),
    polars=code("""
        def etl(input_df1, input_df2):
            return pl.concat([input_df1, input_df2])
    """),
    mutants={
        "sql": ["SELECT * FROM input_df1 UNION SELECT * FROM input_df2"],
        "python": [code("""
            def etl(input_df1, input_df2):
                return pd.concat([input_df1, input_df2], ignore_index=True).drop_duplicates()
        """)],
    },
)

# 13 ------------------------------------------------------------------------------------------------------------------
problem(
    n=13, slug="last-climb", title="Last climb of each mountain", difficulty="medium",
    topics=["window-functions", "ranking", "semi-join"], industry="Mountaineering",
    tables={"mountain_info": {"name": "VARCHAR", "height": "INTEGER", "country": "VARCHAR", "range": "VARCHAR"},
            "mountain_climbers": {"climber_name": "VARCHAR", "mountain_name": "VARCHAR", "climb_date": "DATE",
                                  "climb_time": "DOUBLE"}},
    prompt="""
        For each mountain of mountain_info that has been climbed, return the most recent climb: the climber, the date
        and the climbing time. When several climbs share the most recent date, return all of them. Climbs of mountains
        that are not in mountain_info are ignored.
    """,
    output=["mountain_name", "last_climber_name", "last_climb_date", "last_climb_time"],
    grain="One row per climb on its mountain's most recent climb date.",
    pitfall="ROW_NUMBER keeps one arbitrary climb when two share the last date; RANK (or comparing with the per-mountain "
            "MAX date) keeps both.",
    hints=["Rank climbs per mountain by climb_date, newest first.",
           "Keep rank 1; filter the mountains with IN / EXISTS so a listed mountain cannot duplicate rows."],
    explanation="""
        RANK() OVER (PARTITION BY mountain_name ORDER BY climb_date DESC) = 1 keeps every climb on the latest date.
        Snowflake can filter the window directly with QUALIFY. Comparing climb_date with MAX(climb_date) per mountain
        gives the same rows.
    """,
    changes=["Output names follow the statement (last_climber_name, last_climb_date, last_climb_time). Ties on the last "
             "date keep every climb (ZillaCode's Spark reference ranked ties by climb_time; its SQL kept them all)."],
    zilla_output={"last_climber_name": "climber_name", "last_climb_date": "climb_date", "last_climb_time": "climb_time"},
    edges=[{"id": "tie-and-unknown-mountain", "tables": {
        "mountain_info": rows("name height country range", ("Everest", 8848, "Nepal", "Himalayas"),
                              ("Fuji", 3776, "Japan", "Fuji")),
        "mountain_climbers": rows("climber_name mountain_name climb_date climb_time",
                                  ("Ana", "Everest", "2024-05-20", 9.5), ("Ben", "Everest", "2024-05-20", 8.0),
                                  ("Cid", "Everest", "2023-05-01", 7.0), ("Dee", "K2", "2024-07-01", 11.0)),
    }}],
    sql=code("""
        WITH ranked AS (
            SELECT mountain_name, climber_name, climb_date, climb_time,
                   RANK() OVER (PARTITION BY mountain_name ORDER BY climb_date DESC) AS climb_rank
            FROM mountain_climbers
            WHERE mountain_name IN (SELECT name FROM mountain_info)
        )
        SELECT mountain_name,
               climber_name AS last_climber_name,
               climb_date AS last_climb_date,
               climb_time AS last_climb_time
        FROM ranked
        WHERE climb_rank = 1
    """),
    snowflake=code("""
        SELECT mountain_name,
               climber_name AS last_climber_name,
               climb_date AS last_climb_date,
               climb_time AS last_climb_time
        FROM mountain_climbers
        WHERE mountain_name IN (SELECT name FROM mountain_info)
        QUALIFY RANK() OVER (PARTITION BY mountain_name ORDER BY climb_date DESC) = 1
    """),
    dbt="auto",
    python=code("""
        def etl(mountain_info, mountain_climbers):
            climbs = mountain_climbers[mountain_climbers["mountain_name"].isin(mountain_info["name"])]
            last = climbs[climbs["climb_date"] == climbs.groupby("mountain_name")["climb_date"].transform("max")]
            last = last.rename(columns={"climber_name": "last_climber_name", "climb_date": "last_climb_date",
                                        "climb_time": "last_climb_time"})
            return last[["mountain_name", "last_climber_name", "last_climb_date", "last_climb_time"]]
    """),
    polars=code("""
        def etl(mountain_info, mountain_climbers):
            climbs = mountain_climbers.filter(pl.col("mountain_name").is_in(mountain_info["name"].implode()))
            last = climbs.filter(pl.col("climb_date") == pl.col("climb_date").max().over("mountain_name"))
            return last.select(
                "mountain_name",
                pl.col("climber_name").alias("last_climber_name"),
                pl.col("climb_date").alias("last_climb_date"),
                pl.col("climb_time").alias("last_climb_time"),
            )
    """),
    sparklab=code("""
        from pyspark.sql import functions as F

        mountains = spark.table("mountain_info").withColumnRenamed("name", "mountain_name").select("mountain_name")
        climbs = spark.table("mountain_climbers").join(mountains, "mountain_name", "semi")
        last_dates = climbs.groupBy("mountain_name").agg(F.max("climb_date").alias("climb_date"))
        climbs.join(last_dates, ["mountain_name", "climb_date"]).select(
            F.col("mountain_name"),
            F.col("climber_name").alias("last_climber_name"),
            F.col("climb_date").alias("last_climb_date"),
            F.col("climb_time").alias("last_climb_time"),
        )
    """),
    mutants={
        "sql": ["WITH r AS (SELECT mountain_name, climber_name, climb_date, climb_time, ROW_NUMBER() OVER (PARTITION BY mountain_name ORDER BY climb_date DESC) AS n FROM mountain_climbers WHERE mountain_name IN (SELECT name FROM mountain_info)) SELECT mountain_name, climber_name AS last_climber_name, climb_date AS last_climb_date, climb_time AS last_climb_time FROM r WHERE n = 1",
                "WITH r AS (SELECT mountain_name, climber_name, climb_date, climb_time, RANK() OVER (PARTITION BY mountain_name ORDER BY climb_date DESC) AS n FROM mountain_climbers) SELECT mountain_name, climber_name AS last_climber_name, climb_date AS last_climb_date, climb_time AS last_climb_time FROM r WHERE n = 1"],
        "snowflake": ["SELECT mountain_name, climber_name AS last_climber_name, climb_date AS last_climb_date, climb_time AS last_climb_time FROM mountain_climbers WHERE mountain_name IN (SELECT name FROM mountain_info) QUALIFY ROW_NUMBER() OVER (PARTITION BY mountain_name ORDER BY climb_date DESC) = 1"],
    },
)

# 14 ------------------------------------------------------------------------------------------------------------------
PE_OUTPUT = ["investment_id", "fund_id", "firm_id", "firm_name", "founded_year", "location", "fund_name", "fund_size",
             "fund_start_year", "fund_end_year", "company_name", "investment_amount", "investment_date"]
problem(
    n=14, slug="pe-full-outer", title="Firms, funds and investments with full outer joins", difficulty="hard",
    topics=["full-outer-join", "nulls"], industry="Private equity",
    tables={"pe_firms": {"firm_id": "INTEGER", "firm_name": "VARCHAR", "founded_year": "INTEGER", "location": "VARCHAR"},
            "pe_funds": {"fund_id": "INTEGER", "firm_id": "INTEGER", "fund_name": "VARCHAR", "fund_size": "INTEGER",
                         "fund_start_year": "INTEGER", "fund_end_year": "INTEGER"},
            "pe_investments": {"investment_id": "INTEGER", "fund_id": "INTEGER", "company_name": "VARCHAR",
                               "investment_amount": "INTEGER", "investment_date": "VARCHAR"}},
    prompt="""
        Combine private equity firms, their funds and the funds' investments, keeping every record of every table
        (full outer joins): a firm without funds, a fund without a known firm, and an investment without a known fund
        all appear, with NULLs for the missing side. firm_id and fund_id come from whichever side has them. Missing
        keys (NULL fund_id or firm_id) never match anything. A row whose columns are all NULL (an empty input record)
        is dropped.
    """,
    output=PE_OUTPUT,
    grain="One row per investment of a fund, plus one row per fund without investments, per firm without funds and "
          "per investment without a known fund.",
    pitfall="A LEFT JOIN from firms loses funds and investments that no firm owns. In pandas, merge matches missing "
            "keys with each other (NaN == NaN), unlike SQL, Polars and Spark: keep rows without a key out of the merge.",
    hints=["FULL OUTER JOIN firms to funds on firm_id, then to investments on fund_id.",
           "COALESCE the keys from both sides of each join."],
    explanation="""
        Two FULL OUTER JOINs keep unmatched rows from every side. The output key columns are the COALESCE of both
        sides. SQL never matches NULL keys, but pandas' merge does, so the pandas reference merges only rows that have
        a fund_id and appends the others.
    """,
    changes=["The statement's full outer join is implemented for all three tables (ZillaCode's SQL used left joins "
             "from firms, which the fixtures could not tell apart); an edge check covers funds and investments that no "
             "firm or fund owns. Integer columns are integers (ZillaCode's second test had 1001.0-style floats)."],
    edges=[{"id": "orphans-and-null-keys", "tables": {
        "pe_firms": rows("firm_id firm_name founded_year location", (1, "Alpha Fund", 2010, "New York"),
                         (2, "Beta Fund", 2012, "Boston")),
        "pe_funds": rows("fund_id firm_id fund_name fund_size fund_start_year fund_end_year",
                         (10, 1, "Alpha I", 100, 2011, 2016), (11, 77, "Ghost I", 50, 2013, 2018),
                         (12, None, "Nomad I", 30, 2014, None)),
        "pe_investments": rows("investment_id fund_id company_name investment_amount investment_date",
                               (100, 10, "Company A", 5, "2012-03-01"), (101, 999, "Company B", 7, "2013-04-01"),
                               (102, None, "Company C", 9, "2014-05-01"), (103, 12, "Company D", 3, "2015-06-01")),
    }}],
    sql=code("""
        WITH joined AS (
            SELECT i.investment_id,
                   COALESCE(fu.fund_id, i.fund_id) AS fund_id,
                   COALESCE(f.firm_id, fu.firm_id) AS firm_id,
                   f.firm_name, f.founded_year, f.location,
                   fu.fund_name, fu.fund_size, fu.fund_start_year, fu.fund_end_year,
                   i.company_name, i.investment_amount, i.investment_date
            FROM pe_firms AS f
            FULL OUTER JOIN pe_funds AS fu ON f.firm_id = fu.firm_id
            FULL OUTER JOIN pe_investments AS i ON fu.fund_id = i.fund_id
        )
        SELECT *
        FROM joined
        -- A row whose columns are all NULL (an empty input record) is dropped.
        WHERE investment_id IS NOT NULL
           OR fund_id IS NOT NULL
           OR firm_id IS NOT NULL
           OR firm_name IS NOT NULL
           OR founded_year IS NOT NULL
           OR location IS NOT NULL
           OR fund_name IS NOT NULL
           OR fund_size IS NOT NULL
           OR fund_start_year IS NOT NULL
           OR fund_end_year IS NOT NULL
           OR company_name IS NOT NULL
           OR investment_amount IS NOT NULL
           OR investment_date IS NOT NULL
    """),
    snowflake="same", dbt="auto",
    python=code("""
        COLUMNS = ["investment_id", "fund_id", "firm_id", "firm_name", "founded_year", "location", "fund_name",
                   "fund_size", "fund_start_year", "fund_end_year", "company_name", "investment_amount", "investment_date"]


        def etl(pe_firms, pe_funds, pe_investments):
            firms_funds = pe_firms.merge(pe_funds, on="firm_id", how="outer")
            # pandas matches NaN keys with each other; SQL never does. Merge only the rows that have a fund_id.
            keyed = firms_funds[firms_funds["fund_id"].notna()]
            investments = pe_investments[pe_investments["fund_id"].notna()]
            combined = pd.concat([
                keyed.merge(investments, on="fund_id", how="outer"),
                firms_funds[firms_funds["fund_id"].isna()],
                pe_investments[pe_investments["fund_id"].isna()],
            ], ignore_index=True)
            return combined[COLUMNS].dropna(how="all")
    """),
    polars=code("""
        def etl(pe_firms, pe_funds, pe_investments):
            joined = (pe_firms.join(pe_funds, on="firm_id", how="full", coalesce=True)
                      .join(pe_investments, on="fund_id", how="full", coalesce=True))
            result = joined.select("investment_id", "fund_id", "firm_id", "firm_name", "founded_year", "location",
                                   "fund_name", "fund_size", "fund_start_year", "fund_end_year", "company_name",
                                   "investment_amount", "investment_date")
            return result.filter(~pl.all_horizontal(pl.all().is_null()))
    """),
    sparklab=code("""
        from pyspark.sql import functions as F

        firms = spark.table("pe_firms")
        funds = spark.table("pe_funds")
        investments = spark.table("pe_investments")
        joined = firms.join(funds, "firm_id", "full").join(investments, "fund_id", "full").select(
            "investment_id", "fund_id", "firm_id", "firm_name", "founded_year", "location", "fund_name", "fund_size",
            "fund_start_year", "fund_end_year", "company_name", "investment_amount", "investment_date"
        )
        # Drop rows whose columns are all NULL (an empty input record).
        joined.filter(
            F.col("investment_id").isNotNull()
            | F.col("fund_id").isNotNull()
            | F.col("firm_id").isNotNull()
            | F.col("firm_name").isNotNull()
            | F.col("founded_year").isNotNull()
            | F.col("location").isNotNull()
            | F.col("fund_name").isNotNull()
            | F.col("fund_size").isNotNull()
            | F.col("fund_start_year").isNotNull()
            | F.col("fund_end_year").isNotNull()
            | F.col("company_name").isNotNull()
            | F.col("investment_amount").isNotNull()
            | F.col("investment_date").isNotNull()
        )
    """),
    mutants={
        "sql": ["SELECT i.investment_id, fu.fund_id, f.firm_id, f.firm_name, f.founded_year, f.location, fu.fund_name, fu.fund_size, fu.fund_start_year, fu.fund_end_year, i.company_name, i.investment_amount, i.investment_date FROM pe_firms AS f LEFT JOIN pe_funds AS fu ON f.firm_id = fu.firm_id LEFT JOIN pe_investments AS i ON fu.fund_id = i.fund_id",
                "SELECT i.investment_id, fu.fund_id, f.firm_id, f.firm_name, f.founded_year, f.location, fu.fund_name, fu.fund_size, fu.fund_start_year, fu.fund_end_year, i.company_name, i.investment_amount, i.investment_date FROM pe_firms AS f FULL OUTER JOIN pe_funds AS fu ON f.firm_id = fu.firm_id FULL OUTER JOIN pe_investments AS i ON fu.fund_id = i.fund_id",
                "SELECT i.investment_id, COALESCE(fu.fund_id, i.fund_id) AS fund_id, COALESCE(f.firm_id, fu.firm_id) AS firm_id, f.firm_name, f.founded_year, f.location, fu.fund_name, fu.fund_size, fu.fund_start_year, fu.fund_end_year, i.company_name, i.investment_amount, i.investment_date FROM pe_firms AS f FULL OUTER JOIN pe_funds AS fu ON f.firm_id = fu.firm_id FULL OUTER JOIN pe_investments AS i ON fu.fund_id = i.fund_id"],
        "python": [code("""
            def etl(pe_firms, pe_funds, pe_investments):
                joined = pe_firms.merge(pe_funds, on="firm_id", how="outer").merge(pe_investments, on="fund_id", how="outer")
                return joined[["investment_id", "fund_id", "firm_id", "firm_name", "founded_year", "location", "fund_name",
                               "fund_size", "fund_start_year", "fund_end_year", "company_name", "investment_amount",
                               "investment_date"]]
        """)],
    },
)

# 15 ------------------------------------------------------------------------------------------------------------------
problem(
    n=15, slug="best-pages", title="Best page per domain and overall", difficulty="medium",
    topics=["window-functions", "nulls", "ordering"], industry="SEO",
    tables={"pages": {"domain": "VARCHAR", "url": "VARCHAR", "seo_score": "INTEGER"}},
    prompt="""
        For each domain, return its best page: the highest SEO score, ties broken by the URL in ascending order.
        Also return the best page over all domains (same rule) in overall_highest_page and overall_highest_score, but
        only on the row of the domain that owns it; the other rows have NULL there. A page without a score (NULL) is
        never better than a scored page.
    """,
    output=["domain", "highest_seo_page", "highest_seo_score", "overall_highest_page", "overall_highest_score"],
    grain="One row per domain.",
    pitfall="Snowflake sorts NULLs first in a descending order (they are the largest value) and Polars sorts nulls "
            "first unless nulls_last=True: without NULLS LAST, an unscored page wins. DuckDB, pandas and Spark put "
            "NULLs last by default.",
    hints=["ROW_NUMBER() OVER (PARTITION BY domain ORDER BY seo_score DESC NULLS LAST, url).",
           "The overall best page is also the best page of its own domain."],
    explanation="""
        Rank pages twice with ROW_NUMBER: within the domain and over the whole table, both by score descending with
        NULLs last and the URL as the tie-breaker. Keep each domain's first page and attach the overall first page on
        its own domain. Spelling out NULLS LAST makes the query mean the same thing in every engine.
    """,
    changes=["Ties are broken by URL and NULL scores rank last, so the result is deterministic (ZillaCode left ties "
             "to ROW_NUMBER's arbitrary choice)."],
    edges=[{"id": "ties-and-null-scores", "tables": {"pages": rows(
        "domain url seo_score",
        ("a.com", "https://a.com/x", 95), ("a.com", "https://a.com/z", 60), ("b.com", "https://b.com/b", 90),
        ("b.com", "https://b.com/a", 90), ("b.com", "https://b.com/n", None), ("c.com", "https://c.com/y", 95),
        ("d.com", "https://d.com/q", None), ("d.com", "https://d.com/r", 10),
    )}}],
    sql=code("""
        WITH ranked AS (
            SELECT domain, url, seo_score,
                   ROW_NUMBER() OVER (PARTITION BY domain ORDER BY seo_score DESC NULLS LAST, url) AS domain_rank,
                   ROW_NUMBER() OVER (ORDER BY seo_score DESC NULLS LAST, url) AS overall_rank
            FROM pages
        )
        SELECT b.domain,
               b.url AS highest_seo_page,
               b.seo_score AS highest_seo_score,
               o.url AS overall_highest_page,
               o.seo_score AS overall_highest_score
        FROM ranked AS b
        LEFT JOIN ranked AS o ON o.domain = b.domain AND o.overall_rank = 1
        WHERE b.domain_rank = 1
    """),
    snowflake="same", dbt="auto",
    python=code("""
        def etl(pages):
            ordered = pages.sort_values(["seo_score", "url"], ascending=[False, True], na_position="last")
            best = ordered.drop_duplicates("domain").rename(
                columns={"url": "highest_seo_page", "seo_score": "highest_seo_score"})
            is_top = best["highest_seo_page"] == ordered["url"].iloc[0]
            best["overall_highest_page"] = best["highest_seo_page"].where(is_top)
            best["overall_highest_score"] = best["highest_seo_score"].where(is_top)
            return best[["domain", "highest_seo_page", "highest_seo_score", "overall_highest_page", "overall_highest_score"]]
    """),
    polars=code("""
        def etl(pages):
            ordered = pages.sort(["seo_score", "url"], descending=[True, False], nulls_last=True)
            best = ordered.unique("domain", keep="first", maintain_order=True)
            top = pl.col("url") == ordered["url"][0]
            return best.select(
                "domain",
                pl.col("url").alias("highest_seo_page"),
                pl.col("seo_score").alias("highest_seo_score"),
                pl.when(top).then(pl.col("url")).alias("overall_highest_page"),
                pl.when(top).then(pl.col("seo_score")).alias("overall_highest_score"),
            )
    """),
    sparklab=code("""
        from pyspark.sql import functions as F
        from pyspark.sql import Window

        pages = spark.table("pages")
        by_domain = Window.partitionBy("domain").orderBy(F.col("seo_score").desc(), F.col("url"))
        overall = Window.orderBy(F.col("seo_score").desc(), F.col("url"))
        ranked = pages.withColumn("domain_rank", F.row_number().over(by_domain)).withColumn(
            "overall_rank", F.row_number().over(overall))
        best = ranked.filter(F.col("domain_rank") == 1).select(
            "domain", F.col("url").alias("highest_seo_page"), F.col("seo_score").alias("highest_seo_score"))
        top = ranked.filter(F.col("overall_rank") == 1).select(
            "domain", F.col("url").alias("overall_highest_page"), F.col("seo_score").alias("overall_highest_score"))
        best.join(top, "domain", "left")
    """),
    mutants={
        "sql": ["WITH r AS (SELECT domain, url, seo_score, ROW_NUMBER() OVER (PARTITION BY domain ORDER BY seo_score DESC NULLS FIRST, url) AS d, ROW_NUMBER() OVER (ORDER BY seo_score DESC NULLS FIRST, url) AS o FROM pages) SELECT b.domain, b.url AS highest_seo_page, b.seo_score AS highest_seo_score, t.url AS overall_highest_page, t.seo_score AS overall_highest_score FROM r AS b LEFT JOIN r AS t ON t.domain = b.domain AND t.o = 1 WHERE b.d = 1",
                "WITH r AS (SELECT domain, url, seo_score, ROW_NUMBER() OVER (PARTITION BY domain ORDER BY seo_score DESC NULLS LAST, url DESC) AS d, ROW_NUMBER() OVER (ORDER BY seo_score DESC NULLS LAST, url DESC) AS o FROM pages) SELECT b.domain, b.url AS highest_seo_page, b.seo_score AS highest_seo_score, t.url AS overall_highest_page, t.seo_score AS overall_highest_score FROM r AS b LEFT JOIN r AS t ON t.domain = b.domain AND t.o = 1 WHERE b.d = 1"],
        "snowflake": ["WITH r AS (SELECT domain, url, seo_score, ROW_NUMBER() OVER (PARTITION BY domain ORDER BY seo_score DESC, url) AS d, ROW_NUMBER() OVER (ORDER BY seo_score DESC, url) AS o FROM pages) SELECT b.domain, b.url AS highest_seo_page, b.seo_score AS highest_seo_score, t.url AS overall_highest_page, t.seo_score AS overall_highest_score FROM r AS b LEFT JOIN r AS t ON t.domain = b.domain AND t.o = 1 WHERE b.d = 1"],
        "polars": [code("""
            def etl(pages):
                ordered = pages.sort(["seo_score", "url"], descending=[True, False])
                best = ordered.unique("domain", keep="first", maintain_order=True)
                top = pl.col("url") == ordered["url"][0]
                return best.select("domain", pl.col("url").alias("highest_seo_page"), pl.col("seo_score").alias("highest_seo_score"),
                                   pl.when(top).then(pl.col("url")).alias("overall_highest_page"),
                                   pl.when(top).then(pl.col("seo_score")).alias("overall_highest_score"))
        """)],
    },
)

# 16 ------------------------------------------------------------------------------------------------------------------
problem(
    n=16, slug="overtime-pay", title="Pay with overtime", difficulty="easy",
    topics=["conditional-logic", "joins"], industry="Payroll",
    tables={"employees": {"employee_id": "INTEGER", "name": "VARCHAR", "age": "INTEGER", "position": "VARCHAR"},
            "payroll": {"employee_id": "INTEGER", "hours_worked": "DOUBLE", "hourly_rate": "DOUBLE"}},
    prompt="""
        Compute each employee's pay from their payroll row: up to 40 hours are paid at the hourly rate, and every hour
        above 40 is paid 1.5 times the rate. Employees without a payroll row, and payroll rows of unknown employees,
        are left out.
    """,
    output=["employee_id", "name", "position", "pay"],
    grain="One row per employee with a payroll row.",
    pitfall="Only the hours above 40 earn 1.5 times the rate; the first 40 hours stay at the normal rate. Exactly 40 "
            "hours is not overtime.",
    hints=["CASE WHEN hours_worked <= 40 THEN ... ELSE ... END (IFF in Snowflake).",
           "Equivalently: LEAST(hours, 40) * rate + GREATEST(hours - 40, 0) * rate * 1.5."],
    explanation="""
        Inner join employees to payroll and compute pay with a conditional expression: the base hours at the rate
        plus the overtime hours at 1.5 times the rate.
    """,
    edges=[{"id": "boundaries", "tables": {
        "employees": rows("employee_id name age position", (1, "Ann", 30, "Analyst"), (2, "Ben", 41, "Engineer"),
                          (3, "Cy", 25, "Intern"), (4, "Di", 50, "Manager")),
        "payroll": rows("employee_id hours_worked hourly_rate", (1, 40.0, 20.0), (2, 40.5, 20.0), (3, 0.0, 50.0),
                        (9, 10.0, 10.0)),
    }}],
    sql=code("""
        SELECT e.employee_id, e.name, e.position,
               CASE WHEN p.hours_worked <= 40 THEN p.hours_worked * p.hourly_rate
                    ELSE 40 * p.hourly_rate + (p.hours_worked - 40) * p.hourly_rate * 1.5
               END AS pay
        FROM employees AS e
        JOIN payroll AS p ON e.employee_id = p.employee_id
    """),
    snowflake=code("""
        SELECT e.employee_id, e.name, e.position,
               IFF(p.hours_worked <= 40,
                   p.hours_worked * p.hourly_rate,
                   40 * p.hourly_rate + (p.hours_worked - 40) * p.hourly_rate * 1.5) AS pay
        FROM employees AS e
        JOIN payroll AS p ON e.employee_id = p.employee_id
    """),
    dbt="auto",
    python=code("""
        def etl(employees, payroll):
            joined = employees.merge(payroll, on="employee_id")
            hours, rate = joined["hours_worked"], joined["hourly_rate"]
            joined["pay"] = hours.clip(upper=40) * rate + (hours - 40).clip(lower=0) * rate * 1.5
            return joined[["employee_id", "name", "position", "pay"]]
    """),
    polars=code("""
        def etl(employees, payroll):
            hours, rate = pl.col("hours_worked"), pl.col("hourly_rate")
            return employees.join(payroll, on="employee_id").select(
                "employee_id", "name", "position",
                pl.when(hours <= 40).then(hours * rate).otherwise(40 * rate + (hours - 40) * rate * 1.5).alias("pay"),
            )
    """),
    sparklab=code("""
        from pyspark.sql import functions as F

        employees = spark.table("employees")
        payroll = spark.table("payroll")
        hours = F.col("hours_worked")
        rate = F.col("hourly_rate")
        employees.join(payroll, "employee_id").select(
            "employee_id", "name", "position",
            F.when(hours <= 40, hours * rate).otherwise(rate * 40 + (hours - 40) * rate * 1.5).alias("pay"),
        )
    """),
    mutants={
        "sql": ["SELECT e.employee_id, e.name, e.position, CASE WHEN p.hours_worked <= 40 THEN p.hours_worked * p.hourly_rate ELSE p.hours_worked * p.hourly_rate * 1.5 END AS pay FROM employees AS e JOIN payroll AS p ON e.employee_id = p.employee_id",
                "SELECT e.employee_id, e.name, e.position, CASE WHEN p.hours_worked <= 40 THEN p.hours_worked * p.hourly_rate ELSE 40 * p.hourly_rate + (p.hours_worked - 40) * p.hourly_rate * 1.5 END AS pay FROM employees AS e LEFT JOIN payroll AS p ON e.employee_id = p.employee_id"],
    },
)

# 17 ------------------------------------------------------------------------------------------------------------------
problem(
    n=17, slug="extract-digits", title="Extract the age from a description", difficulty="easy",
    topics=["regular-expressions", "strings", "nulls"], industry="Geology",
    tables={"input_df": {"sample_id": "VARCHAR", "description": "VARCHAR"}},
    prompt="""
        Rock sample descriptions mix letters and digits, for example 'Basalt_450Ma'. Add a column age with the first
        run of digits in the description, as text. When the description has no digit, age is the empty string ''.
    """,
    output=["sample_id", "description", "age"],
    grain="One row per sample.",
    pitfall="Snowflake's REGEXP_SUBSTR returns NULL when nothing matches (DuckDB's regexp_extract returns ''), and "
            "pandas' str.extract returns NaN: wrap the extraction in COALESCE / fillna to get ''.",
    hints=["Extract the pattern [0-9]+ (the first match).", "Replace a missing match with ''."],
    explanation="""
        A regular expression extraction of the first match of [0-9]+. Engines disagree on the no-match value (empty
        string in DuckDB, NULL in Snowflake, NaN/null in pandas and Polars), so the contract fixes it to ''.
    """,
    changes=["Output columns follow the statement's order (sample_id, description, age)."],
    edges=[{"id": "several-numbers", "tables": {"input_df": rows(
        "sample_id description", ("S20", "Gneiss_12_300Ma"), ("S21", "Chalk"), ("S22", "300"),
    )}}],
    sql=code("""
        SELECT sample_id, description, regexp_extract(description, '[0-9]+') AS age
        FROM input_df
    """),
    snowflake=code("""
        SELECT sample_id, description, COALESCE(REGEXP_SUBSTR(description, '[0-9]+'), '') AS age
        FROM input_df
    """),
    dbt="auto",
    python=code("""
        def etl(input_df):
            return input_df.assign(age=input_df["description"].str.extract(r"(\\d+)", expand=False).fillna(""))
    """),
    polars=code("""
        def etl(input_df):
            return input_df.with_columns(pl.col("description").str.extract(r"(\\d+)", 1).fill_null("").alias("age"))
    """),
    mutants={
        "sql": ["SELECT sample_id, description, regexp_extract(description, '[0-9]') AS age FROM input_df"],
        "snowflake": ["SELECT sample_id, description, REGEXP_SUBSTR(description, '[0-9]+') AS age FROM input_df"],
        "python": [code("""
            def etl(input_df):
                return input_df.assign(age=input_df["description"].str.extract(r"(\\d+)", expand=False))
        """)],
    },
)

# 18 ------------------------------------------------------------------------------------------------------------------
problem(
    n=18, slug="dedupe-then-join", title="Remove duplicates, then combine", difficulty="easy",
    topics=["deduplication", "joins"], industry="Manufacturing",
    tables={"products_df": {"product_id": "INTEGER", "product_name": "VARCHAR", "category": "VARCHAR"},
            "manufacturing_processes_df": {"process_id": "INTEGER", "product_id": "INTEGER", "process_name": "VARCHAR",
                                           "duration": "DOUBLE"}},
    rename={"ProductID": "product_id", "ProductName": "product_name", "Category": "category", "ProcessID": "process_id",
            "ProcessName": "process_name", "Duration": "duration"},
    prompt="""
        Both feeds of a manufacturer contain duplicate rows (the same record loaded twice). Remove them, then return
        each product with each of its manufacturing processes. Products without a process are left out.
    """,
    output=["product_id", "product_name", "category", "process_id", "process_name", "duration"],
    grain="One row per distinct (product, process) pair.",
    pitfall="Joining before deduplicating multiplies the duplicates: two copies of a product and two copies of a "
            "process give four rows.",
    hints=["SELECT DISTINCT (drop_duplicates, unique, distinct) on each input first.", "Then an inner join on product_id."],
    explanation="""
        Deduplicate each input, then join. The duplicates are exact copies, so DISTINCT keeps one of each; deduplicating
        on a key alone would silently keep an arbitrary copy if the copies ever differed.
    """,
    changes=["Columns are snake_case (ZillaCode used ProductID, ProductName, ...). Duplicates are exact copies, so the "
             "result no longer depends on which copy a key-based deduplication keeps."],
    edges=[{"id": "double-duplicates", "tables": {
        "products_df": rows("product_id product_name category", (1, "Widget", "Type1"), (1, "Widget", "Type1"),
                            (2, "Gadget", "Type2")),
        "manufacturing_processes_df": rows("process_id product_id process_name duration", (10, 1, "Cutting", 1.5),
                                           (10, 1, "Cutting", 1.5), (11, 1, "Welding", 2.0)),
    }}],
    sql=code("""
        WITH products AS (SELECT DISTINCT * FROM products_df),
             processes AS (SELECT DISTINCT * FROM manufacturing_processes_df)
        SELECT p.product_id, p.product_name, p.category, m.process_id, m.process_name, m.duration
        FROM products AS p
        JOIN processes AS m ON p.product_id = m.product_id
    """),
    snowflake="same", dbt="auto",
    python=code("""
        def etl(products_df, manufacturing_processes_df):
            joined = products_df.drop_duplicates().merge(manufacturing_processes_df.drop_duplicates(), on="product_id")
            return joined[["product_id", "product_name", "category", "process_id", "process_name", "duration"]]
    """),
    polars=code("""
        def etl(products_df, manufacturing_processes_df):
            joined = products_df.unique().join(manufacturing_processes_df.unique(), on="product_id")
            return joined.select("product_id", "product_name", "category", "process_id", "process_name", "duration")
    """),
    sparklab=code("""
        products = spark.table("products_df").distinct()
        processes = spark.table("manufacturing_processes_df").distinct()
        products.join(processes, "product_id").select(
            "product_id", "product_name", "category", "process_id", "process_name", "duration")
    """),
    mutants={
        "sql": ["SELECT p.product_id, p.product_name, p.category, m.process_id, m.process_name, m.duration FROM products_df AS p JOIN manufacturing_processes_df AS m ON p.product_id = m.product_id"],
        "sparklab": ["products = spark.table(\"products_df\")\nprocesses = spark.table(\"manufacturing_processes_df\").distinct()\nproducts.join(processes, \"product_id\").select(\"product_id\", \"product_name\", \"category\", \"process_id\", \"process_name\", \"duration\")\n"],
    },
)

# 19 ------------------------------------------------------------------------------------------------------------------
problem(
    n=19, slug="industry-ranking", title="Investment per industry, largest first", difficulty="easy",
    topics=["aggregation", "ordering"], industry="Venture capital",
    tables={"companies": {"company_id": "INTEGER", "company_name": "VARCHAR", "industry": "VARCHAR"},
            "investments": {"investment_id": "INTEGER", "company_id": "INTEGER", "amount": "DOUBLE"}},
    prompt="""
        Return the total amount invested in each industry, sorted by the total in descending order; industries with
        the same total are sorted by name in ascending order. Industries without investments are left out.
    """,
    output=["industry", "total_investment"], ordered=True,
    order_text="Row order is graded: total_investment descending, then industry ascending.",
    grain="One row per industry with at least one investment.",
    pitfall="Row order is part of this contract, so ties need an explicit tie-breaker; without it, two industries "
            "with the same total can come out in either order.",
    hints=["GROUP BY industry, then ORDER BY total_investment DESC, industry.",
           "Join investments to companies to find their industry."],
    explanation="""
        Join, aggregate, and sort with a complete ordering key. A result set has no order unless ORDER BY gives one,
        and a sort key with ties leaves the tied rows in an unspecified order.
    """,
    changes=["The order became a graded contract with an explicit tie-breaker (industry)."],
    edges=[{"id": "tied-totals", "tables": {
        "companies": rows("company_id company_name industry", (1, "Root", "Retail"), (2, "Seed", "Agri"),
                          (3, "Byte", "Tech"), (4, "Idle", "Mining")),
        "investments": rows("investment_id company_id amount", (1, 1, 5.0), (2, 2, 2.0), (3, 2, 3.0), (4, 3, 7.5)),
    }}],
    sql=code("""
        SELECT c.industry, SUM(i.amount) AS total_investment
        FROM companies AS c
        JOIN investments AS i ON c.company_id = i.company_id
        GROUP BY c.industry
        ORDER BY total_investment DESC, c.industry
    """),
    snowflake="same",
    python=code("""
        def etl(companies, investments):
            totals = (companies.merge(investments, on="company_id")
                      .groupby("industry", as_index=False)["amount"].sum()
                      .rename(columns={"amount": "total_investment"}))
            return totals.sort_values(["total_investment", "industry"], ascending=[False, True])
    """),
    polars=code("""
        def etl(companies, investments):
            totals = companies.join(investments, on="company_id").group_by("industry").agg(
                pl.col("amount").sum().alias("total_investment"))
            return totals.sort(["total_investment", "industry"], descending=[True, False])
    """),
    sparklab=code("""
        from pyspark.sql import functions as F

        companies = spark.table("companies")
        investments = spark.table("investments")
        companies.join(investments, "company_id").groupBy("industry").agg(
            F.sum("amount").alias("total_investment")
        ).orderBy(F.col("total_investment").desc(), F.col("industry"))
    """),
    mutants={
        "sql": ["SELECT c.industry, SUM(i.amount) AS total_investment FROM companies AS c JOIN investments AS i ON c.company_id = i.company_id GROUP BY c.industry ORDER BY total_investment",
                "SELECT c.industry, SUM(i.amount) AS total_investment FROM companies AS c JOIN investments AS i ON c.company_id = i.company_id GROUP BY c.industry ORDER BY total_investment DESC, c.industry DESC"],
    },
)

# 20 ------------------------------------------------------------------------------------------------------------------
problem(
    n=20, slug="project-summary", title="Project duration, staff and equipment", difficulty="medium",
    topics=["aggregation", "dates", "left-join"], industry="Construction",
    tables={"projects": {"project_id": "INTEGER", "project_name": "VARCHAR", "start_date": "DATE", "end_date": "DATE",
                         "budget": "INTEGER"},
            "employees": {"employee_id": "INTEGER", "first_name": "VARCHAR", "last_name": "VARCHAR", "role": "VARCHAR",
                          "project_id": "INTEGER"},
            "equipment": {"equipment_id": "INTEGER", "equipment_name": "VARCHAR", "project_id": "INTEGER",
                          "cost": "INTEGER"}},
    prompt="""
        For every project, return its duration in days (end_date minus start_date), its number of employees, its
        number of distinct roles and the total cost of its equipment. A project without employees or equipment gets 0
        in those columns. A missing role is not a role.
    """,
    output=["project_id", "project_name", "start_date", "end_date", "duration_days", "total_employees", "unique_roles",
            "total_equipment_cost"],
    grain="One row per project.",
    pitfall="Aggregate employees and equipment separately: joining both to the project first multiplies the "
            "employees by the equipment rows. COUNT(DISTINCT role) ignores NULL, but Polars' n_unique() counts null as "
            "a value.",
    hints=["Two pre-aggregations, then LEFT JOINs to projects.", "DATEDIFF(day, start_date, end_date) in Snowflake; "
                                                                 "date_diff('day', ...) or end_date - start_date in DuckDB."],
    explanation="""
        Employees and equipment are independent one-to-many tables: aggregate each per project, LEFT JOIN them to the
        projects, turn missing counts into 0, and compute the duration from the two dates.
    """,
    changes=["A project without employees or equipment gets 0 instead of NULL (ZillaCode's reference returned NULL "
             "from its left joins)."],
    edges=[{"id": "fan-out-and-null-role", "tables": {
        "projects": rows("project_id project_name start_date end_date budget", (1, "Depot", "2024-01-01", "2024-03-01", 100),
                         (2, "Kiosk", "2024-02-10", "2024-02-11", 10)),
        "employees": rows("employee_id first_name last_name role project_id", (1, "Ann", "Lee", "Engineer", 1),
                          (2, "Bo", "Ray", "Engineer", 1), (3, "Cy", "Fox", None, 1), (4, "Di", "Moe", "Architect", 9)),
        "equipment": rows("equipment_id equipment_name project_id cost", (1, "Crane", 1, 100), (2, "Drill", 1, 20),
                          (3, "Truck", 1, 5)),
    }}],
    sql=code("""
        WITH staff AS (
            SELECT project_id, COUNT(employee_id) AS total_employees, COUNT(DISTINCT role) AS unique_roles
            FROM employees
            GROUP BY project_id
        ),
        gear AS (
            SELECT project_id, SUM(cost) AS total_equipment_cost
            FROM equipment
            GROUP BY project_id
        )
        SELECT p.project_id, p.project_name, p.start_date, p.end_date,
               date_diff('day', p.start_date, p.end_date) AS duration_days,
               COALESCE(s.total_employees, 0) AS total_employees,
               COALESCE(s.unique_roles, 0) AS unique_roles,
               COALESCE(g.total_equipment_cost, 0) AS total_equipment_cost
        FROM projects AS p
        LEFT JOIN staff AS s ON p.project_id = s.project_id
        LEFT JOIN gear AS g ON p.project_id = g.project_id
    """),
    snowflake=code("""
        WITH staff AS (
            SELECT project_id, COUNT(employee_id) AS total_employees, COUNT(DISTINCT role) AS unique_roles
            FROM employees
            GROUP BY project_id
        ),
        gear AS (
            SELECT project_id, SUM(cost) AS total_equipment_cost
            FROM equipment
            GROUP BY project_id
        )
        SELECT p.project_id, p.project_name, p.start_date, p.end_date,
               DATEDIFF(day, p.start_date, p.end_date) AS duration_days,
               ZEROIFNULL(s.total_employees) AS total_employees,
               ZEROIFNULL(s.unique_roles) AS unique_roles,
               ZEROIFNULL(g.total_equipment_cost) AS total_equipment_cost
        FROM projects AS p
        LEFT JOIN staff AS s ON p.project_id = s.project_id
        LEFT JOIN gear AS g ON p.project_id = g.project_id
    """),
    dbt="auto",
    python=code("""
        def etl(projects, employees, equipment):
            staff = employees.groupby("project_id", as_index=False).agg(
                total_employees=("employee_id", "count"), unique_roles=("role", "nunique"))
            gear = equipment.groupby("project_id", as_index=False).agg(total_equipment_cost=("cost", "sum"))
            result = projects.merge(staff, on="project_id", how="left").merge(gear, on="project_id", how="left")
            result["duration_days"] = (pd.to_datetime(result["end_date"]) - pd.to_datetime(result["start_date"])).dt.days
            result = result.fillna({"total_employees": 0, "unique_roles": 0, "total_equipment_cost": 0})
            return result[["project_id", "project_name", "start_date", "end_date", "duration_days", "total_employees",
                           "unique_roles", "total_equipment_cost"]]
    """),
    polars=code("""
        def etl(projects, employees, equipment):
            staff = employees.group_by("project_id").agg(
                pl.col("employee_id").count().alias("total_employees"),
                pl.col("role").drop_nulls().n_unique().alias("unique_roles"))
            gear = equipment.group_by("project_id").agg(pl.col("cost").sum().alias("total_equipment_cost"))
            result = projects.join(staff, on="project_id", how="left").join(gear, on="project_id", how="left")
            return result.select(
                "project_id", "project_name", "start_date", "end_date",
                (pl.col("end_date").str.to_date() - pl.col("start_date").str.to_date()).dt.total_days().alias("duration_days"),
                pl.col("total_employees").fill_null(0),
                pl.col("unique_roles").fill_null(0),
                pl.col("total_equipment_cost").fill_null(0),
            )
    """),
    mutants={
        "sql": ["SELECT p.project_id, p.project_name, p.start_date, p.end_date, date_diff('day', p.start_date, p.end_date) AS duration_days, COUNT(e.employee_id) AS total_employees, COUNT(DISTINCT e.role) AS unique_roles, COALESCE(SUM(q.cost), 0) AS total_equipment_cost FROM projects AS p LEFT JOIN employees AS e ON p.project_id = e.project_id LEFT JOIN equipment AS q ON p.project_id = q.project_id GROUP BY p.project_id, p.project_name, p.start_date, p.end_date"],
        "polars": [code("""
            def etl(projects, employees, equipment):
                staff = employees.group_by("project_id").agg(pl.col("employee_id").count().alias("total_employees"), pl.col("role").n_unique().alias("unique_roles"))
                gear = equipment.group_by("project_id").agg(pl.col("cost").sum().alias("total_equipment_cost"))
                result = projects.join(staff, on="project_id", how="left").join(gear, on="project_id", how="left")
                return result.select("project_id", "project_name", "start_date", "end_date",
                    (pl.col("end_date").str.to_date() - pl.col("start_date").str.to_date()).dt.total_days().alias("duration_days"),
                    pl.col("total_employees").fill_null(0), pl.col("unique_roles").fill_null(0), pl.col("total_equipment_cost").fill_null(0))
        """)],
    },
)
