"""Generate content/exercise-packs/governance-v1 from authored specs.

Data governance on the lab catalog: row-level security, column-level security and dynamic data
masking in the SQL pool (T-SQL of Synapse dedicated SQL pool and Fabric Warehouse, translated to
DuckDB), and Unity Catalog row filters, column masks and PII tags in the Databricks Lab. Every
check runs real queries as each principal on an isolated catalog.

Expected rows are computed by running each reference through the graders; review them by hand.
The generator also checks that starters and mutants run and fail. Run from the repository root
with PYTHONPATH=runtime.
"""
from __future__ import annotations

import copy
import json
import textwrap
from pathlib import Path

from pack_quality import write_mutants

ROOT = Path.cwd()
PACK = ROOT / "content" / "exercise-packs" / "governance-v1"
EXERCISES: list[dict] = []


def code(text: str) -> str:
    return textwrap.dedent(text).strip("\n") + "\n"


def exercise(**spec):
    EXERCISES.append(spec)


def table(name, rows, types=None):
    entry = {"name": name, "rows": rows}
    if types:
        entry["types"] = types
    return entry


# 1 -- row-level security (SQL pool) ------------------------------------------------------------
SALES = [{"sale_id": i, "sales_rep": rep, "region": region, "amount": float(amount)}
         for i, (rep, region, amount) in enumerate([
             ("alice", "North", 120), ("bob", "South", 80), ("alice", "North", 45), ("carol", "East", 300),
             ("bob", "South", 60), (None, "West", 999), ("alice", "East", 10)], start=1)]
SALES_TYPES = {"sale_id": "INTEGER", "sales_rep": "VARCHAR", "region": "VARCHAR", "amount": "DOUBLE"}
RLS_SETUP = code("""
    CREATE USER alice WITHOUT LOGIN;
    CREATE USER bob WITHOUT LOGIN;
    CREATE USER carol WITHOUT LOGIN;
    CREATE USER dana WITHOUT LOGIN;
    CREATE USER intern WITHOUT LOGIN;
    CREATE ROLE sales_managers;
    ALTER ROLE sales_managers ADD MEMBER dana;
    GRANT SELECT ON dbo.sales TO alice, bob, carol, intern, sales_managers;
""")
RLS_QUERY = "SELECT sale_id, sales_rep, amount FROM dbo.sales"


def rls_scenario(principals):
    return {"tables": [table("dbo.sales", SALES, SALES_TYPES)], "setup": RLS_SETUP, "query": RLS_QUERY,
            "outcome": "principals", "principals": principals,
            "columns": ["principal", "denied", "sale_id", "sales_rep", "amount"]}


def rls(where, state="ON", policy=True):
    body = code(f"""
        -- Each sales rep sees only their own sales; members of sales_managers see every sale.
        CREATE FUNCTION dbo.fn_sales_rep(@sales_rep AS VARCHAR(40))
        RETURNS TABLE
        WITH SCHEMABINDING
        AS
        RETURN SELECT 1 AS fn_result
               WHERE {where};
        GO
    """)
    if policy:
        body += code(f"""
            CREATE SECURITY POLICY dbo.sales_filter
            ADD FILTER PREDICATE dbo.fn_sales_rep(sales_rep) ON dbo.sales
            WITH (STATE = {state});
        """)
    else:
        body += "-- TODO: bind the predicate to dbo.sales with a security policy.\n"
    return body


