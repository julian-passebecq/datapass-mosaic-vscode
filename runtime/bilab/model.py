"""Star model: which tables are facts and dimensions, their keys, and the relationships between them.

The model file (`bi/model.json`) is Datapass's own format, not a Power BI file. Its relationship settings use
Power BI's vocabulary (cardinality, cross-filter direction, active or inactive) because those are the
decisions a semantic model makes. Every check below is a real query on the catalog's tables:

- table_exists, columns_exist;
- dimensions: key_unique, key_not_null, unknown_member;
- facts and bridges: grain_unique;
- type 2 dimensions: scd2_valid_range, scd2_one_current, scd2_no_overlap, scd2_no_gap;
- relationships: one_side_unique, no_null_keys, no_orphans, fact_to_dimension, single_active_path,
  cross_filter, many_to_many.

Statuses are pass, fail (the model or the data is wrong) and warn (allowed, but usually a design smell).
"""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TABLE = r'^(source|bronze|silver|gold|warehouse|features|metrics)\.[a-z][a-z0-9_]{0,62}$'
IDENT = re.compile(r'^[a-z][a-z0-9_]{0,62}$')
COLUMN_REF = re.compile(r'^((?:source|bronze|silver|gold|warehouse|features|metrics)\.[a-z][a-z0-9_]{0,62})\.([a-z][a-z0-9_]{0,62})$')
CHECK_COLUMNS = ['check', 'subject', 'status', 'detail']
RELATIONSHIP_COLUMNS = ['relationship', 'cardinality', 'cross_filter', 'active', 'observed', 'from_rows',
                        'orphans', 'null_keys']


