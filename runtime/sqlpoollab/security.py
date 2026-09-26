"""Data security in the lab pool: row-level security, column-level security and dynamic data masking.

A documented subset of the T-SQL of Synapse dedicated SQL pool and Fabric Data Warehouse
(both support the three features):

- principals: CREATE USER <name> WITHOUT LOGIN | FROM EXTERNAL PROVIDER, CREATE ROLE,
  ALTER ROLE <role> ADD | DROP MEMBER <user>, DROP USER, DROP ROLE;
- row-level security: security predicates as inline table-valued functions
  (CREATE [OR ALTER] FUNCTION s.f(@p type, ...) RETURNS TABLE WITH SCHEMABINDING AS RETURN
  SELECT 1 AS result [FROM ...] WHERE ...) and CREATE SECURITY POLICY <name> ADD FILTER
  PREDICATE s.f(column, ...) ON <table> [, ...] [WITH (STATE = ON | OFF)], ALTER SECURITY POLICY
  <name> WITH (STATE = ON | OFF), DROP SECURITY POLICY, DROP FUNCTION. BLOCK predicates are refused;
- column-level security: GRANT | DENY | REVOKE SELECT ON <table>[(columns)] TO <principal>;
- dynamic data masking: ALTER TABLE <t> ALTER COLUMN <c> ADD MASKED WITH (FUNCTION = 'default()' |
  'email()' | 'partial(prefix,"padding",suffix)') and DROP MASKED; GRANT | REVOKE UNMASK TO <principal>;
- impersonation: EXECUTE AS USER = '<name>' and REVERT.

Enforcement is real on DuckDB: a SELECT is rewritten for the principal before it is translated.
Every table it reads that has an active filter predicate, or masked columns the principal
cannot unmask, becomes a derived table with the predicate as an EXISTS and the masks as
expressions; SELECT permissions are checked on the tables and on the columns the query uses.
Filter predicates apply to every principal, dbo included (as in SQL Server); dbo holds every
permission and sees unmasked data. Differences from SQL Server, stated in the lab: only SELECT
statements are secured (DML and DDL run as dbo; UPDATE and DELETE are not filtered), reads
through a view are not filtered, and a filter on a masked column compares the masked value
(SQL Server compares the real value, which is why masking is not a security boundary).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

import sqlglot
from sqlglot import exp

from .model import PoolError
from .tsql import Cursor, Statement, Token, identifier, lab_name, read_name, split_commas, tokenize

OWNER = 'dbo'
ALIAS = '__rls'
TRUTH_NOTE = 'T-SQL security translated to DuckDB, not SQL Server: the rows and values are enforced for real on the lab catalog.'
USER_FUNCTIONS = {'USER_NAME', 'SUSER_SNAME', 'SUSER_NAME', 'ORIGINAL_LOGIN', 'SYSTEM_USER'}
MEMBER_FUNCTIONS = {'IS_ROLEMEMBER', 'IS_MEMBER'}
REFUSED_FUNCTIONS = {'SESSION_CONTEXT': 'SESSION_CONTEXT is not simulated: base the predicate on USER_NAME() or a role',
                     'CONTEXT_INFO': 'CONTEXT_INFO is not simulated: base the predicate on USER_NAME() or a role',
                     'DATABASE_PRINCIPAL_ID': 'DATABASE_PRINCIPAL_ID is not simulated: use USER_NAME()'}
NUMERIC = re.compile(r'^(TINYINT|SMALLINT|INTEGER|INT|BIGINT|HUGEINT|DECIMAL|NUMERIC|DOUBLE|FLOAT|REAL)', re.I)
TEMPORAL = re.compile(r'^(DATE|TIMESTAMP|TIME)', re.I)
MASK = re.compile(r"^\s*(default|email|partial|random)\s*\((.*)\)\s*$", re.I | re.S)
PARTIAL = re.compile(r'^\s*(\d{1,3})\s*,\s*"([^"]{0,40})"\s*,\s*(\d{1,3})\s*$')


@dataclass
class Predicate:
    name: str
    parameters: list[str]  # names without @
    body: str  # the T-SQL SELECT the function returns


@dataclass
class Filter:
    function: str
    columns: list[str]
    table: str


@dataclass
class Policy:
    name: str
    filters: list[Filter]
    state: bool = True


@dataclass
class Permission:
    action: str  # GRANT | DENY
    permission: str  # SELECT | UNMASK
    principal: str
    table: str | None = None
    columns: tuple[str, ...] = ()


@dataclass
class Security:
    users: dict[str, str] = field(default_factory=dict)  # lower -> display
    roles: dict[str, set[str]] = field(default_factory=dict)  # lower -> lower members
    role_names: dict[str, str] = field(default_factory=dict)
    functions: dict[str, Predicate] = field(default_factory=dict)
    policies: dict[str, Policy] = field(default_factory=dict)
    permissions: list[Permission] = field(default_factory=list)
    masks: dict[str, dict[str, str]] = field(default_factory=dict)  # table -> column -> function text

    # -- persistence ---------------------------------------------------------------------------------
    def to_json(self) -> dict[str, Any]:
        return {'users': self.users, 'roles': {r: sorted(m) for r, m in self.roles.items()},
                'role_names': self.role_names,
                'functions': {k: {'name': f.name, 'parameters': f.parameters, 'body': f.body}
                              for k, f in self.functions.items()},
                'policies': {k: {'name': p.name, 'state': p.state,
                                 'filters': [{'function': f.function, 'columns': f.columns, 'table': f.table}
                                             for f in p.filters]} for k, p in self.policies.items()},
                'permissions': [{'action': p.action, 'permission': p.permission, 'principal': p.principal,
                                 'table': p.table, 'columns': list(p.columns)} for p in self.permissions],
                'masks': self.masks}

    @classmethod
    def from_json(cls, data: Any) -> 'Security':
        security = cls()
        if not isinstance(data, dict) or not data:
            return security
        try:
            security.users = dict(data.get('users', {}))
            security.roles = {r: set(m) for r, m in data.get('roles', {}).items()}
            security.role_names = dict(data.get('role_names', {}))
            security.functions = {k: Predicate(f['name'], list(f['parameters']), f['body'])
                                  for k, f in data.get('functions', {}).items()}
            security.policies = {k: Policy(p['name'], [Filter(f['function'], list(f['columns']), f['table'])
                                                       for f in p['filters']], bool(p['state']))
                                 for k, p in data.get('policies', {}).items()}
            security.permissions = [Permission(p['action'], p['permission'], p['principal'], p.get('table'),
                                               tuple(p.get('columns', ()))) for p in data.get('permissions', [])]
            security.masks = {t: dict(m) for t, m in data.get('masks', {}).items()}
        except (KeyError, TypeError, ValueError):
            return cls()
        return security

    # -- principals ----------------------------------------------------------------------------------
    def known(self, name: str) -> bool:
        key = name.lower()
        return key == OWNER or key in self.users or key in self.roles

    def memberships(self, principal: str) -> set[str]:
        key = principal.lower()
        found = {key, 'public'}
        found |= {role for role, members in self.roles.items() if key in members}
        if key == OWNER:
            found.add('db_owner')
        return found

    def display(self, principal: str) -> str:
        key = principal.lower()
        return self.users.get(key) or self.role_names.get(key) or principal

    # -- permissions ---------------------------------------------------------------------------------
    def can_unmask(self, principal: str) -> bool:
        if principal.lower() == OWNER:
            return True
        who = self.memberships(principal)
        granted = any(p.permission == 'UNMASK' and p.action == 'GRANT' and p.principal in who for p in self.permissions)
        denied = any(p.permission == 'UNMASK' and p.action == 'DENY' and p.principal in who for p in self.permissions)
        return granted and not denied

    def readable_columns(self, principal: str, table: str, columns: list[str]) -> tuple[bool, set[str]]:
        """(any SELECT grant on the table at all, the columns the principal may read)."""
        if principal.lower() == OWNER:
            return True, set(columns)
        who = self.memberships(principal)
        mine = [p for p in self.permissions if p.permission == 'SELECT' and p.table == table and p.principal in who]
        allowed: set[str] = set()
        for p in mine:
            if p.action == 'GRANT':
                allowed |= set(p.columns) if p.columns else set(columns)
        for p in mine:
            if p.action == 'DENY':
                allowed -= set(p.columns) if p.columns else set(columns)
        any_grant = any(p.action == 'GRANT' for p in mine)
        return any_grant, allowed

    def active_filters(self, table: str) -> list[Filter]:
        return [f for p in self.policies.values() if p.state for f in p.filters if f.table == table]

    def secured(self) -> bool:
        return bool(self.policies or self.masks)


# -- statements ----------------------------------------------------------------------------------------
def handles(statement: Statement) -> bool:
    words = [t.upper for t in statement.significant()[:4]]
    if not words:
        return False
    first, rest = words[0], words[1:]
    if first == 'CREATE':
        return bool(rest) and (rest[0] in ('USER', 'ROLE', 'FUNCTION', 'SECURITY') or rest[:3] == ['OR', 'ALTER', 'FUNCTION'])
    if first == 'ALTER':
        text = ' '.join(t.upper for t in statement.significant())
        return bool(rest) and (rest[0] in ('ROLE', 'SECURITY', 'USER') or ' MASKED' in text)
    if first == 'DROP':
        return bool(rest) and rest[0] in ('USER', 'ROLE', 'FUNCTION', 'SECURITY')
    if first in ('GRANT', 'DENY', 'REVOKE', 'REVERT'):
        return True
    return first in ('EXEC', 'EXECUTE') and bool(rest) and rest[0] == 'AS'


class SecurityStatements:
    """Runs the security statements of a pool script against its Security state."""

    def __init__(self, security: Security, columns: Callable[[str], list[tuple[str, str]]],
                 exists: Callable[[str], bool]):
        self.security = security
        self.columns = columns
        self.exists = exists
        self.principal: str | None = None  # EXECUTE AS USER; None is dbo

    def run(self, statement: Statement) -> tuple[str, str, str | None]:
        """(kind, message, target)."""
        cursor = Cursor(statement.tokens, statement)
        first = cursor.peek_upper()
        if first in ('EXEC', 'EXECUTE'):
            return self._execute_as(cursor, statement)
        if first == 'REVERT':
            cursor.next()
            was, self.principal = self.principal, None
            return 'REVERT', f"Back to dbo (was {was or 'dbo'}).", None
        if self.principal is not None:
            raise PoolError(f"You are running as {self.principal}: security statements need dbo. REVERT first.",
                            line=statement.line)
        if first == 'CREATE':
            return self._create(cursor, statement)
        if first == 'ALTER':
            return self._alter(cursor, statement)
        if first == 'DROP':
            return self._drop(cursor, statement)
        return self._permission(cursor, statement)

    # EXECUTE AS USER = 'name'
    def _execute_as(self, cursor: Cursor, statement: Statement) -> tuple[str, str, str | None]:
        cursor.next()
        cursor.expect('AS')
        if cursor.peek_upper() in ('LOGIN', 'CALLER', 'OWNER', 'SELF'):
            raise PoolError(f"EXECUTE AS {cursor.peek_upper()} is not simulated: use EXECUTE AS USER = '<name>'",
                            line=statement.line)
        cursor.expect('USER')
        cursor.expect('=')
        token = cursor.next()
        if token.kind != 'string':
            raise PoolError("EXECUTE AS USER takes the user's name as a string: EXECUTE AS USER = 'name'",
                            line=statement.line)
        name = token.text[1:-1].replace("''", "'")
        if self.principal is not None:
            raise PoolError('The lab runs one EXECUTE AS at a time: REVERT first', line=statement.line)
        if name.lower() == OWNER:
            return 'EXECUTE AS', 'Running as dbo.', None
        if name.lower() not in self.security.users:
            raise PoolError(f"Cannot execute as the database principal because the principal \"{name}\" does not "
                            "exist, this type of principal cannot be impersonated, or you do not have permission.",
                            line=statement.line)
        self.principal = self.security.display(name)
        return 'EXECUTE AS', f"Running as {self.principal} until REVERT.", None

    def _create(self, cursor: Cursor, statement: Statement) -> tuple[str, str, str | None]:
        cursor.expect('CREATE')
        security = self.security
        if cursor.accept('USER'):
            name = identifier(cursor.next())
            if cursor.accept('WITHOUT'):
                cursor.expect('LOGIN')
            elif cursor.accept('FROM'):
                cursor.expect('EXTERNAL', 'PROVIDER')
            elif not cursor.at_end():
                cursor.fail('CREATE USER takes WITHOUT LOGIN or FROM EXTERNAL PROVIDER in the lab')
            if security.known(name):
                raise PoolError(f"User, group, or role '{name}' already exists in the current database.",
                                line=statement.line)
            security.users[name.lower()] = name
            return 'CREATE USER', f"User {name} created (a lab principal: no login, no connection).", None
        if cursor.accept('ROLE'):
            name = identifier(cursor.next())
            if cursor.accept('AUTHORIZATION'):
                cursor.next()
            if security.known(name):
                raise PoolError(f"User, group, or role '{name}' already exists in the current database.",
                                line=statement.line)
            security.roles[name.lower()] = set()
            security.role_names[name.lower()] = name
            return 'CREATE ROLE', f"Role {name} created.", None
        if cursor.accept('SECURITY'):
            cursor.expect('POLICY')
            return self._policy(cursor, statement)
        replace = cursor.accept('OR', 'ALTER')
        cursor.expect('FUNCTION')
        return self._function(cursor, statement, replace)

    def _function(self, cursor: Cursor, statement: Statement, replace: bool) -> tuple[str, str, str | None]:
        start = cursor.peek()
        name = read_name(cursor, 'function')
        if name in self.security.functions and not replace:
            raise PoolError(f"There is already an object named '{name}' in the database.", line=statement.line)
        header = cursor.parenthesized()
        parameters = []
        for part in split_commas(header):
            sig = [t for t in part if t.significant]
            if not sig:
                continue
            if sig[0].kind != 'var':
                raise PoolError('Function parameters are written @name type', line=statement.line)
            parameters.append(sig[0].text[1:].lower())
        cursor.expect('RETURNS')
        if not cursor.accept('TABLE'):
            raise PoolError('Only inline table-valued functions (security predicates, RETURNS TABLE) are simulated',
                            line=statement.line)
        if cursor.accept('WITH'):
            cursor.expect('SCHEMABINDING')
        cursor.expect('AS')
        cursor.expect('RETURN')
        body = [t for t in cursor.rest() if t.kind != 'comment']
        text = ''.join(t.text for t in body).strip()
        while text.startswith('(') and text.endswith(')'):
            text = text[1:-1].strip()
        try:
            tree = sqlglot.parse_one(text, read='tsql')
        except sqlglot.errors.ParseError as exc:
            raise PoolError(f"The function body must be one SELECT: {str(exc).splitlines()[0]}",
                            line=statement.line) from None
        if not isinstance(tree, exp.Select):
            raise PoolError('A security predicate returns one SELECT (RETURN SELECT 1 AS result WHERE ...)',
                            line=statement.line)
        for node in tree.find_all(exp.Anonymous):
            refused = REFUSED_FUNCTIONS.get(str(node.this).upper())
            if refused:
                raise PoolError(refused, line=statement.line)
        used = {p.name.lower() for p in tree.find_all(exp.Parameter)}
        unknown = sorted(used - set(parameters))
        if unknown:
            raise PoolError(f'Must declare the scalar variable "@{unknown[0]}".', line=statement.line)
        self.security.functions[name] = Predicate(name, parameters, text)
        return ('CREATE FUNCTION', f"Security predicate {name}({', '.join('@' + p for p in parameters)}) created.",
                name)

    def _policy(self, cursor: Cursor, statement: Statement) -> tuple[str, str, str | None]:
        name = read_name(cursor, 'security policy')
        if name in self.security.policies:
            raise PoolError(f"There is already an object named '{name}' in the database.", line=statement.line)
        filters, state = self._predicates(cursor, statement)
        policy = Policy(name, filters, True if state is None else state)
        self.security.policies[name] = policy
        tables = sorted({f.table for f in filters})
        return ('CREATE SECURITY POLICY', f"Security policy {name} filters {', '.join(tables)} "
                f"({'ON' if policy.state else 'OFF'}).", name)

    def _predicates(self, cursor: Cursor, statement: Statement) -> tuple[list[Filter], bool | None]:
        filters: list[Filter] = []
        state = None
        rest = cursor.rest()
        split_at = next((i for i, t in enumerate(rest) if t.upper == 'WITH'), len(rest))
        for part in split_commas(rest[:split_at]):
            sub = Cursor(part, statement)
            if sub.at_end():
                continue
            sub.expect('ADD')
            kind = sub.next().upper
            if kind == 'BLOCK':
                raise PoolError('BLOCK predicates are not simulated in the lab: use FILTER predicates', line=statement.line)
            if kind != 'FILTER':
                sub.fail('Expected ADD FILTER PREDICATE')
            sub.expect('PREDICATE')
            function = read_name(sub, 'function')
            predicate = self.security.functions.get(function)
            if predicate is None:
                raise PoolError(f"Cannot find the object \"{function}\" because it does not exist.", line=statement.line)
            arguments = [identifier(next(t for t in a if t.significant)).lower()
                         for a in split_commas(sub.parenthesized()) if any(t.significant for t in a)]
            sub.expect('ON')
            table = read_name(sub)
            if not self.exists(table):
                raise PoolError(f"Invalid object name '{table}'.", line=statement.line)
            present = [c.lower() for c, _ in self.columns(table)]
            for column in arguments:
                if column not in present:
                    raise PoolError(f"Invalid column name '{column}'.", line=statement.line)
            if len(arguments) != len(predicate.parameters):
                raise PoolError(f"{function} takes {len(predicate.parameters)} argument(s); the predicate names "
                                f"{len(arguments)}", line=statement.line)
            filters.append(Filter(function, arguments, table))
        if split_at < len(rest):
            sub = Cursor(rest[split_at:], statement)
            sub.expect('WITH')
            inner = Cursor(sub.parenthesized(), statement)
            inner.expect('STATE')
            inner.expect('=')
            value = inner.next().upper
            if value not in ('ON', 'OFF'):
                inner.fail('STATE = ON or OFF')
            state = value == 'ON'
        return filters, state

    def _alter(self, cursor: Cursor, statement: Statement) -> tuple[str, str, str | None]:
        cursor.expect('ALTER')
        security = self.security
        if cursor.accept('ROLE'):
            role = identifier(cursor.next()).lower()
            if role not in security.roles:
                raise PoolError(f"Cannot alter the role '{role}', because it does not exist or you do not have "
                                "permission.", line=statement.line)
            verb = cursor.next().upper
            if verb not in ('ADD', 'DROP'):
                cursor.fail('ALTER ROLE ... ADD MEMBER or DROP MEMBER')
            cursor.expect('MEMBER')
            member = identifier(cursor.next())
            if member.lower() not in security.users:
                raise PoolError(f"Cannot add the principal '{member}', because it does not exist or you do not have "
                                "permission.", line=statement.line)
            if verb == 'ADD':
                security.roles[role].add(member.lower())
            else:
                security.roles[role].discard(member.lower())
            return ('ALTER ROLE', f"{security.display(member)} {'added to' if verb == 'ADD' else 'removed from'} "
                    f"{security.display(role)}.", None)
        if cursor.accept('SECURITY'):
            cursor.expect('POLICY')
            name = read_name(cursor, 'security policy')
            policy = security.policies.get(name)
            if policy is None:
                raise PoolError(f"Cannot find the object \"{name}\" because it does not exist.", line=statement.line)
            if cursor.peek_upper() in ('ADD', 'DROP', 'ALTER'):
                raise PoolError('ALTER SECURITY POLICY changes STATE only in the lab: DROP and CREATE the policy to '
                                'change its predicates', line=statement.line)
            _, state = self._predicates(cursor, statement)
            if state is None:
                cursor.fail('ALTER SECURITY POLICY ... WITH (STATE = ON | OFF)')
            policy.state = state
            return 'ALTER SECURITY POLICY', f"Security policy {name} is {'ON' if state else 'OFF'}.", name
        if cursor.accept('USER'):
            raise PoolError('ALTER USER is not simulated in the lab', line=statement.line)
        cursor.expect('TABLE')
        table = read_name(cursor)
        cursor.expect('ALTER')
        cursor.expect('COLUMN')
        column = identifier(cursor.next()).lower()
        present = {c.lower(): t for c, t in self.columns(table)}
        if column not in present:
            raise PoolError(f"Invalid column name '{column}'.", line=statement.line)
        if cursor.accept('DROP'):
            cursor.expect('MASKED')
            if column not in security.masks.get(table, {}):
                raise PoolError(f"Column '{column}' does not have a data masking function.", line=statement.line)
            del security.masks[table][column]
            if not security.masks[table]:
                del security.masks[table]
            return 'ALTER TABLE', f"Mask dropped from {table}.{column}.", table
        cursor.expect('ADD')
        cursor.expect('MASKED')
        cursor.expect('WITH')
        inner = Cursor(cursor.parenthesized(), statement)
        inner.expect('FUNCTION')
        inner.expect('=')
        token = inner.next()
        if token.kind != 'string':
            raise PoolError("MASKED WITH (FUNCTION = '<function>()') takes the function as a string",
                            line=statement.line)
        function = token.text[1:-1].replace("''", "'")
        mask_expression(function, 'x', present[column], statement.line)  # validates it
        security.masks.setdefault(table, {})[column] = function
        return 'ALTER TABLE', f"{table}.{column} is masked with {function} for principals without UNMASK.", table

    def _drop(self, cursor: Cursor, statement: Statement) -> tuple[str, str, str | None]:
        cursor.expect('DROP')
        security = self.security
        kind = cursor.next().upper
        if kind == 'SECURITY':
            cursor.expect('POLICY')
        if_exists = cursor.accept('IF', 'EXISTS')
        if kind in ('USER', 'ROLE'):
            name = identifier(cursor.next()).lower()
            store = security.users if kind == 'USER' else security.roles
            if name not in store:
                if if_exists:
                    return f'DROP {kind}', 'Nothing to drop.', None
                raise PoolError(f"Cannot drop the {kind.lower()} '{name}', because it does not exist or you do not "
                                "have permission.", line=statement.line)
            if kind == 'ROLE' and security.roles[name]:
                raise PoolError('The role has members. It must be empty before it can be dropped.', line=statement.line)
            del store[name]
            security.role_names.pop(name, None)
            for members in security.roles.values():
                members.discard(name)
            security.permissions = [p for p in security.permissions if p.principal != name]
            return f'DROP {kind}', f"Dropped {kind.lower()} {name}.", None
        name = read_name(cursor, 'function' if kind == 'FUNCTION' else 'security policy')
        store2: dict[str, Any] = security.functions if kind == 'FUNCTION' else security.policies
        if name not in store2:
            if if_exists:
                return f'DROP {kind}', 'Nothing to drop.', None
            raise PoolError(f"Cannot drop the {'function' if kind == 'FUNCTION' else 'security policy'} '{name}', "
                            "because it does not exist or you do not have permission.", line=statement.line)
        if kind == 'FUNCTION' and any(f.function == name for p in security.policies.values() for f in p.filters):
            raise PoolError(f"Cannot DROP FUNCTION '{name}' because it is being referenced by a security policy.",
                            line=statement.line)
        del store2[name]
        return ('DROP FUNCTION' if kind == 'FUNCTION' else 'DROP SECURITY POLICY'), f"Dropped {name}.", name

    # GRANT | DENY | REVOKE SELECT ON t[(cols)] TO p ; GRANT | REVOKE UNMASK TO p
    def _permission(self, cursor: Cursor, statement: Statement) -> tuple[str, str, str | None]:
        verb = cursor.next().upper
        permission = cursor.next().upper
        if permission not in ('SELECT', 'UNMASK'):
            raise PoolError(f"{verb} {permission} is not simulated in the lab: only SELECT (tables and columns) and "
                            "UNMASK", line=statement.line)
        table, columns = None, ()
        if permission == 'SELECT' or cursor.peek_upper() == 'ON':
            cursor.expect('ON')
            if cursor.peek_upper() == 'OBJECT':
                cursor.next()
                cursor.expect(':')
                cursor.expect(':')
            if permission == 'UNMASK':
                raise PoolError('The lab grants UNMASK on the database only: GRANT UNMASK TO <principal>',
                                line=statement.line)
            table = read_name(cursor)
            if not self.exists(table):
                raise PoolError(f"Cannot find the object '{table}', because it does not exist or you do not have "
                                "permission.", line=statement.line)
            if cursor.peek_upper() == '(':
                present = [c.lower() for c, _ in self.columns(table)]
                wanted = [identifier(next(t for t in part if t.significant)).lower()
                          for part in split_commas(cursor.parenthesized()) if any(t.significant for t in part)]
                for column in wanted:
                    if column not in present:
                        raise PoolError(f"Invalid column name '{column}'.", line=statement.line)
                columns = tuple(wanted)
        if not (cursor.accept('TO') or cursor.accept('FROM')):
            cursor.fail(f"{verb} ... TO <principal>")
        principals = []
        for part in split_commas(cursor.rest()):
            sig = [t for t in part if t.significant]
            if not sig:
                continue
            name = identifier(sig[0])
            if name.lower() == OWNER:
                raise PoolError('Cannot grant, deny, or revoke permissions to sa, dbo, entity owner, '
                                'information_schema, sys, or yourself.', line=statement.line)
            if not self.security.known(name):
                raise PoolError(f"Cannot find the user '{name}', because it does not exist or you do not have "
                                "permission.", line=statement.line)
            principals.append(name.lower())
        if not principals:
            cursor.fail(f"{verb} ... TO <principal>")
        for principal in principals:
            same = [p for p in self.security.permissions if p.permission == permission and p.principal == principal
                    and p.table == table and (not columns or p.columns == columns or not p.columns)]
            if verb == 'REVOKE':
                self.security.permissions = [p for p in self.security.permissions if p not in same]
            else:
                exact = [p for p in same if p.columns == columns]
                self.security.permissions = [p for p in self.security.permissions if p not in exact]
                self.security.permissions.append(Permission(verb, permission, principal, table, columns))
        what = permission + (f" ON {table}" if table else '') + (f" ({', '.join(columns)})" if columns else '')
        who = ', '.join(self.security.display(p) for p in principals)
        return verb, f"{verb} {what} {'FROM' if verb == 'REVOKE' else 'TO'} {who}.", table


# -- masks -----------------------------------------------------------------------------------------------
def mask_expression(function: str, column_sql: str, duck_type: str, line: int | None = None) -> str:
    """The T-SQL expression that masks a column, as SQL Server's masking functions show it."""
    match = MASK.match(function)
    if not match:
        raise PoolError(f"'{function}' is not a masking function: use default(), email() or "
                        "partial(prefix,\"padding\",suffix)", line=line)
    name, arguments = match.group(1).lower(), match.group(2).strip()
    numeric, temporal = bool(NUMERIC.match(duck_type)), bool(TEMPORAL.match(duck_type))
    if name == 'random':
        raise PoolError('random() masks are not simulated: their values are random. Use default() or partial()',
                        line=line)
    if name == 'default':
        if arguments:
            raise PoolError('default() takes no arguments', line=line)
        value = '0' if numeric else ("CAST('1900-01-01' AS DATE)" if temporal else "'XXXX'")
        return f"CASE WHEN {column_sql} IS NULL THEN NULL ELSE {value} END"
    if numeric or temporal:
        raise PoolError(f"{name}() masks string columns; this column is {duck_type}: use default()", line=line)
    if name == 'email':
        if arguments:
            raise PoolError('email() takes no arguments', line=line)
        return f"CASE WHEN {column_sql} IS NULL THEN NULL ELSE LEFT({column_sql}, 1) + 'XXX@XXXX.com' END"
    parts = PARTIAL.match(arguments)
    if not parts:
        raise PoolError('partial() takes (prefix, "padding", suffix), for example partial(2,"XXXX",1)', line=line)
    prefix, padding, suffix = int(parts.group(1)), parts.group(2).replace("'", "''"), int(parts.group(3))
    return (f"CASE WHEN {column_sql} IS NULL THEN NULL WHEN LEN({column_sql}) > {prefix + suffix} "
            f"THEN LEFT({column_sql}, {prefix}) + '{padding}' + RIGHT({column_sql}, {suffix}) ELSE '{padding}' END")