RLS_WHERE = "@sales_rep = USER_NAME() OR IS_ROLEMEMBER('sales_managers') = 1"
exercise(
    kind="sqlpool", flavor="synapse",
    id="gov-rls-sales-reps", title="Row-level security: each rep sees their own sales", difficulty="medium",
    topics=["row-level-security", "security-policy", "governance"],
    prompt=("dbo.sales holds every sale with its sales_rep. The users alice, bob and carol are sales reps; dana is in "
            "the role sales_managers; intern can read the table but sells nothing. Write a security predicate and a "
            "security policy so that a rep sees only their own rows and sales_managers see every row. A sale without "
            "a rep must stay hidden from reps."),
    sections=[("Graded", "SELECT sale_id, sales_rep, amount FROM dbo.sales run as alice, dana, bob, intern and carol "
                         "(EXECUTE AS USER, then REVERT): the rows each one gets."),
              ("Supported T-SQL", "CREATE FUNCTION ... RETURNS TABLE WITH SCHEMABINDING AS RETURN SELECT 1 AS ... WHERE "
                                  "...; CREATE SECURITY POLICY ... ADD FILTER PREDICATE f(column) ON table WITH (STATE "
                                  "= ON). USER_NAME() and IS_ROLEMEMBER('role') are resolved for the principal. BLOCK "
                                  "predicates are refused.")],
    starter=rls("@sales_rep = USER_NAME()", policy=False),
    solution=rls(RLS_WHERE),
    fixtures=[("reps-and-manager", "visible", rls_scenario(["alice", "dana"])),
              ("other-principals", "hidden", rls_scenario(["bob", "intern"])),
              ("rep-without-sales-row", "edge", rls_scenario(["carol"]))],
    mutants=[rls("@sales_rep = USER_NAME()"),
             rls(RLS_WHERE + " OR @sales_rep IS NULL"),
             rls(RLS_WHERE, state="OFF"),
             rls("@sales_rep = USER_NAME() OR IS_ROLEMEMBER('sales_managers') = 1 OR USER_NAME() = 'intern'")],
    hints=["The predicate function receives the row's sales_rep as @sales_rep; USER_NAME() is the user the query runs "
           "as.",
           "A NULL sales_rep never equals USER_NAME(), so it stays hidden unless you add a clause for it."],
    explanation=("The inline table-valued function returns a row (so the sale is visible) when the sale's rep is the "
                 "current user or when the user is in sales_managers. The security policy binds it to dbo.sales as a "
                 "FILTER predicate, so every SELECT is filtered silently. Filter predicates apply to dbo too: without "
                 "a clause for it, the owner sees nothing."),
    follow_ups=["Run SELECT COUNT(*) FROM dbo.sales as dbo: why is it 0, and what would you add to the predicate for "
                "an ETL account?"],
)

# 2 -- column-level security (SQL pool) ---------------------------------------------------------
CUSTOMERS = [{"customer_id": i, "customer_name": name, "city": city, "email": f"{name.lower()}@example.com",
              "card_number": f"4111-0000-0000-{1000 + i}"}
             for i, (name, city) in enumerate([("Ada", "Paris"), ("Ben", "Lyon"), ("Chloe", "Nantes"),
                                               ("Dev", "Lille")], start=1)]
CLS_SETUP = code("""
    CREATE USER analyst WITHOUT LOGIN;
    CREATE USER fin1 WITHOUT LOGIN;
    CREATE ROLE finance_team;
    ALTER ROLE finance_team ADD MEMBER fin1;
""")
CLS_COLUMNS = ["principal", "denied", "customer_id", "customer_name", "city", "email", "card_number"]


def cls_scenario(query, principals):
    return {"tables": [table("dbo.customers", CUSTOMERS)], "setup": CLS_SETUP, "query": query,
            "outcome": "principals", "principals": principals, "columns": CLS_COLUMNS}


def cls(statements):
    return code("""
        -- analyst reads customers without email and card_number; finance_team reads every column.
    """) + code(statements)


