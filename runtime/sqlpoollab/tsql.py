"""Bounded T-SQL reader for the SQL pool: split scripts, read the Synapse-specific statements, translate the rest.

Nothing here executes SQL. Scripts are split on `;` and on `GO` lines (a stored procedure takes its whole batch).
What only a dedicated SQL pool or a Fabric Warehouse has stays here: table options (DISTRIBUTION, CLUSTERED
COLUMNSTORE INDEX, HEAP, PARTITION, CLUSTER BY), column types of CREATE TABLE, names in the lab's schemas (dbo is the
warehouse layer), literals of partition boundaries. Every query, DML statement and expression is translated by the
shared T-SQL dialect (runtime/sqldialects), with this module's hooks for DECLARE/SET variables, the lab's fixed clock
and dbo.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlglot import exp
from sqldialects import DialectError, translate, translate_expression
from sqldialects.tsql import duckdb_type

from .model import Partitioning, PoolError

LAYERS = ('source', 'bronze', 'silver', 'gold', 'warehouse', 'features', 'metrics')
TABLE_NAME = re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,62}$')
_TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<comment>--[^\n]*|/\*.*?\*/)
  | (?P<string>[Nn]?'(?:''|[^'])*')
  | (?P<bracket>\[(?:\]\]|[^\]])*\])
  | (?P<quoted>"(?:""|[^"])*")
  | (?P<var>@@?[A-Za-z_][A-Za-z0-9_]*)
  | (?P<number>\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)
  | (?P<word>[A-Za-z_#][A-Za-z0-9_$#]*)
  | (?P<op><>|!=|>=|<=|\|\||[-+*/%(),.;=<>!&|^~:])
""", re.S | re.X)


@dataclass
class Token:
    kind: str
    text: str
    line: int

    @property
    def upper(self) -> str:
        return self.text.upper() if self.kind == 'word' else self.text

    @property
    def significant(self) -> bool:
        return self.kind not in ('ws', 'comment')


def tokenize(text: str) -> list[Token]:
    tokens, position, line = [], 0, 1
    while position < len(text):
        match = _TOKEN.match(text, position)
        if not match:
            snippet = text[position:position + 12].split('\n')[0]
            if text[position] in "'[\"" or text.startswith('/*', position):
                raise PoolError(f"Unterminated string, identifier or comment near '{snippet}'", line=line)
            raise PoolError(f"Unexpected character near '{snippet}'", line=line)
        kind = match.lastgroup or 'op'
        value = match.group()
        tokens.append(Token(kind, value, line))
        line += value.count('\n')
        position = match.end()
    return tokens


@dataclass
class Statement:
    tokens: list[Token]
    line: int
    index: int = 0

    @property
    def text(self) -> str:
        return ''.join(t.text for t in self.tokens).strip()

    def significant(self) -> list[Token]:
        return [t for t in self.tokens if t.significant]


def split_statements(script: str) -> list[Statement]:
    """Statements of a script: batches split on GO lines, statements on top-level semicolons."""
    tokens = tokenize(script)
    batches: list[list[Token]] = [[]]
    for index, token in enumerate(tokens):
        if token.kind == 'word' and token.upper == 'GO' and _alone_on_line(tokens, index):
            batches.append([])
            continue
        batches[-1].append(token)
    statements: list[Statement] = []
    for batch in batches:
        significant = [t for t in batch if t.significant]
        if not significant:
            continue
        words = [t.upper for t in significant[:4]]
        if words[:1] == ['CREATE'] and ('PROC' in words[1:4] or 'PROCEDURE' in words[1:4]):
            statements.append(Statement(_trim(batch), significant[0].line))
            continue
        depth, current = 0, []
        for token in batch:
            if token.text == '(':
                depth += 1
            elif token.text == ')':
                depth -= 1
            if token.text == ';' and depth == 0:
                if any(t.significant for t in current):
                    statements.append(Statement(_trim(current), next(t for t in current if t.significant).line))
                current = []
                continue
            current.append(token)
        if any(t.significant for t in current):
            statements.append(Statement(_trim(current), next(t for t in current if t.significant).line))
    for index, statement in enumerate(statements, 1):
        statement.index = index
    return statements


