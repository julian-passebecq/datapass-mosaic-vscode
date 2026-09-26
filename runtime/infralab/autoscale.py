"""The simulated HorizontalPodAutoscaler (autoscaling/v2, CPU and memory utilization) and `lab load replay`.

A mission records the load a Deployment receives as a CPU demand curve (`world.kube.load`: the namespace, the
deployment, a start time and linear segments `[minutes, from millicores, to millicores]`). `lab load replay` plays it
in 15-second steps, the HPA controller's sync period, over a copy of the Deployment's pods:

- each ready pod takes an equal share of the demand, up to its CPU limit (above it the pod is throttled: the minute
  counts as overloaded); with no ready pod any demand is overloaded;
- utilization is the average usage of the ready pods over the pod's CPU request (the sum of its containers'); a
  container without a CPU request makes the metric unavailable and the HPA stops scaling (ScalingActive False,
  FailedGetResourceMetric), as the real controller does;
- desired = ceil(current × utilization / target), skipped inside the 10 % tolerance; when scaling up, pods that are
  not ready yet count as using nothing, and the scale-up is dropped if that reverses the direction;
- behaviour: the default scale-up (the larger of 4 pods or 100 % per 15 s, no stabilization) and scale-down (300 s
  stabilization: the highest recommendation of the window wins, then 100 % per 15 s), or the HPA's `behavior`;
  then minReplicas and maxReplicas;
- new pods are scheduled on the nodes by their requests (FailedScheduling when nothing fits) and become ready after
  the app's start time and readiness probe (`kube.container_status`).

The result (replicas, ready pods, utilization and overloaded minutes per minute) is kept in the world for the
mission checker, with a fingerprint of the HPA, the Deployment's pod template and the nodes, so a check can tell
whether the replay is still current. Nothing runs: this is arithmetic over a recorded curve.
"""
from __future__ import annotations

from datetime import timedelta
import hashlib
import json
import math
from typing import Any

from . import kube, world as worldlib

SYNC = 15
TOLERANCE = 0.1
DEFAULT_UP = {'stabilizationWindowSeconds': 0, 'selectPolicy': 'Max',
              'policies': [{'type': 'Pods', 'value': 4, 'periodSeconds': 15},
                           {'type': 'Percent', 'value': 100, 'periodSeconds': 15}]}
DEFAULT_DOWN = {'stabilizationWindowSeconds': 300, 'selectPolicy': 'Max',
                'policies': [{'type': 'Percent', 'value': 100, 'periodSeconds': 15}]}
MAX_MINUTES = 24 * 60


def hpas(world: dict, namespace: str | None = None) -> list[dict]:
    return sorted((o for o in kube.kube_state(world)['objects'].values() if o['kind'] == 'HorizontalPodAutoscaler'
                   and (namespace is None or o['namespace'] == namespace)), key=lambda o: (o['namespace'], o['name']))


def target_of(world: dict, hpa: dict) -> dict | None:
    ref = hpa['spec']['scaleTargetRef']
    return kube.kube_state(world)['objects'].get(kube.key('Deployment', hpa['namespace'], ref['name']))


def cpu_target(hpa: dict) -> tuple[str, int] | None:
    for metric in hpa['spec'].get('metrics') or []:
        resource = metric.get('resource') or {}
        return resource.get('name', 'cpu'), int(resource['target']['averageUtilization'])
    return ('cpu', 80) if not hpa['spec'].get('metrics') else None


def pod_resources(deployment: dict, resource: str = 'cpu') -> tuple[int | None, int, str | None]:
    """(request per pod or None when a container has none, limit per pod or 0, the container missing a request)."""
    containers = deployment['spec']['template']['spec']['containers']
    request = limit = 0
    for container in containers:
        res = container.get('resources') or {}
        # A limit without a request sets the request too, as the API server defaults it.
        value = (res.get('requests') or {}).get(resource, (res.get('limits') or {}).get(resource))
        if value is None:
            return None, 0, container['name']
        request += kube.cpu_millis(value) if resource == 'cpu' else kube.memory_mib(value)
        cap = (res.get('limits') or {}).get(resource)
        limit += (kube.cpu_millis(cap) if resource == 'cpu' else kube.memory_mib(cap)) if cap is not None else 0
    return request, limit, None


def bounds(hpa: dict) -> tuple[int, int]:
    return int(hpa['spec'].get('minReplicas', 1)), int(hpa['spec']['maxReplicas'])


