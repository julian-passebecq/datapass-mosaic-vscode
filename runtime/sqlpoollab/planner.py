"""Rule-based model of a dedicated SQL pool's distributed plan: the data movement a query needs.

The query is the DuckDB translation of the learner's SELECT, parsed by DuckDB into
an AST (json_serialize_sql); nothing is guessed from text. Rules, from the Synapse
design guidance:

- A join needs no data movement when a side is replicated (the replicated side must
  not be the preserved side of an outer join), or when both sides are hash
  distributed on columns joined with = and of the same data type.
- Otherwise the smaller side is broadcast when it has at most 1/100 of the other
  side's rows (lab rule; the real optimizer is cost-based), else the sides that are
  not distributed on the join column are shuffled on it. Round-robin tables and
  derived tables (subqueries, CTEs) are never aligned.
- GROUP BY / DISTINCT aggregate locally when the stream is distributed on a grouped
  column, else the rows are shuffled on the grouping columns. A global aggregate
  combines 60 partial results.
- Partition elimination needs predicates on the partition column itself compared
  with constants (=, <, <=, >, >=, BETWEEN, IN); a function around the column
  (YEAR(order_date) = 2026) scans every partition.

Operation names follow Synapse's plans (ShuffleMoveOperation, BroadcastMoveOperation,
PartitionMoveOperation, ReturnOperation); row counts are at the lab's scale.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .model import DISTRIBUTIONS, TableDesign
from .physical import partition_range

BROADCAST_RATIO = 100
Column = tuple[str, str]  # (source alias, column), lower case


@dataclass
class Source:
    alias: str
    table: str | None  # schema.table, or None for a derived table
    design: TableDesign | None
    columns: dict[str, str]
    rows: float


@dataclass
class Stream:
    distribution: str  # HASH | ROUND_ROBIN | REPLICATE | UNKNOWN
    hash: list[set[Column]]
    rows: float
    aliases: set[str]
    label: str


@dataclass
class Plan:
    analyzed: bool
    steps: list[dict[str, Any]] = field(default_factory=list)
    scans: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    final: Any = None  # the Stream the query ends with (CTAS placement reads it)

    @property
    def movement(self) -> list[dict[str, Any]]:
        return [s for s in self.steps if s['operation'] != 'ReturnOperation']

    def to_json(self) -> dict[str, Any]:
        notes = list(self.notes)
        if self.analyzed and not self.movement:
            notes.insert(0, 'No data movement: every join and aggregation runs inside the distributions.')
        return {'analyzed': self.analyzed, 'steps': self.steps, 'scans': self.scans, 'notes': notes,
                'data_movement': bool(self.movement)}


class Context:
    """What the planner needs from the pool."""

    def __init__(self, serialize: Callable[[str], dict[str, Any]], design: Callable[[str], TableDesign | None],
                 columns: Callable[[str], dict[str, str]], rows_at_scale: Callable[[str], float],
                 exists: Callable[[str], bool]):
        self.serialize, self.design, self.columns, self.rows_at_scale, self.exists = (
            serialize, design, columns, rows_at_scale, exists)


def plan_select(sql: str, ctx: Context) -> Plan:
    tree = ctx.serialize(sql)
    if tree.get('error'):
        return Plan(False, notes=[f"Plan not analyzed: {tree.get('error_message', 'unsupported query')}"])
    node = tree['statements'][0]['node']
    if node.get('type') != 'SELECT_NODE':
        return Plan(False, notes=['Plan not analyzed: UNION and other set operations are planned branch by branch '
                                  'in Synapse; the lab analyzes single SELECT blocks.'])
    return _Planner(ctx, node).run()


class _Planner:
    def __init__(self, ctx: Context, node: dict[str, Any]):
        self.ctx = ctx
        self.node = node
        self.ctes = {entry['key'].lower() for entry in (node.get('cte_map') or {}).get('map', [])}
        self.sources: dict[str, Source] = {}
        self.plan = Plan(True)

    def run(self) -> Plan:
        from_table = self.node.get('from_table')
        if not from_table or from_table.get('type') == 'EMPTY':
            self.plan.steps.append(self._step('ReturnOperation', None, [], 1, 'No table: the control node returns the result.'))
            return self.plan
        stream = self._from(from_table)
        stream = self._aggregate(stream)
        self._scans()
        self.plan.steps.append(self._step('ReturnOperation', None, [], stream.rows,
                                          'The distributions send their results to the control node, which returns them.'))
        self.plan.final = stream
        return self.plan

    # -- FROM ------------------------------------------------------------------------------------
    def _from(self, ref: dict[str, Any]) -> Stream:
        kind = ref.get('type')
        if kind == 'JOIN':
            left = self._from(ref['left'])
            right = self._from(ref['right'])
            return self._join(left, right, ref)
        alias = (ref.get('alias') or ref.get('table_name') or f"derived{len(self.sources) + 1}").lower()
        if kind == 'BASE_TABLE' and ref.get('table_name', '').lower() not in self.ctes:
            schema = (ref.get('schema_name') or 'warehouse').lower()
            name = f"{schema}.{ref['table_name'].lower()}"
            design = self.ctx.design(name) if self.ctx.exists(name) else None
            columns = self.ctx.columns(name) if self.ctx.exists(name) else {}
            rows = self.ctx.rows_at_scale(name) if self.ctx.exists(name) else 0.0
            source = Source(alias, name, design, columns, rows)
            self.sources[alias] = source
            if design is None:
                return Stream('UNKNOWN', [], rows, {alias}, name)
            hashed = [{(alias, c.lower())} for c in design.hash_columns] if design.distribution == 'HASH' else []
            return Stream(design.distribution, hashed, rows, {alias}, name)
        label = ref.get('table_name') or alias
        self.sources[alias] = Source(alias, None, None, {}, 0.0)
        self.plan.notes.append(f"{label} is a derived table (subquery or CTE): the lab plans it as not distributed "
                               "on any column.")
        return Stream('UNKNOWN', [], 0.0, {alias}, str(label))

    def _join(self, left: Stream, right: Stream, ref: dict[str, Any]) -> Stream:
        join_type = (ref.get('join_type') or 'INNER').upper()
        pairs = self._pairs(ref.get('condition'), left, right)
        for column in ref.get('using_columns') or []:
            lcol = self._resolve_in([column], left.aliases)
            rcol = self._resolve_in([column], right.aliases)
            if lcol and rcol:
                pairs.append((lcol, rcol))
        rows = max(left.rows, right.rows)
        what = f"{left.label} {join_type} JOIN {right.label}"
        if ref.get('ref_type') == 'CROSS' or join_type == 'CROSS' or not pairs:
            small, large = (left, right) if left.rows <= right.rows else (right, left)
            if 'REPLICATE' not in (small.distribution, large.distribution):
                self._move('BroadcastMoveOperation', small, [], f"{what}: no equality condition, so every row must "
                                                               "meet every row: the smaller side is broadcast.")
            return Stream(large.distribution, large.hash, rows, left.aliases | right.aliases, what)
        # Replicated sides need no movement (a replicated preserved side of an outer join does).
        if right.distribution == 'REPLICATE' and join_type in ('INNER', 'LEFT'):
            self.plan.notes.append(f"{what}: {right.label} is replicated, so the join runs locally.")
            return Stream(left.distribution, left.hash, rows, left.aliases | right.aliases, what)
        if left.distribution == 'REPLICATE' and join_type in ('INNER', 'RIGHT'):
            self.plan.notes.append(f"{what}: {left.label} is replicated, so the join runs locally.")
            return Stream(right.distribution, right.hash, rows, left.aliases | right.aliases, what)
        aligned, reason, converted = self._aligned(left, right, pairs)
        if aligned:
            self.plan.notes.append(f"{what}: both sides are hash distributed on the join columns, so the join runs "
                                   "locally in each distribution.")
            merged = [l | r for l, r in zip(left.hash, right.hash)]
            for l, r in pairs:
                for group in merged:
                    if l in group or r in group:
                        group.update({l, r})
            return Stream('HASH', merged, rows, left.aliases | right.aliases, what)
        if reason:
            self.plan.notes.append(f"{what}: {reason}")
        small, large = (left, right) if left.rows <= right.rows else (right, left)
        can_broadcast = join_type == 'INNER' or (join_type == 'LEFT' and small is right) or (
            join_type == 'RIGHT' and small is left)
        if can_broadcast and small.distribution != 'REPLICATE' and small.rows * BROADCAST_RATIO <= large.rows:
            self._move('BroadcastMoveOperation', small, [], f"{what}: {small.label} is small next to {large.label}, "
                                                           "so a full copy is sent to every distribution.")
            return Stream(large.distribution, large.hash, rows, left.aliases | right.aliases, what)
        lcol, rcol = pairs[0]
        for side, column in ((left, lcol), (right, rcol)):
            local = side.distribution == 'HASH' and len(side.hash) == 1 and column in side.hash[0]
            if not local:
                self._move('ShuffleMoveOperation', side, [column],
                           f"{what}: {side.label} is not distributed on {column[1]}, so its rows are shuffled on it "
                           "to meet their matches.")
            elif converted and side is small:
                # The hash of a converted value differs: the lab moves the smaller side.
                self._move('ShuffleMoveOperation', side, [column],
                           f"{what}: {column[1]} has another data type on the other side, so {side.label}'s values "
                           "are converted and its rows shuffled on them.")
        return Stream('HASH', [{lcol, rcol}], rows, left.aliases | right.aliases, what)

    def _aligned(self, left: Stream, right: Stream,
                 pairs: list[tuple[Column, Column]]) -> tuple[bool, str, bool]:
        """Whether the join is distribution compatible; why not; whether only the data types differ."""
        if left.distribution != 'HASH' or right.distribution != 'HASH':
            kinds = {left.label: left.distribution, right.label: right.distribution}
            loose = [f"{label} is {kind.replace('_', '-').lower() if kind != 'UNKNOWN' else 'not distributed on a known column'}"
                     for label, kind in kinds.items() if kind != 'HASH']
            return False, '; '.join(loose) + ', so the join is not distribution compatible.', False
        if len(left.hash) != len(right.hash):
            return False, 'the two sides are hash distributed on different numbers of columns.', False
        for lset, rset in zip(left.hash, right.hash):
            match = [(l, r) for l, r in pairs if l in lset and r in rset]
            if not match:
                lname = sorted(c[1] for c in lset)[0]
                rname = sorted(c[1] for c in rset)[0]
                return False, (f"{left.label} is distributed on {lname} and {right.label} on {rname}, but the join does "
                               "not match those columns with =."), False
            l, r = match[0]
            ltype = self.sources[l[0]].columns.get(l[1], '')
            rtype = self.sources[r[0]].columns.get(r[1], '')
            if ltype and rtype and ltype != rtype:
                return False, f"{l[1]} is {ltype} on one side and {rtype} on the other: the data types must match.", True
        return True, '', False

    def _pairs(self, condition: dict[str, Any] | None, left: Stream, right: Stream) -> list[tuple[Column, Column]]:
        pairs: list[tuple[Column, Column]] = []
        if not condition:
            return pairs
        if condition.get('class') == 'CONJUNCTION' and condition.get('type') == 'CONJUNCTION_AND':
            for child in condition.get('children', []):
                pairs.extend(self._pairs(child, left, right))
            return pairs
        if condition.get('type') == 'COMPARE_EQUAL' and condition['left'].get('class') == 'COLUMN_REF' \
                and condition['right'].get('class') == 'COLUMN_REF':
            a, b = condition['left']['column_names'], condition['right']['column_names']
            la, rb = self._resolve_in(a, left.aliases), self._resolve_in(b, right.aliases)
            if la and rb:
                pairs.append((la, rb))
            else:
                lb, ra = self._resolve_in(b, left.aliases), self._resolve_in(a, right.aliases)
                if lb and ra:
                    pairs.append((lb, ra))
        return pairs

    def _resolve_in(self, names: list[str], aliases: set[str]) -> Column | None:
        names = [n.lower() for n in names]
        if len(names) >= 2:
            alias, column = names[-2], names[-1]
            if alias in aliases:
                return (alias, column)
            for candidate in aliases:  # a table referenced by name without an alias
                source = self.sources.get(candidate)
                if source and source.table and source.table.split('.')[1] == alias:
                    return (candidate, column)
            return None
        matches = [a for a in aliases if names[0] in self.sources.get(a, Source(a, None, None, {}, 0)).columns]
        return (matches[0], names[0]) if len(matches) == 1 else None

    # -- GROUP BY / DISTINCT ----------------------------------------------------------------------------
    def _aggregate(self, stream: Stream) -> Stream:
        groups = [g for g in self.node.get('group_expressions') or []]
        distinct = any(m.get('type') == 'DISTINCT_MODIFIER' for m in self.node.get('modifiers') or [])
        if not groups and distinct:
            groups = [e for e in self.node.get('select_list') or [] if e.get('class') == 'COLUMN_REF']
        aggregates = self._has_aggregate(self.node.get('select_list') or [])
        if not groups:
            if aggregates and stream.distribution != 'REPLICATE':
                self._step_add('PartitionMoveOperation', None, [], DISTRIBUTIONS,
                               'Global aggregate: each distribution aggregates its rows, then the 60 partial results '
                               'are moved to one place and combined.')
                return Stream('REPLICATE', [], 1, stream.aliases, 'aggregate')
            return stream
        columns = {c for c in (self._resolve_in(g['column_names'], stream.aliases) for g in groups
                               if g.get('class') == 'COLUMN_REF') if c}
        if stream.distribution == 'REPLICATE':
            self.plan.notes.append('Aggregation runs on a single copy of replicated data.')
            return stream
        if stream.distribution == 'HASH' and all(group & columns for group in stream.hash):
            self.plan.notes.append('GROUP BY includes the distribution column, so each distribution aggregates its '
                                   'own groups: no shuffle.')
            return stream
        label = ', '.join(sorted(c[1] for c in columns)) or 'the grouping expressions'
        self._move('ShuffleMoveOperation', stream, sorted(columns),
                   f"GROUP BY {label}: rows are shuffled on the grouping columns so each group ends up in one "
                   "distribution (Synapse aggregates partially first).")
        return Stream('HASH', [set(columns)] if columns else [], stream.rows, stream.aliases, 'aggregate')

    def _has_aggregate(self, expressions: list[dict[str, Any]]) -> bool:
        def visit(node: Any) -> bool:
            if isinstance(node, dict):
                if node.get('class') == 'AGGREGATE' or node.get('type') == 'AGGREGATE':
                    return True
                return any(visit(v) for v in node.values())
            if isinstance(node, list):
                return any(visit(v) for v in node)
            return False
        return visit(expressions)

    # -- partition elimination ----------------------------------------------------------------------
    def _scans(self) -> None:
        conjuncts = self._conjuncts(self.node.get('where_clause'))
        for alias, source in self.sources.items():
            if not source.design or not source.design.partition:
                continue
            partition = source.design.partition
            column = partition.column.lower()
            lows, highs, eq_sets, hidden = [], [], [], False
            for expression in conjuncts:
                found = self._range_predicate(expression, alias, column)
                if found == 'hidden':
                    hidden = True
                elif found:
                    kind, values = found
                    if kind == 'eq':
                        eq_sets.append(values)
                    elif kind == 'low':
                        lows.append(values)
                    elif kind == 'high':
                        highs.append(values)
                    elif kind == 'between':
                        lows.append((values[0], True))
                        highs.append((values[1], True))
            total = partition.count
            scanned = [n for n in range(1, total + 1)
                       if self._partition_may_match(partition, n, lows, highs, eq_sets)]
            eliminated = len(scanned) < total
            if eliminated:
                reason = f"Predicates on {column} let the pool skip {total - len(scanned)} of {total} partitions."
            elif hidden:
                reason = (f"{column} is wrapped in a function or cast in the WHERE clause, so the pool cannot use it to "
                          "skip partitions: compare the column itself with constants.")
            else:
                reason = f"No predicate on the partition column {column}: every partition is scanned."
            self.plan.scans.append({'table': source.table, 'alias': alias, 'partitions_scanned': len(scanned),
                                    'partitions_total': total, 'eliminated': eliminated, 'reason': reason})

    def _conjuncts(self, node: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not node:
            return []
        if node.get('class') == 'CONJUNCTION' and node.get('type') == 'CONJUNCTION_AND':
            return [c for child in node.get('children', []) for c in self._conjuncts(child)]
        return [node]

    def _column_of(self, node: dict[str, Any], alias: str, column: str) -> bool:
        if node.get('class') != 'COLUMN_REF':
            return False
        resolved = self._resolve_in(node['column_names'], set(self.sources))
        return resolved == (alias, column)

    def _mentions(self, node: Any, alias: str, column: str) -> bool:
        if isinstance(node, dict):
            if node.get('class') == 'COLUMN_REF':
                return self._column_of(node, alias, column)
            return any(self._mentions(v, alias, column) for v in node.values())
        if isinstance(node, list):
            return any(self._mentions(v, alias, column) for v in node)
        return False

    @staticmethod
    def _constant(node: dict[str, Any]) -> tuple[bool, Any]:
        if node.get('class') == 'CAST' and node.get('child', {}).get('class') == 'CONSTANT':
            node = node['child']
        if node.get('class') == 'CONSTANT':
            value = node.get('value', {})
            if value.get('is_null'):
                return False, None
            return True, value.get('value')
        return False, None

    def _range_predicate(self, node: dict[str, Any], alias: str, column: str) -> Any:
        kind = node.get('type', '')
        flip = {'COMPARE_GREATERTHAN': 'COMPARE_LESSTHAN', 'COMPARE_LESSTHAN': 'COMPARE_GREATERTHAN',
                'COMPARE_GREATERTHANOREQUALTO': 'COMPARE_LESSTHANOREQUALTO',
                'COMPARE_LESSTHANOREQUALTO': 'COMPARE_GREATERTHANOREQUALTO', 'COMPARE_EQUAL': 'COMPARE_EQUAL'}
        if node.get('class') == 'COMPARISON' and kind in flip:
            left, right = node['left'], node['right']
            if self._column_of(right, alias, column):
                left, right, kind = right, left, flip[kind]
            if self._column_of(left, alias, column):
                ok, value = self._constant(right)
                if not ok:
                    return None
                if kind == 'COMPARE_EQUAL':
                    return 'eq', [value]
                if kind in ('COMPARE_GREATERTHAN', 'COMPARE_GREATERTHANOREQUALTO'):
                    return 'low', (value, kind == 'COMPARE_GREATERTHANOREQUALTO')
                return 'high', (value, kind == 'COMPARE_LESSTHANOREQUALTO')
        if node.get('class') == 'BETWEEN' and self._column_of(node['input'], alias, column):
            ok_low, low = self._constant(node['lower'])
            ok_high, high = self._constant(node['upper'])
            if ok_low and ok_high:
                return 'between', (low, high)
        if kind == 'COMPARE_IN' and node.get('children') and self._column_of(node['children'][0], alias, column):
            values = [self._constant(c) for c in node['children'][1:]]
            if all(ok for ok, _ in values):
                return 'eq', [v for _, v in values]
        if self._mentions(node, alias, column):
            return 'hidden'
        return None

    def _partition_may_match(self, partition, number: int, lows, highs, eq_sets) -> bool:
        lower, upper = partition_range(partition, number)
        right = partition.range == 'RIGHT'

        def cmp(a: Any, b: Any) -> int:
            a, b = _comparable(a), _comparable(b)
            return (a > b) - (a < b)

        def contains(value: Any) -> bool:
            if lower is not None:
                c = cmp(value, lower)
                if (right and c < 0) or (not right and c <= 0):
                    return False
            if upper is not None:
                c = cmp(value, upper)
                if (right and c >= 0) or (not right and c > 0):
                    return False
            return True

        for values in eq_sets:
            if not any(contains(v) for v in values):
                return False
        for value, inclusive in lows:
            # rows must be >= / > value: the partition must reach above it
            if upper is not None:
                c = cmp(upper, value)
                if (right and c <= 0) or (not right and (c < 0 or (c == 0 and not inclusive))):
                    return False
        for value, inclusive in highs:
            if lower is not None:
                c = cmp(lower, value)
                if (right and (c > 0 or (c == 0 and not inclusive))) or (not right and c >= 0):
                    return False
        return True

    # -- steps ----------------------------------------------------------------------------------------
    def _step(self, operation: str, stream: Stream | None, columns: list[Column], rows: float, reason: str) -> dict[str, Any]:
        tables = sorted({self.sources[a].table for a in (stream.aliases if stream else set())
                         if self.sources.get(a) and self.sources[a].table})
        return {'operation': operation, 'tables': tables, 'columns': [c[1] for c in columns],
                'rows': round(rows), 'reason': reason}

    def _move(self, operation: str, stream: Stream, columns: list[Column], reason: str) -> None:
        self.plan.steps.append(self._step(operation, stream, columns, stream.rows, reason))

    def _step_add(self, operation: str, stream: Stream | None, columns: list[Column], rows: float, reason: str) -> None:
        self.plan.steps.append(self._step(operation, stream, columns, rows, reason))


def _comparable(value: Any) -> tuple[int, Any]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return (0, value)
    text = str(value)
    try:
        return (0, float(text)) if text.replace('.', '', 1).lstrip('-').isdigit() else (1, text)
    except ValueError:
        return (1, text)