def _alone_on_line(tokens: list[Token], index: int) -> bool:
    before = tokens[index - 1] if index else None
    after = tokens[index + 1] if index + 1 < len(tokens) else None
    starts = before is None or (before.kind == 'ws' and '\n' in before.text)
    ends = after is None or (after.kind == 'ws' and '\n' in after.text) or (
        after.kind == 'comment' and after.text.startswith('--'))
    return starts and ends


def _trim(tokens: list[Token]) -> list[Token]:
    start, end = 0, len(tokens)
    while start < end and not tokens[start].significant:
        start += 1
    while end > start and tokens[end - 1].kind == 'ws':
        end -= 1
    return tokens[start:end]


class Cursor:
    """Walks the significant tokens of a statement; slices keep whitespace for translation."""

    def __init__(self, tokens: list[Token], statement: Statement | None = None):
        self.tokens = list(tokens)
        self.sig = [n for n, t in enumerate(self.tokens) if t.significant]
        self.k = 0
        self.statement = statement

    def peek(self, offset: int = 0) -> Token | None:
        index = self.k + offset
        return self.tokens[self.sig[index]] if index < len(self.sig) else None

    def peek_upper(self, offset: int = 0) -> str:
        token = self.peek(offset)
        return token.upper if token else ''

    def next(self) -> Token:
        token = self.peek()
        if token is None:
            self.fail('Unexpected end of statement')
        self.k += 1
        return token

    def accept(self, *words: str) -> bool:
        if all(self.peek_upper(i) == w for i, w in enumerate(words)):
            self.k += len(words)
            return True
        return False

    def expect(self, *words: str) -> None:
        if not self.accept(*words):
            found = self.peek()
            self.fail(f"Expected {' '.join(words)}" + (f" near '{found.text}'" if found else ' at the end'))

    def at_end(self) -> bool:
        return self.k >= len(self.sig)

    def fail(self, message: str) -> None:
        token = self.peek()
        raise PoolError(message, line=token.line if token else (self.statement.line if self.statement else None))

    def rest(self) -> list[Token]:
        return self.tokens[self.sig[self.k]:] if self.k < len(self.sig) else []

    def parenthesized(self) -> list[Token]:
        """Tokens inside the next (...), whitespace included; consumed."""
        if self.peek_upper() != '(':
            self.fail("Expected '('")
        open_at = self.sig[self.k]
        close_at = _matching(self.tokens, open_at)
        while self.k < len(self.sig) and self.sig[self.k] <= close_at:
            self.k += 1
        return self.tokens[open_at + 1:close_at]


def split_commas(tokens: list[Token]) -> list[list[Token]]:
    parts, current, depth = [], [], 0
    for token in tokens:
        if token.text == '(':
            depth += 1
        elif token.text == ')':
            depth -= 1
        if token.text == ',' and depth == 0:
            parts.append(current)
            current = []
        else:
            current.append(token)
    if current or parts:
        parts.append(current)
    return parts


def identifier(token: Token) -> str:
    if token.kind == 'bracket':
        return token.text[1:-1].replace(']]', ']')
    if token.kind == 'quoted':
        return token.text[1:-1].replace('""', '"')
    if token.kind == 'word':
        return token.text
    raise PoolError(f"Expected a name, found '{token.text}'", line=token.line)


