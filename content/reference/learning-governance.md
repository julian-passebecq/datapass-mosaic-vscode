# Data governance

Cheatsheet for the Learning path *BI, governance and performance*. In the Cloud Lab, T-SQL row-level security, column
permissions and masking are translated to DuckDB and enforced for real (not SQL Server); Unity Catalog row filters and
column masks are translated to DuckDB on SQL tasks (not Databricks). BI Lab lineage is a static analysis of SQL text.

## Access control

| Control | Restricts | Example |
|---|---|---|
| Object grants | which tables a principal can use | `GRANT SELECT ON gold.sales TO analysts` |
| Row-level security | which rows | a rep sees their region (security policy + predicate function) |
| Column-level security | which columns | `DENY SELECT ON customers(email) TO support` |
| Dynamic data masking | what is displayed | `email()` mask; users with `UNMASK` see real values |
| Unity Catalog row filter / column mask | rows / column values, by SQL UDF | `ALTER TABLE ... SET ROW FILTER` |

Masking does not encrypt and does not stop inference (`WHERE salary > 100000`). Combine it with grants.

Unity Catalog: reading `main.sales.orders` needs `USE CATALOG` on `main`, `USE SCHEMA` on `main.sales` and `SELECT`.

## Least privilege

- Jobs run as their own **service principal** with only the grants they need (read silver, write gold).
- Grant to groups, not individuals; review grants regularly.
- No shared personal accounts, no secrets in code, notebooks or images.

## Lineage

- Column lineage: which source columns each column comes from.
- Use it for impact analysis before a change and to find where personal data flows.

## Personal data (GDPR)

| Term | Status |
|---|---|
| Personal data | anything relating to an identifiable person (name, email, customer id, IP address) |
| Pseudonymised | identifiers replaced, re-identification possible with separate data: **still personal data** |
| Anonymous | cannot reasonably be linked back: outside GDPR |

Data minimisation: copy only the columns a use case needs. Unsalted hashes of emails or ids can be reversed by
hashing a known list.

## Classification

Tag sensitive columns (PII, financial, health) where they are created; drive masks and access reviews from the tags.
