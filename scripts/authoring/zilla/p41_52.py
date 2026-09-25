"""ZillaCode problems 41-52 as Datapass specs."""
from .common import code, problem, rows

# 41 ------------------------------------------------------------------------------------------------------------------
problem(
    n=41, slug="height-per-floor", title="Average height per floor", difficulty="easy",
    topics=["arithmetic", "conditional-logic", "nulls"], industry="Architecture",
    tables={"buildings": {"id": "INTEGER", "name": "VARCHAR", "city": "VARCHAR", "country": "VARCHAR",
                          "height_m": "DOUBLE", "floors": "INTEGER"}},
    prompt="""
        For each building, return the average height per floor (height_m divided by floors) rounded to two decimals.
        A building with 0 floors gets 0; a building whose number of floors is unknown (NULL) gets NULL.
    """,
    output=["id", "name", "city", "country", "avg_height_per_floor"],
    grain="One row per building.",
    pitfall="CASE WHEN floors != 0 ... ELSE 0 also sends NULL floors to 0, because the comparison is unknown. Test "
            "floors = 0 instead. Snowflake raises an error on division by zero, so the zero case must not divide.",
    hints=["CASE WHEN floors = 0 THEN 0 ELSE ROUND(height_m / floors, 2) END.", "IFF(floors = 0, 0, ...) in Snowflake."],
    explanation="""
        Guard the division with the zero case only; NULL then propagates through the division to NULL. Snowflake
        evaluates the guarded branch lazily, so no 'Division by zero' error is raised.
    """,
    changes=["A NULL number of floors gives NULL (ZillaCode's references gave 0 or NULL depending on the engine)."],
    edges=[{"id": "zero-and-unknown-floors", "tables": {"buildings": rows(
        "id name city country height_m floors",
        (11, "Pavilion", "Oslo", "Norway", 12.0, 0), (12, "Tower X", "Lima", "Peru", 100.0, None),
        (13, "Block", "Kyiv", "Ukraine", 30.0, 8),
    )}}],
    sql=code("""
        SELECT id, name, city, country,
               CASE WHEN floors = 0 THEN 0 ELSE ROUND(height_m / floors, 2) END AS avg_height_per_floor
        FROM buildings
    """),
    snowflake=code("""
        SELECT id, name, city, country,
               IFF(floors = 0, 0, ROUND(height_m / floors, 2)) AS avg_height_per_floor
        FROM buildings
    """),
    dbt="auto",
    python=code("""
        def etl(buildings):
            per_floor = (buildings["height_m"] / buildings["floors"]).round(2)
            result = buildings[["id", "name", "city", "country"]].copy()
            result["avg_height_per_floor"] = per_floor.where(buildings["floors"] != 0, 0.0)
            return result
    """),
    polars=code("""
        def etl(buildings):
            return buildings.select(
                "id", "name", "city", "country",
                pl.when(pl.col("floors") == 0).then(0.0)
                .otherwise((pl.col("height_m") / pl.col("floors")).round(2)).alias("avg_height_per_floor"))
    """),
    mutants={
        "sql": ["SELECT id, name, city, country, CASE WHEN floors != 0 THEN ROUND(height_m / floors, 2) ELSE 0 END AS avg_height_per_floor FROM buildings"],
        "snowflake": ["SELECT id, name, city, country, IFF(floors != 0, ROUND(height_m / floors, 2), 0) AS avg_height_per_floor FROM buildings"],
    },
)

# 42 ------------------------------------------------------------------------------------------------------------------
problem(
    n=42, slug="species-by-climate", title="Species statistics per climate", difficulty="easy",
    topics=["aggregation", "joins"], industry="Zoology",
    tables={"animal_data": {"id": "VARCHAR", "species": "VARCHAR", "age": "INTEGER", "weight": "DOUBLE", "region": "VARCHAR"},
            "region_data": {"region": "VARCHAR", "climate": "VARCHAR"}},
    rename_tables={"AnimalData": "animal_data", "RegionData": "region_data"},
    rename={"ID": "id", "Species": "species", "Age": "age", "Weight": "weight", "Region": "region", "Climate": "climate",
            "AvgAge": "avg_age", "AvgWeight": "avg_weight", "TotalAnimals": "total_animals"},
    prompt="""
        For each species in each climate, return the average age, the average weight truncated to a whole number, and
        the number of animals. An animal's climate comes from its region; animals of regions without a climate are
        left out. A missing weight is not part of the average.
    """,
    output=["species", "climate", "avg_age", "avg_weight", "total_animals"],
    grain="One row per (species, climate).",
    pitfall="Truncating is not rounding: 205.7 becomes 205. Group by species and climate, not species alone.",
    hints=["Join animals to regions, GROUP BY species, climate.", "FLOOR(AVG(weight)) then cast to an integer."],
    explanation="Join to derive the climate, aggregate at the (species, climate) grain, and truncate the weight average.",
    changes=["Tables and columns are snake_case (ZillaCode used AnimalData, AvgWeight, ...)."],
    edges=[{"id": "two-climates-and-null-weight", "tables": {
        "animal_data": rows("id species age weight region", ("A1", "Wolf", 4, 40.9, "Tundra"), ("A2", "Wolf", 6, 41.8, "Tundra"),
                            ("A3", "Wolf", 5, None, "Forest"), ("A4", "Wolf", 3, 30.5, "Forest"), ("A5", "Lynx", 2, 20.0, "Nowhere")),
        "region_data": rows("region climate", ("Tundra", "Cold"), ("Forest", "Temperate")),
    }}],
    sql=code("""
        SELECT a.species, r.climate,
               AVG(a.age) AS avg_age,
               CAST(FLOOR(AVG(a.weight)) AS INTEGER) AS avg_weight,
               COUNT(*) AS total_animals
        FROM animal_data AS a
        JOIN region_data AS r ON a.region = r.region
        GROUP BY a.species, r.climate
    """),
    snowflake=code("""
        SELECT a.species, r.climate,
               AVG(a.age) AS avg_age,
               FLOOR(AVG(a.weight))::INT AS avg_weight,
               COUNT(*) AS total_animals
        FROM animal_data AS a
        JOIN region_data AS r ON a.region = r.region
        GROUP BY a.species, r.climate
    """),
    dbt="auto",
    python=code("""
        def etl(animal_data, region_data):
            joined = animal_data.merge(region_data, on="region")
            result = joined.groupby(["species", "climate"], as_index=False).agg(
                avg_age=("age", "mean"), avg_weight=("weight", "mean"), total_animals=("id", "size"))
            result["avg_weight"] = result["avg_weight"].map(int)
            return result
    """),
    polars=code("""
        def etl(animal_data, region_data):
            return animal_data.join(region_data, on="region").group_by("species", "climate").agg(
                pl.col("age").mean().alias("avg_age"),
                pl.col("weight").mean().floor().cast(pl.Int64).alias("avg_weight"),
                pl.len().alias("total_animals"))
    """),
    mutants={
        "sql": ["SELECT a.species, r.climate, AVG(a.age) AS avg_age, CAST(ROUND(AVG(a.weight)) AS INTEGER) AS avg_weight, COUNT(*) AS total_animals FROM animal_data AS a JOIN region_data AS r ON a.region = r.region GROUP BY a.species, r.climate",
                "SELECT a.species, MIN(r.climate) AS climate, AVG(a.age) AS avg_age, CAST(FLOOR(AVG(a.weight)) AS INTEGER) AS avg_weight, COUNT(*) AS total_animals FROM animal_data AS a JOIN region_data AS r ON a.region = r.region GROUP BY a.species"],
    },
)