CLS_SOLUTION = """
    GRANT SELECT ON dbo.customers (customer_id, customer_name, city) TO analyst;
    GRANT SELECT ON dbo.customers TO finance_team;
"""
exercise(
    kind="sqlpool", flavor="synapse",
    id="gov-column-security", title="Column-level security with GRANT and DENY", difficulty="easy",
    topics=["column-level-security", "grant", "governance"],
    prompt=("dbo.customers holds each customer's email and card number. The user analyst builds city reports and must "
            "read customer_id, customer_name and city, and nothing else. The role finance_team (member fin1) must "
            "read every column. Nobody has permissions yet: write the GRANT (and, if you prefer, DENY) statements."),
    sections=[("Graded", "Queries run as analyst and fin1 (EXECUTE AS USER): the report columns, SELECT *, and a query "
                         "that reads card_number. A refused query is graded by its permission error."),
              ("Supported T-SQL", "GRANT | DENY | REVOKE SELECT ON table [(columns)] TO principal. A DENY wins over "
                                  "any GRANT, also one given through a role.")],
    starter=cls("GRANT SELECT ON dbo.customers TO analyst, finance_team;"),
    solution=cls(CLS_SOLUTION),
    fixtures=[("report-columns", "visible", cls_scenario("SELECT customer_id, customer_name, city FROM dbo.customers",
                                                         ["analyst", "fin1"])),
              ("select-star", "hidden", cls_scenario("SELECT * FROM dbo.customers", ["analyst", "fin1"])),
              ("card-query", "edge", cls_scenario("SELECT customer_id, card_number FROM dbo.customers", ["analyst"]))],
    mutants=[cls("""
                 GRANT SELECT ON dbo.customers TO analyst, finance_team;
                 DENY SELECT ON dbo.customers (email) TO analyst;
             """),
             cls("""
                 GRANT SELECT ON dbo.customers (customer_id, customer_name, city) TO analyst, finance_team;
             """),
             cls("""
                 GRANT SELECT ON dbo.customers TO finance_team;
             """)],
    hints=["A column list after the table grants only those columns: GRANT SELECT ON t (a, b) TO user.",
           "SELECT * reads every column, so it is refused as soon as one column is not granted."],
    explanation=("Column-level security is a column list on the GRANT: analyst can read three columns, so a query on "
                 "those columns works and SELECT * or any query touching email or card_number fails with a "
                 "permission error. finance_team gets the whole table. Granting the table and denying columns also "
                 "works, but it is easy to forget one sensitive column."),
    follow_ups=["Which is safer when a new sensitive column is added later: a column GRANT or a table GRANT with "
                "column DENYs?"],
)

# 3 -- dynamic data masking (Fabric Warehouse) -------------------------------------------------
CONTACTS = [{"customer_id": 1, "email": "ada@example.com", "phone": "555-201-4471", "birth_date": "1990-04-12"},
            {"customer_id": 2, "email": "ben@contoso.net", "phone": "555-310-9902", "birth_date": "1985-11-30"},
            {"customer_id": 3, "email": None, "phone": "555-777-0001", "birth_date": "2001-01-05"}]
CONTACT_TYPES = {"customer_id": "INTEGER", "email": "VARCHAR", "phone": "VARCHAR", "birth_date": "DATE"}
DDM_SETUP = code("""
    CREATE USER agent1 WITHOUT LOGIN;
    CREATE USER auditor1 WITHOUT LOGIN;
    CREATE ROLE support_agents;
    CREATE ROLE compliance;
    ALTER ROLE support_agents ADD MEMBER agent1;
    ALTER ROLE compliance ADD MEMBER auditor1;
    GRANT SELECT ON dbo.contacts TO support_agents, compliance;
""")


def ddm_scenario(principals):
    return {"flavor": "fabric", "tables": [table("dbo.contacts", CONTACTS, CONTACT_TYPES)], "setup": DDM_SETUP,
            "query": "SELECT customer_id, email, phone, birth_date FROM dbo.contacts", "outcome": "principals",
            "principals": principals,
            "columns": ["principal", "denied", "customer_id", "email", "phone", "birth_date"]}


def ddm(email="email()", phone='partial(0,"XXX-XXX-",4)', birth="default()", unmask="compliance"):
    lines = ["-- Support agents see masked contact details; compliance sees the real values."]
    for column, function in (("email", email), ("phone", phone), ("birth_date", birth)):
        if function:
            lines.append(f"ALTER TABLE dbo.contacts ALTER COLUMN {column} ADD MASKED WITH (FUNCTION = '{function}');")
    if unmask:
        lines.append(f"GRANT UNMASK TO {unmask};")
    return "\n".join(lines) + "\n"


