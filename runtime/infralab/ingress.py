"""The simulated cluster's ingress controller: which Ingress, rule and path a request reaches, as ingress-nginx
routes it, and what the learner's `curl http://<host>/<path>` gets back.

The cluster fixture declares its ingress classes (`world.kube.ingress_classes`: name, controller, the public address,
whether it is the default class). An Ingress is served when its `ingressClassName` names one of them, or when it has
none and a default class exists. Routing follows the Ingress API: rules whose host equals the request's host (a
`*.` wildcard matches one label) win over rules without a host; among their paths an `Exact` path must equal the
request path, a `Prefix` path matches whole path elements (`/api` matches `/api` and `/api/orders`, not `/apis`), the
longest match wins and `Exact` beats `Prefix` at equal length (`ImplementationSpecific` is treated as `Prefix`, as
ingress-nginx does without regex annotations). The backend Service must exist in the Ingress's namespace and expose
the port the backend names (by number or by name); its endpoints come from `kube.py`. Nothing listens anywhere: the
answer is computed from the simulated world.
"""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

from . import kube

NGINX_404 = '<html>\n<head><title>404 Not Found</title></head>\n<body>\n<center><h1>404 Not Found</h1></center>\n<hr><center>nginx</center>\n</body>\n</html>'
NGINX_503 = ('<html>\n<head><title>503 Service Temporarily Unavailable</title></head>\n<body>\n<center><h1>503 Service '
             'Temporarily Unavailable</h1></center>\n<hr><center>nginx</center>\n</body>\n</html>')


def classes(world: dict) -> list[dict]:
    return list(kube.kube_state(world).get('ingress_classes') or [])


def served_by(world: dict, ingress: dict) -> dict | None:
    """The ingress class that serves this Ingress, or None."""
    name = ingress['spec'].get('ingressClassName')
    for cls in classes(world):
        if (name and cls['name'] == name) or (not name and cls.get('default')):
            return cls
    return None


def ingresses(world: dict, namespace: str | None = None) -> list[dict]:
    return sorted((o for o in kube.kube_state(world)['objects'].values() if o['kind'] == 'Ingress'
                   and (namespace is None or o['namespace'] == namespace)), key=lambda o: (o['namespace'], o['name']))


def host_matches(rule_host: str | None, host: str) -> int:
    """2: exact host, 1: wildcard, 0: a rule without host (matches every host), -1: no match."""
    if not rule_host:
        return 0
    if rule_host == host:
        return 2
    if rule_host.startswith('*.') and host.count('.') == rule_host.count('.') and host.endswith(rule_host[1:]):
        return 1
    return -1


def path_matches(path_type: str, rule_path: str, path: str) -> bool:
    if path_type == 'Exact':
        return path == rule_path
    rule_parts = [p for p in rule_path.split('/') if p]
    parts = [p for p in path.split('/') if p]
    return parts[:len(rule_parts)] == rule_parts


def route(world: dict, host: str, path: str) -> tuple[dict | None, dict | None, str]:
    """(ingress, backend, why) for a request; backend None means the controller answers 404 itself."""
    best: tuple | None = None
    for ing in ingresses(world):
        if served_by(world, ing) is None:
            continue
        for rule in ing['spec'].get('rules') or []:
            level = host_matches(rule.get('host'), host)
            if level < 0:
                continue
            for entry in (rule.get('http') or {}).get('paths') or []:
                if path_matches(entry['pathType'], entry['path'], path):
                    rank = (level, len(entry['path'].rstrip('/')), entry['pathType'] == 'Exact')
                    if best is None or rank > best[0]:
                        best = (rank, ing, entry['backend'], f'{entry["path"]} ({entry["pathType"]})')
    if best is not None:
        return best[1], best[2], best[3]
    for ing in ingresses(world):
        if served_by(world, ing) is not None and ing['spec'].get('defaultBackend'):
            return ing, ing['spec']['defaultBackend'], 'defaultBackend'
    return None, None, 'no rule matches'


def service_port(service: dict, port: dict) -> dict | None:
    for entry in service['spec'].get('ports') or []:
        if ('number' in port and entry.get('port') == port['number']) or \
                ('name' in port and entry.get('name') == port['name']):
            return entry
    return None


def backend_problem(world: dict, ingress: dict, backend: dict) -> str | None:
    """Why the controller cannot reach this backend (it answers 503), or None."""
    svc = backend['service']
    service = kube.kube_state(world)['objects'].get(kube.key('Service', ingress['namespace'], svc['name']))
    if service is None:
        return f'service "{ingress["namespace"]}/{svc["name"]}" not found'
    entry = service_port(service, svc['port'])
    if entry is None:
        wanted = svc['port'].get('number', svc['port'].get('name'))
        return f'service "{ingress["namespace"]}/{svc["name"]}" does not have any active endpoint for port {wanted}'
    single = dict(service, spec={**service['spec'], 'ports': [entry]})
    ok, why = kube.service_reachable(world, single)
    return None if ok else why