# 43 ------------------------------------------------------------------------------------------------------------------
problem(
    n=43, slug="top-observations", title="Top three observations with ties", difficulty="medium",
    topics=["window-functions", "ranking", "ordering"], industry="Herpetology",
    tables={"observations": {"obs_id": "INTEGER", "species_id": "INTEGER", "location_id": "INTEGER", "count": "INTEGER"},
            "species": {"species_id": "INTEGER", "species_name": "VARCHAR"}},
    prompt="""
        Join the observations to their species and return the three largest observations by count. Observations tied
        with the third one are all returned (a rank, not a row limit). Sort by count descending, then by obs_id.
    """,
    output=["obs_id", "species_id", "species_name", "location_id", "count"], ordered=True,
    order_text="Row order is graded: count descending, then obs_id ascending.",
    grain="One row per observation ranked 3 or better.",
    pitfall="LIMIT 3 (or head(3)) cuts tied observations arbitrarily; RANK() <= 3 keeps every tie.",
    hints=["RANK() OVER (ORDER BY count DESC) <= 3.", "Sort the final result by count DESC, obs_id."],
    explanation="""
        Top-N with ties is a ranking problem: RANK gives tied rows the same rank, so every observation tied with the
        third one passes the filter. ORDER BY then fixes the output order.
    """,
    changes=["Output columns follow the statement; the order is graded with obs_id breaking ties."],
    edges=[{"id": "tie-at-third", "tables": {
        "observations": rows("obs_id species_id location_id count", (1, 1, 1, 50), (2, 2, 1, 40), (3, 1, 2, 30),
                             (4, 2, 2, 30), (5, 1, 3, 10), (6, 9, 3, 99)),
        "species": rows("species_id species_name", (1, "Gecko"), (2, "Frog")),
    }}],
    sql=code("""
        WITH ranked AS (
            SELECT o.obs_id, o.species_id, s.species_name, o.location_id, o.count,
                   RANK() OVER (ORDER BY o.count DESC) AS count_rank
            FROM observations AS o
            JOIN species AS s ON o.species_id = s.species_id
        )
        SELECT obs_id, species_id, species_name, location_id, count
        FROM ranked
        WHERE count_rank <= 3
        ORDER BY count DESC, obs_id
    """),
    snowflake=code("""
        SELECT o.obs_id, o.species_id, s.species_name, o.location_id, o.count
        FROM observations AS o
        JOIN species AS s ON o.species_id = s.species_id
        QUALIFY RANK() OVER (ORDER BY o.count DESC) <= 3
        ORDER BY o.count DESC, o.obs_id
    """),
    python=code("""
        def etl(observations, species):
            joined = observations.merge(species, on="species_id")
            top = joined[joined["count"].rank(method="min", ascending=False) <= 3]
            top = top.sort_values(["count", "obs_id"], ascending=[False, True])
            return top[["obs_id", "species_id", "species_name", "location_id", "count"]]
    """),
    polars=code("""
        def etl(observations, species):
            joined = observations.join(species, on="species_id")
            top = joined.filter(pl.col("count").rank("min", descending=True) <= 3)
            return top.sort(["count", "obs_id"], descending=[True, False]).select(
                "obs_id", "species_id", "species_name", "location_id", "count")
    """),
    mutants={
        "sql": ["SELECT o.obs_id, o.species_id, s.species_name, o.location_id, o.count FROM observations AS o JOIN species AS s ON o.species_id = s.species_id ORDER BY o.count DESC, o.obs_id LIMIT 3",
                "WITH r AS (SELECT o.obs_id, o.species_id, s.species_name, o.location_id, o.count, DENSE_RANK() OVER (ORDER BY o.count DESC) AS k FROM observations AS o JOIN species AS s ON o.species_id = s.species_id) SELECT obs_id, species_id, species_name, location_id, count FROM r WHERE k <= 3 ORDER BY count DESC, obs_id"],
    },
)

