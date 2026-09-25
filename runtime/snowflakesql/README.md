# Snowflake SQL dialect (snowflakesql)

Practice exercises in the `snowflake` language take a query written in Snowflake SQL. Datapass translates it to
DuckDB with [sqlglot](https://github.com/tobymao/sqlglot) (`read="snowflake"`, `write="duckdb"`) and runs the result
on the local DuckDB catalog. The label everywhere is **Snowflake SQL dialect translated to DuckDB, not Snowflake**:
nothing connects to Snowflake, and no Snowflake account is needed.

## Truth model

| Part | What happens |
| --- | --- |
| Parsing | sqlglot's Snowflake dialect. A query that does not parse is refused with the parser's message. |
| Subset check | Every function and every syntax node must be on an allowlist (`translate.py`). Anything else is refused **by name**, for example `REGEXP_INSTR is not in the supported Snowflake subset; it is refused rather than approximated`. |
| Rewrites | The few constructs whose plain DuckDB translation would change Snowflake's result are rewritten (listed below), or refused when the rewrite would need information the query does not give. |
| Execution | The DuckDB SQL really runs on the local catalog. In Practice, the exercise tables are bound as typed CTEs, as for the `sql` language. |

The translation is pinned to the sqlglot version range in `runtime/pyproject.toml`. `scripts/runtime_smoke.py`
checks the result of every rule below on DuckDB, so a sqlglot upgrade that changes a translation fails CI.

## Accepted

- **One query**: `SELECT`, `WITH`, `UNION [ALL]`, `EXCEPT`/`MINUS`, `INTERSECT`, subqueries, `EXISTS`, `IN`,
  `BETWEEN`, `LIKE`, `ILIKE`, `LIKE ANY`, `IS [NOT] DISTINCT FROM`, joins (`INNER`, `LEFT`, `RIGHT`, `FULL`,
  `CROSS`, `NATURAL`, `USING`), `GROUP BY` (also `GROUP BY ALL`), `HAVING`, `QUALIFY`, `ORDER BY`, `LIMIT`/`OFFSET`,
  `TOP n`, `DISTINCT`, windows with `PARTITION BY`, `ORDER BY` and `ROWS`/`RANGE` frames. Strings: `'...'`,
  `$$...$$`, backslash escapes.
- **Aggregates**: `COUNT` (`*`, one column, `DISTINCT` of one column), `COUNT_IF`, `SUM`, `AVG`, `MIN`, `MAX`,
  `MEDIAN`, `VARIANCE`/`VAR_SAMP`, `VAR_POP`, `STDDEV`/`STDDEV_SAMP`, `STDDEV_POP`,
  `LISTAGG ... WITHIN GROUP (ORDER BY ...)`.
- **Window functions**: `ROW_NUMBER`, `RANK`, `DENSE_RANK`, `NTILE`, `LAG`, `LEAD`, `FIRST_VALUE`, `LAST_VALUE`, and
  the aggregates above with `OVER`.
- **Conditional**: `CASE`, `IFF`, `COALESCE`, `NVL`, `IFNULL`, `NVL2`, `NULLIF`, `ZEROIFNULL`, `NULLIFZERO`,
  `DECODE`, `EQUAL_NULL`, `DIV0`, `GREATEST`, `LEAST`.
- **Strings**: `UPPER`, `LOWER`, `LENGTH`/`LEN`, `TRIM`, `LTRIM`, `RTRIM`, `SUBSTR`/`SUBSTRING`, `LEFT`, `RIGHT`,
  `CONCAT`, `||`, `CONCAT_WS`, `REPLACE`, `SPLIT_PART`, `CHARINDEX`, `POSITION`, `LPAD`, `RPAD`, `REVERSE`,
  `CONTAINS`, `STARTSWITH`, `ENDSWITH`, `REGEXP_REPLACE(subject, pattern[, replacement])`,
  `REGEXP_LIKE(subject, pattern)` / `RLIKE`, `REGEXP_SUBSTR(subject, pattern)`.
- **Dates**: `TO_DATE` / `TRY_TO_DATE` (no format: ISO dates; with a format), `TO_CHAR`/`TO_VARCHAR` of a date or
  timestamp with a format, `DATEDIFF`/`TIMESTAMPDIFF` (year, quarter, month, week, day, hour, minute, second),
  `DATEADD` and `DATE_TRUNC`/`TRUNC(date, part)` (year, quarter, month, week, day), `YEAR`, `QUARTER`, `MONTH`,
  `DAY`, `DAYOFWEEK`, `DAYOFWEEKISO`, `DATE_PART`/`EXTRACT` (year, quarter, month, day, dayofweek, dayofweekiso,
  hour, minute, second), `LAST_DAY`. Formats are literals made of `YYYY`, `YY`, `MM`, `MON`, `MMMM`, `DD`, `DY`,
  `HH24`, `MI`, `SS` and separators.
- **Numbers**: `+ - * /`, `%`/`MOD` by a non-zero number literal, `ABS`, `ROUND`, `CEIL`, `FLOOR`,
  `TRUNC(number[, scale])`, `SQRT`, `POWER`, `LN`, `EXP`, `SIGN`.
- **Casts**: `CAST`, `TRY_CAST`, `::` to `NUMBER`/`DECIMAL`/`INT`/`BIGINT`/`SMALLINT`, `FLOAT`/`DOUBLE`,
  `VARCHAR`/`STRING`/`TEXT`/`CHAR`, `BOOLEAN`, `DATE`, `TIMESTAMP`/`TIMESTAMP_NTZ`/`DATETIME`.

## Rules that keep Snowflake's result

Most of these come from sqlglot; the checks in `runtime_smoke.py` pin them.

| Snowflake behavior | How the DuckDB SQL keeps it |
| --- | --- |
| `REGEXP_REPLACE` replaces every match | the `'g'` flag |
| `REGEXP_LIKE` and `RLIKE` match the whole string | `regexp_full_match` |
| `REGEXP_SUBSTR` returns NULL when nothing matches | `CASE WHEN regexp_matches(...) THEN regexp_extract(...) END` (Datapass rewrite; DuckDB alone returns `''`) |
| `CONCAT`, `CONCAT_WS`, `GREATEST` and `LEAST` return NULL when an argument is NULL | `||`, and explicit NULL checks (DuckDB's versions skip NULLs) |
| NULLs sort as the largest value: last with `ASC`, first with `DESC` | explicit `NULLS FIRST` on descending keys |
| `FIRST_VALUE`/`LAST_VALUE` default to the whole partition | explicit `ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING` |
| Aggregates with `ORDER BY` default to `RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW` | same default in DuckDB |
| Division by zero raises an error | the divisor is checked and `error('Division by zero')` raised (Datapass rewrite; DuckDB returns NULL or infinity) |
| `DATEADD` and `DATE_TRUNC` of a DATE return a DATE | a cast back to DATE (Datapass rewrite; DuckDB returns a TIMESTAMP). The argument's type must be explicit in the query (`TO_DATE(col)`, `col::DATE`, `col::TIMESTAMP`, or another `DATEADD`/`DATE_TRUNC`/`LAST_DAY` of one); otherwise the query is refused. |
| `DATEDIFF(week, ...)` counts Monday week boundaries (default `WEEK_START`) | `date_trunc('week', ...)` on both sides |
| `DAYOFWEEK` is 0 (Sunday) to 6 (default `WEEK_START`) | the same in DuckDB |
| `SPLIT_PART` accepts 0 and negative parts; `SUBSTR` accepts position 0 | explicit `CASE` guards |
| `DATEADD(month, 1, '2024-01-31')` clamps to the last day of the month | the same in DuckDB |
| Unquoted identifiers are case-insensitive | unquoted identifiers are folded to lower case (Snowflake folds them to upper case), so result columns read like the other Datapass engines; quoted identifiers keep their case |

## Refused (examples)

- statements other than one query (`CREATE`, `INSERT`, `MERGE`, `DELETE`, several statements);
- semi-structured data (`VARIANT`, `col:field`, `FLATTEN`, `LATERAL`, `ARRAY_*`, `OBJECT_*`, `PARSE_JSON`);
- time-dependent or random functions (`CURRENT_DATE`, `CURRENT_TIMESTAMP`, `SYSDATE`, `RANDOM`, `UUID_STRING`),
  and `HASH` (different hash functions);
- `REGEXP_INSTR`, `REGEXP_COUNT`, regex parameters (`'i'`, `'e'`), position and occurrence arguments;
- `COUNT(DISTINCT a, b)`, `ASOF` joins, `SAMPLE`, `CONNECT BY`, `MATCH_RECOGNIZE`, `PIVOT`/`UNPIVOT`, time travel,
  `$1` references, bind variables, session variables, `INTERVAL` literals;
- `TIMESTAMP_TZ`/`TIMESTAMP_LTZ` and time-zone functions, week numbers (`WEEK`, `WEEKOFYEAR`);
- `DATEADD`/`DATE_TRUNC` of an expression whose type is not explicit, `TO_CHAR` without a date argument or with other
  format elements, `MOD` by a column;
- any other function not listed under "Accepted".

## Known differences

These are documented rather than hidden. Exercises avoid depending on them.

- **Numeric types.** Snowflake computes with fixed-point `NUMBER`; the translated query follows DuckDB's types. `/`
  returns a DOUBLE (Snowflake returns a NUMBER whose scale is limited: `1/3` is `0.333333` in Snowflake). Casting a
  DOUBLE that ends in exactly .5 to an integer rounds half to even in DuckDB, half away from zero in Snowflake.
  Round results with `ROUND` when a lesson compares decimals.
- **Implicit conversions** follow DuckDB. `DATEDIFF` of two VARCHAR columns fails in DuckDB (Snowflake would cast
  them): cast them with `TO_DATE` or `::TIMESTAMP`.
- **Quoted identifiers** such as `"Name"` still resolve case-insensitively (DuckDB), where Snowflake matches them
  exactly.
- **Unaliased expressions** get DuckDB's generated column name; alias every computed column.
- **Regular expressions** run on RE2. Common POSIX and Perl classes (`[0-9]`, `\d`, `\w`, `[[:alpha:]]`) behave the
  same; backreferences inside a pattern are an RE2 error.
- **Collations** are not supported; string comparison is case-sensitive and byte-ordered, as Snowflake's default.

## Files

- `translate.py`: `translate(source) -> Translation(sql, rewrites)`, the allowlists (`FUNCTIONS`, `SYNTAX`, `TYPES`)
  and the rewrites. Raises `SnowflakeDialectError` (a `ValueError`) outside the subset.
- `datapass_runtime/execution.py` runs the `snowflake` kernel language through it; `datapass_runtime/exercises.py`
  grades `snowflake` exercises like `sql` ones, with truth `semantic-emulation`.
