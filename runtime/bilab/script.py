"""Warehouse SQL scripts: split into statements with their line numbers, then run one by one on the catalog.

Every statement goes through the catalog's SQL contract (no file or network access, CREATE TABLE/VIEW,
INSERT, UPDATE, DELETE, MERGE, DROP, SELECT) and really runs on DuckDB. A script stops at its first error.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from datapass_runtime.catalog import Catalog, sql_tokens

MAX_STATEMENTS = 80
MAX_CHARS = 60_000
TARGET = re.compile(
    r'^\s*(?:CREATE\s+(?:OR\s+REPLACE\s+)?(?:TABLE|VIEW)(?:\s+IF\s+NOT\s+EXISTS)?|INSERT\s+(?:OR\s+\w+\s+)?INTO|'
    r'UPDATE|DELETE\s+FROM|MERGE\s+INTO|DROP\s+(?:TABLE|VIEW)(?:\s+IF\s+EXISTS)?)\s+'
    r'((?:source|bronze|silver|gold|warehouse|features|metrics)\.[A-Za-z][A-Za-z0-9_]*)', re.I)


class ScriptError(ValueError):
    pass


@dataclass
class Statement:
    index: int
    line: int
    text: str
    kind: str
    target: str | None


@dataclass
class StatementResult:
    index: int
    line: int
    kind: str
    target: str | None
    status: str = 'success'
    message: str = ''
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    affected: int | None = None

    def view(self) -> dict[str, Any]:
        return {'index': self.index, 'line': self.line, 'kind': self.kind, 'target': self.target,
                'status': self.status, 'message': self.message, 'columns': self.columns,
                'rows': self.rows[:50], 'affected': self.affected}


def statement_kind(text: str) -> str:
    clean = sql_tokens(text).strip()
    words = re.findall(r'[A-Za-z]+', clean[:80].upper())
    if not words:
        return ''
    if words[0] == 'CREATE':
        return 'CREATE VIEW' if 'VIEW' in words[:5] else 'CREATE TABLE'
    if words[0] == 'DROP':
        return 'DROP'
    return words[0]


def split_script(text: str) -> list[Statement]:
    """Statements in order, with the line each one starts on (comments before it are skipped)."""
    if len(text) > MAX_CHARS:
        raise ScriptError(f'The script is longer than {MAX_CHARS} characters.')
    out: list[Statement] = []
    current, start = '', 0
    for offset, char in enumerate(text):
        current += char
        if char == ';' and sqlite3.complete_statement(current):
            _append(out, current, text, start)
            current, start = '', offset + 1
    _append(out, current, text, start)
    if len(out) > MAX_STATEMENTS:
        raise ScriptError(f'The script has more than {MAX_STATEMENTS} statements.')
    return out


def _leading(chunk: str) -> int:
    """Offset of the statement's first token, past whitespace and comments (on the original text)."""
    i = 0
    while i < len(chunk):
        if chunk[i].isspace():
            i += 1
        elif chunk.startswith('--', i):
            end = chunk.find('\n', i)
            i = len(chunk) if end < 0 else end + 1
        elif chunk.startswith('/*', i):
            end = chunk.find('*/', i + 2)
            i = len(chunk) if end < 0 else end + 2
        else:
            break
    return i


def _append(out: list[Statement], chunk: str, text: str, start: int) -> None:
    if not sql_tokens(chunk).strip(' ;\r\n\t'):
        return
    line = text.count('\n', 0, start + _leading(chunk)) + 1
    body = chunk.strip()
    target = TARGET.match(sql_tokens(body))
    out.append(Statement(len(out) + 1, line, body, statement_kind(body), target.group(1).lower() if target else None))


def run_statements(catalog: Catalog, statements: list[Statement], producer: str) -> list[StatementResult]:
    results: list[StatementResult] = []
    for statement in statements:
        result = StatementResult(statement.index, statement.line, statement.kind, statement.target)
        results.append(result)
        try:
            outcome = catalog.execute(statement.text, producer)
        except Exception as error:  # the DuckDB or contract message is the lesson
            result.status = 'error'
            result.message = _message(error)
            break
        result.columns = list(outcome.get('columns') or [])
        rows = outcome.get('rows') or []
        if result.columns == ['Count'] and len(rows) == 1:
            result.affected = int(rows[0]['Count'] or 0)
        else:
            result.rows = rows
            if statement.kind in ('SELECT', 'WITH'):
                result.affected = outcome.get('total_rows')
    return results


def run_script(catalog: Catalog, text: str, producer: str) -> list[StatementResult]:
    return run_statements(catalog, split_script(text), producer)


def _message(error: Exception) -> str:
    text = str(error).strip()
    # DuckDB prefixes errors with their class ("Catalog Error: ..."); keep it, drop the "LINE n:" caret block.
    return re.split(r'\n\s*LINE \d+:', text)[0].strip()