# 44 ------------------------------------------------------------------------------------------------------------------
problem(
    n=44, slug="portfolio-value", title="Daily portfolio value per firm", difficulty="easy",
    topics=["aggregation", "joins"], industry="Private equity",
    tables={"portfolio": {"pe_firm": "VARCHAR", "company": "VARCHAR", "shares": "INTEGER"},
            "prices": {"date": "DATE", "company": "VARCHAR", "closing_price": "DOUBLE"}},
    rename={"PE_firm": "pe_firm"},
    prompt="""
        A private equity firm holds shares of companies; prices gives each company's closing price per day. Return each
        firm's portfolio value per day: the sum over its holdings of shares times the closing price that day. A
        holding without a price on a day adds nothing that day.
    """,
    output=["pe_firm", "date", "portfolio_value"],
    grain="One row per (firm, date) with at least one priced holding.",
    pitfall="Multiply per holding before summing: SUM(shares) * SUM(price) mixes companies.",
    hints=["Join on company, then SUM(shares * closing_price) GROUP BY pe_firm, date."],
    explanation="Join holdings to the day's prices and aggregate the per-holding value at the (firm, date) grain.",
    changes=["portfolio_value stays a DOUBLE (prices have decimals). Columns are snake_case (pe_firm)."],
    edges=[{"id": "missing-price", "tables": {
        "portfolio": rows("pe_firm company shares", ("Alpha", "A", 10), ("Alpha", "B", 5), ("Beta", "B", 2)),
        "prices": rows("date company closing_price", ("2023-01-01", "A", 1.5), ("2023-01-01", "B", 10.0),
                       ("2023-01-02", "B", 11.0), ("2023-01-02", "Z", 99.0)),
    }}],
    sql=code("""
        SELECT p.pe_firm, pr.date, SUM(p.shares * pr.closing_price) AS portfolio_value
        FROM portfolio AS p
        JOIN prices AS pr ON p.company = pr.company
        GROUP BY p.pe_firm, pr.date
    """),
    snowflake="same", dbt="auto",
    python=code("""
        def etl(portfolio, prices):
            joined = portfolio.merge(prices, on="company")
            joined["value"] = joined["shares"] * joined["closing_price"]
            return joined.groupby(["pe_firm", "date"], as_index=False).agg(portfolio_value=("value", "sum"))
    """),
    polars=code("""
        def etl(portfolio, prices):
            return portfolio.join(prices, on="company").group_by("pe_firm", "date").agg(
                (pl.col("shares") * pl.col("closing_price")).sum().alias("portfolio_value"))
    """),
    sparklab=code("""
        from pyspark.sql import functions as F

        portfolio = spark.table("portfolio")
        prices = spark.table("prices")
        portfolio.join(prices, "company").withColumn("value", F.col("shares") * F.col("closing_price")).groupBy(
            "pe_firm", "date").agg(F.sum("value").alias("portfolio_value"))
    """),
    mutants={
        "sql": ["SELECT p.pe_firm, pr.date, SUM(p.shares) * SUM(pr.closing_price) AS portfolio_value FROM portfolio AS p JOIN prices AS pr ON p.company = pr.company GROUP BY p.pe_firm, pr.date"],
    },
)

# 45 ------------------------------------------------------------------------------------------------------------------
problem(
    n=45, slug="gdp-growth", title="Year-over-year GDP growth", difficulty="medium",
    topics=["self-join", "union", "ordering", "nulls"], industry="Economics",
    tables={"df1": {"country": "VARCHAR", "year": "INTEGER", "gdp": "DOUBLE"},
            "df2": {"country": "VARCHAR", "year": "INTEGER", "gdp": "DOUBLE"}},
    rename={"Country": "country", "Year": "year", "GDP": "gdp", "GDP_growth_rate": "gdp_growth_rate"},
    prompt="""
        Two files hold yearly GDP per country and may both contain the same country-year (the same fact twice). For
        each country and year, return the growth rate from the previous calendar year, (gdp - previous gdp) / previous
        gdp * 100, rounded to two decimals. It is NULL when the previous year is missing or its GDP is 0. Sort by
        country, then year.
    """,
    output=["country", "year", "gdp_growth_rate"], ordered=True,
    order_text="Row order is graded: country ascending, then year ascending.",
    grain="One row per distinct (country, year).",
    pitfall="LAG takes the previous row, which is not the previous year when a year is missing, and duplicate "
            "country-years from the two files would compare a year with itself (0% growth).",
    hints=["UNION (not UNION ALL) removes the duplicated facts.",
           "Join each year to year - 1 of the same country; a LEFT JOIN leaves NULL when it is missing."],
    explanation="""
        Deduplicate with UNION, then self-join on (country, year - 1) so a gap year gives NULL instead of comparing
        with an older year. NULLIF guards the division (Snowflake would raise on a GDP of 0).
    """,
    changes=["The growth compares with the previous calendar year, as the statement says; duplicated country-years "
             "count once (ZillaCode's LAG compared duplicates and non-consecutive years). Columns are snake_case."],
    edges=[{"id": "gap-year-and-duplicates", "tables": {
        "df1": rows("country year gdp", ("France", 2019, 100.0), ("France", 2020, 90.0), ("Chile", 2019, 0.0)),
        "df2": rows("country year gdp", ("France", 2020, 90.0), ("France", 2022, 99.0), ("Chile", 2020, 5.0)),
    }}],
    sql=code("""
        WITH gdp AS (
            SELECT country, year, gdp FROM df1
            UNION
            SELECT country, year, gdp FROM df2
        )
        SELECT cur.country, cur.year,
               ROUND((cur.gdp - prev.gdp) / NULLIF(prev.gdp, 0) * 100, 2) AS gdp_growth_rate
        FROM gdp AS cur
        LEFT JOIN gdp AS prev ON prev.country = cur.country AND prev.year = cur.year - 1
        ORDER BY cur.country, cur.year
    """),
    snowflake="same",
    python=code("""
        def etl(df1, df2):
            gdp = pd.concat([df1, df2]).drop_duplicates()
            previous = gdp.assign(year=gdp["year"] + 1).rename(columns={"gdp": "previous_gdp"})
            joined = gdp.merge(previous, on=["country", "year"], how="left")
            base = joined["previous_gdp"].where(joined["previous_gdp"] != 0)
            joined["gdp_growth_rate"] = ((joined["gdp"] - base) / base * 100).round(2)
            return joined.sort_values(["country", "year"])[["country", "year", "gdp_growth_rate"]]
    """),
    polars=code("""
        def etl(df1, df2):
            gdp = pl.concat([df1, df2]).unique()
            previous = gdp.with_columns(pl.col("year") + 1).rename({"gdp": "previous_gdp"})
            base = pl.when(pl.col("previous_gdp") != 0).then(pl.col("previous_gdp"))
            return gdp.join(previous, on=["country", "year"], how="left").select(
                "country", "year", ((pl.col("gdp") - base) / base * 100).round(2).alias("gdp_growth_rate")
            ).sort("country", "year")
    """),
    mutants={
        "sql": ["WITH g AS (SELECT country, year, gdp FROM df1 UNION SELECT country, year, gdp FROM df2) SELECT country, year, ROUND((gdp - LAG(gdp) OVER (PARTITION BY country ORDER BY year)) / NULLIF(LAG(gdp) OVER (PARTITION BY country ORDER BY year), 0) * 100, 2) AS gdp_growth_rate FROM g ORDER BY country, year",
                "WITH g AS (SELECT country, year, gdp FROM df1 UNION ALL SELECT country, year, gdp FROM df2) SELECT cur.country, cur.year, ROUND((cur.gdp - prev.gdp) / NULLIF(prev.gdp, 0) * 100, 2) AS gdp_growth_rate FROM g AS cur LEFT JOIN g AS prev ON prev.country = cur.country AND prev.year = cur.year - 1 ORDER BY cur.country, cur.year"],
    },
)

