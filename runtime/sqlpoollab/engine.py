"""The simulated SQL pool: runs a T-SQL script statement by statement on the local catalog.

Data statements really run on DuckDB (translated); table designs (distribution,
index, partitions, clustering, constraints, statistics) are kept as metadata and
drive the physical model and the plans. Two flavors:

- synapse: Azure Synapse dedicated SQL pool. CREATE TABLE defaults to ROUND_ROBIN and
  a clustered columnstore index; CTAS requires a DISTRIBUTION option; PRIMARY KEY and
  UNIQUE only as NONCLUSTERED NOT ENFORCED; no FOREIGN KEY; RENAME OBJECT, partition
  SWITCH / SPLIT / MERGE, CREATE INDEX and CREATE STATISTICS.
- fabric: Microsoft Fabric Data Warehouse. No DISTRIBUTION, index or PARTITION options
  (the layout is managed; CLUSTER BY sets data clustering), no partitioned tables, no
  user indexes, and the Synapse types a warehouse table cannot use are refused with
  their migration mapping.
"""
from __future__ import annotations

import re
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ContextManager, Protocol

from .model import FLAVORS, Metadata, Partitioning, PoolError, Procedure, TableDesign
from .physical import partition_number_sql, partition_range
from .planner import Context, plan_select
from .tsql import (FABRIC_TYPE_MAP, Cursor, Statement, TableOptions, Token, Translator, identifier, lab_name,
                   literal_value, names, read_name, read_options, read_type, split_commas, split_statements,
                   sql_literal, tokenize)

MAX_STATEMENTS = 200
MAX_DEPTH = 8
PRODUCER = 'sqlpool'


class Database(Protocol):
    """The local data plane. Implemented by the runtime over the shared catalog."""

    kind: str

    def query(self, sql: str) -> dict[str, Any]: ...  # validated read-only; bounded preview
    def execute(self, sql: str, producer: str) -> dict[str, Any]: ...  # validated statements, one transaction
    def fetch(self, sql: str) -> list[tuple[Any, ...]]: ...  # engine-generated read-only SQL, unbounded
    def generated(self, sql: str) -> None: ...  # engine-generated DDL (sequences, renames); never learner text
    def exists(self, name: str) -> bool: ...
    def columns(self, name: str) -> list[tuple[str, str]]: ...
    def count(self, name: str) -> int: ...
    def serialize(self, select_sql: str) -> dict[str, Any]: ...
    def rename(self, old: str, new: str) -> None: ...
    def session(self) -> ContextManager[None]: ...  # unqualified names resolve to the warehouse schema
    def schema_types(self) -> dict[str, dict[str, dict[str, str]]]: ...  # {schema: {table: {column: type}}}


@dataclass
class StatementResult:
    index: int
    line: int
    kind: str
    status: str = 'ok'
    message: str = ''
    target: str | None = None
    sql: str | None = None
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False
    plan: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)
    children: list['StatementResult'] = field(default_factory=list)