def enforce_bounds(world: dict) -> None:
    """After an apply: an HPA keeps its Deployment inside [minReplicas, maxReplicas] at once."""
    for hpa in hpas(world):
        deployment = target_of(world, hpa)
        if deployment is None:
            continue
        low, high = bounds(hpa)
        replicas = int(deployment['spec'].get('replicas', 1))
        wanted = min(max(replicas, low), high)
        if wanted != replicas:
            kube.event(world, f'horizontalpodautoscaler/{hpa["name"]}', 'SuccessfulRescale',
                       f'New size: {wanted}; reason: Current number of replicas '
                       f'{"below Spec.MinReplicas" if wanted > replicas else "above Spec.MaxReplicas"}')
            kube.scale_to(world, deployment, wanted)


def scenarios(world: dict) -> list[dict]:
    return list(kube.kube_state(world).get('load') or [])


def demand_curve(scenario: dict) -> list[float]:
    """CPU demand (millicores) per minute."""
    out: list[float] = []
    for minutes, start, end in scenario['segments']:
        minutes = int(minutes)
        for i in range(minutes):
            out.append(start + (end - start) * (i / max(1, minutes - 1)) if minutes > 1 else start)
    return out[:MAX_MINUTES]


def fingerprint(world: dict, hpa: dict | None, deployment: dict) -> str:
    data = [hpa['spec'] if hpa else None, deployment['spec']['template'], kube.kube_state(world)['nodes']]
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]


def free_capacity(world: dict, deployment: dict) -> list[list[int]]:
    """[cpu, memory] left on each node once every pod except this Deployment's is placed."""
    k = kube.kube_state(world)
    out = []
    for node in k['nodes']:
        used_cpu = sum(p['cpu'] for p in k['pods'].values() if p['node'] == node['name']
                       and not (p['deployment'] == deployment['name'] and p['namespace'] == deployment['namespace']))
        used_mem = sum(p['mem'] for p in k['pods'].values() if p['node'] == node['name']
                       and not (p['deployment'] == deployment['name'] and p['namespace'] == deployment['namespace']))
        out.append([kube.cpu_millis(node['cpu']) - used_cpu, kube.memory_mib(node['memory']) - used_mem])
    return out


def recommend(rules: dict, history: list[tuple[int, int]], t: int, raw: int, current: int, up: bool) -> int:
    """Stabilization and rate policies of one direction."""
    window = int(rules.get('stabilizationWindowSeconds', 0))
    recent = [r for when, r in history if when > t - window] + [raw]
    stable = min(recent) if up else max(recent)
    if (up and stable <= current) or (not up and stable >= current):
        return current
    limits = []
    for policy in rules.get('policies') or []:
        value = int(policy['value'])
        change = value if policy['type'] == 'Pods' else math.ceil(current * value / 100) if up else \
            math.floor(current * value / 100)
        limits.append(current + change if up else current - change)
    if not limits:
        return stable
    select = rules.get('selectPolicy', 'Max')
    if select == 'Disabled':
        return current
    bound = (max(limits) if select == 'Max' else min(limits)) if up else \
        (min(limits) if select == 'Max' else max(limits))
    return min(stable, bound) if up else max(stable, bound)