# 46 ------------------------------------------------------------------------------------------------------------------
problem(
    n=46, slug="gas-law", title="Pressure times temperature per experiment", difficulty="easy",
    topics=["joins", "arithmetic", "ordering"], industry="Thermodynamics",
    tables={"df_temperature": {"experiment_id": "INTEGER", "temperature": "DOUBLE"},
            "df_pressure": {"experiment_id": "INTEGER", "pressure": "DOUBLE"}},
    rename={"ExperimentID": "experiment_id", "Temperature": "temperature", "Pressure": "pressure", "Result": "result"},
    prompt="""
        For each experiment present in both tables, return result = pressure * temperature, sorted by experiment_id.
        Experiments missing from either table are left out.
    """,
    output=["experiment_id", "result"], ordered=True,
    order_text="Row order is graded: experiment_id ascending.",
    grain="One row per experiment present in both tables.",
    pitfall="Only experiments in both tables count: an outer join would add rows with a NULL result.",
    hints=["Inner join on experiment_id, multiply, ORDER BY experiment_id."],
    explanation="An inner join keeps the experiments measured in both tables; the product is computed per row.",
    changes=["Columns are snake_case (ZillaCode used ExperimentID, Result, ...)."],
    edges=[{"id": "one-sided", "tables": {
        "df_temperature": rows("experiment_id temperature", (3, 300.0), (1, 250.0), (2, 280.0)),
        "df_pressure": rows("experiment_id pressure", (1, 2.0), (3, 1.5), (4, 9.0)),
    }}],
    sql=code("""
        SELECT t.experiment_id, t.temperature * p.pressure AS result
        FROM df_temperature AS t
        JOIN df_pressure AS p ON t.experiment_id = p.experiment_id
        ORDER BY t.experiment_id
    """),
    snowflake="same",
    python=code("""
        def etl(df_temperature, df_pressure):
            joined = df_temperature.merge(df_pressure, on="experiment_id")
            joined["result"] = joined["temperature"] * joined["pressure"]
            return joined.sort_values("experiment_id")[["experiment_id", "result"]]
    """),
    polars=code("""
        def etl(df_temperature, df_pressure):
            return df_temperature.join(df_pressure, on="experiment_id").select(
                "experiment_id", (pl.col("temperature") * pl.col("pressure")).alias("result")).sort("experiment_id")
    """),
    sparklab=code("""
        from pyspark.sql import functions as F

        temperature = spark.table("df_temperature")
        pressure = spark.table("df_pressure")
        temperature.join(pressure, "experiment_id").select(
            "experiment_id", (F.col("temperature") * F.col("pressure")).alias("result")).orderBy("experiment_id")
    """),
    mutants={
        "sql": ["SELECT t.experiment_id, t.temperature * p.pressure AS result FROM df_temperature AS t LEFT JOIN df_pressure AS p ON t.experiment_id = p.experiment_id ORDER BY t.experiment_id",
                "SELECT t.experiment_id, t.temperature * p.pressure AS result FROM df_temperature AS t JOIN df_pressure AS p ON t.experiment_id = p.experiment_id ORDER BY result"],
    },
)