def read_name(cursor: Cursor, what: str = 'table') -> str:
    """schema.table in the lab: dbo is the warehouse schema; one-part names are in warehouse."""
    first = cursor.next()
    if first.kind == 'word' and first.text.startswith('#'):
        raise PoolError(f"Temporary tables (#{first.text[1:]}) are not simulated: create a regular warehouse table",
                        line=first.line)
    parts = [identifier(first)]
    while cursor.peek_upper() == '.':
        cursor.next()
        parts.append(identifier(cursor.next()))
    return lab_name(parts, what, first.line)


def lab_name(parts: list[str], what: str = 'table', line: int | None = None) -> str:
    if len(parts) > 2:
        raise PoolError(f"Three-part names ({'.'.join(parts)}) are not used in the lab: the pool is one database",
                        line=line)
    schema, table = (['warehouse'] + parts)[-2:] if len(parts) == 1 else parts
    schema = 'warehouse' if schema.lower() == 'dbo' else schema.lower()
    if schema not in LAYERS:
        raise PoolError(f"Schema '{schema}' does not exist in the lab pool; use dbo (the warehouse layer) or one of "
                        f"{', '.join(LAYERS)}", line=line)
    if not TABLE_NAME.fullmatch(table):
        raise PoolError(f"The {what} name '{table}' must start with a letter and use letters, digits and _",
                        line=line)
    return f"{schema}.{table.lower()}"


# -- types -------------------------------------------------------------------------------------------
# Data types a Fabric warehouse table can't use, with the type the Synapse migration maps them to.
FABRIC_TYPE_MAP = {'money': 'decimal(19,4)', 'smallmoney': 'decimal(10,4)', 'smalldatetime': 'datetime2',
                   'datetime': 'datetime2', 'nchar': 'char', 'nvarchar': 'varchar', 'tinyint': 'smallint',
                   'binary': 'varbinary', 'datetimeoffset': 'datetime2'}


def read_type(tokens: list[Token], position: int) -> tuple[str, str, int]:
    """(T-SQL type text, DuckDB type, next position) for a type starting at tokens[position]."""
    name = identifier(tokens[position]).lower()
    position += 1
    args: list[str] = []
    if position < len(tokens) and tokens[position].text == '(':
        depth, start = 0, position
        while True:
            if tokens[position].text == '(':
                depth += 1
            elif tokens[position].text == ')':
                depth -= 1
                if depth == 0:
                    break
            position += 1
        args = [a.upper for a in tokens[start + 1:position] if a.text != ',']
        position += 1
    try:
        duck = duckdb_type(name, args)  # the shared T-SQL type table (runtime/sqldialects/tsql.py)
    except ValueError:
        raise PoolError(f"Data type '{name}' is not simulated in the lab pool", line=tokens[position - 1].line) from None
    shown = name + (f"({', '.join(args)})" if args else '')
    return shown, duck, position


# -- WITH ( table options ) ---------------------------------------------------------------------------
@dataclass
class TableOptions:
    distribution: str | None = None
    hash_columns: list[str] = field(default_factory=list)
    index: str | None = None
    index_columns: list[str] = field(default_factory=list)
    partition: Partitioning | None = None
    cluster_by: list[str] = field(default_factory=list)
    mentioned: list[str] = field(default_factory=list)


def literal_value(tokens: list[Token], what: str = 'Partition boundaries') -> Any:
    """The value of a number or quoted string literal; `what` names the values in errors."""
    significant = [t for t in tokens if t.significant]
    sign = ''
    if significant and significant[0].text in '+-' and len(significant) == 2:
        sign, significant = significant[0].text, significant[1:]
    if len(significant) != 1:
        raise PoolError(f'{what} must be literal values', line=tokens[0].line if tokens else None)
    token = significant[0]
    if token.kind == 'number':
        return (int if re.fullmatch(r'\d+', token.text) else float)(sign + token.text)
    if token.kind == 'string':
        return token.text[token.text.index("'") + 1:-1].replace("''", "'")
    raise PoolError(f"{what} must be numbers or quoted literals, not '{token.text}'", line=token.line)