def request(world: dict, url: str) -> tuple[int, str, str]:
    """(status, body, note) of GET url through the ingress controller."""
    parts = urlsplit(url if '://' in url else 'http://' + url)
    host = (parts.hostname or '').lower()
    path = parts.path or '/'
    addresses = {cls.get('address') for cls in classes(world)}
    if host in addresses:
        host = ''
    ingress, backend, why = route(world, host, path)
    if ingress is None:
        return 404, NGINX_404, f'no Ingress rule matches host "{host or "*"}" and path {path}'
    problem = backend_problem(world, ingress, backend)
    if problem:
        return 503, NGINX_503, f'Ingress {ingress["namespace"]}/{ingress["name"]} ({why}): {problem}'
    service = kube.kube_state(world)['objects'][kube.key('Service', ingress['namespace'], backend['service']['name'])]
    pod = next((p for p in kube.kube_state(world)['pods'].values() if p['namespace'] == ingress['namespace'] and p['ready']
                and all(p['labels'].get(k) == v for k, v in (service['spec'].get('selector') or {}).items())), None)
    behaviour = kube.image_behaviour(world, pod['image']) if pod else None
    routes = (behaviour or {}).get('routes') or {}
    body = next((text for prefix, text in sorted(routes.items(), key=lambda kv: -len(kv[0]))
                 if path == prefix or path.startswith(prefix.rstrip('/') + '/')), None)
    if routes and body is None:
        return 404, '{"detail":"Not Found"}', (f'Ingress {ingress["namespace"]}/{ingress["name"]} ({why}) -> service '
                                               f'{backend["service"]["name"]}: the app has no route {path}')
    return 200, body if body is not None else '{"status":"ok"}', (
        f'Ingress {ingress["namespace"]}/{ingress["name"]} ({why}) -> service {backend["service"]["name"]} -> pod '
        f'{pod["name"] if pod else "?"}')


def curl(world: dict, url: str, verbose: bool = False) -> tuple[str, int]:
    status, body, note = request(world, url)
    text = body + '\n'
    if verbose or status >= 400:
        text += f'{kube.DIM}[HTTP {status}; {note}; simulated: nothing listens anywhere]{kube.RESET}\n'
    return text, 0 if status < 400 else 22


def address(world: dict, ingress: dict) -> str:
    cls = served_by(world, ingress)
    return cls.get('address', '') if cls else ''


def get_rows(world: dict, namespace: str, name: str | None) -> str | None:
    items = [i for i in ingresses(world, namespace) if not name or i['name'] == name]
    if not items:
        return None
    rows = [('NAME', 'CLASS', 'HOSTS', 'ADDRESS', 'PORTS', 'AGE')]
    for ing in items:
        hosts = ','.join(r.get('host') or '*' for r in ing['spec'].get('rules') or []) or '*'
        ports = '80, 443' if ing['spec'].get('tls') else '80'
        rows.append((ing['name'], ing['spec'].get('ingressClassName') or '<none>', hosts, address(world, ing), ports,
                     kube.age(world, ing['created_at'])))
    return kube.table(rows)


def class_rows(world: dict) -> str:
    rows = [('NAME', 'CONTROLLER', 'PARAMETERS', 'AGE')]
    for cls in classes(world):
        rows.append((cls['name'] + (' (default)' if cls.get('default') else ''),
                     cls.get('controller', 'k8s.io/ingress-nginx'), '<none>', '30d'))
    return kube.table(rows) if len(rows) > 1 else 'No resources found\n'


def describe(world: dict, ing: dict) -> str:
    spec = ing['spec']
    cls = served_by(world, ing)
    lines = [f'Name:             {ing["name"]}', f'Namespace:        {ing["namespace"]}',
             f'Address:          {address(world, ing)}',
             f'Ingress Class:    {spec.get("ingressClassName") or "<none>"}']
    if cls is None:
        lines.append(f'{kube.YELLOW}                  (no ingress controller serves this class: the Ingress is ignored)'
                     f'{kube.RESET}')
    default = spec.get('defaultBackend')
    lines.append('Default backend:  ' + (f'{default["service"]["name"]}:{json.dumps(default["service"]["port"])}'
                                         if default else '<default>'))
    if spec.get('tls'):
        lines.append('TLS:')
        lines += [f'  {t.get("secretName", "<none>")} terminates {",".join(t.get("hosts") or [])}' for t in spec['tls']]
    lines += ['Rules:', '  Host        Path  Backends', '  ----        ----  --------']
    for rule in spec.get('rules') or []:
        lines.append(f'  {rule.get("host") or "*"}')
        for entry in (rule.get('http') or {}).get('paths') or []:
            svc = entry['backend']['service']
            port = svc['port'].get('number', svc['port'].get('name'))
            problem = backend_problem(world, ing, entry['backend'])
            service = kube.kube_state(world)['objects'].get(kube.key('Service', ing['namespace'], svc['name']))
            eps = ','.join(kube.endpoints(world, service)) if service and not problem else ''
            shown = f'({eps})' if eps else f'({problem})' if problem else '()'
            lines.append(f'              {entry["path"]}   {svc["name"]}:{port} {shown}   [{entry["pathType"]}]')
    events = [e for e in kube.kube_state(world)['events'] if e['object'] == f'ingress/{ing["name"]}']
    lines.append('Events:')
    lines += [f'  {e["type"]:<8} {e["reason"]:<10} {e["message"]}' for e in events[-6:]] or ['  <none>']
    return '\n'.join(lines) + '\n'