exercise(
    kind="sqlpool", flavor="fabric",
    id="gov-dynamic-masking", title="Dynamic data masking for support agents", difficulty="medium",
    topics=["dynamic-data-masking", "unmask", "governance"],
    prompt=("dbo.contacts in a Fabric warehouse holds customers' email, phone and birth date. Members of "
            "support_agents may read the table but must see masked values: the email as email() shows it, only the "
            "last 4 digits of the phone (the rest written as XXX-XXX-) and the default mask for the birth date. "
            "Members of compliance must see the real values."),
    sections=[("Graded", "SELECT customer_id, email, phone, birth_date FROM dbo.contacts run as agent1 (support_agents) "
                         "and auditor1 (compliance)."),
              ("Supported T-SQL", "ALTER TABLE ... ALTER COLUMN ... ADD MASKED WITH (FUNCTION = 'default()' | "
                                  "'email()' | 'partial(prefix,\"padding\",suffix)') and DROP MASKED; GRANT | REVOKE "
                                  "UNMASK TO principal. random() is refused. In the lab a filter on a masked column "
                                  "compares the masked value; SQL Server compares the real one, which is why masking "
                                  "is not a security boundary.")],
    starter=ddm(email="default()", phone=None, birth=None, unmask=None),
    solution=ddm(),
    fixtures=[("agent-and-auditor", "visible", ddm_scenario(["agent1", "auditor1"])),
              ("agent-only", "hidden", ddm_scenario(["agent1"])),
              ("auditor-only", "edge", ddm_scenario(["auditor1"]))],
    mutants=[ddm(unmask="support_agents"),
             ddm(phone='partial(0,"XXX-XXX-",2)'),
             ddm(birth=None),
             ddm(unmask="support_agents, compliance")],
    hints=["partial(prefix, \"padding\", suffix) keeps prefix characters at the start and suffix at the end.",
           "UNMASK is granted to the principals that must see real values; everyone else gets the masks."],
    explanation=("Each masked column keeps its data; the mask is applied when a principal without UNMASK reads it. "
                 "email() keeps the first letter, partial(0,\"XXX-XXX-\",4) keeps the last four digits, default() "
                 "shows 1900-01-01 for a date. GRANT UNMASK TO compliance lets auditors see real values. NULLs stay "
                 "NULL."),
    follow_ups=["An agent runs SELECT customer_id FROM dbo.contacts WHERE phone LIKE '555-201%'. What does SQL Server "
                "return, and why does that make masking a convenience rather than a security control?"],
)

# 4 -- Unity Catalog row filter (Databricks) ---------------------------------------------------
ORDERS = [{"order_id": i, "region": region, "amount": float(amount)}
          for i, (region, amount) in enumerate([("EMEA", 100), ("AMER", 250), ("EMEA", 40), ("APAC", 75),
                                                (None, 999), ("AMER", 20)], start=1)]
GROUPS = {"groups": {"emea_analysts": ["ana@corp.com"], "amer_analysts": ["ben@corp.com"],
                     "admins": ["root@corp.com"]}}
GRANTS_BASE = code("""
    GRANT USE SCHEMA ON SCHEMA main.silver TO `account users`;
    GRANT SELECT ON TABLE main.silver.orders TO `account users`;
""")
ORDERS_QUERY = "SELECT order_id, region, amount FROM main.silver.orders"


def uc_filter_scenario(principals):
    return {"tables": [table("silver.orders", ORDERS, {"order_id": "INTEGER", "region": "VARCHAR",
                                                       "amount": "DOUBLE"})],
            "files": {"unity_catalog": GROUPS}, "outcome": "principal_rows",
            "queries": [{"principal": p, "sql": ORDERS_QUERY} for p in principals],
            "columns": ["principal", "denied", "order_id", "region", "amount"]}


def uc_filter(body, bind=True):
    text = GRANTS_BASE + code(f"""
        -- Analysts see their region's orders; admins see every order.
        CREATE OR REPLACE FUNCTION main.silver.orders_region_filter(region STRING)
        RETURN {body};
    """)
    if bind:
        text += "ALTER TABLE main.silver.orders SET ROW FILTER main.silver.orders_region_filter ON (region);\n"
    return text