def read_options(tokens: list[Token]) -> TableOptions:
    options = TableOptions()
    for part in split_commas(tokens):
        cursor = Cursor(part)
        if cursor.at_end():
            continue
        if cursor.accept('DISTRIBUTION', '='):
            options.mentioned.append('DISTRIBUTION')
            if cursor.accept('HASH'):
                options.distribution = 'HASH'
                options.hash_columns = names(cursor.parenthesized())
                if not 1 <= len(options.hash_columns) <= 8:
                    cursor.fail('HASH distribution takes one to eight columns')
            elif cursor.accept('ROUND_ROBIN'):
                options.distribution = 'ROUND_ROBIN'
            elif cursor.accept('REPLICATE'):
                options.distribution = 'REPLICATE'
            else:
                cursor.fail('DISTRIBUTION is HASH(column), ROUND_ROBIN or REPLICATE')
        elif cursor.accept('CLUSTERED', 'COLUMNSTORE', 'INDEX'):
            options.mentioned.append('INDEX')
            options.index = 'CLUSTERED COLUMNSTORE INDEX'
            if cursor.accept('ORDER'):
                options.index_columns = names(cursor.parenthesized())
        elif cursor.accept('HEAP'):
            options.mentioned.append('INDEX')
            options.index = 'HEAP'
        elif cursor.accept('CLUSTERED', 'INDEX'):
            options.mentioned.append('INDEX')
            options.index = 'CLUSTERED INDEX'
            options.index_columns = names(cursor.parenthesized())
        elif cursor.accept('PARTITION'):
            options.mentioned.append('PARTITION')
            inner = Cursor(cursor.parenthesized())
            column = identifier(inner.next()).lower()
            inner.expect('RANGE')
            side = 'LEFT'
            if inner.accept('RIGHT'):
                side = 'RIGHT'
            else:
                inner.accept('LEFT')
            inner.expect('FOR', 'VALUES')
            values = [literal_value(v) for v in split_commas(inner.parenthesized()) if v]
            if values != sorted(values, key=_sort_key) or len(set(map(_sort_key, values))) != len(values):
                inner.fail('Partition boundary values must be distinct and in ascending order')
            options.partition = Partitioning(column, side, values)
        elif cursor.accept('CLUSTER', 'BY'):
            options.mentioned.append('CLUSTER BY')
            options.cluster_by = names(cursor.parenthesized())
        elif cursor.accept('LOCATION'):
            cursor.fail('LOCATION = USER_DB is for temporary tables, which the lab does not simulate')
        else:
            cursor.fail(f"Unknown table option '{cursor.peek().text}'")
        if not cursor.at_end():
            cursor.fail(f"Unexpected '{cursor.peek().text}' in the table options")
    return options


def names(tokens: list[Token]) -> list[str]:
    """Column names of a (a, [b] ASC, ...) list, lower case; sort directions are dropped."""
    out = []
    for part in split_commas(tokens):
        significant = [t for t in part if t.significant]
        if significant:
            out.append(identifier(significant[0]).lower())
    return out


def _sort_key(value: Any) -> tuple[int, Any]:
    return (0, value) if isinstance(value, (int, float)) else (1, str(value))


# -- queries, statements and expressions: the shared T-SQL dialect -------------------------------------------------
# Notes of the shared translator that the pool does not repeat on every statement.
QUIET_NOTES = {'OPTION (...) query hints are ignored: they do not change the result'}
STATEMENT_WORDS = {'SELECT', 'WITH', 'INSERT', 'UPDATE', 'DELETE', 'MERGE'}


@dataclass
class Translation:
    sql: str
    notes: list[str] = field(default_factory=list)


