"""Plan-driven teaching simulation, separate from local relational execution.

All byte volumes, intermediate cardinalities and throughput are assumptions.
Only catalog row counts/result cardinalities supplied by the adapter are real.
No benchmark calibration, random numbers, or correctness grading lives here.

Exchange placement follows Spark's physical planning closely enough to count
shuffles honestly: an operator that needs rows clustered by keys K reuses an
existing hash partitioning on a subset of K instead of adding an exchange, a
broadcast join keeps the streamed side's partitioning, and Catalyst's
EliminateSorts drops a sort whose order a later join or order-insensitive
aggregate discards. Exchanges are still modeled, never measured.
"""
import re
from dataclasses import asdict
from .cost import credits
from .runtime import ClusterProfile, _schedule_stage, _finalize_job, _aqe_split
from .sparklab import Expr

# Spark refuses to broadcast a relation larger than 8 GB, even with a hint.
MAX_BROADCAST_MB = 8 * 1024

_WINDOW = re.compile(r' OVER \((?:PARTITION BY ((?:"(?:[^"]|"")*"(?:, )?)+))?')
_IDENT = re.compile(r'"((?:[^"]|"")*)"')
# Operators Catalyst's EliminateSorts can look through, and aggregate
# functions whose result never depends on input order (SUM/AVG are excluded:
# Spark keeps sorts under floating-point sums, and SparkLab plans carry no types).
_SORT_TRANSPARENT = {'filter', 'select', 'withColumn', 'drop', 'rename', 'alias'}
_ORDER_FREE_AGGREGATES = ('MIN(', 'MAX(', 'COUNT(')


def _window_specs(values):
    """PARTITION BY column lists of every window expression, in order. [] is a global window."""
    specs = []
    for value in values:
        if not isinstance(value, Expr):
            continue
        for match in _WINDOW.finditer(value.sql):
            spec = [name.replace('""', '"') for name in _IDENT.findall(match.group(1) or '')]
            if spec not in specs:
                specs.append(spec)
    return specs


def _kept_columns(cols):
    """Columns a select passes through unchanged; None when `*` keeps all of them."""
    kept = []
    for item in cols:
        if isinstance(item, str):
            if item == '*':
                return None
            kept.append(item)
            continue
        match = _IDENT.fullmatch(getattr(item, 'sql', ''))
        if match:
            name = match.group(1).replace('""', '"')
            if getattr(item, 'label', None) in (None, name):
                kept.append(name)
    return kept


def _is_window(op):
    # Only Column expressions: a join's `other` DataFrame also has a .sql property.
    values = op.detail['cols'] if op.kind == 'select' else op.detail.values()
    return any(isinstance(v, Expr) and ' OVER (' in v.sql for v in values)


def _sort_eliminated(ops, index, consumer):
    """True when Catalyst's EliminateSorts would remove the orderBy at ops[index]."""
    for op in ops[index + 1:]:
        if op.kind in _SORT_TRANSPARENT and not _is_window(op):
            continue
        if op.kind == 'aggregate':
            return all(getattr(e, 'sql', '').startswith(_ORDER_FREE_AGGREGATES) for e in op.detail['exprs'])
        return op.kind in {'join', 'distinct', 'orderBy'}
    return consumer == 'join'