UC_FILTER = ("is_account_group_member('admins')\n"
             "    OR (is_account_group_member('emea_analysts') AND region = 'EMEA')\n"
             "    OR (is_account_group_member('amer_analysts') AND region = 'AMER')")
exercise(
    kind="grants",
    id="gov-uc-row-filter", title="Unity Catalog row filter by region", difficulty="medium",
    topics=["row-filter", "unity-catalog", "governance"],
    prompt=("main.silver.orders is readable by all account users. Members of emea_analysts must see only EMEA orders, "
            "members of amer_analysts only AMER orders, and members of admins every order. Anyone else sees no rows. "
            "Write the SQL UDF and bind it to the table as a row filter, in the workspace's grants.sql."),
    sections=[("Graded", "SELECT order_id, region, amount FROM main.silver.orders run as ana@corp.com (emea_analysts), "
                         "ben@corp.com (amer_analysts), root@corp.com (admins) and bob@corp.com (no group)."),
              ("Supported SQL", "CREATE [OR REPLACE] FUNCTION main.<schema>.<name>(<param> <TYPE>) RETURN "
                                "<expression>; ALTER TABLE ... SET ROW FILTER <function> ON (<columns>) | DROP ROW "
                                "FILTER. is_account_group_member('<group>'), is_member('<group>') and current_user() "
                                "are resolved for the principal.")],
    starter=uc_filter("region = 'EMEA'", bind=False),
    solution=uc_filter(UC_FILTER),
    fixtures=[("analysts", "visible", uc_filter_scenario(["ana@corp.com", "ben@corp.com"])),
              ("admin-and-outsider", "hidden", uc_filter_scenario(["root@corp.com", "bob@corp.com"])),
              ("emea-only", "edge", uc_filter_scenario(["ana@corp.com"]))],
    mutants=[uc_filter("is_account_group_member('admins') OR is_account_group_member('emea_analysts') "
                       "OR is_account_group_member('amer_analysts')"),
             uc_filter(UC_FILTER.replace("region = 'EMEA')", "(region = 'EMEA' OR region IS NULL))")),
             uc_filter("(is_account_group_member('emea_analysts') AND region = 'EMEA')\n"
                       "    OR (is_account_group_member('amer_analysts') AND region = 'AMER')"),
             uc_filter(UC_FILTER, bind=False)],
    hints=["A row filter keeps the rows where the function returns true, for the user who runs the query.",
           "The admin bypass must be its own OR branch: it must not widen what analysts see."],
    explanation=("The UDF returns true for admins whatever the region, and for analysts only on their own region; "
                 "SET ROW FILTER binds it to the table, so every query on main.silver.orders is filtered for its "
                 "user. Orders without a region match no analyst branch and stay visible to admins only."),
    follow_ups=["How would you express the region of each group in a mapping table instead of the function body? "
                "(The lab keeps filters as one expression; Databricks also allows a lookup in the function.)"],
)

# 5 -- PII tags and column masks (Databricks) --------------------------------------------------
PEOPLE = [{"customer_id": 1, "customer_name": "Ada", "email": "ada@example.com", "phone": "+33 6 12 34 56 78",
           "country": "FR"},
          {"customer_id": 2, "customer_name": "Ben", "email": "ben@example.com", "phone": "+1 212 555 0100",
           "country": "US"},
          {"customer_id": 3, "customer_name": "Chloe", "email": None, "phone": "+44 20 7946 0000", "country": "GB"}]
PII_GROUPS = {"groups": {"analysts": ["ana@corp.com"], "pii_readers": ["hr@corp.com"]}}
PII_BASE = code("""
    GRANT USE SCHEMA ON SCHEMA main.silver TO `account users`;
    GRANT SELECT ON TABLE main.silver.customers TO `account users`;
    -- Classify the personal data.
    ALTER TABLE main.silver.customers ALTER COLUMN email SET TAGS ('pii' = 'email');
    ALTER TABLE main.silver.customers ALTER COLUMN phone SET TAGS ('pii' = 'phone');
""")