class Translator:
    """T-SQL text of a pool statement or expression -> DuckDB SQL, through the shared T-SQL dialect.

    Hooks: DECLARE/SET variables become literals, GETDATE() and CURRENT_TIMESTAMP read the lab's fixed clock, dbo is
    the warehouse schema, and unqualified names are typed as warehouse tables (the pool's search path)."""

    default_schema = 'warehouse'

    def __init__(self, variables: dict[str, Any] | None = None, now: datetime | None = None,
                 schema: dict[str, Any] | None = None):
        self.variables = {k.lower(): v for k, v in (variables or {}).items()}
        self.clock = now or datetime(2026, 3, 5, 12, 0, 0)
        self.schema = schema
        self.line: int | None = None

    def translate(self, tokens: list[Token]) -> Translation:
        tokens = [t for t in tokens if t.kind != 'comment']
        significant = [t for t in tokens if t.significant]
        self.line = significant[0].line if significant else None
        into = self._select_into(tokens)
        if into is not None:
            raise PoolError("SELECT ... INTO isn't supported in a dedicated SQL pool: use CREATE TABLE AS SELECT (CTAS)",
                            line=into.line)
        text = ''.join(t.text for t in tokens).strip()
        try:
            if significant and significant[0].upper in STATEMENT_WORDS:
                result = translate(text, 'tsql', mode='statement', schema=self.schema, hooks=self)
            else:
                result = translate_expression(text, 'tsql', schema=self.schema, hooks=self)
        except DialectError as error:
            raise PoolError(str(error), line=self.line) from error
        return Translation(result.sql, [note for note in result.rewrites if note not in QUIET_NOTES])

    # -- hooks of the shared translator ----------------------------------------------------------------------------
    def parameter(self, node: exp.Parameter) -> exp.Expression:
        key = node.name.lower()
        if key not in self.variables:
            raise PoolError(f'Must declare the scalar variable "@{node.name}".', line=self.line)
        value = self.variables[key]
        if value is None:
            return exp.Null()
        if isinstance(value, bool):
            return exp.Boolean(this=value)
        if isinstance(value, (int, float, Decimal)):
            literal = exp.Literal.number(str(abs(value)))
            return exp.Neg(this=literal) if value < 0 else literal
        if isinstance(value, datetime):
            return exp.Cast(this=exp.Literal.string(value.isoformat(sep=' ')), to=exp.DataType.build('TIMESTAMP'))
        if isinstance(value, date):
            return exp.Cast(this=exp.Literal.string(value.isoformat()), to=exp.DataType.build('DATE'))
        return exp.Literal.string(str(value))

    def now(self) -> exp.Expression:
        return exp.Cast(this=exp.Literal.string(self.clock.strftime('%Y-%m-%d %H:%M:%S')),
                        to=exp.DataType.build('TIMESTAMP'))

    def table(self, node: exp.Table) -> None:
        if node.db and node.db.lower() == 'dbo':
            node.set('db', exp.to_identifier('warehouse'))

    @staticmethod
    def _select_into(tokens: list[Token]) -> Token | None:
        """The INTO of a SELECT ... INTO (not INSERT INTO or MERGE INTO), outside parentheses."""
        seen_select, depth = False, 0
        for token in tokens:
            if token.text == '(':
                depth += 1
            elif token.text == ')':
                depth -= 1
            elif token.kind == 'word' and depth == 0:
                if token.upper in ('INSERT', 'MERGE'):
                    return None
                if token.upper == 'SELECT':
                    seen_select = True
                elif token.upper == 'INTO' and seen_select:
                    return token
        return None


def _matching(tokens: list[Token], open_at: int) -> int:
    depth = 0
    for k in range(open_at, len(tokens)):
        if tokens[k].text == '(':
            depth += 1
        elif tokens[k].text == ')':
            depth -= 1
            if depth == 0:
                return k
    raise PoolError("Missing ')'", line=tokens[open_at].line)


def sql_literal(value: Any) -> str:
    if value is None:
        return 'NULL'
    if isinstance(value, bool):
        return 'TRUE' if value else 'FALSE'
    if isinstance(value, (int, float)):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"