def logical_plan(df):
    nodes = []
    def visit(frame, consumer=None):
        parent = len(nodes)
        nodes.append(dict(id=parent, operation='scan', source=frame.source, parents=[], dependency='narrow',
                          concept='Lazy catalog relation; Run requests a local result.'))
        for index, op in enumerate(frame.ops):
            parents = [parent]
            if op.kind == 'join':
                parents.append(visit(op.detail['other'], consumer='join'))
            window = _is_window(op)
            wide = op.kind in {'join','aggregate','orderBy','repartition','distinct','dedupe'} or window
            kind = 'window' if window else op.kind
            specs = _window_specs(op.detail['cols'] if op.kind == 'select' else op.detail.values()) if window else []
            concepts = {
                'join':'Match keys with duplicate-sensitive and SQL NULL semantics; broadcast or exchange inputs.',
                'aggregate':'Co-locate grouping keys across a shuffle boundary; partial aggregation is not modeled.',
                'window':'Exchange by partition keys then sort. A single ordered key cannot be split by AQE.',
                'orderBy':'Global range exchange and local sort; output ordering is semantic.',
                'repartition':'Explicit wide exchange; partition count changes virtual tasks, not rows.',
                'coalesce':'Reduce partitions without a new shuffle.',
                'distinct':'Shuffle to co-locate equal rows before removing duplicates.',
                'dedupe':'Shuffle by duplicate keys; the retained non-key values are unspecified.',
            }
            keys = None
            if op.kind == 'aggregate':
                keys = list(op.detail['keys'])
            elif op.kind == 'join':
                keys = list(op.detail['on'])
            elif op.kind == 'dedupe' and op.detail['cols'] is not None:
                keys = list(op.detail['cols'])
            elif op.kind == 'repartition':
                keys = list(op.detail['keys'])
            changed = ([op.detail['name']] if op.kind == 'withColumn' else list(op.detail['cols']) if op.kind == 'drop'
                       else [op.detail['existing']] if op.kind == 'rename' else [])
            parent = len(nodes)
            nodes.append(dict(id=parent, operation=kind, parents=parents,
                              dependency='wide' if wide else 'narrow',
                              concept=concepts.get(kind, 'Lazy narrow transformation; no independent Spark action.'),
                              global_window=(window and any(not spec for spec in specs)) or (kind=='aggregate' and not op.detail['keys']) or (kind=='dedupe' and op.detail['cols']==()),
                              join_type=op.detail.get('how'),
                              partitions=op.detail.get('n'), broadcast=bool(op.detail.get('broadcast')),
                              limit=op.detail.get('n') if kind == 'limit' else None,
                              keys=keys, window_partitions=specs,
                              kept_columns=_kept_columns(op.detail['cols']) if op.kind == 'select' else None,
                              changed_columns=changed,
                              sort_eliminated=op.kind == 'orderBy' and _sort_eliminated(frame.ops, index, consumer)))
        return parent
    visit(df)
    return nodes


def _clustered(current, required):
    """HashPartitioning(current) satisfies ClusteredDistribution(required)."""
    return bool(current) and set(current) <= set(required)


def _describe_keys(keys):
    return ', '.join(keys) if keys else 'all columns'


