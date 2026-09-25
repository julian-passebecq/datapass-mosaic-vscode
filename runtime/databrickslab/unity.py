"""Unity Catalog in the lab: three-level names, owners, grants and the privilege checks of a job's principal.

The lab has one catalog, `main`. Its schemas are the lab's layers (source, bronze,
silver, gold, warehouse, features, metrics) plus `ml` for registered models; a
table `main.silver.orders` is the lab table `silver.orders`, and a two-level name
uses the default catalog `main`.

Privileges follow the Unity Catalog model:
- reading a table needs USE CATALOG on the catalog, USE SCHEMA on the schema and
  SELECT on the table; SELECT, MODIFY and USE SCHEMA granted on a schema or catalog
  are inherited by what it contains;
- writing to a table needs MODIFY and SELECT (plus the usage privileges);
- creating a table needs CREATE TABLE on the schema; its creator owns it;
- registering a model needs CREATE MODEL on the schema; loading one needs EXECUTE;
  setting an alias needs ownership of the model;
- an owner holds every privilege on its object; ALL PRIVILEGES implies the others;
- all users have USE CATALOG on `main` by default (the `account users` group).

Grants come from factory/databricks/grants.sql (GRANT / REVOKE / ALTER ... OWNER TO)
and groups from unity_catalog.json. Jobs run as their `run_as` principal; without
one they run as you, the workspace admin who owns the lab's existing objects.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

CATALOG = 'main'
LAB_USER = 'you@datapass.lab'
ALL_USERS = 'account users'
TABLE_SCHEMAS = ('source', 'bronze', 'silver', 'gold', 'warehouse', 'features', 'metrics')
MODEL_SCHEMAS = TABLE_SCHEMAS + ('ml',)
PRIVILEGES = {
    'CATALOG': {'USE CATALOG', 'USE SCHEMA', 'SELECT', 'MODIFY', 'CREATE SCHEMA', 'CREATE TABLE', 'CREATE MODEL',
                'EXECUTE', 'BROWSE', 'ALL PRIVILEGES'},
    'SCHEMA': {'USE SCHEMA', 'SELECT', 'MODIFY', 'CREATE TABLE', 'CREATE MODEL', 'EXECUTE', 'ALL PRIVILEGES'},
    'TABLE': {'SELECT', 'MODIFY', 'ALL PRIVILEGES'},
    'FUNCTION': {'EXECUTE', 'ALL PRIVILEGES'},  # registered models are functions in Unity Catalog
}
_NAME = re.compile(r'`[^`]+`|[A-Za-z_][\w-]*')


class PermissionDenied(ValueError):
    pass


def lab_table(name: str) -> str:
    """main.silver.orders or silver.orders -> silver.orders (errors name the Unity Catalog object)."""
    parts = [p.strip('`') for p in name.split('.')]
    if len(parts) == 3:
        if parts[0].lower() != CATALOG:
            raise ValueError(f"[NO_SUCH_CATALOG_EXCEPTION] Catalog '{parts[0]}' was not found: the lab has one "
                             f"Unity Catalog catalog, '{CATALOG}'" + (" (hive_metastore is the legacy metastore, "
                                                                       "not simulated)" if parts[0].lower() == 'hive_metastore' else ''))
        parts = parts[1:]
    if len(parts) != 2:
        raise ValueError(f"Name a table as catalog.schema.table or schema.table: {name!r}")
    return f"{parts[0].lower()}.{parts[1].lower()}"


def full_name(table: str) -> str:
    return f"{CATALOG}.{table}"


@dataclass
class Grant:
    privilege: str
    securable: str  # CATALOG | SCHEMA | TABLE | FUNCTION
    name: str  # main | main.silver | main.silver.orders | main.ml.model
    principal: str


@dataclass
class UnityCatalog:
    groups: dict[str, set[str]] = field(default_factory=dict)
    grants: list[Grant] = field(default_factory=list)
    owners: dict[str, str] = field(default_factory=dict)  # securable name -> owner (default: you)
    warnings: list[str] = field(default_factory=list)

    # -- identities --------------------------------------------------------------------------------
    def identities(self, principal: str) -> set[str]:
        found = {principal, ALL_USERS}
        for group, members in self.groups.items():
            if principal in members:
                found.add(group)
        return found

    def owner(self, name: str) -> str:
        return self.owners.get(name, LAB_USER)

    # -- checks ------------------------------------------------------------------------------------
    def has(self, principal: str, privilege: str, securable: str, name: str) -> bool:
        if principal == LAB_USER:
            return True
        who = self.identities(principal)
        chain = _chain(securable, name)
        if securable in ('TABLE', 'FUNCTION') and self.owner(name) in who:
            return True
        for kind, obj in chain:
            if kind in ('SCHEMA', 'CATALOG') and self.owner(obj) in who and obj == name:
                return True
            for grant in self.grants:
                if grant.principal in who and grant.name == obj and grant.securable == kind and (
                        grant.privilege == privilege or grant.privilege == 'ALL PRIVILEGES'):
                    return True
        if privilege == 'USE CATALOG' and name == CATALOG:
            return True  # all users have USE CATALOG on main by default
        return False

    def require(self, principal: str, privilege: str, securable: str, name: str) -> None:
        if not self.has(principal, privilege, securable, name):
            kind = {'CATALOG': 'Catalog', 'SCHEMA': 'Schema', 'TABLE': 'Table', 'FUNCTION': 'Model'}[securable]
            raise PermissionDenied(f"[INSUFFICIENT_PERMISSIONS] Insufficient privileges: User {principal} does not "
                                   f"have {privilege} on {kind} '{name}'.")

    def _usage(self, principal: str, schema: str) -> None:
        self.require(principal, 'USE CATALOG', 'CATALOG', CATALOG)
        self.require(principal, 'USE SCHEMA', 'SCHEMA', f"{CATALOG}.{schema}")

    def check_read(self, principal: str, table: str) -> None:
        self._usage(principal, table.split('.')[0])
        self.require(principal, 'SELECT', 'TABLE', full_name(table))

    def check_write(self, principal: str, table: str, exists: bool) -> None:
        schema = table.split('.')[0]
        if schema == 'source':
            raise PermissionDenied(f"The source layer is read-only in the lab: {full_name(table)}")
        self._usage(principal, schema)
        if exists:
            self.require(principal, 'MODIFY', 'TABLE', full_name(table))
            self.require(principal, 'SELECT', 'TABLE', full_name(table))
        else:
            self.require(principal, 'CREATE TABLE', 'SCHEMA', f"{CATALOG}.{schema}")

    def created(self, principal: str, table: str) -> None:
        if principal != LAB_USER and full_name(table) not in self.owners:
            self.owners[full_name(table)] = principal

    def check_model(self, principal: str, model: str, action: str, exists: bool) -> None:
        schema = model.split('.')[1]
        self._usage(principal, schema)
        if action == 'register':
            if not exists:
                self.require(principal, 'CREATE MODEL', 'SCHEMA', f"{CATALOG}.{schema}")
            elif self.owner(model) not in self.identities(principal) and principal != LAB_USER:
                raise PermissionDenied(f"[INSUFFICIENT_PERMISSIONS] User {principal} is not the owner of model "
                                       f"'{model}': only its owner can create new versions in the lab")
        elif action == 'alias':
            if principal != LAB_USER and self.owner(model) not in self.identities(principal):
                raise PermissionDenied(f"[INSUFFICIENT_PERMISSIONS] Only the owner of '{model}' can set its aliases")
        else:
            self.require(principal, 'EXECUTE', 'FUNCTION', model)

    # -- effective grants for the UI --------------------------------------------------------------
    def describe(self) -> dict[str, Any]:
        return {'catalog': CATALOG, 'lab_user': LAB_USER, 'groups': {g: sorted(m) for g, m in self.groups.items()},
                'grants': [{'privilege': g.privilege, 'securable': g.securable, 'name': g.name,
                            'principal': g.principal} for g in self.grants],
                'owners': dict(self.owners), 'warnings': list(self.warnings)}


def _chain(securable: str, name: str) -> list[tuple[str, str]]:
    parts = name.split('.')
    chain = [(securable, name)]
    if securable in ('TABLE', 'FUNCTION') and len(parts) == 3:
        chain += [('SCHEMA', '.'.join(parts[:2])), ('CATALOG', parts[0])]
    elif securable == 'SCHEMA' and len(parts) == 2:
        chain.append(('CATALOG', parts[0]))
    return chain


def load_unity(config: Any, grants_sql: str | None, owners: dict[str, str], existing_tables: set[str],
               models: set[str]) -> UnityCatalog:
    uc = UnityCatalog(owners=dict(owners))
    if isinstance(config, dict):
        for group, members in (config.get('groups') or {}).items():
            if isinstance(members, list) and all(isinstance(m, str) for m in members):
                uc.groups[str(group)] = set(members)
            else:
                uc.warnings.append(f"unity_catalog.json: group {group!r} needs a list of member names")
    if grants_sql:
        for number, statement in _statements(grants_sql):
            try:
                _apply(uc, statement, existing_tables, models)
            except ValueError as exc:
                uc.warnings.append(f"grants.sql line {number}: {exc}")
    return uc


def _statements(text: str) -> list[tuple[int, str]]:
    out, current, start = [], [], 1
    for number, line in enumerate(text.splitlines(), 1):
        code = line.split('--', 1)[0]
        if not current and code.strip():
            start = number
        current.append(code)
        if code.rstrip().endswith(';'):
            out.append((start, ' '.join(current).strip().rstrip(';').strip()))
            current = []
    if ''.join(current).strip():
        out.append((start, ' '.join(current).strip()))
    return out


_GRANT = re.compile(r'^(GRANT|REVOKE)\s+(.+?)\s+ON\s+(CATALOG|SCHEMA|TABLE|FUNCTION|MODEL)\s+(\S+)\s+(TO|FROM)\s+(.+)$',
                    re.I | re.S)
_OWNER = re.compile(r'^ALTER\s+(CATALOG|SCHEMA|TABLE|MODEL)\s+(\S+)\s+OWNER\s+TO\s+(.+)$', re.I | re.S)


def _principal(text: str) -> str:
    value = text.strip()
    if value.startswith('`') and value.endswith('`'):
        return value[1:-1]
    if not re.fullmatch(r'[\w.@-]+', value):
        raise ValueError(f"Quote principals with backticks: {value}")
    return value


def _object(kind: str, raw: str, existing_tables: set[str], models: set[str]) -> str:
    parts = [p.strip('`').lower() for p in raw.split('.')]
    if kind == 'CATALOG':
        if parts != [CATALOG]:
            raise ValueError(f"Catalog '{raw}' does not exist: the lab has one catalog, '{CATALOG}'")
        return CATALOG
    if len(parts) == 2 and kind != 'SCHEMA':
        parts = [CATALOG] + parts
    if parts[0] != CATALOG:
        raise ValueError(f"Catalog '{parts[0]}' does not exist: the lab has one catalog, '{CATALOG}'")
    if kind == 'SCHEMA':
        if len(parts) == 1:
            raise ValueError('Name the schema as main.<schema>')
        if len(parts) == 2 and parts[1] in MODEL_SCHEMAS:
            return f"{CATALOG}.{parts[1]}"
        raise ValueError(f"Schema '{raw}' does not exist (lab schemas: {', '.join(MODEL_SCHEMAS)})")
    if len(parts) != 3:
        raise ValueError(f"Name the object as main.<schema>.<name>: {raw}")
    name = '.'.join(parts)
    if kind == 'TABLE' and '.'.join(parts[1:]) not in existing_tables:
        raise ValueError(f"Table '{name}' does not exist yet; grant on the schema to cover tables created later. "
                         "Skipped")
    if kind in ('FUNCTION', 'MODEL') and name not in models:
        raise ValueError(f"Model '{name}' is not registered yet. Skipped")
    return name


def _apply(uc: UnityCatalog, statement: str, existing_tables: set[str], models: set[str]) -> None:
    owner = _OWNER.match(statement)
    if owner:
        kind = 'FUNCTION' if owner.group(1).upper() == 'MODEL' else owner.group(1).upper()
        uc.owners[_object(kind, owner.group(2), existing_tables, models)] = _principal(owner.group(3))
        return
    match = _GRANT.match(statement)
    if not match:
        raise ValueError('Only GRANT, REVOKE and ALTER ... OWNER TO statements are read from grants.sql')
    verb, privileges, kind, raw, _, principal = match.groups()
    kind = 'FUNCTION' if kind.upper() == 'MODEL' else kind.upper()
    name = _object(kind, raw, existing_tables, models)
    who = _principal(principal)
    for privilege in (' '.join(p.split()).upper() for p in privileges.split(',')):
        if privilege not in PRIVILEGES[kind]:
            raise ValueError(f"Privilege {privilege} is not applicable to a {kind.lower()} (applicable: "
                             f"{', '.join(sorted(PRIVILEGES[kind]))})")
        grant = Grant(privilege, kind, name, who)
        if verb.upper() == 'GRANT':
            if not any(g == grant for g in uc.grants):
                uc.grants.append(grant)
        else:
            uc.grants = [g for g in uc.grants if g != grant]