def pii_tables():
    return [table("silver.customers", PEOPLE)]


def pii_scenario(principal):
    return {"tables": pii_tables(), "files": {"unity_catalog": PII_GROUPS}, "outcome": "pii", "pii_principal": principal}


def pii_rows_scenario(principals):
    return {"tables": pii_tables(), "files": {"unity_catalog": PII_GROUPS}, "outcome": "principal_rows",
            "queries": [{"principal": p, "sql": "SELECT customer_id, customer_name, email, phone "
                                                "FROM main.silver.customers"} for p in principals],
            "columns": ["principal", "denied", "customer_id", "customer_name", "email", "phone"]}


def pii(email_group="pii_readers", phone_group="pii_readers", mask_phone=True, base=PII_BASE):
    text = base + code(f"""
        -- Every column tagged pii is masked for everyone outside pii_readers.
        CREATE OR REPLACE FUNCTION main.silver.mask_email(email STRING)
        RETURN CASE WHEN is_account_group_member('{email_group}') THEN email ELSE '***@***' END;
        CREATE OR REPLACE FUNCTION main.silver.mask_phone(phone STRING)
        RETURN IF(is_account_group_member('{phone_group}'), phone, concat('*** ', right(phone, 2)));
        ALTER TABLE main.silver.customers ALTER COLUMN email SET MASK main.silver.mask_email;
    """)
    if mask_phone:
        text += "ALTER TABLE main.silver.customers ALTER COLUMN phone SET MASK main.silver.mask_phone;\n"
    return text


exercise(
    kind="grants",
    id="gov-uc-pii-masks", title="Mask every PII-tagged column", difficulty="medium",
    topics=["column-mask", "pii-tags", "unity-catalog", "governance"],
    prompt=("main.silver.customers is readable by all account users, and its email and phone columns are tagged "
            "pii. Mask every pii column for everyone except the group pii_readers: the email as '***@***' and the "
            "phone as '*** ' followed by its last two characters. Members of pii_readers see the real values."),
    sections=[("Graded", "For each column tagged pii: does ana@corp.com (analysts) see it masked, and does "
                         "hr@corp.com (pii_readers) see it unmasked (a real query per column: masked means no "
                         "non-null value comes back unchanged); and the customers query as both."),
              ("Supported SQL", "CREATE [OR REPLACE] FUNCTION ... RETURN <expression>; ALTER TABLE ... ALTER COLUMN "
                                "... SET MASK <function> [USING COLUMNS (...)] | DROP MASK; ALTER TABLE ... ALTER "
                                "COLUMN ... SET TAGS ('key' = 'value') | UNSET TAGS ('key').")],
    starter=PII_BASE + "-- TODO: mask the pii columns.\n",
    solution=pii(),
    fixtures=[("analyst-masked", "visible", pii_scenario("ana@corp.com")),
              ("reader-unmasked", "hidden", pii_scenario("hr@corp.com")),
              ("customer-rows", "edge", pii_rows_scenario(["ana@corp.com", "hr@corp.com"]))],
    mutants=[pii(email_group="analysts", phone_group="analysts"),
             pii(mask_phone=False),
             pii(phone_group="account users"),
             pii(base=PII_BASE.replace("ALTER TABLE main.silver.customers ALTER COLUMN phone SET TAGS ('pii' = "
                                       "'phone');\n", ""))],
    hints=["A column mask is a SQL UDF whose first parameter is the column's value; what it returns is what the user "
           "sees.",
           "The PII check follows the tags: a pii column without a mask is a leak, and so is a mask that lets the "
           "wrong group through."],
    explanation=("Tags classify the data; masks enforce it. Each pii column gets SET MASK with a UDF that returns the "
                 "real value only for pii_readers. The check walks every column tagged pii and runs a real query as "
                 "each principal, so an untagged, unmasked or wrongly granted column shows up."),
    follow_ups=["Which group would you give the pii_readers role in production, and how would you audit who is in "
                "it?"],
)