# 47 ------------------------------------------------------------------------------------------------------------------
problem(
    n=47, slug="experiments-full-join", title="Experiments and materials, all of them", difficulty="easy",
    topics=["full-outer-join", "nulls"], industry="Materials engineering",
    tables={"df_experiments": {"experiment_id": "INTEGER", "material_id": "INTEGER", "experiment_date": "VARCHAR",
                               "experiment_results": "DOUBLE"},
            "df_materials": {"material_id": "INTEGER", "material_name": "VARCHAR", "material_type": "VARCHAR"}},
    prompt="""
        Join experiments to materials on material_id with a full outer join: every experiment and every material
        appears, with NULLs for the missing side. material_id comes from whichever side has it; an experiment without
        a material_id matches nothing.
    """,
    output=["experiment_id", "material_id", "material_name", "material_type", "experiment_date", "experiment_results"],
    grain="One row per matched pair, plus one per unmatched experiment and per unmatched material.",
    pitfall="Selecting e.material_id loses the id of materials without experiments: COALESCE both sides (USING does it "
            "for you).",
    hints=["FULL OUTER JOIN ... ON e.material_id = m.material_id.", "COALESCE(e.material_id, m.material_id)."],
    explanation="A full outer join keeps both sides' unmatched rows; the join key must be merged from both sides.",
    changes=["Output columns follow the statement's order."],
    edges=[{"id": "unmatched-both-sides", "tables": {
        "df_experiments": rows("experiment_id material_id experiment_date experiment_results",
                               (1, 101, "2023-07-01", 7.5), (2, None, "2023-07-02", 8.0), (3, 999, "2023-07-03", 6.0)),
        "df_materials": rows("material_id material_name material_type", (101, "Steel", "Metal"), (102, "Oak", "Wood")),
    }}],
    sql=code("""
        SELECT e.experiment_id,
               COALESCE(e.material_id, m.material_id) AS material_id,
               m.material_name, m.material_type, e.experiment_date, e.experiment_results
        FROM df_experiments AS e
        FULL OUTER JOIN df_materials AS m ON e.material_id = m.material_id
    """),
    snowflake="same", dbt="auto",
    python=code("""
        def etl(df_experiments, df_materials):
            joined = df_experiments.merge(df_materials, on="material_id", how="outer")
            return joined[["experiment_id", "material_id", "material_name", "material_type", "experiment_date",
                           "experiment_results"]]
    """),
    polars=code("""
        def etl(df_experiments, df_materials):
            return df_experiments.join(df_materials, on="material_id", how="full", coalesce=True).select(
                "experiment_id", "material_id", "material_name", "material_type", "experiment_date", "experiment_results")
    """),
    sparklab=code("""
        experiments = spark.table("df_experiments")
        materials = spark.table("df_materials")
        experiments.join(materials, "material_id", "full").select(
            "experiment_id", "material_id", "material_name", "material_type", "experiment_date", "experiment_results")
    """),
    mutants={
        "sql": ["SELECT e.experiment_id, e.material_id, m.material_name, m.material_type, e.experiment_date, e.experiment_results FROM df_experiments AS e FULL OUTER JOIN df_materials AS m ON e.material_id = m.material_id",
                "SELECT e.experiment_id, e.material_id, m.material_name, m.material_type, e.experiment_date, e.experiment_results FROM df_experiments AS e LEFT JOIN df_materials AS m ON e.material_id = m.material_id"],
    },
)