# -- enforcement --------------------------------------------------------------------------------------------
def _lab_table(node: exp.Table) -> str | None:
    parts = [p for p in (node.catalog, node.db, node.name) if p]
    try:
        return lab_name(parts)
    except PoolError:
        return None


def _bracket(name: str) -> str:
    return '[' + name.replace(']', ']]') + ']'


def rewrite(tokens: list[Token], security: Security, principal: str | None,
            columns: Callable[[str], list[tuple[str, str]]], exists: Callable[[str], bool],
            line: int | None = None) -> tuple[list[Token], list[str]]:
    """The learner's SELECT as the principal sees it: permission checks, row filters, masks. (tokens, notes)."""
    who = principal or OWNER
    impersonated = who.lower() != OWNER
    if not impersonated and not security.secured():
        return tokens, []
    text = ''.join(t.text for t in tokens if t.kind != 'comment').strip().rstrip(';')
    try:
        tree = sqlglot.parse_one(text, read='tsql')
    except sqlglot.errors.ParseError:
        if impersonated:
            raise PoolError('The lab could not read this query to apply your permissions', line=line) from None
        return tokens, []
    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    targets: list[tuple[exp.Table, str]] = []
    for node in list(tree.find_all(exp.Table)):
        if not node.db and node.name.lower() in ctes:
            continue
        name = _lab_table(node)
        if name and exists(name):
            targets.append((node, name))
    if not targets:
        return tokens, []
    notes: list[str] = []
    changed = False
    for node, name in targets:
        table_columns = columns(name)
        names = [c.lower() for c, _ in table_columns]
        if impersonated:
            _check_select(tree, node, name, names, security, who, line)
        filters = security.active_filters(name)
        masks = {} if security.can_unmask(who) else security.masks.get(name, {})
        if not filters and not masks:
            continue
        projection = []
        for column, duck_type in table_columns:
            ref = f"{ALIAS}.{_bracket(column)}"
            function = masks.get(column.lower())
            projection.append(f"{mask_expression(function, ref, duck_type, line)} AS {_bracket(column)}"
                              if function else ref)
        where = [f"EXISTS ({_predicate_sql(security, f, who)})" for f in filters]
        schema, table = name.split('.')
        inner = (f"SELECT {', '.join(projection)} FROM {schema}.{_bracket(table)} AS {ALIAS}"
                 + (f" WHERE {' AND '.join(where)}" if where else ''))
        alias = node.alias or node.name
        subquery = exp.Subquery(this=sqlglot.parse_one(inner, read='tsql'), alias=exp.TableAlias(
            this=exp.to_identifier(alias)))
        node.replace(subquery)
        changed = True
        if filters:
            notes.append(f"Row-level security: {name} filtered by {', '.join(sorted({f.function for f in filters}))} "
                         f"for {who}.")
        if masks:
            notes.append(f"Dynamic data masking: {', '.join(sorted(masks))} of {name} masked for {who}.")
    if not changed:
        return tokens, notes
    return tokenize(tree.sql(dialect='tsql')), [TRUTH_NOTE] + notes


