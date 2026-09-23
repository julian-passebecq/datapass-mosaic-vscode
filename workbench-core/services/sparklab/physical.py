"""Plan-driven teaching simulation, separate from local relational execution.

All byte volumes, intermediate cardinalities and throughput are assumptions.
Only catalog row counts/result cardinalities supplied by the adapter are real.
No benchmark calibration, random numbers, or correctness grading lives here.
"""
from dataclasses import asdict
from .cost import credits
from .runtime import ClusterProfile, _schedule_stage, _finalize_job, _aqe_split


def logical_plan(df):
    nodes = []
    def visit(frame):
        parent = len(nodes)
        nodes.append(dict(id=parent, operation='scan', source=frame.source, parents=[], dependency='narrow',
                          concept='Lazy catalog relation; Run requests a local result.'))
        for op in frame.ops:
            parents = [parent]
            if op.kind == 'join':
                parents.append(visit(op.detail['other']))
            window = any(' OVER (' in getattr(v, 'sql', '') for v in op.detail.values())
            if op.kind == 'select':
                window = any(' OVER (' in getattr(v, 'sql', '') for v in op.detail['cols'])
            wide = op.kind in {'join','aggregate','orderBy','repartition','distinct','dedupe'} or window
            kind = 'window' if window else op.kind
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
            parent = len(nodes)
            nodes.append(dict(id=parent, operation=kind, parents=parents,
                              dependency='wide' if wide else 'narrow',
                              concept=concepts.get(kind, 'Lazy narrow transformation; no independent Spark action.'),
                              global_window=(window and 'PARTITION BY' not in str(op.detail)) or (kind=='aggregate' and not op.detail['keys']) or (kind=='dedupe' and op.detail['cols']==()),
                              join_type=op.detail.get('how'),
                              partitions=op.detail.get('n'), broadcast=bool(op.detail.get('broadcast')),
                              limit=op.detail.get('n') if kind == 'limit' else None))
        return parent
    visit(df)
    return nodes


def simulate_plan(df, statistics, profile: ClusterProfile, aqe: bool, result_rows=None):
    nodes = logical_plan(df)
    stages, evidence, states = [], [], {}
    for node in nodes:
        kind, parents = node['operation'], node['parents']
        notes = []
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
            input_rows = rows
            operator, shuffle = kind, 0.0
            if kind == 'join':
                right = states[parents[1]]
                input_rows += right['rows']
                # Unknown selectivity: conservative authored default, never claimed measured.
                mb += right['mb']
                broadcast = (node['broadcast'] or (right['catalog_statistics_available'] and right['mb'] <= profile.broadcast_threshold_mb)) and node.get('join_type') not in {'full','full_outer','right','right_outer'}
                operator = 'broadcast_join' if broadcast else 'shuffle_join'
                notes.append('Broadcast exchange to every active worker' if broadcast else 'Both inputs exchange by join keys')
            if node['dependency'] == 'wide' and operator != 'broadcast_join':
                shuffle = mb / 1024
                count = 1 if node.get('global_window') else node['partitions'] if kind == 'repartition' else profile.shuffle_partitions
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
        before_count = len(parts)
        stage = _schedule_stage(len(stages), kind, operator, parts, profile,
                                shuffle_read_gb=shuffle, shuffle_write_gb=shuffle, notes=notes)
        # Each logical operator is a teaching stage (no codegen fusion claimed).
        stage.duration_s += profile.scheduler_overhead_s
        stages.append(stage)
        states[node['id']] = dict(rows=rows, mb=mb, parts=parts, catalog_statistics_available=stat.get('catalog_statistics_available',True) if kind=='scan' else left['catalog_statistics_available'])
        data = asdict(stage)
        data.update(dependencies=parents, task_count=len(stage.tasks), tasks=data['tasks'][:12],
                    task_preview_only=len(stage.tasks)>12, input_rows=input_rows, output_rows=rows,
                    row_truth='assumed intermediate cardinality', input_bytes=round(mb*1048576),
                    output_bytes=round(mb*1048576), partitions=before_count,
                    scheduler_overhead_s=profile.scheduler_overhead_s,
                    straggler=stage.max_task_s > max(stage.p50_task_s, 0.001)*3,
                    broadcast_mb=states[parents[1]]['mb'] if operator=='broadcast_join' else 0,
                    sort=kind in {'window','orderBy'} or operator=='shuffle_join',
                    storage_pruning=stat.get('partition_pruning') if kind=='scan' else None)
        evidence.append(data)
    job = _finalize_job(profile, aqe, stages, {'model':'plan-driven-v1','fusion':'not modeled'})
    metrics = job.as_dict()
    metrics.pop('truth_confidence', None)
    metrics.update(stages=evidence, job_id='job-0', scheduler_overhead_s=len(stages)*profile.scheduler_overhead_s,
                   startup_overhead_s=profile.cold_start_seconds)
    if result_rows is not None:
        metrics['local_result_rows'] = result_rows
    return job, metrics, nodes