class ScdSpec(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: Literal[0, 1, 2, 3, 6]
    valid_from: str | None = None
    valid_to: str | None = None
    current_flag: str | None = None
    # How the current version ends: a far-future date (the usual 9999-12-31) or NULL.
    open_end: str | None = '9999-12-31'

    @model_validator(mode='after')
    def versioned(self) -> 'ScdSpec':
        if self.type in (2, 6) and not (self.valid_from and self.valid_to):
            raise ValueError('a type 2 (or 6) dimension names its valid_from and valid_to columns')
        for column in (self.valid_from, self.valid_to, self.current_flag):
            if column is not None and not IDENT.fullmatch(column):
                raise ValueError(f'{column!r} is not a simple lowercase column name')
        if self.open_end is not None and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', self.open_end):
            raise ValueError('open_end is a YYYY-MM-DD date or null')
        return self


class ModelTable(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(pattern=TABLE)
    role: Literal['fact', 'dimension', 'bridge']
    key: str | None = None
    business_key: list[str] = Field(default_factory=list, max_length=4)
    grain: list[str] = Field(default_factory=list, max_length=6)
    unknown_member: int | str | None = None
    scd: ScdSpec | None = None
    description: str = Field(default='', max_length=400)

    @model_validator(mode='after')
    def shaped(self) -> 'ModelTable':
        for column in [self.key, *self.business_key, *self.grain]:
            if column is not None and not IDENT.fullmatch(column):
                raise ValueError(f'{self.name}: {column!r} is not a simple lowercase column name')
        if self.role == 'dimension' and not self.key:
            raise ValueError(f'{self.name}: a dimension names its key')
        if self.role != 'dimension' and (self.scd or self.unknown_member is not None):
            raise ValueError(f'{self.name}: only dimensions have an SCD type or an unknown member')
        if self.scd and self.scd.type in (2, 6) and not self.business_key:
            raise ValueError(f'{self.name}: a type 2 dimension names its business_key (the key its versions share)')
        return self


class Relationship(BaseModel):
    model_config = ConfigDict(extra='forbid', populate_by_name=True)
    from_: str = Field(alias='from', pattern=COLUMN_REF.pattern)
    to: str = Field(pattern=COLUMN_REF.pattern)
    cardinality: Literal['many-to-one', 'one-to-one', 'one-to-many', 'many-to-many'] = 'many-to-one'
    cross_filter: Literal['single', 'both'] = 'single'
    active: bool = True

    @property
    def label(self) -> str:
        return f'{self.from_} -> {self.to}'

    def sides(self) -> tuple[tuple[str, str], tuple[str, str]]:
        a, b = COLUMN_REF.fullmatch(self.from_), COLUMN_REF.fullmatch(self.to)
        return (a.group(1), a.group(2)), (b.group(1), b.group(2))


class StarModel(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(default='model', max_length=80)
    description: str = Field(default='', max_length=1000)
    tables: list[ModelTable] = Field(default_factory=list, max_length=24)
    relationships: list[Relationship] = Field(default_factory=list, max_length=48)

    @model_validator(mode='after')
    def unique(self) -> 'StarModel':
        names = [t.name for t in self.tables]
        if len(names) != len(set(names)):
            raise ValueError('each table appears once in the model')
        return self

    def table(self, name: str) -> ModelTable | None:
        return next((t for t in self.tables if t.name == name), None)


class _Db:
    def __init__(self, catalog):
        self.catalog = catalog
        self.columns_cache: dict[str, list[str] | None] = {}

    def columns(self, table: str) -> list[str] | None:
        if table not in self.columns_cache:
            if not self.catalog.exists(table):
                self.columns_cache[table] = None
            else:
                cursor = self.catalog.db.execute(f'SELECT * FROM {table} LIMIT 0')
                self.columns_cache[table] = [d[0].lower() for d in cursor.description]
        return self.columns_cache[table]

    def one(self, sql: str) -> Any:
        return self.catalog.db.execute(sql).fetchone()

    def all(self, sql: str) -> list[tuple]:
        return self.catalog.db.execute(sql).fetchall()


def _q(column: str) -> str:
    return '"' + column + '"'


def _literal(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return 'NULL' if value is None else ('TRUE' if value else 'FALSE')
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def check_model(catalog, model: StarModel) -> dict[str, Any]:
    """Run every check on the catalog; returns {'checks': rows, 'relationships': rows}."""
    db = _Db(catalog)
    checks: list[dict[str, Any]] = []

    def add(check: str, subject: str, ok: bool | None, detail: str = '', warn: bool = False) -> None:
        status = 'pass' if ok else ('warn' if warn else 'fail')
        checks.append({'check': check, 'subject': subject, 'status': status, 'detail': detail})

    present: set[str] = set()
    for table in model.tables:
        columns = db.columns(table.name)
        add('table_exists', table.name, columns is not None, '' if columns is not None else 'The table is not in the catalog.')
        if columns is None:
            continue
        wanted = [c for c in [table.key, *table.business_key, *table.grain] if c]
        if table.scd:
            wanted += [c for c in (table.scd.valid_from, table.scd.valid_to, table.scd.current_flag) if c]
        missing = [c for c in dict.fromkeys(wanted) if c not in columns]
        add('columns_exist', table.name, not missing, f"Missing: {', '.join(missing)}" if missing else '')
        if missing:
            continue
        present.add(table.name)
        if table.role == 'dimension':
            _dimension_checks(db, table, add)
        if table.grain:
            key = ', '.join(_q(c) for c in table.grain)
            duplicates = db.one(f'SELECT COUNT(*) FROM (SELECT {key} FROM {table.name} GROUP BY {key} HAVING COUNT(*) > 1)')[0]
            add('grain_unique', table.name, duplicates == 0,
                f'{duplicates} grain value(s) ({", ".join(table.grain)}) appear on more than one row.' if duplicates else
                f'One row per {", ".join(table.grain)}.')

    relationships = []
    active_pairs: dict[frozenset, list[str]] = {}
    for relationship in model.relationships:
        (from_table, from_column), (to_table, to_column) = relationship.sides()
        subject = relationship.label
        from_columns, to_columns = db.columns(from_table), db.columns(to_table)
        missing = [ref for ref, cols, col in ((relationship.from_, from_columns, from_column),
                                               (relationship.to, to_columns, to_column)) if not cols or col not in cols]
        add('relationship_columns', subject, not missing, f"Not found: {', '.join(missing)}" if missing else '')
        if missing:
            continue
        stats = _relationship_stats(db, from_table, from_column, to_table, to_column)
        relationships.append({'relationship': subject, 'cardinality': relationship.cardinality,
                              'cross_filter': relationship.cross_filter, 'active': relationship.active,
                              'observed': stats['observed'], 'from_rows': stats['from_rows'],
                              'orphans': stats['orphans'], 'null_keys': stats['from_nulls']})
        ones = {'many-to-one': [('to', to_table, to_column, stats['to_unique'])],
                'one-to-one': [('from', from_table, from_column, stats['from_unique']),
                               ('to', to_table, to_column, stats['to_unique'])],
                'one-to-many': [('from', from_table, from_column, stats['from_unique'])],
                'many-to-many': []}[relationship.cardinality]
        bad = [f'{t}.{c}' for _, t, c, unique in ones if not unique]
        add('one_side_unique', subject, not bad,
            f"{', '.join(bad)} repeats values, so it cannot be the 'one' side (observed {stats['observed']})." if bad
            else f"Observed {stats['observed']}.")
        many_table, many_column = (to_table, to_column) if relationship.cardinality == 'one-to-many' else (from_table, from_column)
        nulls = stats['to_nulls'] if relationship.cardinality == 'one-to-many' else stats['from_nulls']
        add('no_null_keys', subject, nulls == 0,
            f'{nulls} row(s) of {many_table} have no {many_column}: point them to an unknown member instead.' if nulls else '')
        orphans = stats['orphans']
        add('no_orphans', subject, orphans == 0,
            f"{orphans} {from_table}.{from_column} value(s) have no match in {to_table}.{to_column}"
            + (f" (for example {stats['orphan_sample']})" if stats['orphan_sample'] is not None else '') + '.'
            if orphans else '')
        roles = (model.table(from_table), model.table(to_table))
        if roles[0] and roles[1]:
            fact_to_fact = roles[0].role == 'fact' and roles[1].role == 'fact'
            wrong_way = roles[0].role == 'dimension' and roles[1].role == 'fact' and relationship.cardinality == 'many-to-one'
            add('fact_to_dimension', subject, not (fact_to_fact or wrong_way),
                'Facts relate to each other through shared (conformed) dimensions, not directly.' if fact_to_fact else
                'A dimension is the one side: relate the fact (many) to the dimension (one).' if wrong_way else '',
                warn=fact_to_fact)
        if relationship.active:
            active_pairs.setdefault(frozenset((from_table, to_table)), []).append(subject)
        if relationship.cross_filter == 'both':
            bridge = any(model.table(t) and model.table(t).role == 'bridge' for t in (from_table, to_table))
            add('cross_filter', subject, bridge,
                'Both directions is meant for bridge tables; elsewhere it creates ambiguous filter paths.', warn=True)
        if relationship.cardinality == 'many-to-many':
            add('many_to_many', subject, False, 'Prefer a bridge table between the two tables.', warn=True)
    for pair, subjects in active_pairs.items():
        tables = sorted(pair)
        add('single_active_path', ' / '.join(tables), len(subjects) <= 1,
            f"{len(subjects)} active relationships between the same tables: keep one active, mark the others "
            f"inactive (role-playing), and use them explicitly." if len(subjects) > 1 else '')
    return {'checks': checks, 'relationships': relationships}


def _dimension_checks(db: _Db, table: ModelTable, add) -> None:
    key = _q(table.key)
    stats = db.one(f'SELECT COUNT(*), COUNT(DISTINCT {key}), COUNT(*) - COUNT({key}) FROM {table.name}')
    rows, distinct, nulls = stats
    add('key_unique', table.name, rows - nulls == distinct,
        f'{rows - nulls - distinct} duplicate {table.key} value(s).' if rows - nulls != distinct else f'{rows} rows, one per {table.key}.')
    add('key_not_null', table.name, nulls == 0, f'{nulls} row(s) without {table.key}.' if nulls else '')
    if table.unknown_member is not None:
        found = db.one(f'SELECT COUNT(*) FROM {table.name} WHERE {key} = {_literal(table.unknown_member)}')[0]
        add('unknown_member', table.name, found == 1,
            f'{table.key} = {table.unknown_member} is the unknown member: {found} row(s) found, 1 expected.' if found != 1 else '')
    scd = table.scd
    if not scd or scd.type not in (2, 6):
        return
    bk = ', '.join(_q(c) for c in table.business_key)
    exclude = f' WHERE {key} <> {_literal(table.unknown_member)}' if table.unknown_member is not None else ''
    versions = f'(SELECT * FROM {table.name}{exclude})'
    start, end = _q(scd.valid_from), _q(scd.valid_to)
    open_end = f"CAST({_literal(scd.open_end)} AS DATE)" if scd.open_end else None
    end_value = f'COALESCE({end}, DATE \'9999-12-31\')' if open_end is None else end
    bad_range = db.one(f'SELECT COUNT(*) FROM {versions} WHERE {start} IS NULL OR {start} >= {end_value}')[0]
    add('scd2_valid_range', table.name, bad_range == 0,
        f'{bad_range} version(s) where {scd.valid_from} is missing or not before {scd.valid_to}.' if bad_range else '')
    is_open = f'{end} IS NULL' if open_end is None else f'{end} = {open_end}'
    current = f'{_q(scd.current_flag)}' if scd.current_flag else is_open
    wrong_current = db.one(
        f'SELECT COUNT(*) FROM (SELECT {bk}, COUNT(*) FILTER (WHERE {current}) AS n FROM {versions} GROUP BY {bk}) '
        f'WHERE n <> 1')[0]
    add('scd2_one_current', table.name, wrong_current == 0,
        f'{wrong_current} {"/".join(table.business_key)} value(s) do not have exactly one current version.' if wrong_current else '')
    if scd.current_flag:
        mismatched = db.one(f'SELECT COUNT(*) FROM {versions} WHERE ({_q(scd.current_flag)}) IS DISTINCT FROM ({is_open})')[0]
        add('scd2_current_flag', table.name, mismatched == 0,
            f'{mismatched} version(s) where {scd.current_flag} disagrees with an open {scd.valid_to}.' if mismatched else '')
    join = ' AND '.join(f'a.{_q(c)} = b.{_q(c)}' for c in table.business_key)
    overlaps = db.one(
        f'SELECT COUNT(*) FROM {versions} AS a JOIN {versions} AS b ON {join} AND a.{key} < b.{key} '
        f'AND a.{start} < {end_value.replace(end, "b." + end)} AND b.{start} < {end_value.replace(end, "a." + end)}')[0]
    add('scd2_no_overlap', table.name, overlaps == 0,
        f'{overlaps} pair(s) of versions of the same {"/".join(table.business_key)} are valid at the same time.' if overlaps else '')
    gaps = db.one(
        f'SELECT COUNT(*) FROM (SELECT {end_value} AS e, LEAD({start}) OVER (PARTITION BY {bk} ORDER BY {start}) AS next_start '
        f'FROM {versions}) WHERE next_start IS NOT NULL AND next_start <> e')[0]
    add('scd2_no_gap', table.name, gaps == 0,
        f'{gaps} version(s) end on a different day than the next version starts.' if gaps else '')


def _relationship_stats(db: _Db, from_table: str, from_column: str, to_table: str, to_column: str) -> dict[str, Any]:
    f, t = _q(from_column), _q(to_column)
    rows, distinct, nulls = db.one(f'SELECT COUNT(*), COUNT(DISTINCT {f}), COUNT(*) - COUNT({f}) FROM {from_table}')
    to_rows, to_distinct, to_nulls = db.one(f'SELECT COUNT(*), COUNT(DISTINCT {t}), COUNT(*) - COUNT({t}) FROM {to_table}')
    orphans = db.one(f'SELECT COUNT(DISTINCT a.{f}) FROM {from_table} AS a WHERE a.{f} IS NOT NULL AND NOT EXISTS '
                     f'(SELECT 1 FROM {to_table} AS b WHERE b.{t} = a.{f})')[0]
    sample = db.one(f'SELECT MIN(a.{f}) FROM {from_table} AS a WHERE a.{f} IS NOT NULL AND NOT EXISTS '
                    f'(SELECT 1 FROM {to_table} AS b WHERE b.{t} = a.{f})')[0] if orphans else None
    from_unique = rows - nulls == distinct
    to_unique = to_rows - to_nulls == to_distinct
    observed = {(True, True): 'one-to-one', (False, True): 'many-to-one', (True, False): 'one-to-many',
                (False, False): 'many-to-many'}[(from_unique, to_unique)]
    return {'from_rows': rows, 'from_nulls': nulls, 'to_nulls': to_nulls, 'from_unique': from_unique,
            'to_unique': to_unique, 'observed': observed, 'orphans': orphans,
            'orphan_sample': None if sample is None else str(sample)}
