"""Bounded T-SQL reader: split scripts, read the statements the lab supports, translate a subset to DuckDB SQL.

Nothing here executes SQL. Scripts are split on `;` and on `GO` lines (a stored
procedure takes its whole batch). Expressions are translated token by token:
[brackets] and "quotes" become DuckDB identifiers, N'...' strings become plain
strings, dbo maps to the lab's warehouse schema, and a documented set of
functions and types is rewritten (ISNULL, LEN, GETDATE, CONVERT, DATEADD,
DATEDIFF, DATEPART, CHARINDEX, IIF, EOMONTH, COUNT_BIG, TOP, OPTION hints).
String concatenation with + is not translated: use CONCAT.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

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
_TYPES = {
    'bigint': 'BIGINT', 'int': 'INTEGER', 'integer': 'INTEGER', 'smallint': 'SMALLINT', 'tinyint': 'UTINYINT',
    'bit': 'BOOLEAN', 'money': 'DECIMAL(19,4)', 'smallmoney': 'DECIMAL(10,4)', 'real': 'FLOAT', 'date': 'DATE',
    'time': 'TIME', 'datetime': 'TIMESTAMP', 'datetime2': 'TIMESTAMP', 'smalldatetime': 'TIMESTAMP',
    'datetimeoffset': 'TIMESTAMPTZ', 'char': 'VARCHAR', 'varchar': 'VARCHAR', 'nchar': 'VARCHAR',
    'nvarchar': 'VARCHAR', 'uniqueidentifier': 'UUID', 'binary': 'BLOB', 'varbinary': 'BLOB',
}
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
    if name in ('decimal', 'numeric'):
        precision = int(args[0]) if args and args[0].isdigit() else 18
        scale = int(args[1]) if len(args) > 1 and args[1].isdigit() else 0
        duck = f"DECIMAL({min(precision, 38)},{scale})"
    elif name == 'float':
        duck = 'FLOAT' if args and args[0].isdigit() and int(args[0]) <= 24 else 'DOUBLE'
    elif name in _TYPES:
        duck = _TYPES[name]
    else:
        raise PoolError(f"Data type '{name}' is not simulated in the lab pool", line=tokens[position - 1].line)
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


# -- expression translation ----------------------------------------------------------------------------
_DATE_PARTS = {'year': 'YEAR', 'yy': 'YEAR', 'yyyy': 'YEAR', 'quarter': 'QUARTER', 'qq': 'QUARTER', 'q': 'QUARTER',
               'month': 'MONTH', 'mm': 'MONTH', 'm': 'MONTH', 'week': 'WEEK', 'wk': 'WEEK', 'ww': 'WEEK',
               'day': 'DAY', 'dd': 'DAY', 'd': 'DAY', 'dayofyear': 'DOY', 'dy': 'DOY', 'y': 'DOY',
               'hour': 'HOUR', 'hh': 'HOUR', 'minute': 'MINUTE', 'mi': 'MINUTE', 'n': 'MINUTE',
               'second': 'SECOND', 'ss': 'SECOND', 's': 'SECOND', 'weekday': 'DOW', 'dw': 'DOW'}
_NOW_FUNCTIONS = {'GETDATE', 'SYSDATETIME', 'GETUTCDATE', 'SYSUTCDATETIME'}


@dataclass
class Translation:
    sql: str
    notes: list[str] = field(default_factory=list)


class Translator:
    """T-SQL expression and query text -> DuckDB SQL, for the lab's subset."""

    def __init__(self, variables: dict[str, Any] | None = None, now: datetime | None = None):
        self.variables = {k.lower(): v for k, v in (variables or {}).items()}
        self.now = now or datetime(2026, 3, 5, 12, 0, 0)
        self.notes: list[str] = []

    def translate(self, tokens: list[Token]) -> Translation:
        tokens = [t for t in tokens if t.kind != 'comment']
        tokens = self._strip_option_clause(tokens)
        tokens, limit = self._rewrite_tops(tokens)
        out: list[str] = []
        i = 0
        while i < len(tokens):
            token = tokens[i]
            i, text = self._token(tokens, i)
            out.append(text)
        sql = ''.join(out).strip()
        if limit is not None:
            sql += f" LIMIT {limit}"
        return Translation(sql, list(self.notes))

    # -- one token (or a rewritten call) -> text; returns the next position
    def _token(self, tokens: list[Token], i: int) -> tuple[int, str]:
        token = tokens[i]
        if token.kind == 'bracket' or token.kind == 'quoted':
            name = identifier(token)
            if self._is_schema_position(tokens, i) and name.lower() == 'dbo':
                return i + 1, 'warehouse'
            return i + 1, '"' + name.replace('"', '""') + '"'
        if token.kind == 'string':
            return i + 1, token.text[1:] if token.text[0] in 'Nn' else token.text
        if token.kind == 'var':
            key = token.text.lower().lstrip('@')
            if token.text.startswith('@@'):
                raise PoolError(f"System variable {token.text} is not simulated", line=token.line)
            if key not in self.variables:
                raise PoolError(f'Must declare the scalar variable "{token.text}".', line=token.line)
            return i + 1, sql_literal(self.variables[key])
        if token.kind != 'word':
            return i + 1, token.text
        upper = token.upper
        following = _next_significant(tokens, i)
        if upper == 'DBO' and following is not None and tokens[following].text == '.':
            return i + 1, 'warehouse'
        if following is not None and tokens[following].text == '(':
            if upper == 'ISNULL':
                return i + 1, 'COALESCE'
            if upper == 'LEN':
                return i + 1, 'length'
            if upper == 'COUNT_BIG':
                return i + 1, 'COUNT'
            if upper == 'IIF':
                return i + 1, 'if'
            if upper in _NOW_FUNCTIONS:
                end = _matching(tokens, following)
                return end + 1, f"TIMESTAMP '{self.now.strftime('%Y-%m-%d %H:%M:%S')}'"
            if upper in ('CONVERT', 'DATEADD', 'DATEDIFF', 'DATEPART', 'CHARINDEX', 'CAST', 'TRY_CAST', 'EOMONTH'):
                return self._call(tokens, i, following, upper)
        if upper == 'CURRENT_TIMESTAMP':
            return i + 1, f"TIMESTAMP '{self.now.strftime('%Y-%m-%d %H:%M:%S')}'"
        if upper == 'INTO' and self._select_into(tokens, i):
            raise PoolError("SELECT ... INTO isn't supported in a dedicated SQL pool: use CREATE TABLE AS SELECT (CTAS)",
                            line=token.line)
        return i + 1, token.text

    def _call(self, tokens: list[Token], i: int, open_at: int, name: str) -> tuple[int, str]:
        end = _matching(tokens, open_at)
        args = split_commas([t for t in tokens[open_at + 1:end]])
        sub = lambda part: Translator(self.variables, self.now).translate(part).sql

        def date(part: list[Token]) -> str:
            # T-SQL converts a string literal to datetime here; DuckDB needs the cast.
            significant = [t for t in part if t.significant]
            if len(significant) == 1 and significant[0].kind == 'string':
                return f"CAST({sub(part)} AS TIMESTAMP)"
            return sub(part)

        line = tokens[i].line
        if name in ('CAST', 'TRY_CAST'):
            inner = tokens[open_at + 1:end]
            as_at = _last_top_level(inner, 'AS')
            if as_at is None:
                raise PoolError(f"{name} needs 'AS type'", line=line)
            significant = [t for t in inner[as_at + 1:] if t.significant]
            _, duck, _ = read_type(significant, 0)
            return end + 1, f"{name}({sub(inner[:as_at])} AS {duck})"
        if name == 'CONVERT':
            if len(args) < 2:
                raise PoolError('CONVERT(type, expression[, style]) needs a type and an expression', line=line)
            type_tokens = [t for t in args[0] if t.significant]
            _, duck, _ = read_type(type_tokens, 0)
            if len(args) == 3:
                self.notes.append('CONVERT style argument ignored: the lab converts with CAST')
            return end + 1, f"CAST({sub(args[1])} AS {duck})"
        if name in ('DATEADD', 'DATEDIFF', 'DATEPART'):
            part_tokens = [t for t in args[0] if t.significant] if args else []
            part = _DATE_PARTS.get(part_tokens[0].text.lower().strip("'")) if len(part_tokens) == 1 else None
            if part is None:
                raise PoolError(f"{name} needs a date part such as day, month or year", line=line)
            if name == 'DATEADD':
                if len(args) != 3 or part in ('DOY', 'DOW'):
                    raise PoolError('DATEADD(part, number, date) is translated for year, quarter, month, week, day, '
                                    'hour, minute and second', line=line)
                amount = sub(args[1])
                if part == 'QUARTER':
                    return end + 1, f"({date(args[2])} + INTERVAL (3 * ({amount})) MONTH)"
                return end + 1, f"({date(args[2])} + INTERVAL ({amount}) {part})"
            if name == 'DATEDIFF':
                if len(args) != 3:
                    raise PoolError('DATEDIFF(part, start, end) takes three arguments', line=line)
                return end + 1, f"date_diff('{part.lower()}', {date(args[1])}, {date(args[2])})"
            if len(args) != 2:
                raise PoolError('DATEPART(part, date) takes two arguments', line=line)
            return end + 1, f"date_part('{part.lower()}', {date(args[1])})"
        if name == 'EOMONTH':
            if len(args) not in (1, 2):
                raise PoolError('EOMONTH(date[, months]) takes one or two arguments', line=line)
            day = f"CAST({date(args[0])} AS DATE)"
            if len(args) == 2:
                day = f"({day} + INTERVAL ({sub(args[1])}) MONTH)"
            return end + 1, f"last_day({day})"
        # CHARINDEX(substring, string) -> instr(string, substring)
        if len(args) != 2:
            raise PoolError('CHARINDEX(substring, string) is translated without a start position', line=line)
        return end + 1, f"instr({sub(args[1])}, {sub(args[0])})"

    @staticmethod
    def _is_schema_position(tokens: list[Token], i: int) -> bool:
        following = _next_significant(tokens, i)
        return following is not None and tokens[following].text == '.'

    @staticmethod
    def _select_into(tokens: list[Token], i: int) -> bool:
        previous = [t for t in tokens[:i] if t.significant]
        return any(t.upper == 'SELECT' for t in previous) and not any(t.upper in ('INSERT', 'MERGE') for t in previous)

    @staticmethod
    def _strip_option_clause(tokens: list[Token]) -> list[Token]:
        significant = [(n, t) for n, t in enumerate(tokens) if t.significant]
        depth = 0
        for n, token in significant:
            if token.text == '(':
                depth += 1
            elif token.text == ')':
                depth -= 1
            elif depth == 0 and token.upper == 'OPTION':
                following = _next_significant(tokens, n)
                if following is not None and tokens[following].text == '(':
                    return tokens[:n]
        return tokens

    def _rewrite_tops(self, tokens: list[Token]) -> tuple[list[Token], str | None]:
        """SELECT [DISTINCT] TOP n ... becomes ... LIMIT n: at the end of the statement for a top-level
        SELECT, before the closing parenthesis for a subquery or a CTE. Returns the top-level limit."""
        tokens = list(tokens)
        limit: str | None = None
        inserts: list[tuple[int, str]] = []
        opened: list[int] = []
        for n, token in enumerate(tokens):
            if not token.significant:
                continue
            if token.text == '(':
                opened.append(n)
            elif token.text == ')':
                if opened:
                    opened.pop()
            elif token.upper == 'SELECT':
                top = self._top_clause(tokens, n)
                if top is None:
                    continue
                value, first, last = top
                for k in range(first, last + 1):
                    tokens[k] = Token('ws', ' ', tokens[k].line)
                if opened:
                    inserts.append((_matching(tokens, opened[-1]), value))
                elif limit is None:
                    limit = value
                else:
                    raise PoolError('Only one top-level SELECT TOP is translated per statement', line=token.line)
        for close, value in sorted(inserts, reverse=True):
            tokens.insert(close, Token('word', f' LIMIT {value} ', tokens[close].line))
        return tokens, limit

    def _top_clause(self, tokens: list[Token], select_at: int) -> tuple[str, int, int] | None:
        """The TOP n after a SELECT [DISTINCT | ALL]: (n, first token, last token), or None."""
        top_at = _next_significant(tokens, select_at)
        if top_at is not None and tokens[top_at].upper in ('DISTINCT', 'ALL'):
            top_at = _next_significant(tokens, top_at)
        if top_at is None or tokens[top_at].upper != 'TOP':
            return None
        value_at = _next_significant(tokens, top_at)
        if value_at is None:
            raise PoolError('TOP needs a number', line=tokens[top_at].line)
        if tokens[value_at].text == '(':
            last = _matching(tokens, value_at)
            inner = [t for t in tokens[value_at + 1:last] if t.significant]
        else:
            last, inner = value_at, [tokens[value_at]]
        if len(inner) == 1 and inner[0].kind == 'var' and not inner[0].text.startswith('@@'):
            key = inner[0].text[1:].lower()
            if key not in self.variables:
                raise PoolError(f'Must declare the scalar variable "{inner[0].text}".', line=inner[0].line)
            value = str(self.variables[key])
        else:
            value = ''.join(t.text for t in inner)
        if not re.fullmatch(r'\d+', value):
            raise PoolError('TOP needs a whole number (or a variable holding one)', line=tokens[top_at].line)
        after = _next_significant(tokens, last)
        if after is not None and tokens[after].upper == 'PERCENT':
            raise PoolError('TOP ... PERCENT is not translated', line=tokens[top_at].line)
        if after is not None and tokens[after].upper == 'WITH':
            tie = _next_significant(tokens, after)
            if tie is not None and tokens[tie].upper == 'TIES':
                raise PoolError('TOP ... WITH TIES is not translated', line=tokens[top_at].line)
        return value, top_at, last


def _next_significant(tokens: list[Token], i: int) -> int | None:
    for k in range(i + 1, len(tokens)):
        if tokens[k].significant:
            return k
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


def _last_top_level(tokens: list[Token], word: str) -> int | None:
    depth, found = 0, None
    for k, token in enumerate(tokens):
        if token.text == '(':
            depth += 1
        elif token.text == ')':
            depth -= 1
        elif depth == 0 and token.upper == word:
            found = k
    return found


def sql_literal(value: Any) -> str:
    if value is None:
        return 'NULL'
    if isinstance(value, bool):
        return 'TRUE' if value else 'FALSE'
    if isinstance(value, (int, float)):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"