class SqlPool:
    def __init__(self, db: Database, metadata: Metadata, flavor: str = 'synapse', now: datetime | None = None,
                 scale: float = 1.0, variables: dict[str, Any] | None = None, depth: int = 0):
        if flavor not in FLAVORS:
            raise PoolError(f"Unknown flavor '{flavor}'; use one of {', '.join(FLAVORS)}")
        self.db = db
        self.metadata = metadata
        self.flavor = flavor
        self.now = now or datetime(2026, 3, 5, 12, 0, 0)
        self.scale = scale
        self.variables: dict[str, Any] = dict(variables or {})
        self.types: dict[str, str] = {}
        self.depth = depth
        self.last_plan: dict[str, Any] | None = None
        self.last_query: str | None = None

    # -- script ------------------------------------------------------------------------------------
    def run(self, script: str) -> list[StatementResult]:
        results: list[StatementResult] = []
        try:
            statements = split_statements(script)
        except PoolError as exc:
            return [StatementResult(0, exc.line or 1, 'SCRIPT', 'error', exc.message)]
        if len(statements) > MAX_STATEMENTS:
            return [StatementResult(0, 1, 'SCRIPT', 'error', f"A lab script runs at most {MAX_STATEMENTS} statements")]
        context = self.db.session() if self.depth == 0 else nullcontext()
        with context:
            for statement in statements:
                result = self._safe(statement)
                results.append(result)
                if result.status == 'error':
                    break
        if self.depth == 0:
            self.metadata.save()
        return results

    def _safe(self, statement: Statement) -> StatementResult:
        try:
            return self.statement(statement)
        except PoolError as exc:
            return StatementResult(statement.index, exc.line or statement.line, self._kind(statement), 'error', exc.message)
        except Exception as exc:  # DuckDB errors on translated SQL: report them as the statement's error
            message = str(exc).split('\n')[0]
            return StatementResult(statement.index, statement.line, self._kind(statement), 'error', message)

    @staticmethod
    def _kind(statement: Statement) -> str:
        words = [t.upper for t in statement.significant()[:3]]
        return ' '.join(words[:2]) if words else 'STATEMENT'

    def statement(self, statement: Statement) -> StatementResult:
        cursor = Cursor(statement.tokens, statement)
        first, second = cursor.peek_upper(), cursor.peek_upper(1)
        if first == 'CREATE':
            if second == 'TABLE':
                return self.create_table(statement, cursor)
            if second in ('PROC', 'PROCEDURE') or (second == 'OR' and cursor.peek_upper(2) == 'ALTER'):
                return self.create_procedure(statement, cursor)
            if second == 'STATISTICS':
                return self.create_statistics(statement, cursor)
            if second == 'VIEW':
                return self.dml(statement, 'CREATE VIEW')
            if second == 'SCHEMA':
                raise PoolError("The lab pool's schemas are fixed: dbo (the warehouse layer) and the lakehouse layers",
                                line=statement.line)
            return self.create_index(statement, cursor)
        if first == 'DROP':
            return self.drop(statement, cursor)
        if first == 'IF':
            return self.if_object_id(statement, cursor)
        if first == 'RENAME':
            return self.rename(statement, cursor)
        if first == 'TRUNCATE':
            return self.truncate(statement, cursor)
        if first == 'ALTER':
            return self.alter(statement, cursor)
        if first == 'UPDATE' and second == 'STATISTICS':
            cursor.expect('UPDATE', 'STATISTICS')
            name = read_name(cursor)
            self._design(name)
            return StatementResult(statement.index, statement.line, 'UPDATE STATISTICS', target=name,
                                   message=f"Statistics of {name} refreshed (simulated).")
        if first in ('INSERT', 'UPDATE', 'DELETE', 'MERGE'):
            return self.dml(statement, first)
        if first in ('SELECT', 'WITH'):
            return self.select(statement, statement.tokens, explain=False)
        if first == 'EXPLAIN':
            cursor.next()
            return self.select(statement, cursor.rest(), explain=True)
        if first in ('EXEC', 'EXECUTE'):
            return self.execute(statement, cursor)
        if first == 'DECLARE':
            return self.declare(statement, cursor)
        if first == 'SET':
            return self.set_variable(statement, cursor)
        if first == 'PRINT':
            cursor.next()
            rest = cursor.rest()
            sig = [t for t in rest if t.significant]
            if not sig:
                raise PoolError('PRINT needs a message', line=statement.line)
            value = literal_value(sig) if len(sig) == 1 and sig[0].kind == 'string' else \
                self._evaluate(rest, None, statement.line)
            return StatementResult(statement.index, statement.line, 'PRINT', message='' if value is None else str(value))
        raise PoolError(f"'{first}' statements are not simulated in the lab pool. Supported: CREATE TABLE (and CTAS), "
                        "INSERT, UPDATE, DELETE, MERGE, SELECT, EXPLAIN, DROP, TRUNCATE, RENAME OBJECT, ALTER TABLE "
                        "SWITCH/SPLIT/MERGE, CREATE INDEX, CREATE/UPDATE STATISTICS, procedures, DECLARE/SET.",
                        line=statement.line)

    # -- helpers ------------------------------------------------------------------------------------
    def _translator(self) -> Translator:
        # The tables' types as they are now: the script may have created some since the last statement.
        return Translator(self.variables, self.now, self.db.schema_types())

    def _design(self, name: str) -> TableDesign:
        if not self.db.exists(name):
            raise PoolError(f"Invalid object name '{name}'.")
        design = self.metadata.tables.get(name)
        if design is None:
            design = TableDesign(name, created_by='outside the pool (defaults)')
            if self.flavor == 'fabric':
                design.distribution, design.index = 'AUTO', 'AUTO'
        return design

    def design_of(self, name: str) -> TableDesign | None:
        return self._design(name) if self.db.exists(name) else None

    def rows_at_scale(self, name: str) -> float:
        design = self.metadata.tables.get(name)
        factor = design.scale_factor if design and design.scale_factor else self.scale
        return self.db.count(name) * factor

    def planner_context(self) -> Context:
        def columns(name: str) -> dict[str, str]:
            return {c.lower(): t for c, t in self.db.columns(name)}
        return Context(self.db.serialize, self.design_of, columns, self.rows_at_scale, self.db.exists)

    def _sources_factor(self, sql: str) -> float | None:
        """Scale factor of a table built from others: the largest factor among the tables it reads."""
        factors = []
        for name, design in self.metadata.tables.items():
            bare = name.split('.')[1]
            if design.scale_factor and (re.search(rf"\b{re.escape(name)}\b", sql, re.I) or (
                    name.startswith('warehouse.') and re.search(rf"(?<![.\w]){re.escape(bare)}\b", sql, re.I))):
                factors.append(design.scale_factor)
        return max(factors) if factors else None

    def _check_columns(self, name: str, wanted: list[str], what: str) -> None:
        present = {c.lower() for c, _ in self.db.columns(name)}
        missing = [c for c in wanted if c.lower() not in present]
        if missing:
            raise PoolError(f"Invalid column name '{missing[0]}' in {what} of {name}.")

    # -- CREATE TABLE / CTAS -------------------------------------------------------------------------
    def create_table(self, statement: Statement, cursor: Cursor) -> StatementResult:
        cursor.expect('CREATE', 'TABLE')
        name = read_name(cursor)
        if self.db.exists(name):
            raise PoolError(f"There is already an object named '{name}' in the database.", line=statement.line)
        column_tokens: list[Token] | None = None
        if cursor.peek_upper() == '(':
            column_tokens = cursor.parenthesized()
        options = TableOptions()
        if cursor.accept('WITH'):
            options = read_options(cursor.parenthesized())
        if cursor.accept('AS'):
            return self._ctas(statement, name, column_tokens, options, cursor.rest())
        if not cursor.at_end():
            cursor.fail(f"Unexpected '{cursor.peek().text}' after CREATE TABLE")
        if column_tokens is None:
            raise PoolError('CREATE TABLE needs column definitions or AS SELECT', line=statement.line)
        self._check_options(options, ctas=False, line=statement.line)
        columns, constraints, identity = self._column_definitions(column_tokens, statement.line)
        ddl_columns = []
        sequence = None
        for column, duck, not_null, default in columns:
            text = f'"{column}" {duck}'
            if column == identity:
                sequence = f"{name}__{column}_seq"
                text += f" DEFAULT nextval('{sequence}')"
            elif default is not None:
                text += f" DEFAULT {default}"
            if not_null:
                text += ' NOT NULL'
            ddl_columns.append(text)
        if sequence:
            self.db.generated(f"CREATE SEQUENCE IF NOT EXISTS {sequence} START 1")
        self.db.execute(f"CREATE TABLE {name} ({', '.join(ddl_columns)})", f"{PRODUCER}:CREATE TABLE")
        design = self._new_design(name, options, 'CREATE TABLE')
        design.constraints = constraints
        design.identity = identity
        try:
            self._validate_design(design, statement.line)
            for constraint in constraints:
                self._check_columns(name, constraint['columns'], 'a constraint')
        except PoolError:
            self._drop_table(name, True, statement.line)
            raise
        self.metadata.tables[name] = design
        return StatementResult(statement.index, statement.line, 'CREATE TABLE', target=name,
                               message=f"Created {name}: {design.label()}.", notes=self._design_notes(design))

    def _ctas(self, statement: Statement, name: str, column_tokens: list[Token] | None, options: TableOptions,
              select_tokens: list[Token]) -> StatementResult:
        self._check_options(options, ctas=True, line=statement.line)
        if self.flavor == 'synapse' and 'DISTRIBUTION' not in options.mentioned:
            raise PoolError('CREATE TABLE AS SELECT requires a DISTRIBUTION option (HASH, ROUND_ROBIN or REPLICATE): '
                            'unlike CREATE TABLE, CTAS has no default distribution.', line=statement.line)
        translated = self._translator().translate(select_tokens)
        select_sql = translated.sql
        if column_tokens is not None:
            aliases = names(column_tokens)
            select_sql = (f"SELECT * FROM ({select_sql}) AS ctas_source("
                          + ', '.join(f'"{a}"' for a in aliases) + ')')
        plan = plan_select(select_sql, self.planner_context()) if self.flavor == 'synapse' else None
        rows_in = plan.final.rows if plan is not None and plan.final is not None else 0
        self.db.execute(f"CREATE TABLE {name} AS {select_sql}", f"{PRODUCER}:CTAS")
        design = self._new_design(name, options, 'CTAS')
        design.scale_factor = self._sources_factor(select_sql)
        try:
            self._validate_design(design, statement.line)
        except PoolError:
            self.db.execute(f"DROP TABLE {name}", f"{PRODUCER}:CTAS")
            raise
        self.metadata.tables[name] = design
        notes = list(translated.notes) + self._design_notes(design)
        plan_json = None
        if plan is not None:
            self._placement(plan, design, rows_in)
            plan_json = plan.to_json()
        rows = self.db.count(name)
        return StatementResult(statement.index, statement.line, 'CTAS', target=name, sql=select_sql,
                               message=f"Created {name} with {rows} rows: {design.label()}.", plan=plan_json,
                               notes=notes)

    @staticmethod
    def _placement(plan, design: TableDesign, rows: float) -> None:
        """Where CTAS writes its rows, given how the query's result is distributed."""
        if not plan.analyzed:
            return
        if plan.steps and plan.steps[-1]['operation'] == 'ReturnOperation':
            plan.steps.pop()  # CTAS writes into the new table instead of returning rows
        final = plan.final
        if design.distribution == 'HASH':
            aligned = (final is not None and final.distribution == 'HASH' and len(final.hash) == len(design.hash_columns)
                       and all(any(col == wanted for _, col in group)
                               for group, wanted in zip(final.hash, design.hash_columns)))
            keys = ', '.join(design.hash_columns)
            if aligned:
                plan.notes.append(f"The result is already distributed on {keys}: each distribution writes its own rows "
                                  "into the new table.")
            else:
                plan.steps.append({'operation': 'ShuffleMoveOperation', 'tables': [design.name],
                                   'columns': list(design.hash_columns), 'rows': round(rows),
                                   'reason': f"The new table is HASH({keys}): every row moves to the distribution "
                                             f"of its {keys} value."})
        elif design.distribution == 'REPLICATE':
            plan.notes.append('A replicated table is first stored round-robin; the full copies on the compute nodes are '
                              'built by the first query that reads it.')
        else:
            plan.notes.append('A round-robin table takes the rows as they come, spread evenly: no alignment needed.')

    def _check_options(self, options: TableOptions, ctas: bool, line: int) -> None:
        if self.flavor == 'fabric':
            blocked = [m for m in options.mentioned if m != 'CLUSTER BY']
            if 'PARTITION' in blocked:
                raise PoolError("Partitioned tables aren't supported in Fabric Data Warehouse.", line=line)
            if blocked:
                raise PoolError(f"Fabric Data Warehouse takes no {' or '.join(dict.fromkeys(blocked))} option: it "
                                "manages the data layout itself (Delta tables in OneLake). Remove the Synapse options; "
                                "use WITH (CLUSTER BY (...)) for data clustering.", line=line)
            if options.cluster_by and not 1 <= len(options.cluster_by) <= 4:
                raise PoolError('CLUSTER BY takes one to four columns.', line=line)
        elif 'CLUSTER BY' in options.mentioned:
            raise PoolError('CLUSTER BY is Fabric Data Warehouse syntax; a dedicated SQL pool uses DISTRIBUTION, an '
                            'index option and PARTITION.', line=line)
        if options.mentioned.count('INDEX') > 1 or options.mentioned.count('DISTRIBUTION') > 1:
            raise PoolError('Give one distribution and one index option.', line=line)

    def _new_design(self, name: str, options: TableOptions, created_by: str) -> TableDesign:
        if self.flavor == 'fabric':
            return TableDesign(name, 'AUTO', [], 'AUTO', [], None, list(options.cluster_by), created_by=created_by)
        return TableDesign(name, options.distribution or 'ROUND_ROBIN', list(options.hash_columns),
                           options.index or 'CLUSTERED COLUMNSTORE INDEX', list(options.index_columns),
                           options.partition, created_by=created_by)

    def _validate_design(self, design: TableDesign, line: int) -> None:
        columns = {c.lower(): t for c, t in self.db.columns(design.name)}
        wanted = list(design.hash_columns) + list(design.index_columns) + list(design.cluster_by) + (
            [design.partition.column] if design.partition else [])
        for column in wanted:
            if column.lower() not in columns:
                raise PoolError(f"Invalid column name '{column}' in the table options of {design.name}.", line=line)
        if design.index == 'CLUSTERED COLUMNSTORE INDEX' and design.index_columns:
            strings = [c for c in design.index_columns if columns[c.lower()].startswith('VARCHAR')]
            if strings:
                raise PoolError(f"An ordered clustered columnstore index can't be created on string columns ({strings[0]}).",
                                line=line)
        if design.partition:
            kind = columns[design.partition.column.lower()]
            numeric = kind.split('(')[0] in ('INTEGER', 'BIGINT', 'SMALLINT', 'UTINYINT', 'DECIMAL', 'DOUBLE', 'FLOAT')
            for value in design.partition.boundaries:
                if numeric != (isinstance(value, (int, float)) and not isinstance(value, bool)):
                    raise PoolError(f"Partition boundary {sql_literal(value)} doesn't match the type of "
                                    f"{design.partition.column} ({kind}).", line=line)

    def _design_notes(self, design: TableDesign) -> list[str]:
        notes = []
        if design.distribution == 'ROUND_ROBIN' and design.created_by == 'CREATE TABLE':
            notes.append('ROUND_ROBIN is the default: fine for staging, but joins on this table will move data.')
        if design.partition and design.partition.range == 'LEFT':
            notes.append('RANGE LEFT (the default): each boundary value belongs to the partition on its left.')
        return notes

    def _column_definitions(self, tokens: list[Token], line: int):
        columns, constraints, identity = [], [], None
        for part in split_commas(tokens):
            significant = [t for t in part if t.significant]
            if not significant:
                continue
            head = significant[0].upper
            if head in ('CONSTRAINT', 'PRIMARY', 'UNIQUE', 'FOREIGN'):
                constraints.append(self._table_constraint(significant, line))
                continue
            column = identifier(significant[0]).lower()
            shown, duck, position = read_type(significant, 1)
            base = shown.split('(')[0]
            if self.flavor == 'fabric' and base in FABRIC_TYPE_MAP:
                raise PoolError(f"Fabric Data Warehouse doesn't support the {base} data type ({column}): use "
                                f"{FABRIC_TYPE_MAP[base]}.", line=significant[0].line)
            not_null, default = False, None
            rest = Cursor(significant[position:])
            while not rest.at_end():
                if rest.accept('NOT', 'NULL'):
                    not_null = True
                elif rest.accept('NULL'):
                    not_null = False
                elif rest.accept('IDENTITY'):
                    if rest.peek_upper() == '(':
                        rest.parenthesized()
                    if identity:
                        rest.fail('A table has at most one IDENTITY column')
                    identity = column
                    if duck not in ('INTEGER', 'BIGINT'):
                        rest.fail('An IDENTITY column is INT or BIGINT')
                elif rest.accept('COLLATE'):
                    rest.next()
                elif rest.accept('DEFAULT'):
                    token = rest.next()
                    if token.text == '(':
                        rest.fail('DEFAULT takes a literal value here')
                    default = sql_literal(literal_value([token], 'Column defaults'))
                elif rest.peek_upper() in ('CONSTRAINT', 'PRIMARY', 'UNIQUE'):
                    constraints.append(self._table_constraint(rest.tokens[rest.sig[rest.k]:], line, column))
                    break
                else:
                    rest.fail(f"Unexpected '{rest.peek().text}' in the definition of {column}")
            columns.append((column, duck, not_null, default))
        if not columns:
            raise PoolError('CREATE TABLE needs at least one column', line=line)
        return columns, constraints, identity

    def _table_constraint(self, tokens: list[Token], line: int, column: str | None = None) -> dict[str, Any]:
        cursor = Cursor(tokens)
        name = None
        if cursor.accept('CONSTRAINT'):
            name = identifier(cursor.next())
        if cursor.accept('FOREIGN', 'KEY'):
            if self.flavor == 'synapse':
                raise PoolError('FOREIGN KEY constraints are not supported in a dedicated SQL pool.', line=line)
            columns = names(cursor.parenthesized()) if cursor.peek_upper() == '(' else [column]
            cursor.expect('REFERENCES')
            ref = read_name(cursor)
            if cursor.peek_upper() == '(':
                cursor.parenthesized()
            if not cursor.accept('NOT', 'ENFORCED'):
                raise PoolError('FOREIGN KEY is only supported with NOT ENFORCED in Fabric Data Warehouse.', line=line)
            return {'kind': 'FOREIGN KEY', 'name': name, 'columns': columns, 'references': ref, 'enforced': False}
        if cursor.accept('PRIMARY', 'KEY'):
            kind = 'PRIMARY KEY'
        elif cursor.accept('UNIQUE'):
            kind = 'UNIQUE'
        else:
            cursor.fail('Expected PRIMARY KEY, UNIQUE or FOREIGN KEY')
        clustered = 'NONCLUSTERED' if cursor.accept('NONCLUSTERED') else 'CLUSTERED' if cursor.accept('CLUSTERED') else None
        columns = names(cursor.parenthesized()) if cursor.peek_upper() == '(' else [column]
        enforced = not cursor.accept('NOT', 'ENFORCED')
        if clustered != 'NONCLUSTERED' or enforced:
            raise PoolError(f"{kind} is only supported with NONCLUSTERED and NOT ENFORCED: the pool does not check "
                            "uniqueness, so duplicates are not prevented.", line=line)
        return {'kind': kind, 'name': name, 'columns': [c for c in columns if c], 'enforced': False}

    # -- DROP / RENAME / TRUNCATE ------------------------------------------------------------------------
    def drop(self, statement: Statement, cursor: Cursor) -> StatementResult:
        cursor.expect('DROP')
        if cursor.accept('TABLE'):
            if_exists = cursor.accept('IF', 'EXISTS')
            dropped = []
            for part in split_commas(cursor.rest()):
                sub = Cursor(part)
                name = read_name(sub)
                dropped.append(self._drop_table(name, if_exists, statement.line))
            names_done = [n for n in dropped if n]
            return StatementResult(statement.index, statement.line, 'DROP TABLE', target=', '.join(names_done) or None,
                                   message=f"Dropped {', '.join(names_done)}." if names_done else 'Nothing to drop.')
        if cursor.accept('VIEW'):
            return self.dml(statement, 'DROP VIEW')
        if cursor.peek_upper() in ('PROC', 'PROCEDURE'):
            cursor.next()
            if_exists = cursor.accept('IF', 'EXISTS')
            name = read_name(cursor, 'procedure')
            if name not in self.metadata.procedures:
                if if_exists:
                    return StatementResult(statement.index, statement.line, 'DROP PROCEDURE', message='Nothing to drop.')
                raise PoolError(f"Cannot drop the procedure '{name}', because it does not exist.", line=statement.line)
            del self.metadata.procedures[name]
            return StatementResult(statement.index, statement.line, 'DROP PROCEDURE', target=name,
                                   message=f"Dropped procedure {name}.")
        if cursor.accept('INDEX'):
            index = identifier(cursor.next()).lower()
            cursor.expect('ON')
            name = read_name(cursor)
            design = self._stored_design(name)
            if index not in design.nonclustered_indexes:
                raise PoolError(f"Cannot drop the index '{name}.{index}', because it does not exist.", line=statement.line)
            del design.nonclustered_indexes[index]
            return StatementResult(statement.index, statement.line, 'DROP INDEX', target=name, message=f"Dropped index {index}.")
        if cursor.accept('STATISTICS'):
            parts = [identifier(t) for t in cursor.rest() if t.significant and t.text != '.']
            name = lab_name(parts[:-1], line=statement.line)
            design = self._stored_design(name)
            design.statistics.pop(parts[-1].lower(), None)
            return StatementResult(statement.index, statement.line, 'DROP STATISTICS', target=name,
                                   message=f"Dropped statistics {parts[-1]}.")
        cursor.fail('DROP supports TABLE, VIEW, PROCEDURE, INDEX and STATISTICS')

    def _drop_table(self, name: str, if_exists: bool, line: int) -> str | None:
        if not self.db.exists(name):
            if if_exists:
                return None
            raise PoolError(f"Cannot drop the table '{name}', because it does not exist or you do not have permission.",
                            line=line)
        design = self.metadata.tables.pop(name, None)
        self.db.execute(f"DROP TABLE {name}", f"{PRODUCER}:DROP")
        if design and design.identity:
            self.db.generated(f"DROP SEQUENCE IF EXISTS {name}__{design.identity}_seq")
        return name

    def if_object_id(self, statement: Statement, cursor: Cursor) -> StatementResult:
        cursor.expect('IF', 'OBJECT_ID')
        args = split_commas(cursor.parenthesized())
        literal = [t for t in args[0] if t.significant] if args else []
        if len(literal) != 1 or literal[0].kind != 'string':
            cursor.fail("OBJECT_ID takes the object name as a string, for example OBJECT_ID('dbo.fact_sales')")
        target = read_name(Cursor(tokenize(literal_value(literal, 'OBJECT_ID names'))))
        cursor.expect('IS', 'NOT', 'NULL')
        cursor.expect('DROP', 'TABLE')
        name = read_name(cursor)
        if name != target:
            cursor.fail('The lab supports IF OBJECT_ID(...) IS NOT NULL DROP TABLE on the same table')
        dropped = self._drop_table(name, True, statement.line)
        return StatementResult(statement.index, statement.line, 'DROP TABLE', target=dropped,
                               message=f"Dropped {dropped}." if dropped else f"{name} does not exist: nothing to drop.")

    def rename(self, statement: Statement, cursor: Cursor) -> StatementResult:
        if self.flavor == 'fabric':
            raise PoolError('RENAME OBJECT is dedicated SQL pool syntax; the lab simulates it in the Synapse flavor only.',
                            line=statement.line)
        cursor.expect('RENAME', 'OBJECT')
        if cursor.accept('OBJECT') and not cursor.accept(':'):
            cursor.fail("Expected OBJECT::name")
        cursor.accept(':')
        old = read_name(cursor)
        cursor.expect('TO')
        new_token = cursor.next()
        if not cursor.at_end():
            cursor.fail('RENAME OBJECT keeps the schema: give the new name without a schema')
        new = lab_name([old.split('.')[0], identifier(new_token)], line=statement.line)
        if not self.db.exists(old):
            raise PoolError(f"Invalid object name '{old}'.", line=statement.line)
        if self.db.exists(new):
            raise PoolError(f"There is already an object named '{new}' in the database.", line=statement.line)
        self.db.rename(old, new)
        design = self.metadata.tables.pop(old, None)
        if design:
            design.name = new
            self.metadata.tables[new] = design
        return StatementResult(statement.index, statement.line, 'RENAME OBJECT', target=new,
                               message=f"Renamed {old} to {new} (a metadata operation: no data moves).")

    def truncate(self, statement: Statement, cursor: Cursor) -> StatementResult:
        cursor.expect('TRUNCATE', 'TABLE')
        name = read_name(cursor)
        self._design(name)
        self.db.execute(f"DELETE FROM {name}", f"{PRODUCER}:TRUNCATE")
        return StatementResult(statement.index, statement.line, 'TRUNCATE TABLE', target=name,
                               message=f"Truncated {name}; its design is unchanged.")

    # -- ALTER TABLE ---------------------------------------------------------------------------------
    def alter(self, statement: Statement, cursor: Cursor) -> StatementResult:
        cursor.expect('ALTER')
        if cursor.accept('INDEX'):
            if not cursor.accept('ALL'):
                cursor.next()
            cursor.expect('ON')
            name = read_name(cursor)
            self._design(name)
            cursor.expect('REBUILD')
            return StatementResult(statement.index, statement.line, 'ALTER INDEX', target=name,
                                   message=f"Rebuilt the indexes of {name} (simulated: rowgroups are recompressed).")
        cursor.expect('TABLE')
        name = read_name(cursor)
        if cursor.accept('SWITCH'):
            return self.switch(statement, cursor, name)
        if cursor.peek_upper() in ('SPLIT', 'MERGE'):
            return self.split_merge(statement, cursor, name)
        if cursor.accept('ADD'):
            design = self._stored_design(name)
            constraint = self._table_constraint(cursor.rest(), statement.line)
            self._check_columns(name, constraint['columns'], 'the constraint')
            design.constraints.append(constraint)
            return StatementResult(statement.index, statement.line, 'ALTER TABLE', target=name,
                                   message=f"Added {constraint['kind']} (NOT ENFORCED) on {', '.join(constraint['columns'])}: "
                                           "the pool does not check it.")
        cursor.fail('ALTER TABLE supports SWITCH, SPLIT RANGE, MERGE RANGE and ADD CONSTRAINT here')

    def _stored_design(self, name: str) -> TableDesign:
        design = self._design(name)
        self.metadata.tables[name] = design
        return design

    def switch(self, statement: Statement, cursor: Cursor, source: str) -> StatementResult:
        if self.flavor == 'fabric':
            raise PoolError("Partition switching isn't available in Fabric Data Warehouse (no partitioned tables).",
                            line=statement.line)
        source_partition = int(cursor.next().text) if cursor.accept('PARTITION') else None
        cursor.expect('TO')
        target = read_name(cursor)
        target_partition = int(cursor.next().text) if cursor.accept('PARTITION') else None
        truncate_target = False
        if cursor.accept('WITH'):
            option = [t.upper for t in cursor.parenthesized() if t.significant]
            truncate_target = option == ['TRUNCATE_TARGET', '=', 'ON']
            if not truncate_target and option != ['TRUNCATE_TARGET', '=', 'OFF']:
                raise PoolError('SWITCH takes WITH (TRUNCATE_TARGET = ON | OFF)', line=statement.line)
        src, dst = self._design(source), self._design(target)
        problem = self._switch_problem(src, dst)
        if problem:
            raise PoolError(f"ALTER TABLE SWITCH statement failed: {problem}", line=statement.line)
        src_filter = self._partition_filter(src, source_partition, statement.line)
        dst_filter = self._partition_filter(dst, target_partition, statement.line)
        if source_partition is not None or target_partition is not None:
            if src.partition is None or dst.partition is None or source_partition is None or target_partition is None:
                raise PoolError('ALTER TABLE SWITCH statement failed: give PARTITION numbers on both partitioned tables.',
                                line=statement.line)
            if partition_range(src.partition, source_partition) != partition_range(dst.partition, target_partition) \
                    or src.partition.range != dst.partition.range:
                raise PoolError(f"ALTER TABLE SWITCH statement failed: partition {source_partition} of {source} and "
                                f"partition {target_partition} of {target} don't cover the same range of values.",
                                line=statement.line)
        occupied = self.db.fetch(f"SELECT COUNT(*) FROM {target} WHERE {dst_filter}")[0][0]
        if occupied and not truncate_target:
            where = f"partition {target_partition} of {target}" if target_partition else target
            raise PoolError(f"ALTER TABLE SWITCH statement failed: {where} is not empty "
                            "(use WITH (TRUNCATE_TARGET = ON) to replace it).", line=statement.line)
        moved = self.db.fetch(f"SELECT COUNT(*) FROM {source} WHERE {src_filter}")[0][0]
        self.db.execute(f"DELETE FROM {target} WHERE {dst_filter}; INSERT INTO {target} SELECT * FROM {source} WHERE "
                        f"{src_filter}; DELETE FROM {source} WHERE {src_filter}", f"{PRODUCER}:SWITCH")
        where = f" partition {source_partition}" if source_partition else ''
        return StatementResult(statement.index, statement.line, 'ALTER TABLE SWITCH', target=target,
                               message=f"Switched{where} of {source} into {target}: {moved} rows, a metadata "
                                       "operation in the pool (no row-by-row copy).")

    def _switch_problem(self, src: TableDesign, dst: TableDesign) -> str | None:
        src_cols = [(c.lower(), t) for c, t in self.db.columns(src.name)]
        dst_cols = [(c.lower(), t) for c, t in self.db.columns(dst.name)]
        if src_cols != dst_cols:
            return 'the two tables do not have the same columns, types and order.'
        if (src.distribution, src.hash_columns) != (dst.distribution, dst.hash_columns):
            return f"the tables are not distributed the same way ({src.label()} vs {dst.label()})."
        if src.index != dst.index:
            return f"the tables do not have the same index ({src.index} vs {dst.index})."
        if (src.partition is None) != (dst.partition is None):
            return 'one table is partitioned and the other is not.'
        if src.partition and dst.partition and src.partition.column.lower() != dst.partition.column.lower():
            return 'the tables are partitioned on different columns.'
        return None

    def _partition_filter(self, design: TableDesign, number: int | None, line: int) -> str:
        if number is None:
            return 'TRUE'
        if design.partition is None or not 1 <= number <= design.partition.count:
            raise PoolError(f"{design.name} has no partition {number}.", line=line)
        types = {c.lower(): t for c, t in self.db.columns(design.name)}
        kind = types[design.partition.column.lower()]
        return f"{partition_number_sql(design.partition, kind)} = {number}"

    def split_merge(self, statement: Statement, cursor: Cursor, name: str) -> StatementResult:
        action = cursor.next().upper
        cursor.expect('RANGE')
        values = [literal_value(v) for v in split_commas(cursor.parenthesized()) if v]
        if len(values) != 1:
            raise PoolError(f"{action} RANGE takes one boundary value", line=statement.line)
        value = values[0]
        design = self._stored_design(name)
        if design.partition is None:
            raise PoolError(f"{name} is not partitioned.", line=statement.line)
        boundaries = design.partition.boundaries
        if action == 'MERGE':
            if value not in boundaries:
                raise PoolError(f"MERGE RANGE: {sql_literal(value)} is not a boundary of {name}.", line=statement.line)
            boundaries.remove(value)
            return StatementResult(statement.index, statement.line, 'ALTER TABLE MERGE RANGE', target=name,
                                   message=f"Removed boundary {sql_literal(value)}: {design.partition.count} partitions.")
        if value in boundaries:
            raise PoolError(f"SPLIT RANGE: {sql_literal(value)} is already a boundary of {name}.", line=statement.line)
        types = {c.lower(): t for c, t in self.db.columns(name)}
        kind = types[design.partition.column.lower()]
        candidate = Partitioning(design.partition.column, design.partition.range,
                                 sorted(boundaries + [value], key=lambda v: (not isinstance(v, (int, float)), v)))
        position = candidate.boundaries.index(value) + 1
        if design.index == 'CLUSTERED COLUMNSTORE INDEX':
            before = Partitioning(design.partition.column, design.partition.range, boundaries)
            rows = self.db.fetch(f"SELECT COUNT(*) FROM {name} WHERE {partition_number_sql(before, kind)} = {position}")[0][0]
            if rows:
                raise PoolError('SPLIT clause of ALTER PARTITION statement failed because the partition is not empty. '
                                'Only empty partitions can be split in when a columnstore index exists on the table.',
                                line=statement.line)
        design.partition = candidate
        return StatementResult(statement.index, statement.line, 'ALTER TABLE SPLIT RANGE', target=name,
                               message=f"Added boundary {sql_literal(value)}: {candidate.count} partitions.")

    # -- indexes and statistics -------------------------------------------------------------------------
    def create_index(self, statement: Statement, cursor: Cursor) -> StatementResult:
        cursor.expect('CREATE')
        if self.flavor == 'fabric':
            raise PoolError("Fabric Data Warehouse doesn't support user-defined indexes: it manages the data layout "
                            "(use CLUSTER BY for data clustering).", line=statement.line)
        if cursor.accept('UNIQUE'):
            raise PoolError('Unique indexes are not supported in a dedicated SQL pool.', line=statement.line)
        clustered = 'CLUSTERED' if cursor.accept('CLUSTERED') else 'NONCLUSTERED' if cursor.accept('NONCLUSTERED') else None
        columnstore = cursor.accept('COLUMNSTORE')
        cursor.expect('INDEX')
        index = identifier(cursor.next()).lower()
        cursor.expect('ON')
        name = read_name(cursor)
        design = self._stored_design(name)
        columns = names(cursor.parenthesized()) if cursor.peek_upper() == '(' else []
        if clustered == 'CLUSTERED':
            if design.index != 'HEAP':
                raise PoolError(f"{name} already has a {design.index.lower()}: a table has one clustered structure.",
                                line=statement.line)
            if columnstore:
                order = names(cursor.parenthesized()) if cursor.accept('ORDER') else []
                design.index, design.index_columns = 'CLUSTERED COLUMNSTORE INDEX', order
            else:
                if not columns:
                    cursor.fail('A clustered index needs its key columns')
                design.index, design.index_columns = 'CLUSTERED INDEX', columns
            self._validate_design(design, statement.line)
            return StatementResult(statement.index, statement.line, 'CREATE INDEX', target=name,
                                   message=f"{name} is now {design.label()}.")
        if columnstore:
            raise PoolError('Nonclustered columnstore indexes are not supported in a dedicated SQL pool.',
                            line=statement.line)
        if not columns:
            cursor.fail('An index needs its key columns')
        self._check_columns(name, columns, f"index {index}")
        design.nonclustered_indexes[index] = columns
        return StatementResult(statement.index, statement.line, 'CREATE INDEX', target=name,
                               message=f"Created nonclustered index {index} on {name} ({', '.join(columns)}): selective "
                                       "lookups on these columns can seek instead of scanning.")

    def create_statistics(self, statement: Statement, cursor: Cursor) -> StatementResult:
        cursor.expect('CREATE', 'STATISTICS')
        stat = identifier(cursor.next()).lower()
        cursor.expect('ON')
        name = read_name(cursor)
        design = self._stored_design(name)
        columns = names(cursor.parenthesized())
        if self.flavor == 'fabric' and len(columns) > 1:
            raise PoolError("Manually created multi-column statistics aren't supported in Fabric Data Warehouse.",
                            line=statement.line)
        self._check_columns(name, columns, f"statistics {stat}")
        design.statistics[stat] = columns
        return StatementResult(statement.index, statement.line, 'CREATE STATISTICS', target=name,
                               message=f"Created statistics {stat} on {name} ({', '.join(columns)}).")

    # -- data statements ------------------------------------------------------------------------------
    def dml(self, statement: Statement, kind: str) -> StatementResult:
        translated = self._translator().translate(statement.tokens)
        sql = translated.sql
        target = self._target(statement, kind)
        before = self.db.count(target) if target and self.db.exists(target) else None
        result = self.db.execute(sql, f"{PRODUCER}:{kind}")
        notes = list(translated.notes)
        message = f"{kind} ran."
        if target and self.db.exists(target):
            design = self._design(target)
            after = self.db.count(target)
            if kind == 'INSERT' and not design.scale_factor:
                factor = self._sources_factor(sql)
                if factor:
                    design.scale_factor = factor
                    self.metadata.tables[target] = design
            if kind == 'UPDATE' and design.distribution == 'HASH' and any(
                    re.search(rf'\bSET\b.*\b{re.escape(c)}\s*=', sql, re.I | re.S) for c in design.hash_columns):
                notes.append('Updating a distribution column moves each changed row to its new distribution (a shuffle).')
            if design.distribution == 'REPLICATE' and kind in ('INSERT', 'UPDATE', 'DELETE', 'MERGE'):
                notes.append('Replicated table changed: its copies on the compute nodes are rebuilt on the next query.')
            if before is not None:
                message = f"{kind} on {target}: {after} rows (was {before})."
            else:
                message = f"{kind} on {target}: {after} rows."
        elif result.get('rows'):
            message = f"{kind} ran."
        return StatementResult(statement.index, statement.line, kind, target=target, sql=sql, message=message,
                               notes=notes)

    def _target(self, statement: Statement, kind: str) -> str | None:
        cursor = Cursor(statement.tokens)
        try:
            if kind == 'INSERT':
                cursor.expect('INSERT')
                cursor.accept('INTO')
                return read_name(cursor)
            if kind == 'UPDATE':
                cursor.expect('UPDATE')
                return read_name(cursor)
            if kind == 'DELETE':
                cursor.expect('DELETE')
                cursor.accept('FROM')
                return read_name(cursor)
            if kind == 'MERGE':
                cursor.expect('MERGE')
                cursor.accept('INTO')
                return read_name(cursor)
        except PoolError:
            return None
        return None

    def select(self, statement: Statement, tokens: list[Token], explain: bool) -> StatementResult:
        translated = self._translator().translate(tokens)
        sql = translated.sql
        plan_json = None
        if self.flavor == 'synapse':
            plan_json = plan_select(sql, self.planner_context()).to_json()
        else:
            plan_json = {'analyzed': False, 'steps': [], 'scans': [], 'data_movement': False,
                         'notes': ['Fabric Data Warehouse distributes data and plans queries automatically: there is no '
                                   'user-controlled distribution to reason about.']}
        self.last_plan, self.last_query = plan_json, sql
        if explain:
            return StatementResult(statement.index, statement.line, 'EXPLAIN', sql=sql, plan=plan_json,
                                   message='Distributed plan (simulated); the query was not run.')
        result = self.db.query(sql)
        return StatementResult(statement.index, statement.line, 'SELECT', sql=sql, columns=result['columns'],
                               rows=result['rows'], truncated=result['truncated'], plan=plan_json,
                               notes=list(translated.notes),
                               message=f"{len(result['rows'])}{'+' if result['truncated'] else ''} rows.")

    # -- variables --------------------------------------------------------------------------------
    def declare(self, statement: Statement, cursor: Cursor) -> StatementResult:
        cursor.expect('DECLARE')
        declared = []
        for part in split_commas(cursor.rest()):
            significant = [t for t in part if t.significant]
            if not significant:
                continue
            if significant[0].kind != 'var':
                raise PoolError('DECLARE takes @name type [= value]', line=statement.line)
            key = significant[0].text[1:].lower()
            depth, equals_at = 0, None
            for position, token in enumerate(part):
                if token.text == '(':
                    depth += 1
                elif token.text == ')':
                    depth -= 1
                elif token.text == '=' and depth == 0:
                    equals_at = position
                    break
            type_tokens = [t for t in (part[:equals_at] if equals_at is not None else part) if t.significant][1:]
            if not type_tokens:
                raise PoolError(f"DECLARE @{key} needs a type", line=statement.line)
            _, duck, _ = read_type(type_tokens, 0)
            value = self._evaluate(part[equals_at + 1:], duck, statement.line) if equals_at is not None else None
            self.variables[key] = value
            self.types[key] = duck
            declared.append(f"@{key} = {sql_literal(value)}")
        return StatementResult(statement.index, statement.line, 'DECLARE', message=', '.join(declared))

    def set_variable(self, statement: Statement, cursor: Cursor) -> StatementResult:
        cursor.expect('SET')
        token = cursor.next()
        if token.kind != 'var':
            raise PoolError("SET here assigns a variable: SET @name = value (session options aren't simulated)",
                            line=statement.line)
        key = token.text[1:].lower()
        if key not in self.variables:
            raise PoolError(f'Must declare the scalar variable "{token.text}".', line=statement.line)
        cursor.expect('=')
        value = self._evaluate(cursor.rest(), self.types.get(key), statement.line)
        self.variables[key] = value
        return StatementResult(statement.index, statement.line, 'SET', message=f"@{key} = {sql_literal(value)}")

    def _evaluate(self, tokens: list[Token], duck_type: str | None, line: int) -> Any:
        expression = self._translator().translate(tokens).sql
        sql = f"SELECT CAST(({expression}) AS {duck_type}) AS v" if duck_type else f"SELECT ({expression}) AS v"
        rows = self.db.query(sql)['rows']
        value = rows[0]['v'] if rows else None
        return value

    # -- procedures -------------------------------------------------------------------------------
    def create_procedure(self, statement: Statement, cursor: Cursor) -> StatementResult:
        cursor.expect('CREATE')
        alter = cursor.accept('OR', 'ALTER')
        if not (cursor.accept('PROCEDURE') or cursor.accept('PROC')):
            cursor.fail('Expected PROCEDURE')
        name = read_name(cursor, 'procedure')
        if name in self.metadata.procedures and not alter:
            raise PoolError(f"There is already an object named '{name}' in the database.", line=statement.line)
        parameters = []
        header: list[Token] = []
        while not cursor.at_end() and cursor.peek_upper() != 'AS':
            header.append(cursor.next())
        cursor.expect('AS')
        inner = header[1:-1] if header and header[0].text == '(' and header[-1].text == ')' else header
        for part in split_commas(inner):
            sig = [t for t in part if t.significant]
            if not sig:
                continue
            if sig[0].kind != 'var':
                raise PoolError('Procedure parameters are written @name type [= default]', line=sig[0].line)
            shown, _, position = read_type(sig, 1)
            default = None
            rest = sig[position:]
            if rest and rest[0].text == '=':
                if len(rest) < 2:
                    raise PoolError('A parameter default needs a value', line=rest[0].line)
                default = 'NULL' if rest[1].upper == 'NULL' else sql_literal(literal_value(rest[1:2], 'Parameter defaults'))
                rest = rest[2:]
            if rest and rest[0].upper in ('OUTPUT', 'OUT'):
                raise PoolError('OUTPUT parameters are not simulated', line=rest[0].line)
            parameters.append((sig[0].text[1:].lower(), shown, default))
        body = cursor.rest()
        sig = [t for t in body if t.significant]
        if sig and sig[0].upper == 'BEGIN' and sig[-1].upper == 'END':
            first, last = body.index(sig[0]), len(body) - 1 - body[::-1].index(sig[-1])
            body = body[first + 1:last]
        text = ''.join(t.text for t in body).strip()
        if not text:
            raise PoolError('The procedure body is empty', line=statement.line)
        split_statements(text)  # the body must tokenize
        self.metadata.procedures[name] = Procedure(name, parameters, text, statement.line)
        verb = 'Altered' if alter else 'Created'
        return StatementResult(statement.index, statement.line, 'CREATE PROCEDURE', target=name,
                               message=f"{verb} procedure {name}({', '.join('@' + p[0] for p in parameters)}).")

    def execute(self, statement: Statement, cursor: Cursor) -> StatementResult:
        cursor.next()
        name = read_name(cursor, 'procedure')
        procedure = self.metadata.procedures.get(name)
        if procedure is None:
            raise PoolError(f"Could not find stored procedure '{name}'.", line=statement.line)
        if self.depth >= MAX_DEPTH:
            raise PoolError('Procedures nest at most 8 levels in the lab', line=statement.line)
        supplied: dict[str, Any] = {}
        positional = 0
        for part in split_commas(cursor.rest()):
            sig = [t for t in part if t.significant]
            if not sig:
                continue
            if sig[0].kind == 'var' and len(sig) >= 3 and sig[1].text == '=':
                key, value_tokens = sig[0].text[1:].lower(), sig[2:]
            else:
                if positional >= len(procedure.parameters):
                    raise PoolError(f"Procedure or function {name} has too many arguments specified.", line=statement.line)
                key, value_tokens = procedure.parameters[positional][0], sig
                positional += 1
            if key not in {p[0] for p in procedure.parameters}:
                raise PoolError(f"@{key} is not a parameter for procedure {name}.", line=statement.line)
            supplied[key] = self._argument(value_tokens, statement.line)
        arguments: dict[str, Any] = {}
        for parameter, kind, default in procedure.parameters:
            if parameter in supplied:
                value = supplied[parameter]
            elif default is not None:
                value = None if default == 'NULL' else literal_value(tokenize(default))
            else:
                raise PoolError(f"Procedure or function '{name}' expects parameter '@{parameter}', which was not "
                                "supplied.", line=statement.line)
            arguments[parameter] = self._typed(value, kind, name, parameter, statement.line)
        inner = SqlPool(self.db, self.metadata, self.flavor, self.now, self.scale, arguments, self.depth + 1)
        children = inner.run(procedure.body)
        failed = next((c for c in children if c.status == 'error'), None)
        if inner.last_plan is not None:
            self.last_plan, self.last_query = inner.last_plan, inner.last_query
        if failed:
            raise PoolError(f"{name} failed at its statement {failed.index}: {failed.message}", line=statement.line)
        return StatementResult(statement.index, statement.line, 'EXEC', target=name, children=children,
                               message=f"EXEC {name}: {len(children)} statement(s) ran.")

    def _argument(self, tokens: list[Token], line: int) -> Any:
        if len(tokens) == 1 and tokens[0].kind == 'var':
            key = tokens[0].text[1:].lower()
            if key not in self.variables:
                raise PoolError(f'Must declare the scalar variable "{tokens[0].text}".', line=line)
            return self.variables[key]
        if len(tokens) == 1 and tokens[0].upper == 'NULL':
            return None
        # As in SQL Server, EXEC takes constants and variables, not expressions.
        return literal_value(tokens, 'Procedure arguments')

    def _typed(self, value: Any, kind: str, procedure: str, parameter: str, line: int) -> Any:
        base = kind.split('(')[0].lower()
        if value is None:
            return None
        try:
            if base in ('int', 'bigint', 'smallint', 'tinyint'):
                return int(value)
            if base in ('decimal', 'numeric', 'float', 'real', 'money', 'smallmoney'):
                return float(value)
            if base == 'bit':
                return bool(int(value)) if not isinstance(value, bool) else value
        except (TypeError, ValueError):
            raise PoolError(f"Error converting data type for @{parameter} of {procedure}: {sql_literal(value)} is not "
                            f"{kind}.", line=line) from None
        return value if isinstance(value, str) else str(value) if base in ('varchar', 'nvarchar', 'char', 'nchar',
                                                                             'date', 'datetime', 'datetime2') else value
