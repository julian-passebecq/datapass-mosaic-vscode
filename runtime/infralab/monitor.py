"""Simulated virtual machines and Azure Monitor: the `az` commands of the lab, metric scenarios and alert replay.

The subscription's virtual machines and data factories carry a metric scenario from the mission (a base level, a
little deterministic noise and incidents at fixed times). `az monitor metrics list` reads it; `az monitor metrics
alert create` stores an alert rule in the simulated subscription; `lab alerts replay` evaluates every rule over the
scenario the way Azure Monitor evaluates static metric alerts (aggregation over the window, every evaluation
frequency, resolved after three evaluations without the condition). Nothing is sent to Azure.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import random
import re
from typing import Any

from . import world as worldlib

BOLD, GREEN, YELLOW, RED, CYAN, DIM, RESET = '\x1b[1m', '\x1b[32m', '\x1b[33m', '\x1b[31m', '\x1b[36m', '\x1b[2m', '\x1b[0m'
AGGREGATIONS = {'avg': 'Average', 'min': 'Minimum', 'max': 'Maximum', 'total': 'Total', 'count': 'Count'}
OPERATORS = {'>': 'GreaterThan', '>=': 'GreaterThanOrEqual', '<': 'LessThan', '<=': 'LessThanOrEqual',
             '=': 'Equals', '!=': 'NotEquals'}
WINDOWS = {'1m': 1, '5m': 5, '15m': 15, '30m': 30, '1h': 60, '6h': 360, '12h': 720, '1d': 1440}
FREQUENCIES = {'1m': 1, '5m': 5, '15m': 15, '30m': 30, '1h': 60}
ISO = {'PT1M': '1m', 'PT5M': '5m', 'PT15M': '15m', 'PT30M': '30m', 'PT1H': '1h', 'PT6H': '6h', 'PT12H': '12h',
       'P1D': '1d', 'PT24H': '1d'}
RESOLVE_AFTER = 3


class AzError(Exception):
    pass


# ---- Metrics -------------------------------------------------------------------------------------------------------


def scenario_window(resource: dict, world: dict) -> tuple[datetime, int]:
    scenario = resource.get('metrics') or {}
    end = worldlib.parse_time(scenario.get('end') or world['clock'])
    minutes = int(scenario.get('minutes', 1440))
    return end - timedelta(minutes=minutes), minutes


def series(resource: dict, metric: str, world: dict) -> list[tuple[datetime, float]]:
    """One point per minute over the scenario window: base level, deterministic noise, then incidents."""
    scenario = resource.get('metrics') or {}
    spec = (scenario.get('series') or {}).get(metric)
    if spec is None:
        raise AzError(f"Metric '{metric}' is not available for {resource['attributes']['name']}. Available: "
                      f"{', '.join(sorted(scenario.get('series') or {}))}")
    start, minutes = scenario_window(resource, world)
    seed = int(hashlib.sha256(f'{resource["id"]}|{metric}'.encode()).hexdigest()[:12], 16)
    rng = random.Random(seed)
    base, noise = float(spec.get('base', 0)), float(spec.get('noise', 0))
    points = []
    for i in range(minutes):
        moment = start + timedelta(minutes=i)
        value = base + (rng.uniform(-noise, noise) if noise else 0.0)
        points.append([moment, value])
    for event in spec.get('events', []):
        begin = worldlib.parse_time(event['from'])
        length = int(event.get('minutes', 1))
        ramp = int(event.get('ramp', 0))
        for i, point in enumerate(points):
            offset = (point[0] - begin).total_seconds() / 60
            if 0 <= offset < length:
                target = float(event['value'])
                if ramp and offset < ramp:
                    target = point[1] + (target - point[1]) * (offset + 1) / (ramp + 1)
                jitter = rng.uniform(-float(event.get('noise', 0)), float(event.get('noise', 0))) if event.get('noise') else 0
                point[1] = target + jitter
    low, high = spec.get('min', 0), spec.get('max')
    out = []
    for moment, value in points:
        value = max(low, value) if low is not None else value
        value = min(high, value) if high is not None else value
        out.append((moment, round(value, 2)))
    return out


def aggregate(values: list[float], aggregation: str) -> float | None:
    if not values:
        return None
    if aggregation == 'Average':
        return sum(values) / len(values)
    if aggregation == 'Minimum':
        return min(values)
    if aggregation == 'Maximum':
        return max(values)
    if aggregation == 'Total':
        return sum(values)
    return float(len(values))


def compare(value: float, operator: str, threshold: float) -> bool:
    return {'GreaterThan': value > threshold, 'GreaterThanOrEqual': value >= threshold, 'LessThan': value < threshold,
            'LessThanOrEqual': value <= threshold, 'Equals': value == threshold,
            'NotEquals': value != threshold}[operator]


def replay(rule: dict, resource: dict, world: dict) -> list[dict[str, str]]:
    """Fired and resolved times of one static metric alert over the scenario."""
    points = series(resource, rule['metric'], world)
    window, frequency = WINDOWS[rule['window']], FREQUENCIES[rule['frequency']]
    start = points[0][0]
    incidents: list[dict[str, str]] = []
    fired_at, misses = None, 0
    for i in range(window - 1, len(points), frequency):
        values = [v for _, v in points[i - window + 1:i + 1]]
        moment = points[i][0] + timedelta(minutes=1)
        value = aggregate(values, rule['aggregation'])
        met = value is not None and compare(value, rule['operator'], float(rule['threshold']))
        if met:
            misses = 0
            if fired_at is None:
                fired_at = moment
                incidents.append({'fired': worldlib.format_time(moment), 'value': f'{value:.2f}'})
        elif fired_at is not None:
            misses += 1
            if misses >= RESOLVE_AFTER:
                incidents[-1]['resolved'] = worldlib.format_time(moment)
                fired_at, misses = None, 0
    del start
    return incidents


# ---- Resources -------------------------------------------------------------------------------------------------------


def resources_of(world: dict, arm_type: str | None = None, group: str | None = None) -> list[dict]:
    out = []
    for resource in world['azure']['resources'].values():
        if arm_type and resource['type'].lower() != arm_type.lower():
            continue
        if group and f'/resourcegroups/{group.lower()}/' not in resource['id'].lower() + '/':
            continue
        out.append(resource)
    return sorted(out, key=lambda r: r['id'])


def resource_group_of(resource_id: str) -> str:
    m = re.search(r'/resourceGroups/([^/]+)', resource_id, re.I)
    return m.group(1) if m else ''


def find_resource(world: dict, ref: str, group: str | None = None, arm_type: str | None = None) -> dict:
    """A resource by id, or (lab convenience) by name, optionally within a resource group."""
    resources = world['azure']['resources']
    if ref.startswith('/'):
        for rid, resource in resources.items():
            if rid.lower() == ref.lower():
                return resource
        raise AzError(f"(ResourceNotFound) The Resource '{ref}' was not found.")
    matches = [r for r in resources_of(world, arm_type, group) if r['attributes'].get('name') == ref]
    if not matches:
        raise AzError(f"(ResourceNotFound) The Resource '{ref}' under resource group '{group or '?'}' was not found.")
    if len(matches) > 1:
        raise AzError(f"More than one resource is named '{ref}': use its full resource id.")
    return matches[0]


def alert_id(world: dict, group: str, name: str) -> str:
    return (f'/subscriptions/{world["azure"]["subscription_id"]}/resourceGroups/{group}/providers/'
            f'Microsoft.Insights/metricAlerts/{name}')


def parse_condition(text: str, resource: dict) -> dict[str, Any]:
    """`avg Percentage CPU > 85`: aggregation, metric, operator, threshold (az monitor metrics alert syntax)."""
    m = re.fullmatch(r'\s*(avg|min|max|total|count)\s+(.+?)\s*(>=|<=|!=|>|<|=)\s*(-?\d+(?:\.\d+)?)\s*', text)
    if not m:
        if ' where ' in text:
            raise AzError('Dimension filters (where ...) are not simulated in this lab.')
        raise AzError(f'usage error: --condition "{text}" is not valid. Expected "{{avg,min,max,total,count}} '
                      '{metric} {=,!=,>,>=,<,<=} {threshold}", for example: --condition "avg Percentage CPU > 90"')
    aggregation, metric, operator, threshold = m.groups()
    metric = metric.strip().strip('"\'')
    available = (resource.get('metrics') or {}).get('series') or {}
    if metric not in available:
        raise AzError(f"The metric '{metric}' does not exist for {resource['attributes']['name']}. Available metrics: "
                      f"{', '.join(sorted(available))}")
    return {'aggregation': AGGREGATIONS[aggregation], 'metric': metric, 'operator': OPERATORS[operator],
            'threshold': float(threshold)}


def duration_value(value: str, allowed: dict[str, int], option: str) -> str:
    value = ISO.get(value.upper(), value.lower())
    if value not in allowed:
        raise AzError(f'{option} must be one of {", ".join(allowed)} (got {value}).')
    return value


# ---- az commands -------------------------------------------------------------------------------------------------


def options(args: list[str]) -> tuple[dict[str, str | bool], list[str]]:
    out: dict[str, str | bool] = {}
    positional: list[str] = []
    i = 0
    aliases = {'-n': '--name', '-g': '--resource-group', '-o': '--output'}
    while i < len(args):
        arg = aliases.get(args[i], args[i])
        if arg.startswith('--'):
            if '=' in arg:
                key, value = arg.split('=', 1)
                out[key] = value
            elif i + 1 < len(args) and not args[i + 1].startswith('--') and not (args[i + 1] in aliases):
                out[arg] = args[i + 1]
                i += 1
            else:
                out[arg] = True
        else:
            positional.append(arg)
        i += 1
    return out, positional


def output(value: Any, fmt: str | bool | None, columns: list[tuple[str, str]] | None = None) -> str:
    if fmt == 'table' and columns:
        rows = value if isinstance(value, list) else [value]
        header = [c for c, _ in columns]
        body = [[str(r.get(key, '')) for _, key in columns] for r in rows]
        widths = [max(len(h), *(len(b[i]) for b in body)) if body else len(h) for i, h in enumerate(header)]
        lines = ['  '.join(h.ljust(w) for h, w in zip(header, widths)),
                 '  '.join('-' * w for w in widths)]
        lines += ['  '.join(v.ljust(w) for v, w in zip(b, widths)).rstrip() for b in body]
        return '\n'.join(lines) + '\n'
    if fmt == 'tsv':
        rows = value if isinstance(value, list) else [value]
        return '\n'.join('\t'.join(str(v) for v in (r.values() if isinstance(r, dict) else [r])) for r in rows) + '\n'
    return json.dumps(value, indent=2) + '\n'


def need(opts: dict, *names: str) -> None:
    missing = [n for n in names if not opts.get(n)]
    if missing:
        raise AzError(f'the following arguments are required: {", ".join(missing)}')


def vm_view(resource: dict) -> dict:
    a = resource['attributes']
    return {'name': a.get('name'), 'resourceGroup': resource_group_of(resource['id']), 'location': a.get('location'),
            'hardwareProfile': {'vmSize': a.get('size')}, 'storageProfile': {'osDisk': {'osType': a.get('os_type')}},
            'powerState': a.get('power_state', 'VM running'), 'id': resource['id'], 'tags': a.get('tags', {})}


def alert_view(rule: dict) -> dict:
    return {'name': rule['name'], 'resourceGroup': rule['resource_group'], 'enabled': rule['enabled'],
            'severity': rule['severity'], 'scopes': [rule['scope']],
            'criteria': {'allOf': [{'metricName': rule['metric'], 'timeAggregation': rule['aggregation'],
                                    'operator': rule['operator'], 'threshold': rule['threshold']}]},
            'windowSize': 'PT' + rule['window'].upper() if rule['window'] != '1d' else 'P1D',
            'evaluationFrequency': 'PT' + rule['frequency'].upper(),
            'actions': [{'actionGroupId': a} for a in rule['actions']], 'description': rule.get('description', ''),
            'id': rule['id']}


def az(args: list[str], world: dict) -> tuple[str, int, dict]:
    if not args or args[0] in ('help', '-h', '--help'):
        return HELP, 0, {}
    azure = world['azure']
    group_cmd = ' '.join(args[:4])
    opts, positional = options(args)
    fmt = opts.get('--output')
    head = ' '.join(positional[:4])
    if head.startswith('login'):
        return (f'{DIM}(simulated) Signed in to the lab subscription "{azure.get("subscription_name", "lab")}". No '
                f'Azure account is used.{RESET}\n'), 0, {}
    if head.startswith('account show'):
        return output({'id': azure['subscription_id'], 'name': azure.get('subscription_name', 'lab'),
                       'tenantId': azure['tenant_id'], 'state': 'Enabled', 'isDefault': True}, fmt), 0, {}
    if head.startswith('group list'):
        rows = [{'Name': r['attributes']['name'], 'Location': r['attributes']['location']}
                for r in resources_of(world, 'Microsoft.Resources/resourceGroups')]
        return output(rows, fmt, [('Name', 'Name'), ('Location', 'Location')]), 0, {}
    if head.startswith('group show'):
        need(opts, '--name')
        resource = find_resource(world, str(opts['--name']), None, 'Microsoft.Resources/resourceGroups')
        a = resource['attributes']
        view = {'id': resource['id'], 'name': a['name'], 'location': a['location'], 'tags': a.get('tags') or {},
                'managedBy': a.get('managed_by'), 'properties': {'provisioningState': 'Succeeded'}}
        if opts.get('--query') == 'id':
            return resource['id'] + '\n', 0, {}
        return output(view, fmt), 0, {}
    if head.startswith('resource list'):
        rows = [{'Name': r['attributes'].get('name'), 'ResourceGroup': resource_group_of(r['id']),
                 'Type': r['type'], 'id': r['id']}
                for r in resources_of(world, None, opts.get('--resource-group') or None)
                if r['type'] != 'Microsoft.Resources/resourceGroups']
        return output(rows, fmt, [('Name', 'Name'), ('ResourceGroup', 'ResourceGroup'), ('Type', 'Type')]), 0, {}
    if head.startswith('vm list'):
        rows = [vm_view(r) for r in resources_of(world, 'Microsoft.Compute/virtualMachines', opts.get('--resource-group') or None)]
        table_rows = [{'Name': v['name'], 'ResourceGroup': v['resourceGroup'], 'Location': v['location'],
                       'Size': v['hardwareProfile']['vmSize'], 'Os': v['storageProfile']['osDisk']['osType'],
                       'PowerState': v['powerState']} for v in rows]
        if fmt == 'table':
            return output(table_rows, fmt, [(k, k) for k in ('Name', 'ResourceGroup', 'Location', 'Size', 'Os', 'PowerState')]), 0, {}
        return output(rows, fmt), 0, {}
    if head.startswith('vm show') or head.startswith('vm restart') or head.startswith('vm start') or head.startswith('vm stop') or head.startswith('vm deallocate'):
        need(opts, '--name')
        resource = find_resource(world, str(opts['--name']), opts.get('--resource-group') or None,
                                 'Microsoft.Compute/virtualMachines')
        verb = positional[1]
        if verb == 'show':
            view = vm_view(resource)
            if opts.get('--query') == 'id':
                return resource['id'] + '\n', 0, {}
            return output(view, fmt), 0, {}
        state = {'restart': 'VM running', 'start': 'VM running', 'stop': 'VM stopped', 'deallocate': 'VM deallocated'}[verb]
        resource['attributes']['power_state'] = state
        worldlib.advance(world, 45 if verb == 'restart' else 30)
        return f'{DIM}(simulated) {verb} of {resource["attributes"]["name"]} finished: {state}.{RESET}\n', 0, {'vm': verb}
    if head.startswith('monitor metrics list-definitions'):
        need(opts, '--resource')
        resource = find_resource(world, str(opts['--resource']), opts.get('--resource-group') or None)
        series_spec = (resource.get('metrics') or {}).get('series') or {}
        rows = [{'Metric': name, 'Unit': spec.get('unit', ''), 'Description': spec.get('description', '')}
                for name, spec in sorted(series_spec.items())]
        return output(rows, fmt or 'table', [('Metric', 'Metric'), ('Unit', 'Unit'), ('Description', 'Description')]), 0, {}
    if head.startswith('monitor metrics list'):
        need(opts, '--resource', '--metric')
        resource = find_resource(world, str(opts['--resource']), opts.get('--resource-group') or None)
        return metrics_table(resource, opts, world), 0, {}
    if head.startswith('monitor action-group list'):
        rows = [{'Name': r['attributes']['name'], 'ResourceGroup': resource_group_of(r['id']),
                 'ShortName': r['attributes'].get('short_name', ''),
                 'Receivers': ', '.join(r['attributes'].get('receivers', []))}
                for r in resources_of(world, 'Microsoft.Insights/actionGroups')]
        return output(rows, fmt, [('Name', 'Name'), ('ResourceGroup', 'ResourceGroup'), ('ShortName', 'ShortName'),
                                  ('Receivers', 'Receivers')]), 0, {}
    if head.startswith('monitor metrics alert'):
        return alert_command(positional[3] if len(positional) > 3 else '', opts, world)
    del group_cmd
    raise AzError(f"'{' '.join(positional[:3])}' is not an az command the lab simulates. See 'az help'.")


def metrics_table(resource: dict, opts: dict, world: dict) -> str:
    metric = str(opts['--metric'])
    interval = duration_value(str(opts.get('--interval', '1h')), WINDOWS, '--interval')
    aggregation = str(opts.get('--aggregation', 'Average')).capitalize()
    if aggregation not in AGGREGATIONS.values():
        raise AzError(f'--aggregation must be one of {", ".join(AGGREGATIONS.values())}')
    points = series(resource, metric, world)
    start = worldlib.parse_time(str(opts['--start-time'])) if opts.get('--start-time') else points[0][0]
    end = worldlib.parse_time(str(opts['--end-time'])) if opts.get('--end-time') else points[-1][0] + timedelta(minutes=1)
    step = WINDOWS[interval]
    rows = []
    bucket_start = start
    while bucket_start < end and len(rows) < 300:
        bucket_end = min(bucket_start + timedelta(minutes=step), end)
        values = [v for t, v in points if bucket_start <= t < bucket_end]
        value = aggregate(values, aggregation)
        rows.append({'Timestamp': worldlib.format_time(bucket_start), 'Name': metric,
                     aggregation: '' if value is None else f'{value:.2f}'})
        bucket_start = bucket_end
    unit = ((resource.get('metrics') or {}).get('series') or {}).get(metric, {}).get('unit', '')
    header = f'{DIM}{resource["attributes"]["name"]} · {metric} ({unit}) · {aggregation} per {interval} · simulated scenario{RESET}\n'
    return header + output(rows, 'table', [('Timestamp', 'Timestamp'), ('Name', 'Name'), (aggregation, aggregation)])


def alert_command(verb: str, opts: dict, world: dict) -> tuple[str, int, dict]:
    azure = world['azure']
    alerts = azure.setdefault('alerts', {})
    fmt = opts.get('--output')
    if verb == 'list':
        rows = [alert_view(r) for r in alerts.values()
                if not opts.get('--resource-group') or r['resource_group'] == opts['--resource-group']]
        if fmt == 'table':
            table_rows = [{'Name': v['name'], 'Enabled': v['enabled'], 'Severity': v['severity'],
                           'Condition': f'{v["criteria"]["allOf"][0]["timeAggregation"]} {v["criteria"]["allOf"][0]["metricName"]} '
                                        f'{v["criteria"]["allOf"][0]["operator"]} {v["criteria"]["allOf"][0]["threshold"]:g}',
                           'Window': v['windowSize'], 'Frequency': v['evaluationFrequency']} for v in rows]
            return output(table_rows, fmt, [(k, k) for k in ('Name', 'Enabled', 'Severity', 'Condition', 'Window', 'Frequency')]), 0, {}
        return output(rows, fmt), 0, {}
    need(opts, '--name', '--resource-group')
    name, group = str(opts['--name']), str(opts['--resource-group'])
    rid = alert_id(world, group, name)
    if verb == 'show':
        if rid not in alerts:
            raise AzError(f"(ResourceNotFound) The Resource 'Microsoft.Insights/metricAlerts/{name}' under resource group "
                          f"'{group}' was not found.")
        return output(alert_view(alerts[rid]), fmt), 0, {}
    if verb == 'delete':
        alerts.pop(rid, None)
        worldlib.advance(world, 3)
        return '', 0, {'alert': 'deleted', 'name': name}
    group_id = f'/subscriptions/{azure["subscription_id"]}/resourceGroups/{group}'
    if group_id not in azure['resources']:
        raise AzError(f"(ResourceGroupNotFound) Resource group '{group}' could not be found.")
    if verb == 'create':
        need(opts, '--scopes', '--condition')
        if rid in alerts:
            raise AzError(f'An alert rule named {name} already exists in {group}: use update, or delete it first.')
        scope = find_resource(world, str(opts['--scopes']).split()[0], None)
        rule = {'id': rid, 'name': name, 'resource_group': group, 'scope': scope['id'], 'enabled': True,
                'severity': 2, 'window': '5m', 'frequency': '1m', 'actions': [], 'description': ''}
        rule.update(parse_condition(str(opts['--condition']), scope))
    elif verb == 'update':
        if rid not in alerts:
            raise AzError(f"(ResourceNotFound) The alert rule '{name}' was not found in '{group}'.")
        rule = dict(alerts[rid])
        if opts.get('--condition'):
            raise AzError('update does not take --condition: use --add-condition / --remove-conditions in Azure; in '
                          'this lab, delete the rule and create it again.')
    else:
        raise AzError(f"'az monitor metrics alert {verb}' is not simulated (create, update, list, show, delete).")
    if opts.get('--window-size'):
        rule['window'] = duration_value(str(opts['--window-size']), WINDOWS, '--window-size')
    if opts.get('--evaluation-frequency'):
        rule['frequency'] = duration_value(str(opts['--evaluation-frequency']), FREQUENCIES, '--evaluation-frequency')
    if WINDOWS[rule['frequency']] > WINDOWS[rule['window']]:
        raise AzError('--evaluation-frequency must be less than or equal to --window-size.')
    if opts.get('--severity') is not None and opts.get('--severity') is not True:
        severity = str(opts['--severity'])
        if severity not in {'0', '1', '2', '3', '4'}:
            raise AzError('--severity must be 0 (critical) to 4 (verbose).')
        rule['severity'] = int(severity)
    if opts.get('--enabled') is not None:
        rule['enabled'] = str(opts['--enabled']).lower() in ('true', '1', 'yes')
    if opts.get('--description'):
        rule['description'] = str(opts['--description'])
    for option in ('--action', '--action-groups', '--add-action'):
        if opts.get(option):
            groups = []
            for ref in str(opts[option]).split():
                action_group = find_resource(world, ref, None, 'Microsoft.Insights/actionGroups')
                groups.append(action_group['id'])
            rule['actions'] = sorted(set(rule['actions']) | set(groups))
    alerts[rid] = rule
    worldlib.advance(world, 4)
    return output(alert_view(rule), fmt), 0, {'alert': verb, 'name': name}


# ---- lab alerts replay ------------------------------------------------------------------------------------------------


def lab(args: list[str], world: dict) -> tuple[str, int, dict]:
    if args[:2] != ['alerts', 'replay']:
        return ('Datapass lab commands (not Azure):\n  lab alerts replay [--name RULE]   replay the metric scenario '
                'against your alert rules\n  lab status                         what the simulated world holds\n'), 0, {}
    opts, _ = options(args[2:])
    alerts = world['azure'].get('alerts', {})
    rules = [r for r in alerts.values() if not opts.get('--name') or r['name'] == opts['--name']]
    if not rules:
        return f'{YELLOW}No alert rules to replay.{RESET} Create one with az monitor metrics alert create.\n', 1, {}
    lines = [f'{BOLD}Replaying the simulated scenario against {len(rules)} alert rule(s){RESET} '
             f'{DIM}(Datapass lab command; Azure Monitor semantics: aggregation over the window, evaluated every '
             f'frequency, resolved after {RESOLVE_AFTER} evaluations without the condition){RESET}\n']
    total = 0
    for rule in sorted(rules, key=lambda r: r['name']):
        resource = world['azure']['resources'].get(rule['scope'])
        condition = f'{rule["aggregation"]} {rule["metric"]} {rule["operator"]} {rule["threshold"]:g}'
        lines.append(f'{BOLD}{rule["name"]}{RESET}  sev {rule["severity"]} · {condition} · window {rule["window"]} · '
                     f'every {rule["frequency"]}' + ('' if rule['enabled'] else f' {YELLOW}(disabled){RESET}'))
        if resource is None:
            lines.append(f'  {RED}its scope no longer exists{RESET}')
            continue
        if not rule['actions']:
            lines.append(f'  {YELLOW}no action group: it would fire, but nobody is notified{RESET}')
        if not rule['enabled']:
            continue
        incidents = replay(rule, resource, world)
        total += len(incidents)
        if not incidents:
            lines.append(f'  {DIM}never fired over the scenario{RESET}')
        for incident in incidents:
            resolved = incident.get('resolved', 'still firing at the end of the scenario')
            lines.append(f'  {RED}fired{RESET} {incident["fired"]} (value {incident["value"]}) → resolved {resolved}')
        lines.append('')
    worldlib.advance(world, 1)
    return '\n'.join(lines) + '\n', 0, {'rules': len(rules), 'incidents': total}


HELP = f"""az (simulated by Datapass: no Azure account is used)

  az login | az account show | az group list | az resource list [-g RG]
  az vm list [-g RG] [-o table] | az vm show -g RG -n NAME | az vm restart -g RG -n NAME
  az monitor metrics list-definitions --resource NAME_OR_ID
  az monitor metrics list --resource NAME_OR_ID --metric "Percentage CPU" [--interval 5m] [--aggregation Maximum]
      [--start-time 2026-10-05T01:00:00Z --end-time 2026-10-05T03:00:00Z]
  az monitor action-group list [-o table]
  az monitor metrics alert create -n NAME -g RG --scopes NAME_OR_ID --condition "avg Percentage CPU > 90"
      --window-size 15m --evaluation-frequency 5m --severity 2 --action ACTION_GROUP [--description TEXT]
  az monitor metrics alert update|show|delete -n NAME -g RG | list [-g RG] [-o table]

  lab alerts replay        {DIM}(Datapass lab command) evaluate your rules over the scenario{RESET}

{DIM}Resources can be named instead of given by full id (a lab convenience; Azure wants ids for --scopes).{RESET}
"""