# -- pack assembly ---------------------------------------------------------------------------------
SQLPOOL_SIM = ("Your T-SQL script runs on the lab's simulated {product}: the statements are translated to DuckDB for a "
               "documented subset and really run, on an isolated catalog built for each check. Security (row-level "
               "security, column permissions, dynamic data masking) is enforced for real by rewriting each query for "
               "the user it runs as: T-SQL security translated to DuckDB, not SQL Server. Nothing connects to Azure "
               "or Fabric. End statements with ; (a function takes its own GO batch).")
UC_SIM = ("Your grants.sql runs on the lab's simulated Azure Databricks Unity Catalog: grants, row filters, column "
          "masks and tags follow Databricks' rules, and each check runs real queries as each principal on an isolated "
          "local catalog (DuckDB): Unity Catalog row filters and column masks translated to DuckDB, not Databricks. "
          "Nothing connects to Azure Databricks.")
PRODUCT = {"synapse": "Azure Synapse dedicated SQL pool", "fabric": "Microsoft Fabric Data Warehouse"}


def definition(spec: dict, rank: int) -> dict:
    by_visibility = {"visible": [], "hidden": [], "edge": []}
    for fid, visibility, _ in spec["fixtures"]:
        by_visibility[visibility].append(fid)
    pool = spec["kind"] == "sqlpool"
    simulator = SQLPOOL_SIM.format(product=PRODUCT[spec["flavor"]]) if pool else UC_SIM
    sections = [{"title": "Simulator", "body": simulator}] + [{"title": t, "body": b} for t, b in spec["sections"]]
    projections = {json.dumps(sc.get("columns")) for _, _, sc in spec["fixtures"]}
    exact = json.loads(projections.pop()) if len(projections) == 1 else None
    if exact is None and not pool:
        exact = None
    return {
        "schema_version": 1, "id": spec["id"], "version": "1", "title": spec["title"],
        "difficulty": spec["difficulty"], "topics": spec["topics"],
        "tags": ["cloud-lab", "governance", "sql-pool" if pool else "databricks", "simulated"],
        "origin": "authored", "language": "sqlpool" if pool else "databricks-grants",
        "runtime": "datapass-sqlpool-sim-v1" if pool else "datapass-databricks-sim-v1",
        "prompt": spec["prompt"], "sections": sections, "starter_source": spec["starter"],
        "fixtures": [{"id": f"{spec['id']}-fixtures", "version": "1"}],
        "visible_checks": [{"id": fid, "description": "Rows each principal gets, enforced on the lab catalog."}
                           for fid in by_visibility["visible"]],
        "hidden_check_refs": by_visibility["hidden"], "edge_check_refs": by_visibility["edge"],
        "hints": spec["hints"], "solution": {"available": True, "reveal": "explicit"},
        "explanation": spec["explanation"], "follow_ups": spec["follow_ups"],
        "canonical_placement": {"domain": "governance", "topic": spec["topics"][0]},
        "related_associations": ["cloud-lab/sql-pool" if pool else "cloud-lab/databricks"],
        "recommendation": {"rank": rank, "reason": "Data governance progression"},
        "validator_version": "rows-v2",
        "validation": {"kind": "rows", "ordered": False, "duplicate_sensitive": True, "relative_tolerance": 1e-09,
                       "absolute_tolerance": 1e-06, "required_columns": exact or [], "exact_schema": exact,
                       "forbidden_extra_columns": True, "null_semantics": "equal"},
        "runtime_requirements": ["sqlpool-simulator" if pool else "databricks-simulator"],
        "provenance": {"source": ("Authored for Datapass Workbench: row-level security, column-level security and "
                                  "dynamic data masking in Synapse / Fabric Warehouse; Unity Catalog row filters, "
                                  "column masks and tags (Microsoft Learn)"),
                       "fixtures": "Authored scenarios; expected rows computed by running the reference and reviewed"},
        "constraints": {"truth": ("T-SQL security translated to DuckDB, not SQL Server: rows and values enforced on an "
                                  "isolated local catalog." if pool else
                                  "Unity Catalog row filters and column masks translated to DuckDB, not Databricks: "
                                  "enforced on an isolated local catalog.")},
        "truth": "simulated",
    }


