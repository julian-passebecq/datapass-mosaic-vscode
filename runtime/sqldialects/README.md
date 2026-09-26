# SQL dialects translated to DuckDB (sqldialects)

One translator for the whole Workbench. SQL written in **T-SQL**, **Snowflake**, **BigQuery**, **Spark SQL** or
**PostgreSQL** is translated to DuckDB with [sqlglot](https://github.com/tobymao/sqlglot) and really runs on the local
DuckDB catalog. Every result is labelled **"<dialect> dialect translated to DuckDB, not <engine>"** (for example
"T-SQL dialect translated to DuckDB, not SQL Server"). Nothing connects to SQL Server, Snowflake, BigQuery, Spark,
Databricks or PostgreSQL, and no account is needed.

Callers:

| Caller | Mode | Types from |
| --- | --- | --- |
| Mosaic, **Run active SQL** on a `.sql` file whose first line is `-- dialect: <name>` | `script` | the catalog (`information_schema`) |
| Mosaic, **Explain active SQL** (EXPLAIN ANALYZE of the translation) | `query` | the catalog |
| Practice, languages `snowflake`, `tsql`, `bigquery`, `sparksql` (dialect `spark`) | `query` | the exercise's fixture tables |
| Cloud Lab SQL pool (`runtime/sqlpoollab`): every T-SQL query, DML statement and expression | `statement` | the pool's tables |

## Truth model

| Part | What happens |
| --- | --- |
| Parsing | sqlglot's reader for the dialect (`tsql`, `snowflake`, `bigquery`, `databricks` for Spark SQL, `postgres`). SQL that does not parse is refused with the parser's message. |
| Subset check | Every syntax node and every function must be on the dialect's allowlist (`<dialect>.py`). Anything else is refused **by name**, for example `PATINDEX is not in the supported T-SQL subset; it is refused rather than approximated`. |
| Types | Where a dialect's result depends on a type (integer division, CAST to an integer, T-SQL `AVG` of integers), the translator annotates the query with the caller's schema. When a type stays unknown, the construct is refused and the message says how to make it explicit. |
| Rewrites | The constructs whose plain DuckDB translation would change the engine's result are rewritten (tables below). Each rewrite is reported with the translation. |
| Execution | The DuckDB SQL goes through the catalog's own validation (no file or network access, the same statement contract as DuckDB SQL) and really runs. |

The rule of thumb: **where DuckDB would silently return a different value, the construct is rewritten or refused.**
Where DuckDB raises an error and the engine would return a value, the difference is listed under "Known differences".

The translation is pinned to the sqlglot version range in `runtime/pyproject.toml`. `scripts/runtime_smoke.py` checks
the result of every rule below on DuckDB, and each expected value is the engine's documented result, so a sqlglot
upgrade that changes a translation fails CI.

## Modes

- `query`: exactly one `SELECT` / `WITH` query.
- `script`: 1 to 20 statements: queries, `CREATE [OR REPLACE] TABLE|VIEW name AS query`, `INSERT INTO name [(columns)]
  query|VALUES`, `DROP TABLE|VIEW [IF EXISTS]`. Column definitions, table options, `UPDATE`, `DELETE` and `MERGE` are
  refused (write them in DuckDB SQL).
- `statement`: one `SELECT`, `INSERT`, `UPDATE`, `DELETE` or `MERGE` (the SQL pool splits its own batches).

Shared by every dialect: the clock and random values (`GETDATE`, `CURRENT_DATE`, `NOW`, `RAND`, `NEWID`, `UUID`...)
are refused so a result can be reproduced and graded; table functions that read files or the network are refused;
division and modulo by zero raise an error, as in every one of these engines (DuckDB returns NULL); NULL ordering
follows the engine (sqlglot writes explicit `NULLS FIRST` / `NULLS LAST`).

## T-SQL

SQL Server, Azure SQL, Synapse dedicated SQL pool, Fabric Warehouse. Assumed settings: `DATEFIRST 7` (us_english),
`CONCAT_NULL_YIELDS_NULL ON`, `ANSI_NULLS ON`.

Accepted: queries with `TOP n` (also in subqueries), `OFFSET ... FETCH`, `[bracketed]` and `"quoted"` names,
`N'...'` strings, joins, `EXISTS`, `IN`, windows; `COUNT`, `COUNT_BIG`, `SUM`, `AVG`, `MIN`, `MAX`, `STDEV`, `STDEVP`,
`VAR`, `VARP`, `STRING_AGG ... WITHIN GROUP`; `ROW_NUMBER`, `RANK`, `DENSE_RANK`, `NTILE`, `LAG`, `LEAD`,
`FIRST_VALUE`, `LAST_VALUE`, `PERCENT_RANK`, `CUME_DIST`; `IIF`, `CASE`, `ISNULL`, `COALESCE`, `NULLIF`, `GREATEST`,
`LEAST`; `UPPER`, `LOWER`, `LEN`, `LTRIM`, `RTRIM`, `TRIM`, `LEFT`, `RIGHT`, `SUBSTRING`, `CHARINDEX`, `REPLACE`,
`REPLICATE`, `REVERSE`, `STUFF`, `CONCAT`, `CONCAT_WS`, `SPACE`, `ASCII`, `CHAR`, `UNICODE`; `DATEADD`, `DATEDIFF`,
`DATEPART`, `DATENAME` (month, weekday), `YEAR`, `MONTH`, `DAY`, `EOMONTH`, `DATEFROMPARTS`, `DATETRUNC`; `ABS`,
`ROUND(x, n)`, `CEILING`, `FLOOR`, `SQRT`, `POWER`, `SQUARE`, `LOG`, `LOG10`, `EXP`, `SIGN`, `PI`; `CAST`,
`TRY_CAST`, `CONVERT`, `TRY_CONVERT`. `OPTION (...)` query hints and `WITH (NOLOCK)` table hints are ignored (noted).

| T-SQL behavior | How the DuckDB SQL keeps it |
| --- | --- |
| `int / int` is an integer division that truncates (`7 / 2 = 3`, `-7 / 2 = -3`) | `//` when both types are integers; refused when a type is unknown |
| `AVG` of integers is an integer (truncated) | `CAST(TRUNC(AVG(x)) AS BIGINT)`, also over a window |
| `+` between strings concatenates; NULL makes the result NULL | `||` when both sides are strings |
| `CAST` of a decimal or float to an integer truncates | `TRUNC` first |
| `CAST('2.5' AS INT)` is an error, `TRY_CAST` gives NULL | a whole-number check on the text (DuckDB rounds to 3) |
| `CAST` to `VARCHAR(n)` keeps n characters, `CHAR(n)` pads, no length means 30; a number that does not fit gives `*` (int) or an overflow error (decimal) | `LEFT`, `RPAD`, `CASE` |
| `LEN` ignores trailing spaces | `LENGTH(RTRIM(...))` |
| `DATEADD` of a `DATE` stays a `DATE`; a date string is read as `DATETIME` | a cast back to `DATE`; `CAST(... AS TIMESTAMP)` |
| `DATEDIFF` counts boundaries; `week` boundaries are Sundays | `date_diff` on timestamps; Sunday-shifted weeks |
| `DATEPART(weekday, d)` is 1 for Sunday | `dayofweek + 1` |
| `POWER` returns the type of its first argument (`POWER(2, 0.5) = 1`) | `CAST(TRUNC(POWER(...)) AS BIGINT)` for integers |
| `SUBSTRING` with a start below 1 counts the missing positions against the length | a `CASE` (DuckDB reads a negative start from the end) |
| `DECIMAL` without a precision is `DECIMAL(18, 0)`, `FLOAT` is 8 bytes, `TINYINT` is 0-255, `BIT` is `BOOLEAN`-like | explicit DuckDB types |
| `CONVERT(VARCHAR, date, style)` for styles 23, 101, 103, 104, 112, 120, 121 (and the reverse, text to date) | `strftime` / `strptime` with the style's format |

Refused (examples): variables `@x` outside the SQL pool, `@@ROWCOUNT`, temporary tables `#t`, `SELECT ... INTO`,
`TOP ... PERCENT` and `WITH TIES`, `CROSS/OUTER APPLY`, `PIVOT`, `FORMAT` (.NET patterns), `DATEPART(week)`
(depends on DATEFIRST: use `iso_week`), `CHOOSE`, `PATINDEX`, `LIKE '[a-c]%'` character classes, `ROUND` with a third
argument or without a length, date arithmetic with `+` (use `DATEADD`), `CAST` of a `DATETIME`, a float or a `BIT` to
text (T-SQL formats them differently: use `CONVERT` with a style or `CASE`), `DATETIMEOFFSET`, binary types.

Known differences: **collation**: SQL Server's default collation compares strings case-insensitively and ignores
trailing spaces (`'ann' = 'Ann '`); here comparisons, `GROUP BY`, `DISTINCT`, `LIKE`, `REPLACE` and `CHARINDEX` are
case-sensitive. Decimal results keep DuckDB's precision and scale (`1.0 / 3`), `SUM` of `int` does not overflow at
2^31, `DATETIME` has no 3.33 ms rounding, `REAL` is computed as `DOUBLE`, and date strings must be ISO (`2024-01-31`).

## Snowflake

Practice language `snowflake`. The subset of PR #19, unchanged.

Accepted: one query with `SELECT`, `WITH`, `UNION [ALL]`, `EXCEPT`/`MINUS`, `INTERSECT`, subqueries, `EXISTS`, `IN`,
`BETWEEN`, `LIKE`, `ILIKE`, `LIKE ANY`, `IS [NOT] DISTINCT FROM`, joins (`INNER`, `LEFT`, `RIGHT`, `FULL`, `CROSS`,
`NATURAL`, `USING`), `GROUP BY` (also `GROUP BY ALL`), `HAVING`, `QUALIFY`, `ORDER BY`, `LIMIT`/`OFFSET`, `TOP n`,
`DISTINCT`, windows; strings `'...'`, `$$...$$`, backslash escapes. Aggregates `COUNT` (`*`, one column, `DISTINCT`
of one column), `COUNT_IF`, `SUM`, `AVG`, `MIN`, `MAX`, `MEDIAN`, `VARIANCE`/`VAR_SAMP`, `VAR_POP`,
`STDDEV`/`STDDEV_SAMP`, `STDDEV_POP`, `LISTAGG ... WITHIN GROUP`; windows `ROW_NUMBER`, `RANK`, `DENSE_RANK`,
`NTILE`, `LAG`, `LEAD`, `FIRST_VALUE`, `LAST_VALUE`; `CASE`, `IFF`, `COALESCE`, `NVL`, `IFNULL`, `NVL2`, `NULLIF`,
`ZEROIFNULL`, `NULLIFZERO`, `DECODE`, `EQUAL_NULL`, `DIV0`, `GREATEST`, `LEAST`; `UPPER`, `LOWER`, `LENGTH`/`LEN`,
`TRIM`, `LTRIM`, `RTRIM`, `SUBSTR`/`SUBSTRING`, `LEFT`, `RIGHT`, `CONCAT`, `||`, `CONCAT_WS`, `REPLACE`, `SPLIT_PART`,
`CHARINDEX`, `POSITION`, `LPAD`, `RPAD`, `REVERSE`, `CONTAINS`, `STARTSWITH`, `ENDSWITH`,
`REGEXP_REPLACE(subject, pattern[, replacement])`, `REGEXP_LIKE(subject, pattern)` / `RLIKE`,
`REGEXP_SUBSTR(subject, pattern)`; `TO_DATE` / `TRY_TO_DATE`, `TO_CHAR`/`TO_VARCHAR` of a date with a format,
`DATEDIFF`/`TIMESTAMPDIFF`, `DATEADD`, `DATE_TRUNC`/`TRUNC(date, part)`, `YEAR`, `QUARTER`, `MONTH`, `DAY`,
`DAYOFWEEK`, `DAYOFWEEKISO`, `DATE_PART`/`EXTRACT`, `LAST_DAY` (formats made of `YYYY`, `YY`, `MM`, `MON`, `MMMM`,
`DD`, `DY`, `HH24`, `MI`, `SS` and separators); `+ - * /`, `%`/`MOD` by a non-zero literal, `ABS`, `ROUND`, `CEIL`,
`FLOOR`, `TRUNC(number[, scale])`, `SQRT`, `POWER`, `LN`, `EXP`, `SIGN`; `CAST`, `TRY_CAST`, `::` to numbers, text,
`BOOLEAN`, `DATE`, `TIMESTAMP`/`TIMESTAMP_NTZ`/`DATETIME`.

| Snowflake behavior | How the DuckDB SQL keeps it |
| --- | --- |
| `REGEXP_REPLACE` replaces every match | the `'g'` flag |
| `REGEXP_LIKE` and `RLIKE` match the whole string | `regexp_full_match` |
| `REGEXP_SUBSTR` returns NULL when nothing matches | `CASE WHEN regexp_matches(...) THEN regexp_extract(...) END` |
| `CONCAT`, `CONCAT_WS`, `GREATEST` and `LEAST` return NULL when an argument is NULL | `||` and explicit NULL checks |
| NULLs sort as the largest value | explicit `NULLS FIRST` on descending keys |
| `FIRST_VALUE`/`LAST_VALUE` default to the whole partition | an explicit frame |
| Division by zero raises an error | the divisor is checked |
| `DATEADD` and `DATE_TRUNC` of a DATE return a DATE | a cast back to DATE; the argument's type must be explicit (`TO_DATE(col)`, `col::DATE`), otherwise refused |
| `DATEDIFF(week, ...)` counts Monday week boundaries | `date_trunc('week', ...)` on both sides |
| `SPLIT_PART` accepts 0 and negative parts; `SUBSTR` accepts position 0 | `CASE` guards |
| Unquoted identifiers are case-insensitive | folded to lower case, so result columns read like the other engines |

Refused (examples): statements other than one query, semi-structured data (`VARIANT`, `col:field`, `FLATTEN`,
`LATERAL`, `ARRAY_*`, `OBJECT_*`, `PARSE_JSON`), `HASH`, `REGEXP_INSTR`, `REGEXP_COUNT`, regex parameters and
occurrence arguments, `COUNT(DISTINCT a, b)`, `ASOF` joins, `SAMPLE`, `CONNECT BY`, `MATCH_RECOGNIZE`, `PIVOT`, time
travel, `$1`, bind and session variables, `INTERVAL` literals, `TIMESTAMP_TZ`/`TIMESTAMP_LTZ`, week numbers, `MOD` by a
column.

Known differences: Snowflake computes with fixed-point `NUMBER` (`1/3` is `0.333333`); `/` returns a DOUBLE here.
Implicit conversions follow DuckDB (`DATEDIFF` of two VARCHAR columns fails: cast them). Quoted identifiers resolve
case-insensitively. Unaliased expressions get DuckDB's column names. Regular expressions run on RE2. No collations.

## BigQuery

GoogleSQL. Accepted: queries with `QUALIFY`, `SELECT * EXCEPT (...)`, backticked names, `dataset.table` (the
catalog's layers); `COUNT`, `COUNTIF`, `SUM`, `AVG`, `MIN`, `MAX`, `STDDEV`, `STDDEV_POP`, `VARIANCE`, `VAR_POP`,
`STRING_AGG(x, sep [ORDER BY ...])`, `LOGICAL_AND`, `LOGICAL_OR`; the window functions of T-SQL; `IF`, `CASE`,
`IFNULL`, `COALESCE`, `NULLIF`, `GREATEST`, `LEAST`; `UPPER`, `LOWER`, `LENGTH`, `TRIM`, `LEFT`, `RIGHT`,
`SUBSTR`, `STRPOS`, `INSTR`, `REPLACE`, `REPEAT`, `REVERSE`, `CONCAT`, `||`, `LPAD`, `RPAD`, `STARTS_WITH`,
`ENDS_WITH`, `REGEXP_CONTAINS`, `REGEXP_EXTRACT`, `REGEXP_REPLACE`; `DATE_ADD`, `DATE_SUB`, `DATE_DIFF`,
`DATE_TRUNC`, `EXTRACT`, `FORMAT_DATE`, `PARSE_DATE`, `DATE(y, m, d)`, `DATE(ts)`, `LAST_DAY`; `ABS`, `ROUND`, `CEIL`,
`FLOOR`, `TRUNC`, `SQRT`, `POW`, `LN`, `LOG10`, `EXP`, `SIGN`, `DIV`, `MOD`, `SAFE_DIVIDE`; `CAST`, `SAFE_CAST` to
`INT64`, `NUMERIC`, `FLOAT64`, `STRING`, `BOOL`, `DATE`, `DATETIME`, `TIMESTAMP`.

| BigQuery behavior | How the DuckDB SQL keeps it |
| --- | --- |
| `CONCAT`, `GREATEST`, `LEAST` return NULL when an argument is NULL | `||`, explicit NULL checks |
| NULLs sort first ascending | explicit `NULLS FIRST` |
| `DATE_ADD`, `DATE_SUB`, `DATE_TRUNC` of a DATE return a DATE; `WEEK` starts on Sunday | casts back to DATE; Sunday truncation |
| `DATE_DIFF(..., WEEK)` counts Sunday boundaries | Sunday-shifted weeks |
| `EXTRACT(DAYOFWEEK ...)` is 1 for Sunday | `dayofweek + 1` |
| `REGEXP_EXTRACT` returns NULL when nothing matches, and the capturing group when the pattern has one | `CASE WHEN regexp_matches(...) THEN regexp_extract(..., group) END` |
| `SUBSTR` position 0 is position 1 | position 1 |
| `CAST` of a FLOAT64 to `INT64` rounds half away from zero; `CAST('2.5' AS INT64)` is an error | `ROUND` first; a whole-number check |
| `NUMERIC` is `DECIMAL(38, 9)` | explicit type (DuckDB's `DECIMAL` is `(18, 3)`) |

Refused (examples): arrays, `UNNEST`, `ARRAY_AGG`, `STRUCT`, `SPLIT`, JSON functions, `project.dataset.table`,
`BIGNUMERIC`, `APPROX_*`, `TIMESTAMP_*` and `DATETIME_*` functions, `WEEK` numbers in `EXTRACT` (use `ISOWEEK`),
`REGEXP_EXTRACT` with several groups, positions or occurrences, format elements other than `%Y %y %m %d %b %B %a %A
%H %M %S %j`, `CURRENT_DATE`, `RAND`, `GENERATE_UUID`.

Known differences: decimal literals such as `0.1` are exact DECIMALs here and FLOAT64 in BigQuery (`0.1 + 0.2`);
`TIMESTAMP` values have no time zone (read as UTC); integer overflow errors match, but DuckDB's messages differ.

## Spark SQL

ANSI mode, the default of Apache Spark 4 and Databricks SQL (read with sqlglot's Databricks dialect): `CAST` raises on
bad input, division by zero raises. Accepted: queries with `QUALIFY` (Databricks), backticked names, `LIMIT`;
`COUNT`, `COUNT_IF`, `SUM`, `AVG`, `MIN`, `MAX`, `STDDEV`, `STDDEV_POP`, `VARIANCE`, `VAR_POP`, `MEDIAN`, `BOOL_AND`,
`BOOL_OR`; window functions; `IF`, `CASE`, `NVL`, `IFNULL`, `NVL2`, `COALESCE`, `NULLIF`, `GREATEST`, `LEAST`;
`UPPER`, `LOWER`, `LENGTH`, `TRIM`, `LEFT`, `RIGHT`, `SUBSTRING`/`SUBSTR`, `INSTR`, `LOCATE`, `REPLACE`, `REPEAT`,
`REVERSE`, `CONCAT`, `CONCAT_WS`, `LPAD`, `RPAD`, `STARTSWITH`, `ENDSWITH`, `SPLIT_PART`, `REGEXP_EXTRACT`,
`REGEXP_REPLACE`, `RLIKE`/`REGEXP_LIKE`; `DATE_ADD`, `DATE_SUB`, `ADD_MONTHS`, `DATEDIFF`, `DATE_TRUNC`,
`TRUNC(date, fmt)`, `YEAR`, `QUARTER`, `MONTH`, `DAY`, `DAYOFWEEK`, `DAYOFYEAR`, `EXTRACT`, `LAST_DAY`, `DATE_FORMAT`,
`TO_DATE`; `ABS`, `ROUND`, `CEIL`, `FLOOR`, `SQRT`, `POW`, `LN`, `LOG10`, `EXP`, `SIGN`, `DIV`, `%`/`MOD`; `CAST`,
`TRY_CAST`.

| Spark behavior | How the DuckDB SQL keeps it |
| --- | --- |
| `CONCAT` returns NULL when an argument is NULL | `||` |
| NULLs sort first ascending | explicit `NULLS FIRST` |
| `DATE_ADD`, `DATE_SUB`, `ADD_MONTHS`, `TRUNC(date, ...)` return a DATE | casts back to DATE |
| `DAYOFWEEK` is 1 for Sunday | `dayofweek + 1` |
| `CAST` of a decimal or double to an integer truncates; a malformed string is an error (ANSI) | `TRUNC` first; a whole-number check |
| `DECIMAL` without a precision is `DECIMAL(10, 0)` | explicit type |
| `SUBSTRING` position 0 is position 1 | position 1 |
| Division and `%` by zero raise `[DIVIDE_BY_ZERO]` | the divisor is checked |

Refused (examples): arrays, maps and structs (`EXPLODE`, `COLLECT_LIST`, `SPLIT`), `LATERAL VIEW`, `MONTHS_BETWEEN`,
`FIRST`/`LAST` (non-deterministic), `BROUND`, date patterns other than `yyyy yy MM MMM MMMM dd HH mm ss E EEEE`,
`CURRENT_DATE`, `NOW`, `RAND`, `UUID`, `TABLESAMPLE`.

Known differences: `TIMESTAMP` values have no session time zone (UTC); `VARCHAR(n)` lengths are not enforced;
decimal division keeps DuckDB's precision.

## PostgreSQL

Accepted: queries with `DISTINCT ON`, `FILTER (WHERE ...)`, `LIMIT`/`OFFSET`/`FETCH`, `ILIKE`, `~`, `~*`,
`IS [NOT] DISTINCT FROM`, `::` casts, `INTERVAL '1 month'` (one unit); `COUNT`, `SUM`, `AVG`, `MIN`, `MAX`,
`STDDEV`, `STDDEV_SAMP`, `STDDEV_POP`, `VARIANCE`, `VAR_POP`, `STRING_AGG(x, sep [ORDER BY ...])`, `BOOL_AND`,
`BOOL_OR`, `PERCENTILE_CONT ... WITHIN GROUP`; window functions; `CASE`, `COALESCE`, `NULLIF`, `GREATEST`, `LEAST`;
`UPPER`, `LOWER`, `LENGTH`, `CHAR_LENGTH`, `TRIM`, `BTRIM`, `LTRIM`, `RTRIM`, `LEFT`, `RIGHT`, `SUBSTRING`,
`POSITION`, `STRPOS`, `REPLACE`, `REPEAT`, `REVERSE`, `CONCAT`, `CONCAT_WS`, `LPAD`, `RPAD`, `SPLIT_PART`,
`REGEXP_REPLACE` (flag `g`), `STARTS_WITH`; `TO_CHAR`, `TO_DATE`, `DATE_TRUNC`, `EXTRACT`/`DATE_PART`; `ABS`, `ROUND`,
`CEIL`, `FLOOR`, `TRUNC`, `SQRT`, `POWER`, `LN`, `LOG`, `EXP`, `SIGN`, `MOD`, `DIV`; `CAST` to `INT`, `BIGINT`,
`SMALLINT`, `NUMERIC(p, s)`, `REAL`, `DOUBLE PRECISION`, `TEXT`, `VARCHAR(n)`, `BOOLEAN`, `DATE`, `TIMESTAMP`.

| PostgreSQL behavior | How the DuckDB SQL keeps it |
| --- | --- |
| `int / int` is an integer division that truncates | `//` when both types are integers; refused when a type is unknown |
| Unquoted identifiers fold to lower case | lower case, so `SELECT Name AS FullName` returns `fullname` |
| NULLs sort last ascending, first descending | explicit `NULLS FIRST` on descending keys |
| `ROUND` of a `double precision` rounds half to even; `round(double precision, n)` does not exist | `ROUND_EVEN(x, 0)`; refused |
| `SUBSTRING` with a start below 1 counts the missing positions | a `CASE` |
| `CAST('2.5' AS INT)` is an error | a whole-number check |
| `VARCHAR(n)` keeps n characters | `LEFT` |
| `NUMERIC` without a precision keeps its digits | `DECIMAL(38, 10)` |

Refused (examples): arrays, `UNNEST`, `GENERATE_SERIES`, JSON operators, `AGE`, timestamp subtraction (an INTERVAL),
`TIMESTAMPTZ`, `CHAR(n)`, `EXTRACT(EPOCH|SECOND ...)`, `SUBSTRING(text FROM pattern)`, regex flags other than `g`,
`TO_CHAR` elements other than `YYYY YY MM DD HH24 MI SS`, `NOW`, `CURRENT_DATE`, `RANDOM`.

Known differences: `NUMERIC` division keeps DuckDB's precision (`1 / 3::numeric`); quoted identifiers resolve
case-insensitively; collations are not supported.

## Files

- `core.py`: parsing, statement shapes, schema annotation (a qualified copy; types map back by node id), the
  allowlist check, the post-order rewrite and DuckDB generation. `translate_with` and `translate_expression_with`.
- `rules.py`: rules shared by several dialects (CAST semantics, zero guards, SQL-standard `SUBSTRING`, Sunday weeks).
- `tsql.py`, `snowflake.py`, `bigquery.py`, `spark.py`, `postgres.py`: one dialect each.
- `__init__.py`: `translate(source, dialect, mode=, schema=, hooks=)`, `translate_expression`, `dialects()`.
- Callers: `datapass_runtime/sql_dialects.py` (Mosaic run and explain, Practice), `sqlpoollab/tsql.py` (the SQL pool).
