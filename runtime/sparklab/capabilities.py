"""One support table for the API and notebook help. No submitted Python executes."""
SUPPORT = {
    'schema_version': 1,
    'execution': 'Lazy SQL plans; Run materializes the last DataFrame as a bounded notebook preview action.',
    'supported': [
        {'operation': 'spark.table', 'scope': 'Shared catalog tables, or server-owned exercise input'},
        {'operation': 'select / withColumn / drop / withColumnRenamed / alias', 'scope': 'Known schemas; alias is a label, qualified columns are unsupported'},
        {'operation': 'filter / where', 'scope': 'Column expressions with &, |, ~; no SQL strings'},
        {'operation': 'join', 'scope': 'Same-name single/multiple keys; inner, left, right, full, semi, anti. Duplicate non-key columns must be renamed.'},
        {'operation': 'groupBy.agg', 'scope': 'sum, avg, min, max, count, countDistinct; alias aggregate outputs'},
        {'operation': 'orderBy / sort / limit / distinct / dropDuplicates', 'scope': 'Ascending NULLS FIRST, descending NULLS LAST; subset dedupe survivor is unspecified'},
        {'operation': 'col / lit / coalesce / when.otherwise', 'scope': 'Scalar expressions, null predicates, eqNullSafe, bounded casts and aliases'},
        {'operation': 'Window', 'scope': 'partitionBy/orderBy, ROWS frames, row_number/lag/lead and aggregates; tied ordering is unspecified'},
        {'operation': 'repartition / coalesce / broadcast', 'scope': 'Teaching plan hints only; they never change result rows'},
    ],
    'unsupported': ['selectExpr and SQL-string filters (use Column expressions)',
                    'Python and/or on Columns (use parenthesized &/|)',
                    'UDFs, loops, arbitrary Python, streaming, filesystem reads',
                    'Predicate/qualified-column joins and ambiguous duplicate column names',
                    'collect/show/count actions inside Python; use Run preview or groupBy().agg(F.count("*"))',
                    'Full PySpark type/ANSI/decimal parity and vendor runtime parity'],
}