def simulate(world: dict, scenario: dict, hpa: dict | None, deployment: dict) -> dict:
    curve = demand_curve(scenario)
    replicas = int(deployment['spec'].get('replicas', 1))
    request, limit, missing = pod_resources(deployment)
    container = deployment['spec']['template']['spec']['containers'][0]
    status = kube.container_status(world, container)
    ready_after = status['ready_after']
    cap = limit or 2000
    per_pod_request = request or 0
    free = free_capacity(world, deployment)
    pods: list[dict] = []           # {'ready_at': seconds or None, 'node': index or None}

    def place(t: int) -> dict:
        for index, room in enumerate(free):
            if room[0] >= per_pod_request:
                room[0] -= per_pod_request
                return {'ready_at': None if ready_after is None else t + ready_after, 'node': index}
        return {'ready_at': None, 'node': None}

    def remove(count: int) -> None:
        for _ in range(count):
            victim = sorted(pods, key=lambda p: (p['ready_at'] is not None, -(p['ready_at'] or 0)))[0]
            if victim['node'] is not None:
                free[victim['node']][0] += per_pod_request
            pods.remove(victim)

    for _ in range(replicas):
        pod = place(-600)
        if pod['ready_at'] is not None:
            pod['ready_at'] = -600
        pods.append(pod)
    target = cpu_target(hpa) if hpa else None
    low, high = bounds(hpa) if hpa else (replicas, replicas)
    behavior = (hpa or {}).get('spec', {}).get('behavior') or {}
    up_rules = {**DEFAULT_UP, **(behavior.get('scaleUp') or {})}
    down_rules = {**DEFAULT_DOWN, **(behavior.get('scaleDown') or {})}
    history: list[tuple[int, int]] = []
    minutes: list[dict] = []
    events: list[str] = []
    active, reason = True, ''
    if hpa and missing:
        active = False
        reason = (f'failed to get cpu utilization: missing request for cpu in container "{missing}" of Pod '
                  f'"{deployment["name"]}-{kube.template_hash(deployment["spec"]["template"])}-{kube.pod_suffix("0")}"')
    elif hpa and target is None:
        active, reason = False, 'no supported metric'
    elif hpa and target[0] != 'cpu':
        active, reason = False, 'the recorded load is CPU only: a memory target never moves in this replay'
    limited = False
    peak = replicas
    unschedulable = 0
    for minute, demand in enumerate(curve):
        overloaded = False
        utilization = None
        for step in range(60 // SYNC):
            t = minute * 60 + step * SYNC
            ready = [p for p in pods if p['ready_at'] is not None and p['ready_at'] <= t]
            per_pod = demand / len(ready) if ready else math.inf
            if demand > 0 and per_pod > cap:
                overloaded = True
            used = min(per_pod, cap) if ready else 0
            if request:
                utilization = round(used / request * 100) if ready else None
            if hpa is None or not active or not ready:
                continue
            ratio = (used / request) / (target[1] / 100)
            current = len(pods)
            if abs(ratio - 1) <= TOLERANCE:
                raw = current
            else:
                raw = math.ceil(current * ratio)
                if raw > current and len(ready) < current:
                    diluted = (used * len(ready) / current) / request / (target[1] / 100)
                    raw = current if diluted <= 1 else math.ceil(current * diluted)
            wanted = min(max(raw, low), high)
            limited = limited or raw > high
            if wanted > current:
                wanted = min(recommend(up_rules, history, t, wanted, current, True), high)
            elif wanted < current:
                wanted = max(recommend(down_rules, history, t, wanted, current, False), low)
            history.append((t, min(max(raw, low), high)))
            history[:] = [(when, r) for when, r in history if when > t - 3600]
            if wanted != current:
                why = 'above' if wanted > current else 'below'
                clock = worldlib.format_time(worldlib.parse_time(scenario['start']) + timedelta(seconds=t))[11:16]
                events.append(f'{clock}  New size: {wanted}; reason: cpu resource utilization (percentage of request) '
                              f'{why} target')
                if wanted > current:
                    for _ in range(wanted - current):
                        pod = place(t)
                        unschedulable += pod['node'] is None
                        pods.append(pod)
                else:
                    remove(current - wanted)
                peak = max(peak, wanted)
        ready_count = sum(p['ready_at'] is not None and p['ready_at'] <= minute * 60 + 59 for p in pods)
        minutes.append({'minute': minute, 'demand': round(demand), 'replicas': len(pods), 'ready': ready_count,
                        'utilization': utilization, 'overloaded': overloaded})
    return {'namespace': deployment['namespace'], 'deployment': deployment['name'], 'hpa': hpa['name'] if hpa else None,
            'start': scenario['start'], 'active': active, 'reason': reason, 'limited': limited,
            'target': target[1] if target else None, 'min': low, 'max': high, 'request_m': request,
            'limit_m': limit or None, 'initial_replicas': replicas, 'final_replicas': len(pods),
            'peak_replicas': peak, 'unschedulable': unschedulable,
            'overloaded_minutes': [m['minute'] for m in minutes if m['overloaded']], 'minutes': minutes,
            'events': events[-40:], 'fingerprint': fingerprint(world, hpa, deployment), 'at': world['clock']}


def clock_of(record: dict, minute: int) -> str:
    return worldlib.format_time(worldlib.parse_time(record['start']) + timedelta(minutes=minute))[11:16]


def spans(minutes: list[int]) -> list[tuple[int, int]]:
    out: list[list[int]] = []
    for m in minutes:
        if out and m == out[-1][1] + 1:
            out[-1][1] = m
        else:
            out.append([m, m])
    return [(a, b) for a, b in out]


def replay(world: dict, args: list[str]) -> tuple[str, int, dict]:
    if args[:2] != ['load', 'replay']:
        return ('Datapass lab commands (not Kubernetes):\n  lab load replay     replay the recorded load against the '
                'cluster; HorizontalPodAutoscalers react to it\n'), 0, {}
    k = kube.kube_state(world)
    lines = []
    records = []
    if not scenarios(world):
        return f'{kube.YELLOW}This mission records no load to replay.{kube.RESET}\n', 1, {}
    for scenario in scenarios(world):
        deployment = k['objects'].get(kube.key('Deployment', scenario['namespace'], scenario['deployment']))
        title = f'{scenario["namespace"]}/{scenario["deployment"]}'
        if deployment is None:
            lines.append(f'{kube.RED}deployment {title} does not exist: nothing receives the load{kube.RESET}')
            continue
        hpa = next((h for h in hpas(world, scenario['namespace'])
                    if h['spec']['scaleTargetRef']['name'] == scenario['deployment']), None)
        record = simulate(world, scenario, hpa, deployment)
        records.append(record)
        lines.append(f'{kube.BOLD}Replaying "{scenario.get("title", "recorded load")}" on {title}{kube.RESET} '
                     f'{kube.DIM}(Datapass lab command: {len(record["minutes"])} recorded minutes, the HPA synced every '
                     f'{SYNC} s; nothing runs){kube.RESET}')
        if hpa is None:
            lines.append(f'  {kube.YELLOW}no HorizontalPodAutoscaler targets {scenario["deployment"]}: it stays at '
                         f'{record["initial_replicas"]} replica(s){kube.RESET}')
        else:
            lines.append(f'  hpa/{hpa["name"]}: cpu target {record["target"]}% of request '
                         f'({record["request_m"] if record["request_m"] is not None else "no"}m), '
                         f'{record["min"]}..{record["max"]} replicas')
            if not record['active']:
                lines.append(f'  {kube.RED}ScalingActive False: {record["reason"]}{kube.RESET}')
        rows = [('TIME', 'CPU DEMAND', 'REPLICAS', 'READY', 'CPU/REQUEST', '')]
        shown = set(range(0, len(record['minutes']), 15)) | {len(record['minutes']) - 1}
        for prev, cur in zip(record['minutes'], record['minutes'][1:]):
            if cur['replicas'] != prev['replicas'] or cur['overloaded'] != prev['overloaded']:
                shown.add(cur['minute'])
        for m in record['minutes']:
            if m['minute'] in shown:
                util = '<unknown>' if m['utilization'] is None else f'{m["utilization"]}%'
                if record['target']:
                    util += f'/{record["target"]}%'
                rows.append((clock_of(record, m['minute']), f'{m["demand"]}m', m['replicas'], m['ready'], util,
                             f'{kube.RED}overloaded{kube.RESET}' if m['overloaded'] else ''))
        lines.append(kube.table(rows).rstrip('\n'))
        peak = max(record['minutes'], key=lambda m: m['demand']) if record['minutes'] else None
        summary = [f'Peak demand {peak["demand"]}m at {clock_of(record, peak["minute"])}' if peak else '',
                   f'replicas {record["initial_replicas"]} -> {record["peak_replicas"]} (peak) -> '
                   f'{record["final_replicas"]} (end)']
        lines.append('  ' + '; '.join(s for s in summary if s) + '.')
        if record['unschedulable']:
            lines.append(f'  {kube.YELLOW}{record["unschedulable"]} new pod(s) stayed Pending: FailedScheduling, '
                         f'Insufficient cpu (each asks for {record["request_m"]}m){kube.RESET}')
        if record['overloaded_minutes']:
            ranges = ', '.join(f'{clock_of(record, a)}' + (f'-{clock_of(record, b)}' if b > a else '')
                               for a, b in spans(record['overloaded_minutes'])[:6])
            lines.append(f'  {kube.RED}{len(record["overloaded_minutes"])} overloaded minute(s): {ranges} (every ready '
                         f'pod at its CPU limit of {record["limit_m"] or 2000}m: throttled, requests queue){kube.RESET}')
        else:
            lines.append(f'  {kube.GREEN}No overloaded minute.{kube.RESET}')
        # The cluster ends as the replay left it.
        if record['final_replicas'] != int(deployment['spec'].get('replicas', 1)):
            kube.scale_to(world, deployment, record['final_replicas'])
        for text in record['events']:
            kube.event(world, f'horizontalpodautoscaler/{hpa["name"] if hpa else "-"}', 'SuccessfulRescale', text[7:])
        lines.append('')
    k.setdefault('replays', [])
    k['replays'] = (k['replays'] + [{kk: v for kk, v in r.items()} for r in records])[-10:]
    worldlib.advance(world, 5)
    return '\n'.join(lines) + '\n', 0, {'replayed': len(records),
                                        'overloaded': sum(len(r['overloaded_minutes']) for r in records)}


def last_replay(world: dict, namespace: str, deployment: str) -> dict | None:
    for record in reversed(kube.kube_state(world).get('replays') or []):
        if record['namespace'] == namespace and record['deployment'] == deployment:
            return record
    return None


def status(world: dict, hpa: dict) -> dict:
    """What `kubectl get hpa` shows now: utilization at the recorded load's first minute."""
    deployment = target_of(world, hpa)
    target = cpu_target(hpa)
    out = {'current': None, 'target': target[1] if target else None, 'replicas': 0, 'reason': '', 'active': True}
    if deployment is None:
        out.update(active=False, reason=f'the HPA was unable to get the target\'s current scale: deployments/scale.apps '
                                        f'"{hpa["spec"]["scaleTargetRef"]["name"]}" not found')
        return out
    out['replicas'] = int(deployment['spec'].get('replicas', 1))
    request, limit, missing = pod_resources(deployment)
    if missing:
        out.update(active=False, reason=f'failed to get cpu utilization: missing request for cpu in container '
                                        f'"{missing}"')
        return out
    scenario = next((s for s in scenarios(world) if s['namespace'] == hpa['namespace']
                     and s['deployment'] == deployment['name']), None)
    ready = sum(p['ready'] for p in kube.kube_state(world)['pods'].values()
                if p['deployment'] == deployment['name'] and p['namespace'] == hpa['namespace'])
    demand = demand_curve(scenario)[0] if scenario else 0
    if ready:
        out['current'] = round(min(demand / ready, limit or 2000) / request * 100)
    return out


def get_rows(world: dict, namespace: str, name: str | None) -> str | None:
    items = [h for h in hpas(world, namespace) if not name or h['name'] == name]
    if not items:
        return None
    rows = [('NAME', 'REFERENCE', 'TARGETS', 'MINPODS', 'MAXPODS', 'REPLICAS', 'AGE')]
    for hpa in items:
        st = status(world, hpa)
        current = '<unknown>' if st['current'] is None else f'{st["current"]}%'
        low, high = bounds(hpa)
        target = cpu_target(hpa)
        rows.append((hpa['name'], f'Deployment/{hpa["spec"]["scaleTargetRef"]["name"]}',
                     f'{target[0] if target else "cpu"}: {current}/{st["target"]}%', low, high, st['replicas'],
                     kube.age(world, hpa['created_at'])))
    return kube.table(rows)


def describe(world: dict, hpa: dict) -> str:
    st = status(world, hpa)
    low, high = bounds(hpa)
    deployment = target_of(world, hpa)
    target = cpu_target(hpa)
    current = '<unknown>' if st['current'] is None else f'{st["current"]}%'
    lines = [f'Name:                                                  {hpa["name"]}',
             f'Namespace:                                             {hpa["namespace"]}',
             f'Reference:                                             Deployment/{hpa["spec"]["scaleTargetRef"]["name"]}',
             'Metrics:                                               ( current / target )',
             f'  resource {target[0] if target else "cpu"} on pods  (as a percentage of request):  {current} / {st["target"]}%',
             f'Min replicas:                                          {low}',
             f'Max replicas:                                          {high}',
             f'Deployment pods:                                       {st["replicas"]} current / {st["replicas"]} desired',
             'Conditions:', '  Type            Status  Reason                   Message',
             '  ----            ------  ------                   -------',
             '  AbleToScale     True    ReadyForNewScale         recommended size matches current size']
    if st['active']:
        lines.append('  ScalingActive   True    ValidMetricFound         the HPA was able to successfully calculate a '
                     'replica count from cpu resource utilization (percentage of request)')
    else:
        lines.append(f'  ScalingActive   False   FailedGetResourceMetric  the HPA was unable to compute the replica '
                     f'count: {st["reason"]}')
    record = last_replay(world, hpa['namespace'], deployment['name']) if deployment else None
    if record and record['limited']:
        lines.append('  ScalingLimited  True    TooManyReplicas          the desired replica count is more than the '
                     'maximum replica count')
    else:
        lines.append('  ScalingLimited  False   DesiredWithinRange       the desired count is within the acceptable '
                     'range')
    lines.append('Events:' + (' (from the last lab load replay)' if record else ''))
    events = [e for e in kube.kube_state(world)['events'] if e['object'] == f'horizontalpodautoscaler/{hpa["name"]}']
    lines += [f'  {e["type"]:<8} {e["reason"]:<18} {e["message"]}' for e in events[-12:]] or ['  <none>']
    return '\n'.join(lines) + '\n'