# 48 ------------------------------------------------------------------------------------------------------------------
problem(
    n=48, slug="split-fields", title="Split names and product info", difficulty="easy",
    topics=["strings", "joins"], industry="Flooring retail",
    tables={"customers": {"customer_id": "INTEGER", "full_name": "VARCHAR", "location": "VARCHAR"},
            "orders": {"order_id": "INTEGER", "customer_id": "INTEGER", "product_id": "INTEGER", "quantity": "INTEGER"},
            "products": {"product_id": "INTEGER", "product_info": "VARCHAR"}},
    prompt="""
        Return every order with its customer and product details. Split full_name at its first space: first_name is
        the text before it and last_name everything after it ('Mary Ann Lee' gives 'Mary' and 'Ann Lee'). Split
        product_info ('type,color') at the comma into product_type and product_color. Orders of unknown customers or
        products are left out.
    """,
    output=["order_id", "customer_id", "first_name", "last_name", "location", "product_id", "product_type",
            "product_color", "quantity"],
    grain="One row per order with a known customer and product.",
    pitfall="SPLIT_PART(full_name, ' ', 2) returns only the second word; a last name can contain spaces.",
    hints=["first_name: SPLIT_PART(full_name, ' ', 1).",
           "last_name: the substring after the first space (SUBSTR with POSITION / strpos)."],
    explanation="""
        Splitting at the first separator is a different operation from taking the second field: use the separator's
        position for the remainder. The product info has exactly one comma, so SPLIT_PART works there.
    """,
    changes=["last_name is everything after the first space (ZillaCode took the second word)."],
    edges=[{"id": "long-names", "tables": {
        "customers": rows("customer_id full_name location", (1, "Mary Ann Lee", "Ohio"), (2, "Bo Ray", "Utah")),
        "orders": rows("order_id customer_id product_id quantity", (10, 1, 100, 2), (11, 2, 101, 1), (12, 3, 100, 5)),
        "products": rows("product_id product_info", (100, "Vinyl,Light Grey"), (101, "Tile,Blue")),
    }}],
    sql=code("""
        SELECT o.order_id, c.customer_id,
               split_part(c.full_name, ' ', 1) AS first_name,
               substr(c.full_name, strpos(c.full_name, ' ') + 1) AS last_name,
               c.location, p.product_id,
               split_part(p.product_info, ',', 1) AS product_type,
               split_part(p.product_info, ',', 2) AS product_color,
               o.quantity
        FROM orders AS o
        JOIN customers AS c ON o.customer_id = c.customer_id
        JOIN products AS p ON o.product_id = p.product_id
    """),
    snowflake=code("""
        SELECT o.order_id, c.customer_id,
               SPLIT_PART(c.full_name, ' ', 1) AS first_name,
               SUBSTR(c.full_name, POSITION(' ' IN c.full_name) + 1) AS last_name,
               c.location, p.product_id,
               SPLIT_PART(p.product_info, ',', 1) AS product_type,
               SPLIT_PART(p.product_info, ',', 2) AS product_color,
               o.quantity
        FROM orders AS o
        JOIN customers AS c ON o.customer_id = c.customer_id
        JOIN products AS p ON o.product_id = p.product_id
    """),
    dbt="auto",
    python=code("""
        def etl(customers, orders, products):
            customers = customers.copy()
            customers[["first_name", "last_name"]] = customers["full_name"].str.split(" ", n=1, expand=True)
            products = products.copy()
            products[["product_type", "product_color"]] = products["product_info"].str.split(",", n=1, expand=True)
            joined = orders.merge(customers, on="customer_id").merge(products, on="product_id")
            return joined[["order_id", "customer_id", "first_name", "last_name", "location", "product_id", "product_type",
                           "product_color", "quantity"]]
    """),
    polars=code("""
        def etl(customers, orders, products):
            name = pl.col("full_name").str.splitn(" ", 2)
            info = pl.col("product_info").str.splitn(",", 2)
            customers = customers.with_columns(name.struct.field("field_0").alias("first_name"),
                                               name.struct.field("field_1").alias("last_name"))
            products = products.with_columns(info.struct.field("field_0").alias("product_type"),
                                             info.struct.field("field_1").alias("product_color"))
            return orders.join(customers, on="customer_id").join(products, on="product_id").select(
                "order_id", "customer_id", "first_name", "last_name", "location", "product_id", "product_type",
                "product_color", "quantity")
    """),
    mutants={
        "sql": ["SELECT o.order_id, c.customer_id, split_part(c.full_name, ' ', 1) AS first_name, split_part(c.full_name, ' ', 2) AS last_name, c.location, p.product_id, split_part(p.product_info, ',', 1) AS product_type, split_part(p.product_info, ',', 2) AS product_color, o.quantity FROM orders AS o JOIN customers AS c ON o.customer_id = c.customer_id JOIN products AS p ON o.product_id = p.product_id"],
        "snowflake": ["SELECT o.order_id, c.customer_id, SPLIT_PART(c.full_name, ' ', 1) AS first_name, SPLIT_PART(c.full_name, ' ', -1) AS last_name, c.location, p.product_id, SPLIT_PART(p.product_info, ',', 1) AS product_type, SPLIT_PART(p.product_info, ',', 2) AS product_color, o.quantity FROM orders AS o JOIN customers AS c ON o.customer_id = c.customer_id JOIN products AS p ON o.product_id = p.product_id"],
    },
)

# 49 ------------------------------------------------------------------------------------------------------------------
problem(
    n=49, slug="name-lengths", title="Lengths of trimmed names", difficulty="easy",
    topics=["strings", "left-join", "self-join"], industry="Airlines",
    tables={"flights": {"flight_id": "INTEGER", "origin_airport": "VARCHAR", "destination_airport": "VARCHAR"},
            "airports": {"airport_id": "VARCHAR", "airport_name": "VARCHAR"},
            "planes": {"plane_id": "INTEGER", "plane_model": "VARCHAR"}},
    prompt="""
        For every flight, return the length of its origin airport's name, of its destination airport's name, and of its
        plane's model (the plane whose plane_id equals the flight_id), each measured after trimming leading and trailing
        spaces. An unknown airport or plane gives a NULL length; the flight is kept.
    """,
    output=["flight_id", "origin_airport_name_length", "destination_airport_name_length", "plane_model_length"],
    grain="One row per flight.",
    pitfall="The airports table is used twice (origin and destination): join it twice under two aliases. An inner join "
            "would drop flights with an unknown airport.",
    hints=["LEFT JOIN airports AS o ... LEFT JOIN airports AS d ...", "LENGTH(TRIM(name))."],
    explanation="The same lookup table plays two roles, so it is joined twice with different aliases; LEFT JOINs keep every flight.",
    changes=["Names with surrounding spaces are trimmed as the statement asks; an edge check covers them."],
    edges=[{"id": "spaces-and-unknowns", "tables": {
        "flights": rows("flight_id origin_airport destination_airport", (1, "A1", "B1"), (2, "A1", "ZZ")),
        "airports": rows("airport_id airport_name", ("A1", "  Oslo "), ("B1", "Bergen")),
        "planes": rows("plane_id plane_model", (1, " A320 ")),
    }}],
    sql=code("""
        SELECT f.flight_id,
               length(trim(o.airport_name)) AS origin_airport_name_length,
               length(trim(d.airport_name)) AS destination_airport_name_length,
               length(trim(p.plane_model)) AS plane_model_length
        FROM flights AS f
        LEFT JOIN airports AS o ON f.origin_airport = o.airport_id
        LEFT JOIN airports AS d ON f.destination_airport = d.airport_id
        LEFT JOIN planes AS p ON f.flight_id = p.plane_id
    """),
    snowflake="same", dbt="auto",
    python=code("""
        def etl(flights, airports, planes):
            names = airports.set_index("airport_id")["airport_name"].str.strip().str.len()
            models = planes.set_index("plane_id")["plane_model"].str.strip().str.len()
            return pd.DataFrame({
                "flight_id": flights["flight_id"],
                "origin_airport_name_length": flights["origin_airport"].map(names),
                "destination_airport_name_length": flights["destination_airport"].map(names),
                "plane_model_length": flights["flight_id"].map(models),
            })
    """),
    polars=code("""
        def etl(flights, airports, planes):
            lengths = airports.select("airport_id", pl.col("airport_name").str.strip_chars().str.len_chars().alias("n"))
            models = planes.select(pl.col("plane_id").alias("flight_id"),
                                   pl.col("plane_model").str.strip_chars().str.len_chars().alias("plane_model_length"))
            return (flights
                    .join(lengths.rename({"airport_id": "origin_airport", "n": "origin_airport_name_length"}),
                          on="origin_airport", how="left")
                    .join(lengths.rename({"airport_id": "destination_airport", "n": "destination_airport_name_length"}),
                          on="destination_airport", how="left")
                    .join(models, on="flight_id", how="left")
                    .select("flight_id", "origin_airport_name_length", "destination_airport_name_length",
                            "plane_model_length"))
    """),
    mutants={
        "sql": ["SELECT f.flight_id, length(o.airport_name) AS origin_airport_name_length, length(d.airport_name) AS destination_airport_name_length, length(p.plane_model) AS plane_model_length FROM flights AS f LEFT JOIN airports AS o ON f.origin_airport = o.airport_id LEFT JOIN airports AS d ON f.destination_airport = d.airport_id LEFT JOIN planes AS p ON f.flight_id = p.plane_id",
                "SELECT f.flight_id, length(trim(o.airport_name)) AS origin_airport_name_length, length(trim(d.airport_name)) AS destination_airport_name_length, length(trim(p.plane_model)) AS plane_model_length FROM flights AS f JOIN airports AS o ON f.origin_airport = o.airport_id JOIN airports AS d ON f.destination_airport = d.airport_id JOIN planes AS p ON f.flight_id = p.plane_id"],
    },
)