def outcome(spec, source, scenario):
    if spec["kind"] == "sqlpool":
        from datapass_runtime.sqlpool_grading import ScriptRejected, run_fixture
        from sqlpoollab.exercise import PoolScenario
        from sqlpoollab.model import PoolError
        scenario = {"flavor": spec["flavor"], **scenario}
        try:
            return run_fixture(source, PoolScenario.model_validate(scenario)), None
        except (ScriptRejected, PoolError) as exc:
            return None, str(exc)
    from databrickslab.exercise import DbxScenario, graded_columns, project
    from datapass_runtime.databricks_grading import JobRejected, run_fixture as run_dbx
    parsed = DbxScenario.model_validate(scenario)
    try:
        rows = run_dbx("databricks-grants", source, parsed)
    except JobRejected as exc:
        return None, str(exc)
    return project(rows, graded_columns(parsed, rows)), None


def main() -> None:
    from datapass_runtime.exercise_contracts import RowValidation
    from datapass_runtime.exercise_packs import PackRegistry
    from datapass_runtime.exercise_validation import validate_result
    ids = [spec["id"] for spec in EXERCISES]
    assert len(ids) == len(set(ids))
    definitions, grading, problems = [], {}, []
    for rank, spec in enumerate(EXERCISES, start=1):
        for _, _, scenario in spec["fixtures"]:
            if spec["kind"] == "sqlpool":
                scenario.setdefault("flavor", spec["flavor"])
        public = definition(spec, rank)
        definitions.append(public)
        validation = RowValidation.model_validate(public["validation"])
        fixtures = []
        for fid, visibility, scenario in spec["fixtures"]:
            rows, error = outcome(spec, spec["solution"], copy.deepcopy(scenario))
            if error:
                problems.append(f"{spec['id']}/{fid}: reference rejected: {error}")
                rows = []
            fixtures.append({"id": fid, "visibility": visibility, "input_rows": [], "scenario": scenario, "expected": rows})
        grading[spec["id"]] = {"solution": spec["solution"], "fixtures": fixtures}
        for label, source in [("starter", spec["starter"])] + [(f"mutant {i}", m) for i, m in enumerate(spec["mutants"])]:
            failed = False
            for fixture in fixtures:
                rows, error = outcome(spec, source, copy.deepcopy(fixture["scenario"]))
                if error:
                    problems.append(f"{spec['id']}: {label} does not run: {error}")
                    failed = True
                    break
                columns = fixture["scenario"].get("columns") or (list(rows[0]) if rows else [])
                if not validate_result({"rows": rows, "columns": columns, "truncated": False}, fixture["expected"],
                                       validation):
                    failed = True
            if not failed:
                problems.append(f"{spec['id']}: {label} passes every check")
    manifest = {"schema_version": 1, "id": "governance-v1", "version": "1",
                "title": ("Governance: row and column security, masking and PII (simulated SQL pool and Unity "
                          "Catalog)"),
                "enabled": True, "provenance": {"source": "Authored for Datapass Workbench"}}
    PackRegistry().register(manifest, definitions, grading)
    PACK.mkdir(parents=True, exist_ok=True)
    for name, data in (("manifest.json", manifest), ("exercises.json", definitions), ("grading.server.json", grading)):
        (PACK / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_mutants(PACK, {spec["id"]: spec["mutants"] for spec in EXERCISES}, replace_all=True)
    for spec in EXERCISES:
        print(f"== {spec['id']}")
        for fixture in grading[spec["id"]]["fixtures"]:
            print(f"   {fixture['id']:22s}", json.dumps(fixture["expected"])[:300])
    if problems:
        print("\nPROBLEMS:\n  " + "\n  ".join(problems))


if __name__ == "__main__":
    main()