def _check_select(tree: exp.Expression, node: exp.Table, name: str, names: list[str], security: Security,
                  who: str, line: int | None) -> None:
    any_grant, allowed = security.readable_columns(who, name, names)
    schema, table = name.split('.')
    shown_schema = 'dbo' if schema == 'warehouse' else schema
    if not allowed:
        raise PoolError(f"The SELECT permission was denied on the object '{table}', database 'lab', schema "
                        f"'{shown_schema}'.", line=line)
    used = _used_columns(tree, node, names)
    for column in used:
        if column not in allowed:
            raise PoolError(f"The SELECT permission was denied on the column '{column}' of the object '{table}', "
                            f"database 'lab', schema '{shown_schema}'.", line=line)


def _used_columns(tree: exp.Expression, node: exp.Table, names: list[str]) -> list[str]:
    """Columns of one table a query reads: its star, qualified references and unqualified names it has."""
    alias = (node.alias or node.name).lower()
    qualifiers = {alias, node.name.lower()}
    used: list[str] = []
    for star in tree.find_all(exp.Star):
        parent = star.parent
        if isinstance(parent, exp.Column):
            if parent.table.lower() in qualifiers:
                return list(names)
        elif isinstance(parent, exp.Select):
            return list(names)
    for column in tree.find_all(exp.Column):
        if isinstance(column.this, exp.Star):
            continue
        key = column.name.lower()
        if key in names and (not column.table or column.table.lower() in qualifiers) and key not in used:
            used.append(key)
    return used


def _predicate_sql(security: Security, flt: Filter, who: str) -> str:
    predicate = security.functions[flt.function]
    tree = sqlglot.parse_one(predicate.body, read='tsql')
    binding = dict(zip(predicate.parameters, flt.columns))
    memberships = security.memberships(who)

    def swap(node: exp.Expression) -> exp.Expression:
        if isinstance(node, exp.Parameter):
            return exp.column(binding[node.name.lower()], table=ALIAS)
        if isinstance(node, exp.CurrentUser):
            return exp.Literal.string(security.display(who))
        if isinstance(node, exp.Anonymous):
            fn = str(node.this).upper()
            if fn in USER_FUNCTIONS and not node.expressions:
                return exp.Literal.string(security.display(who))
            if fn in MEMBER_FUNCTIONS and len(node.expressions) == 1 and node.expressions[0].is_string:
                role = node.expressions[0].this.lower()
                return exp.Literal.number(1 if role in memberships else 0)
        return node

    return tree.transform(swap).sql(dialect='tsql')