# 50 ------------------------------------------------------------------------------------------------------------------
ARTIFACTS = {"id": "VARCHAR", "item": "VARCHAR", "period": "VARCHAR", "material": "VARCHAR", "quantity": "INTEGER"}
problem(
    n=50, slug="bulk-artifacts", title="Artifacts found in bulk", difficulty="easy",
    topics=["filtering", "strings"], industry="Archaeology",
    tables={"artifacts": ARTIFACTS},
    rename={"ID": "id", "Item": "item", "Period": "period", "Material": "material", "Quantity": "quantity"},
    prompt="""
        Return the artifacts found in quantities greater than 100, with their material in upper case. The other columns
        are unchanged; an unknown material stays unknown.
    """,
    output=list(ARTIFACTS), grain="One row per artifact with a quantity above 100.",
    pitfall="'Greater than 100' excludes exactly 100.",
    hints=["UPPER(material) and WHERE quantity > 100."],
    explanation="A projection with a string function and a strict filter; UPPER(NULL) is NULL in every engine.",
    changes=["id is text, as the statement's schema says; columns are snake_case."],
    edges=[{"id": "boundary-and-null", "tables": {"artifacts": rows(
        "id item period material quantity", ("11", "Coin", "Roman", "Silver", 100), ("12", "Bead", "Roman", None, 101),
        ("13", "Shard", "Bronze Age", "clay", 250),
    )}}],
    sql=code("""
        SELECT id, item, period, upper(material) AS material, quantity
        FROM artifacts
        WHERE quantity > 100
    """),
    snowflake="same", dbt="auto",
    python=code("""
        def etl(artifacts):
            bulk = artifacts[artifacts["quantity"] > 100]
            return bulk.assign(material=bulk["material"].str.upper())
    """),
    polars=code("""
        def etl(artifacts):
            return artifacts.filter(pl.col("quantity") > 100).with_columns(pl.col("material").str.to_uppercase())
    """),
    mutants={
        "sql": ["SELECT id, item, period, upper(material) AS material, quantity FROM artifacts WHERE quantity >= 100"],
    },
)

# 51 ------------------------------------------------------------------------------------------------------------------
problem(
    n=51, slug="valid-expressions", title="Valid arithmetic expressions", difficulty="medium",
    topics=["regular-expressions", "ordering"], industry="Mathematics",
    tables={"df_math_expr": {"id": "INTEGER", "expression": "VARCHAR"}},
    prompt="""
        Keep the rows whose whole expression is numbers (digits 0-9) separated by the operators +, -, * or /, with at
        least one operator: '5+3' and '2*3+1' are valid, '7', 'x1+2' and '1+2 ' are not. Return them sorted by id (the
        input order).
    """,
    output=["id", "expression"], ordered=True,
    order_text="Row order is graded: id ascending.",
    grain="One row per valid expression.",
    pitfall="The whole string must match. Snowflake's REGEXP_LIKE matches the whole string implicitly, DuckDB's "
            "regexp_matches and Polars' str.contains search for a match anywhere, so anchor them with ^ and $.",
    hints=["The pattern is ([0-9]+[-+*/])+[0-9]+.", "Full match: regexp_full_match (DuckDB), REGEXP_LIKE (Snowflake), "
                                                     "str.fullmatch (pandas)."],
    explanation="""
        Regular expression engines differ on whether a pattern must cover the whole value. Anchoring (or a full-match
        function) makes the rule explicit; in the character class, '-' goes first so it is not a range.
    """,
    changes=["The order is graded by id, which is the input order ZillaCode's statement asked to keep."],
    edges=[{"id": "partial-matches", "tables": {"df_math_expr": rows(
        "id expression", (1, "x1+2"), (2, "1+2 "), (3, "7"), (4, "3--4"), (5, "10/2*3"), (6, "8-2"),
    )}}],
    sql=code("""
        SELECT id, expression
        FROM df_math_expr
        WHERE regexp_full_match(expression, '([0-9]+[-+*/])+[0-9]+')
        ORDER BY id
    """),
    snowflake=code("""
        SELECT id, expression
        FROM df_math_expr
        WHERE REGEXP_LIKE(expression, '([0-9]+[-+*/])+[0-9]+')
        ORDER BY id
    """),
    python=code("""
        def etl(df_math_expr):
            valid = df_math_expr["expression"].str.fullmatch(r"([0-9]+[-+*/])+[0-9]+")
            return df_math_expr[valid.fillna(False).astype(bool)].sort_values("id")
    """),
    polars=code("""
        def etl(df_math_expr):
            return df_math_expr.filter(pl.col("expression").str.contains(r"^([0-9]+[-+*/])+[0-9]+$")).sort("id")
    """),
    mutants={
        "sql": ["SELECT id, expression FROM df_math_expr WHERE regexp_matches(expression, '([0-9]+[-+*/])+[0-9]+') ORDER BY id"],
        "polars": [code("""
            def etl(df_math_expr):
                return df_math_expr.filter(pl.col("expression").str.contains(r"([0-9]+[-+*/])+[0-9]+")).sort("id")
        """)],
    },
)