def simulate_plan(df, statistics, profile: ClusterProfile, aqe: bool, result_rows=None):
    nodes = logical_plan(df)
    stages, evidence, states = [], [], {}
    facts = dict(exchanges=0, shuffle_joins=0, broadcast_joins=0, global_windows=0,
                 output_partitions=0, exchange_details=[], refused_broadcasts=[])
    for node in nodes:
        kind, parents = node['operation'], node['parents']
        notes = []
        # (reason, partitioning, keys, modeled MB) for every Exchange this operator needs.
        exchanges = []
        if kind == 'scan':
            stat = statistics.get(node['source'], {})
            rows = int(stat.get('rows', 0))
            mb = float(stat.get('bytes', rows * 128)) / 1048576
            count = min(4096, int(stat.get('partitions', profile.default_partitions)))
            hot = float(stat.get('hot_fraction', 0))
            parts = [mb / max(count, 1)] * max(count, 1)
            if hot and count > 1:
                parts = [mb * hot] + [mb * (1-hot)/(count-1)] * (count-1)
            operator, shuffle = 'scan', 0.0
            input_rows = rows
            hash_keys = None
            pruning = stat.get('partition_pruning')
            if pruning:
                notes.append(
                    f"DuckLake identity-partition metadata reduced candidate files "
                    f"from {pruning['total_files']} to {pruning['candidate_files']} "
                    f"({pruning['pruned_files']} pruned before modeled scan)."
                )
        else:
            left = states[parents[0]]
            rows, mb, parts = left['rows'], left['mb'], list(left['parts'])
            hash_keys = left['hash_keys']
            input_rows = rows
            operator, shuffle = kind, 0.0
            if kind == 'join':
                right = states[parents[1]]
                input_rows += right['rows']
                keys = node['keys']
                # Unknown selectivity: conservative authored default, never claimed measured.
                eligible = node.get('join_type') not in {'full','full_outer','right','right_outer'}
                broadcast = eligible and (node['broadcast'] or (right['catalog_statistics_available'] and right['mb'] <= profile.broadcast_threshold_mb))
                if broadcast and right['mb'] > MAX_BROADCAST_MB:
                    broadcast = False
                    facts['refused_broadcasts'].append(dict(stage_id=node['id'], modeled_gb=round(right['mb'] / 1024, 3)))
                    notes.append(f"Real Spark fails a broadcast larger than 8 GB (modeled build side {right['mb'] / 1024:.1f} GB); modeled as a shuffle join instead")
                mb += right['mb']
                if broadcast:
                    operator = 'broadcast_join'
                    facts['broadcast_joins'] += 1
                    notes.append('Broadcast exchange to every active worker; the streamed side keeps its partitioning')
                else:
                    operator = 'shuffle_join'
                    facts['shuffle_joins'] += 1
                    left_ok = _clustered(left['hash_keys'], keys)
                    right_ok = _clustered(right['hash_keys'], keys)
                    if left_ok and right_ok and set(left['hash_keys']) != set(right['hash_keys']):
                        right_ok = False
                    target = tuple(left['hash_keys'] if left_ok else right['hash_keys'] if right_ok else keys)
                    if not left_ok:
                        exchanges.append(('join left side', 'hash', list(target), left['mb']))
                    if not right_ok:
                        exchanges.append(('join right side', 'hash', list(target), right['mb']))
                    if left_ok or right_ok:
                        notes.append('An input already hash-partitioned by the join key is reused without a new exchange')
                    else:
                        notes.append('Both inputs exchange by join keys')
                    hash_keys = None if node.get('join_type') in {'full', 'full_outer'} else target
            elif node['dependency'] == 'wide':
                if kind == 'orderBy' and node.get('sort_eliminated'):
                    notes.append('Catalyst EliminateSorts removes this sort: a later join or aggregate does not keep row order')
                elif kind == 'repartition':
                    exchanges.append(('repartition', 'hash' if node['keys'] else 'round robin', node['keys'] or None, mb))
                    hash_keys = tuple(node['keys']) or None
                elif kind == 'orderBy':
                    exchanges.append(('orderBy', 'range', None, mb))
                    hash_keys = None
                elif kind == 'window':
                    for spec in node['window_partitions']:
                        if not spec:
                            exchanges.append(('window without partitionBy', 'single partition', None, mb))
                            facts['global_windows'] += 1
                            hash_keys = None
                        elif _clustered(hash_keys, spec):
                            notes.append(f'Existing hash partitioning on {_describe_keys(hash_keys)} already clusters this window; no new exchange')
                        else:
                            exchanges.append(('window', 'hash', spec, mb))
                            hash_keys = tuple(spec)
                elif node.get('global_window'):
                    exchanges.append((kind, 'single partition', None, mb))
                    hash_keys = None
                else:
                    required = node['keys']  # None: every output column (distinct / full-row dedupe)
                    if (bool(hash_keys) if required is None else _clustered(hash_keys, required)):
                        notes.append(f'Existing hash partitioning on {_describe_keys(hash_keys)} already clusters these rows; no new exchange')
                    else:
                        exchanges.append((kind, 'hash', required, mb))
                        hash_keys = tuple(required) if required else None
            if exchanges:
                shuffle = sum(x[3] for x in exchanges) / 1024
                count = 1 if any(x[1] == 'single partition' for x in exchanges) else node['partitions'] if kind == 'repartition' else profile.shuffle_partitions
                hot_fraction = max(left['parts'], default=0) / max(left['mb'], 1e-12)
                parts = [mb/count] * count
                if hot_fraction > 5/count and count > 1:
                    parts = [mb*hot_fraction] + [mb*(1-hot_fraction)/(count-1)]*(count-1)
                if aqe and operator == 'shuffle_join':
                    parts, split_notes = _aqe_split(parts, {
                        'advisory_partition_mb': profile.advisory_partition_mb,
                        'skew_factor': 5, 'skew_threshold_mb': 256})
                    notes.extend(split_notes)
                if aqe and kind != 'repartition':
                    # Merge only contiguous small buckets, without splitting grouped/window keys.
                    merged, pending = [], 0.0
                    for part in parts:
                        if pending and pending + part > profile.advisory_partition_mb:
                            merged.append(pending); pending = 0.0
                        pending += part
                    if pending or not merged: merged.append(pending)
                    notes.append(f'AQE coalesced {len(parts)} buckets to {len(merged)} tasks')
                    parts = merged
                if kind in {'window','aggregate'}:
                    notes.append('Hot grouping/window keys remain co-located; no unsafe key splitting')
            elif kind == 'coalesce':
                target = min(len(parts), node['partitions'])
                merged = [0.0]*target
                for i, part in enumerate(parts): merged[min(target-1, i*target//len(parts))] += part
                parts = merged
            if kind == 'limit':
                rows = min(rows, node['limit'])
            # Narrow operators keep a hash partitioning only while its key columns survive unchanged.
            if kind in {'coalesce', 'limit'}:
                hash_keys = None
            if hash_keys and set(hash_keys) & set(node.get('changed_columns') or []):
                hash_keys = None
            if hash_keys and node.get('kept_columns') is not None and not set(hash_keys) <= set(node['kept_columns']):
                hash_keys = None
        before_count = len(parts)
        stage = _schedule_stage(len(stages), kind, operator, parts, profile,
                                shuffle_read_gb=shuffle, shuffle_write_gb=shuffle, notes=notes)
        # Each logical operator is a teaching stage (no codegen fusion claimed).
        stage.duration_s += profile.scheduler_overhead_s
        stages.append(stage)
        states[node['id']] = dict(rows=rows, mb=mb, parts=parts, hash_keys=hash_keys,
                                  catalog_statistics_available=stat.get('catalog_statistics_available',True) if kind=='scan' else left['catalog_statistics_available'])
        exchange_evidence = [dict(reason=reason, partitioning=partitioning, keys=keys, modeled_gb=round(size / 1024, 3))
                             for reason, partitioning, keys, size in exchanges]
        facts['exchanges'] += len(exchanges)
        facts['exchange_details'].extend(dict(stage_id=node['id'], operation=kind, **x) for x in exchange_evidence)
        data = asdict(stage)
        data.update(dependencies=parents, task_count=len(stage.tasks), tasks=data['tasks'][:12],
                    task_preview_only=len(stage.tasks)>12, input_rows=input_rows, output_rows=rows,
                    row_truth='assumed intermediate cardinality', input_bytes=round(mb*1048576),
                    output_bytes=round(mb*1048576), partitions=before_count,
                    scheduler_overhead_s=profile.scheduler_overhead_s,
                    straggler=stage.max_task_s > max(stage.p50_task_s, 0.001)*3,
                    broadcast_mb=states[parents[1]]['mb'] if operator=='broadcast_join' else 0,
                    sort=kind in {'window','orderBy'} and not node.get('sort_eliminated') or operator=='shuffle_join',
                    exchanges=exchange_evidence,
                    output_partitioning=list(hash_keys) if hash_keys else None,
                    storage_pruning=stat.get('partition_pruning') if kind=='scan' else None)
        evidence.append(data)
    facts['output_partitions'] = len(states[nodes[-1]['id']]['parts'])
    facts['truth'] = 'Modeled exchange placement over assumed input sizes; not Apache Spark telemetry'
    job = _finalize_job(profile, aqe, stages, {'model':'plan-driven-v2','fusion':'not modeled'})
    metrics = job.as_dict()
    metrics.pop('truth_confidence', None)
    metrics.update(stages=evidence, job_id='job-0', scheduler_overhead_s=len(stages)*profile.scheduler_overhead_s,
                   startup_overhead_s=profile.cold_start_seconds, plan_facts=facts)
    if result_rows is not None:
        metrics['local_result_rows'] = result_rows
    return job, metrics, nodes