# 52 ------------------------------------------------------------------------------------------------------------------
problem(
    n=52, slug="stars-and-planets", title="Planets with their stars", difficulty="easy",
    topics=["joins", "renaming"], industry="Astronomy",
    tables={"df_star": {"id": "INTEGER", "name": "VARCHAR", "color": "VARCHAR", "type": "VARCHAR", "distance": "DOUBLE"},
            "df_planet": {"id": "INTEGER", "name": "VARCHAR", "star_id": "INTEGER", "type": "VARCHAR", "distance": "DOUBLE"}},
    prompt="""
        Return every planet with the star it orbits (df_planet.star_id = df_star.id). Both tables have id, name, type
        and distance columns, so rename them: star_name, star_color, star_type, planet_name, planet_type,
        distance_star_earth (the star's distance, in light years) and distance_planet_star (the planet's, in AU).
        Planets of unknown stars and stars without planets are left out.
    """,
    output=["star_name", "star_color", "star_type", "planet_name", "planet_type", "distance_star_earth",
            "distance_planet_star"],
    grain="One row per planet of a known star.",
    pitfall="The join is planet.star_id = star.id, not id = id; the same column names on both sides must be "
            "qualified and renamed.",
    hints=["JOIN df_planet AS p ON p.star_id = s.id.", "Alias every output column."],
    explanation="Qualified column references and aliases resolve the name clash between the two tables.",
    edges=[{"id": "unknown-star", "tables": {
        "df_star": rows("id name color type distance", (1, "Sun", "Yellow", "Dwarf", 0.0), (2, "Vega", "Blue", "Main", 25.0)),
        "df_planet": rows("id name star_id type distance", (1, "Earth", 1, "Terrestrial", 1.0),
                          (2, "Earth", 9, "Terrestrial", 3.0), (3, "Mars", 1, "Terrestrial", 1.52)),
    }}],
    sql=code("""
        SELECT s.name AS star_name, s.color AS star_color, s.type AS star_type,
               p.name AS planet_name, p.type AS planet_type,
               s.distance AS distance_star_earth, p.distance AS distance_planet_star
        FROM df_star AS s
        JOIN df_planet AS p ON p.star_id = s.id
    """),
    snowflake="same", dbt="auto",
    python=code("""
        def etl(df_star, df_planet):
            joined = df_star.merge(df_planet, left_on="id", right_on="star_id", suffixes=("_star", "_planet"))
            return joined.rename(columns={
                "name_star": "star_name", "color": "star_color", "type_star": "star_type",
                "name_planet": "planet_name", "type_planet": "planet_type",
                "distance_star": "distance_star_earth", "distance_planet": "distance_planet_star",
            })[["star_name", "star_color", "star_type", "planet_name", "planet_type", "distance_star_earth",
                "distance_planet_star"]]
    """),
    polars=code("""
        def etl(df_star, df_planet):
            stars = df_star.select(pl.col("id").alias("star_id"), pl.col("name").alias("star_name"),
                                   pl.col("color").alias("star_color"), pl.col("type").alias("star_type"),
                                   pl.col("distance").alias("distance_star_earth"))
            planets = df_planet.select("star_id", pl.col("name").alias("planet_name"), pl.col("type").alias("planet_type"),
                                       pl.col("distance").alias("distance_planet_star"))
            return stars.join(planets, on="star_id").select(
                "star_name", "star_color", "star_type", "planet_name", "planet_type", "distance_star_earth",
                "distance_planet_star")
    """),
    sparklab=code("""
        from pyspark.sql import functions as F

        stars = spark.table("df_star").select(
            F.col("id").alias("star_id"), F.col("name").alias("star_name"), F.col("color").alias("star_color"),
            F.col("type").alias("star_type"), F.col("distance").alias("distance_star_earth"))
        planets = spark.table("df_planet").select(
            "star_id", F.col("name").alias("planet_name"), F.col("type").alias("planet_type"),
            F.col("distance").alias("distance_planet_star"))
        stars.join(planets, "star_id").select(
            "star_name", "star_color", "star_type", "planet_name", "planet_type", "distance_star_earth",
            "distance_planet_star")
    """),
    mutants={
        "sql": ["SELECT s.name AS star_name, s.color AS star_color, s.type AS star_type, p.name AS planet_name, p.type AS planet_type, s.distance AS distance_star_earth, p.distance AS distance_planet_star FROM df_star AS s JOIN df_planet AS p ON p.id = s.id",
                "SELECT s.name AS star_name, s.color AS star_color, s.type AS star_type, p.name AS planet_name, p.type AS planet_type, p.distance AS distance_star_earth, s.distance AS distance_planet_star FROM df_star AS s JOIN df_planet AS p ON p.star_id = s.id"],
    },
)
