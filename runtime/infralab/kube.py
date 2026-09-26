"""The simulated Kubernetes cluster: `kubectl apply` of Deployments, Services, ConfigMaps, Namespaces, Ingresses and
HorizontalPodAutoscalers.

Manifests are read with `yaml.safe_load_all` and validated strictly (unknown fields refused, as the API server's strict
field validation does) for the documented subset. The cluster is a record in `.infralab/world.json`: nodes with
allocatable CPU and memory, the images its registry knows (with the behaviour of the app inside: the port it listens
on, its health path, a crash), ReplicaSets and Pods derived by a deterministic controller. A rolling update is
simulated in five-second steps with the Deployment's maxSurge and maxUnavailable, readiness probes and the progress
deadline, and records the fewest ready pods during the rollout. Ingress routing (the cluster's ingress controller)
is in `ingress.py`, the HorizontalPodAutoscaler and the replay of a recorded load in `autoscale.py`. Nothing is
deployed.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

import yaml

from . import world as worldlib

BOLD, GREEN, YELLOW, RED, CYAN, DIM, RESET = '\x1b[1m', '\x1b[32m', '\x1b[33m', '\x1b[31m', '\x1b[36m', '\x1b[2m', '\x1b[0m'
TICK = 5
MAX_MANIFEST_BYTES = 400_000

KINDS = {'Deployment': 'apps/v1', 'Service': 'v1', 'ConfigMap': 'v1', 'Namespace': 'v1',
         'Ingress': 'networking.k8s.io/v1', 'HorizontalPodAutoscaler': 'autoscaling/v2'}
NOUNS = {'Deployment': 'deployment.apps', 'Service': 'service', 'ConfigMap': 'configmap', 'Namespace': 'namespace',
         'Ingress': 'ingress.networking.k8s.io', 'HorizontalPodAutoscaler': 'horizontalpodautoscaler.autoscaling'}
PLURALS = {'Deployment': 'deployments.apps', 'Service': 'services', 'ConfigMap': 'configmaps',
           'Namespace': 'namespaces', 'Ingress': 'ingresses.networking.k8s.io',
           'HorizontalPodAutoscaler': 'horizontalpodautoscalers.autoscaling'}
RESOURCE_NAMES = {
    'pods': 'Pod', 'pod': 'Pod', 'po': 'Pod', 'deployments': 'Deployment', 'deployment': 'Deployment',
    'deploy': 'Deployment', 'services': 'Service', 'service': 'Service', 'svc': 'Service', 'replicasets': 'ReplicaSet',
    'replicaset': 'ReplicaSet', 'rs': 'ReplicaSet', 'endpoints': 'Endpoints', 'ep': 'Endpoints', 'nodes': 'Node',
    'node': 'Node', 'no': 'Node', 'configmaps': 'ConfigMap', 'configmap': 'ConfigMap', 'cm': 'ConfigMap',
    'namespaces': 'Namespace', 'namespace': 'Namespace', 'ns': 'Namespace', 'events': 'Event', 'ev': 'Event',
    'ingresses': 'Ingress', 'ingress': 'Ingress', 'ing': 'Ingress', 'ingressclasses': 'IngressClass',
    'ingressclass': 'IngressClass', 'horizontalpodautoscalers': 'HorizontalPodAutoscaler',
    'horizontalpodautoscaler': 'HorizontalPodAutoscaler', 'hpa': 'HorizontalPodAutoscaler',
}
# Fields the lab accepts, per object path; anything else is an unknown field (strict decoding).
FIELDS = {
    'Deployment': {'apiVersion', 'kind', 'metadata', 'spec'},
    'Deployment.spec': {'replicas', 'selector', 'template', 'strategy', 'minReadySeconds', 'revisionHistoryLimit',
                        'progressDeadlineSeconds', 'paused'},
    'strategy': {'type', 'rollingUpdate'},
    'rollingUpdate': {'maxSurge', 'maxUnavailable'},
    'selector': {'matchLabels', 'matchExpressions'},
    'template': {'metadata', 'spec'},
    'metadata': {'name', 'namespace', 'labels', 'annotations'},
    'podSpec': {'containers', 'restartPolicy', 'serviceAccountName', 'nodeSelector', 'volumes',
                'terminationGracePeriodSeconds', 'imagePullSecrets'},
    'container': {'name', 'image', 'ports', 'env', 'envFrom', 'resources', 'readinessProbe', 'livenessProbe',
                  'startupProbe', 'command', 'args', 'imagePullPolicy', 'volumeMounts', 'workingDir'},
    'port': {'name', 'containerPort', 'protocol'},
    'resources': {'requests', 'limits'},
    'probe': {'httpGet', 'tcpSocket', 'exec', 'initialDelaySeconds', 'periodSeconds', 'timeoutSeconds',
              'failureThreshold', 'successThreshold'},
    'httpGet': {'path', 'port', 'scheme', 'httpHeaders'},
    'tcpSocket': {'port'},
    'Service': {'apiVersion', 'kind', 'metadata', 'spec'},
    'Service.spec': {'type', 'selector', 'ports', 'clusterIP', 'sessionAffinity'},
    'servicePort': {'name', 'port', 'targetPort', 'protocol', 'nodePort'},
    'ConfigMap': {'apiVersion', 'kind', 'metadata', 'data'},
    'Namespace': {'apiVersion', 'kind', 'metadata'},
    'Ingress': {'apiVersion', 'kind', 'metadata', 'spec'},
    'Ingress.spec': {'ingressClassName', 'rules', 'tls', 'defaultBackend'},
    'ingressRule': {'host', 'http'},
    'ingressHttp': {'paths'},
    'ingressPath': {'path', 'pathType', 'backend'},
    'ingressBackend': {'service', 'resource'},
    'ingressService': {'name', 'port'},
    'backendPort': {'number', 'name'},
    'ingressTLS': {'hosts', 'secretName'},
    'HorizontalPodAutoscaler': {'apiVersion', 'kind', 'metadata', 'spec'},
    'HorizontalPodAutoscaler.spec': {'scaleTargetRef', 'minReplicas', 'maxReplicas', 'metrics', 'behavior'},
    'scaleTargetRef': {'apiVersion', 'kind', 'name'},
    'metric': {'type', 'resource', 'pods', 'object', 'external', 'containerResource'},
    'resourceMetric': {'name', 'target'},
    'metricTarget': {'type', 'averageUtilization', 'averageValue', 'value'},
    'behavior': {'scaleUp', 'scaleDown'},
    'scalingRules': {'stabilizationWindowSeconds', 'selectPolicy', 'policies'},
    'scalingPolicy': {'type', 'value', 'periodSeconds'},
}
DNS_LABEL = re.compile(r'[a-z0-9]([-a-z0-9]*[a-z0-9])?')


class KubeError(Exception):
    pass


# ---- Quantities ------------------------------------------------------------------------------------------------------


def cpu_millis(value: Any) -> int:
    text = str(value).strip()
    if text.endswith('m'):
        return int(float(text[:-1]))
    return int(float(text) * 1000)


def memory_mib(value: Any) -> int:
    text = str(value).strip()
    units = {'Ki': 1 / 1024, 'Mi': 1, 'Gi': 1024, 'K': 1 / 1048.576, 'M': 0.953674, 'G': 953.674}
    for unit, factor in units.items():
        if text.endswith(unit):
            return int(float(text[:-len(unit)]) * factor)
    return int(float(text) / 1048576)


def percent_or_int(value: Any, total: int, round_up: bool) -> int:
    if isinstance(value, str) and value.endswith('%'):
        fraction = total * int(value[:-1]) / 100
        return math.ceil(fraction) if round_up else math.floor(fraction)
    return int(value)


# ---- Validation ------------------------------------------------------------------------------------------------------


def strict(obj: Any, allowed_key: str, path: str, source: str, kind: str, name: str) -> None:
    if not isinstance(obj, dict):
        raise KubeError(f'Error from server (BadRequest): error when creating "{source}": {kind} in version '
                        f'"{KINDS.get(kind, "v1")}" cannot be handled as a {kind}: {path}: expected an object')
    for key in obj:
        if key not in FIELDS[allowed_key]:
            raise KubeError(f'Error from server (BadRequest): error when creating "{source}": {kind} in version '
                            f'"{KINDS.get(kind, "v1")}" cannot be handled as a {kind}: strict decoding error: unknown '
                            f'field "{path}.{key}"' if path else f'unknown field "{key}"')


def validate(doc: dict, source: str) -> dict:
    if not isinstance(doc, dict):
        raise KubeError(f'error: error validating "{source}": a manifest must be a YAML mapping')
    missing = [f for f in ('apiVersion', 'kind') if not doc.get(f)]
    if missing:
        raise KubeError(f'error: error validating "{source}": error validating data: [{", ".join(f + " not set" for f in missing)}]')
    kind, version = doc['kind'], doc['apiVersion']
    meta = doc.get('metadata') or {}
    name = meta.get('name', '')
    if kind not in KINDS or KINDS[kind] != version:
        expected = f' ({kind} is in {KINDS[kind]})' if kind in KINDS else ''
        raise KubeError(f'error: resource mapping not found for name: "{name}" namespace: "" from "{source}": no matches '
                        f'for kind "{kind}" in version "{version}"{expected}\nensure CRDs are installed first'
                        + ('' if kind in KINDS else f'\n{DIM}(the lab simulates {", ".join(sorted(KINDS))}){RESET}'))
    strict(doc, kind, '', source, kind, name)
    strict(meta, 'metadata', 'metadata', source, kind, name)
    if not re.fullmatch(r'[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*', str(name)) or len(str(name)) > 63:
        raise KubeError(f'The {kind} "{name}" is invalid: metadata.name: Invalid value: "{name}": a lowercase RFC 1123 '
                        'subdomain must consist of lower case alphanumeric characters, \'-\' or \'.\'')
    spec = doc.get('spec') or {}
    if kind == 'Deployment':
        strict(spec, 'Deployment.spec', 'spec', source, kind, name)
        selector = spec.get('selector') or {}
        strict(selector, 'selector', 'spec.selector', source, kind, name)
        template = spec.get('template') or {}
        strict(template, 'template', 'spec.template', source, kind, name)
        strict(template.get('metadata') or {}, 'metadata', 'spec.template.metadata', source, kind, name)
        pod = template.get('spec') or {}
        strict(pod, 'podSpec', 'spec.template.spec', source, kind, name)
        labels = (template.get('metadata') or {}).get('labels') or {}
        match = selector.get('matchLabels') or {}
        if not match:
            raise KubeError(f'The Deployment "{name}" is invalid: spec.selector: Required value')
        if any(labels.get(k) != v for k, v in match.items()):
            raise KubeError(f'The Deployment "{name}" is invalid: spec.template.metadata.labels: Invalid value: '
                            f'map[string]string{json.dumps(labels)}: `selector` does not match template `labels`')
        containers = pod.get('containers') or []
        if not containers:
            raise KubeError(f'The Deployment "{name}" is invalid: spec.template.spec.containers: Required value')
        for i, container in enumerate(containers):
            base = f'spec.template.spec.containers[{i}]'
            strict(container, 'container', base, source, kind, name)
            if not container.get('name') or not container.get('image'):
                raise KubeError(f'The Deployment "{name}" is invalid: {base}.image: Required value')
            for j, port in enumerate(container.get('ports') or []):
                strict(port, 'port', f'{base}.ports[{j}]', source, kind, name)
            resources = container.get('resources') or {}
            strict(resources, 'resources', f'{base}.resources', source, kind, name)
            for section in ('requests', 'limits'):
                for key, value in (resources.get(section) or {}).items():
                    try:
                        cpu_millis(value) if key == 'cpu' else memory_mib(value)
                    except ValueError:
                        raise KubeError(f'quantities must match the regular expression: {base}.resources.{section}.'
                                        f'{key}: "{value}"') from None
            for probe_name in ('readinessProbe', 'livenessProbe', 'startupProbe'):
                probe = container.get(probe_name)
                if probe is None:
                    continue
                strict(probe, 'probe', f'{base}.{probe_name}', source, kind, name)
                if 'httpGet' in probe:
                    strict(probe['httpGet'], 'httpGet', f'{base}.{probe_name}.httpGet', source, kind, name)
                if 'tcpSocket' in probe:
                    strict(probe['tcpSocket'], 'tcpSocket', f'{base}.{probe_name}.tcpSocket', source, kind, name)
        strategy = spec.get('strategy') or {}
        strict(strategy, 'strategy', 'spec.strategy', source, kind, name)
        rolling = strategy.get('rollingUpdate') or {}
        strict(rolling, 'rollingUpdate', 'spec.strategy.rollingUpdate', source, kind, name)
        if strategy.get('type', 'RollingUpdate') not in ('RollingUpdate', 'Recreate'):
            raise KubeError(f'The Deployment "{name}" is invalid: spec.strategy.type: Unsupported value: '
                            f'"{strategy.get("type")}": supported values: "Recreate", "RollingUpdate"')
        if strategy.get('type') == 'Recreate' and rolling:
            raise KubeError(f'The Deployment "{name}" is invalid: spec.strategy.rollingUpdate: Forbidden: may not be '
                            'specified when strategy `type` is \'Recreate\'')
        replicas = int(spec.get('replicas', 1))
        surge = percent_or_int(rolling.get('maxSurge', '25%'), replicas, True)
        unavailable = percent_or_int(rolling.get('maxUnavailable', '25%'), replicas, False)
        if strategy.get('type', 'RollingUpdate') == 'RollingUpdate' and surge == 0 and unavailable == 0:
            raise KubeError(f'The Deployment "{name}" is invalid: spec.strategy.rollingUpdate.maxUnavailable: Invalid '
                            'value: intstr.IntOrString{IntVal:0}: may not be 0 when `maxSurge` is 0')
    elif kind == 'Service':
        strict(spec, 'Service.spec', 'spec', source, kind, name)
        if spec.get('type', 'ClusterIP') not in ('ClusterIP', 'NodePort', 'LoadBalancer'):
            raise KubeError(f'The Service "{name}" is invalid: spec.type: Unsupported value: "{spec.get("type")}"')
        ports = spec.get('ports') or []
        if not ports:
            raise KubeError(f'The Service "{name}" is invalid: spec.ports: Required value')
        for j, port in enumerate(ports):
            strict(port, 'servicePort', f'spec.ports[{j}]', source, kind, name)
            if 'port' not in port:
                raise KubeError(f'The Service "{name}" is invalid: spec.ports[{j}].port: Required value')
    elif kind == 'Ingress':
        validate_ingress(spec, source, name)
    elif kind == 'HorizontalPodAutoscaler':
        validate_hpa(spec, source, name)
    if kind == 'Namespace' and (not DNS_LABEL.fullmatch(str(name)) or meta.get('namespace')):
        raise KubeError(f'The Namespace "{name}" is invalid: metadata.name: Invalid value: "{name}": a lowercase RFC '
                        '1123 label must consist of lower case alphanumeric characters or \'-\'')
    return doc


def validate_ingress(spec: dict, source: str, name: str) -> None:
    kind = 'Ingress'
    strict(spec, 'Ingress.spec', 'spec', source, kind, name)
    invalid = f'The Ingress "{name}" is invalid: '

    def backend(value: Any, where: str) -> None:
        strict(value, 'ingressBackend', where, source, kind, name)
        if 'resource' in value:
            raise KubeError(f'{invalid}{where}.resource: resource backends are not simulated (use service)')
        service = value.get('service')
        if not isinstance(service, dict):
            raise KubeError(f'{invalid}{where}: Invalid value: "": resource or service backend is required')
        strict(service, 'ingressService', f'{where}.service', source, kind, name)
        if not service.get('name'):
            raise KubeError(f'{invalid}{where}.service.name: Required value')
        port = service.get('port')
        if not isinstance(port, dict):
            raise KubeError(f'{invalid}{where}.service.port: Required value: port name or number is required')
        strict(port, 'backendPort', f'{where}.service.port', source, kind, name)
        if 'number' in port and 'name' in port:
            raise KubeError(f'{invalid}{where}.service.port: Invalid value: cannot set both port name & port number')
        if 'number' not in port and 'name' not in port:
            raise KubeError(f'{invalid}{where}.service.port.name: Required value: port name or number is required')
        if 'number' in port and (not isinstance(port['number'], int) or not 0 < port['number'] < 65536):
            raise KubeError(f'{invalid}{where}.service.port.number: Invalid value: {port["number"]}: must be between '
                            '1 and 65535, inclusive')

    rules = spec.get('rules') or []
    if not rules and not spec.get('defaultBackend'):
        raise KubeError(f'{invalid}spec: Invalid value: ...: either `defaultBackend` or `rules` must be specified')
    if spec.get('defaultBackend') is not None:
        backend(spec['defaultBackend'], 'spec.defaultBackend')
    for i, rule in enumerate(rules):
        where = f'spec.rules[{i}]'
        strict(rule, 'ingressRule', where, source, kind, name)
        host = rule.get('host')
        if host is not None and (':' in str(host) or not re.fullmatch(r'(\*\.)?[a-z0-9]([-a-z0-9.]*[a-z0-9])?',
                                                                    str(host))):
            raise KubeError(f'{invalid}{where}.host: Invalid value: "{host}": a lowercase RFC 1123 subdomain must '
                            'consist of lower case alphanumeric characters, \'-\' or \'.\' (no port, no scheme)')
        http = rule.get('http')
        if http is None:
            continue
        strict(http, 'ingressHttp', f'{where}.http', source, kind, name)
        paths = http.get('paths') or []
        if not paths:
            raise KubeError(f'{invalid}{where}.http.paths: Required value')
        for j, path in enumerate(paths):
            at = f'{where}.http.paths[{j}]'
            strict(path, 'ingressPath', at, source, kind, name)
            if 'pathType' not in path:
                raise KubeError(f'{invalid}{at}.pathType: Required value: pathType must be specified')
            if path['pathType'] not in ('Exact', 'Prefix', 'ImplementationSpecific'):
                raise KubeError(f'{invalid}{at}.pathType: Unsupported value: "{path["pathType"]}": supported values: '
                                '"Exact", "ImplementationSpecific", "Prefix"')
            if not str(path.get('path', '')).startswith('/'):
                raise KubeError(f'{invalid}{at}.path: Invalid value: "{path.get("path", "")}": must be an absolute '
                                'path')
            if 'backend' not in path:
                raise KubeError(f'{invalid}{at}.backend: Required value')
            backend(path['backend'], f'{at}.backend')
    for i, tls in enumerate(spec.get('tls') or []):
        strict(tls, 'ingressTLS', f'spec.tls[{i}]', source, kind, name)


def validate_hpa(spec: dict, source: str, name: str) -> None:
    kind = 'HorizontalPodAutoscaler'
    strict(spec, 'HorizontalPodAutoscaler.spec', 'spec', source, kind, name)
    invalid = f'The HorizontalPodAutoscaler "{name}" is invalid: '
    target = spec.get('scaleTargetRef')
    if not isinstance(target, dict):
        raise KubeError(f'{invalid}spec.scaleTargetRef.kind: Required value')
    strict(target, 'scaleTargetRef', 'spec.scaleTargetRef', source, kind, name)
    if not target.get('kind'):
        raise KubeError(f'{invalid}spec.scaleTargetRef.kind: Required value')
    if not target.get('name'):
        raise KubeError(f'{invalid}spec.scaleTargetRef.name: Required value')
    if target['kind'] != 'Deployment':
        raise KubeError(f'{invalid}spec.scaleTargetRef.kind: the lab scales Deployments only')
    maximum = spec.get('maxReplicas')
    if maximum is None:
        raise KubeError(f'{invalid}spec.maxReplicas: Required value')
    minimum = spec.get('minReplicas', 1)
    if not isinstance(minimum, int) or minimum < 1:
        raise KubeError(f'{invalid}spec.minReplicas: Invalid value: {minimum}: must be greater than or equal to 1')
    if not isinstance(maximum, int) or maximum < 1:
        raise KubeError(f'{invalid}spec.maxReplicas: Invalid value: {maximum}: must be greater than 0')
    if maximum < minimum:
        raise KubeError(f'{invalid}spec.maxReplicas: Invalid value: {maximum}: must be greater than or equal to '
                        '`minReplicas`')
    for i, metric in enumerate(spec.get('metrics') or []):
        where = f'spec.metrics[{i}]'
        strict(metric, 'metric', where, source, kind, name)
        if metric.get('type') != 'Resource':
            raise KubeError(f'{invalid}{where}.type: the lab simulates Resource metrics (cpu, memory) only, not '
                            f'"{metric.get("type")}"')
        resource = metric.get('resource')
        if not isinstance(resource, dict):
            raise KubeError(f'{invalid}{where}.resource: Required value: must populate information for the given '
                            'metric source')
        strict(resource, 'resourceMetric', f'{where}.resource', source, kind, name)
        if resource.get('name') not in ('cpu', 'memory'):
            raise KubeError(f'{invalid}{where}.resource.name: Required value: must specify a resource name')
        goal = resource.get('target')
        if not isinstance(goal, dict):
            raise KubeError(f'{invalid}{where}.resource.target: Required value')
        strict(goal, 'metricTarget', f'{where}.resource.target', source, kind, name)
        if goal.get('type') != 'Utilization':
            raise KubeError(f'{invalid}{where}.resource.target.type: the lab simulates Utilization targets only')
        value = goal.get('averageUtilization')
        if not isinstance(value, int) or value < 1:
            raise KubeError(f'{invalid}{where}.resource.target.averageUtilization: Required value: must set either a '
                            'target raw value or a target utilization')
    behavior = spec.get('behavior')
    if behavior is not None:
        strict(behavior, 'behavior', 'spec.behavior', source, kind, name)
        for part in ('scaleUp', 'scaleDown'):
            rules = behavior.get(part)
            if rules is None:
                continue
            strict(rules, 'scalingRules', f'spec.behavior.{part}', source, kind, name)
            window = rules.get('stabilizationWindowSeconds', 0)
            if not isinstance(window, int) or not 0 <= window <= 3600:
                raise KubeError(f'{invalid}spec.behavior.{part}.stabilizationWindowSeconds: Invalid value: {window}: '
                                'must be less than or equal to 3600')
            for j, policy in enumerate(rules.get('policies') or []):
                strict(policy, 'scalingPolicy', f'spec.behavior.{part}.policies[{j}]', source, kind, name)
                if policy.get('type') not in ('Pods', 'Percent'):
                    raise KubeError(f'{invalid}spec.behavior.{part}.policies[{j}].type: Unsupported value: '
                                    f'"{policy.get("type")}": supported values: "Percent", "Pods"')


def load_manifests(folder: Path, target: str) -> list[tuple[str, dict]]:
    """Every object of the file or folder, validated; the first invalid one raises."""
    out = []
    for relative, doc, problem in read_manifests(folder, target):
        if problem:
            raise KubeError(problem)
        out.append((relative, doc))
    return out


def read_manifests(folder: Path, target: str) -> list[tuple[str, Any, str | None]]:
    """(file, object, error) for every object: a YAML error stops everything, an invalid object only itself."""
    path = (folder / target).resolve()
    if not path.is_relative_to(folder.resolve()):
        raise KubeError(f'error: the path "{target}" is outside the mission folder')
    if path.is_dir():
        files = sorted(p for p in path.iterdir() if p.suffix in ('.yaml', '.yml', '.json') and p.is_file())
        if not files:
            raise KubeError(f'error: no objects passed to apply (no .yaml files in {target})')
    elif path.is_file():
        files = [path]
    else:
        raise KubeError(f'error: the path "{target}" does not exist')
    out = []
    for file in files:
        relative = file.relative_to(folder.resolve()).as_posix()
        if file.stat().st_size > MAX_MANIFEST_BYTES:
            raise KubeError(f'error: {relative} is too large for the lab')
        try:
            docs = [d for d in yaml.safe_load_all(file.read_text(encoding='utf-8')) if d is not None]
        except yaml.YAMLError as error:
            raise KubeError(f'error: error parsing {relative}: {error}') from None
        for doc in docs:
            try:
                out.append((relative, validate(doc, relative), None))
            except KubeError as error:
                out.append((relative, doc, str(error)))
    return out


# ---- Cluster model ---------------------------------------------------------------------------------------------------


def key(kind: str, namespace: str, name: str) -> str:
    return f'{kind}/{namespace}/{name}'


def kube_state(world: dict) -> dict:
    kube = world['kube']
    kube.setdefault('objects', {})
    kube.setdefault('replicasets', {})
    kube.setdefault('pods', {})
    kube.setdefault('events', [])
    kube.setdefault('rollouts', [])
    kube.setdefault('nodes', [])
    kube.setdefault('images', {})
    return kube


def event(world: dict, obj: str, reason: str, message: str, kind: str = 'Normal', at: str | None = None) -> None:
    events = kube_state(world)['events']
    events.append({'at': at or world['clock'], 'object': obj, 'type': kind, 'reason': reason, 'message': message})
    del events[:-300]


def template_hash(template: dict) -> str:
    return hashlib.sha256(json.dumps(template, sort_keys=True).encode()).hexdigest()[:10]


def pod_suffix(seed: str) -> str:
    alphabet = 'bcdfghjklmnpqrstvwxz2456789'
    digest = int(hashlib.sha256(seed.encode()).hexdigest(), 16)
    return ''.join(alphabet[(digest >> (5 * i)) % len(alphabet)] for i in range(5))


def pod_ip(name: str) -> str:
    digest = hashlib.sha256(name.encode()).digest()
    return f'10.244.{digest[0] % 4}.{2 + digest[1] % 250}'


def image_behaviour(world: dict, image: str) -> dict | None:
    images = kube_state(world)['images']
    return images.get(image)


def container_status(world: dict, container: dict) -> dict[str, Any]:
    """What happens to a container of this spec: image pull, crash, the port it listens on, readiness."""
    """Timings are seconds after the pod starts: `ready_after` (the kubelet reports Ready), `serve_after` (the app
    really answers), `crash_after` (a crashing app that looked ready stops being ready). None means never."""
    behaviour = image_behaviour(world, container['image'])
    probe = container.get('readinessProbe')
    if behaviour is None:
        return {'reason': 'ImagePullBackOff', 'ready_after': None, 'serve_after': None, 'crash_after': None,
                'restarts': 0, 'message': f'Failed to pull image "{container["image"]}": not found in the lab registry',
                'logs': []}
    start = int(behaviour.get('start_s', 5))
    if behaviour.get('crash'):
        # Without a readiness probe the container counts as ready as soon as it starts, until it crashes.
        return {'reason': 'CrashLoopBackOff', 'ready_after': None if probe else 1, 'serve_after': None,
                'crash_after': None if probe else start, 'restarts': 5,
                'message': 'Back-off restarting failed container', 'logs': behaviour.get('logs', []) + [behaviour['crash']]}
    listen = int(behaviour.get('listens', 8080))
    ports = {p.get('name'): int(p['containerPort']) for p in container.get('ports') or [] if p.get('containerPort')}
    logs = list(behaviour.get('logs', [f'listening on 0.0.0.0:{listen}']))
    liveness = container.get('livenessProbe')
    if liveness is not None:
        ok, why = probe_result(liveness, ports, listen, behaviour)
        if not ok:
            return {'reason': 'CrashLoopBackOff', 'ready_after': None, 'serve_after': None, 'crash_after': None,
                    'restarts': 4, 'message': f'Liveness probe failed: {why}; the container is restarted', 'logs': logs}
    if probe is None:
        return {'reason': 'Running', 'ready_after': 1, 'serve_after': start, 'crash_after': None, 'restarts': 0,
                'message': '', 'logs': logs, 'probe': None}
    ok, why = probe_result(probe, ports, listen, behaviour)
    if not ok:
        return {'reason': 'Running', 'ready_after': None, 'serve_after': start, 'crash_after': None, 'restarts': 0,
                'message': f'Readiness probe failed: {why}', 'logs': logs}
    delay = int(probe.get('initialDelaySeconds', 0))
    return {'reason': 'Running', 'ready_after': max(start, delay) + int(probe.get('periodSeconds', 10)) // 2,
            'serve_after': start, 'crash_after': None, 'restarts': 0, 'message': '', 'logs': logs, 'probe': 'passing'}


def probe_result(probe: dict, ports: dict, listen: int, behaviour: dict) -> tuple[bool, str]:
    def resolve(port: Any) -> int | None:
        if isinstance(port, int) or (isinstance(port, str) and port.isdigit()):
            return int(port)
        return ports.get(port)

    if 'httpGet' in probe:
        get = probe['httpGet']
        port = resolve(get.get('port'))
        path = get.get('path', '/')
        if port is None:
            return False, f'the named port {get.get("port")!r} is not declared by the container'
        if port != listen:
            return False, f'Get "http://10.244.0.5:{port}{path}": dial tcp 10.244.0.5:{port}: connect: connection refused'
        health = behaviour.get('health_path')
        if health and path != health:
            return False, f'HTTP probe failed with statuscode: 404 ({path})'
        return True, ''
    if 'tcpSocket' in probe:
        port = resolve(probe['tcpSocket'].get('port'))
        if port != listen:
            return False, f'dial tcp 10.244.0.5:{port}: connect: connection refused'
        return True, ''
    if 'exec' in probe:
        return True, ''
    return False, 'the probe has no handler (httpGet, tcpSocket or exec)'


def requests_of(container: dict) -> tuple[int, int]:
    resources = container.get('resources') or {}
    # A limit without a request sets the request too, as the API server defaults it.
    requests = {**(resources.get('limits') or {}), **(resources.get('requests') or {})}
    return cpu_millis(requests.get('cpu', 0)), memory_mib(requests.get('memory', 0))


def schedule(world: dict, pod_spec: dict, exclude: set[str]) -> tuple[str | None, str]:
    """First node with room for the pod's requests, or (None, reason)."""
    kube = kube_state(world)
    cpu = sum(requests_of(c)[0] for c in pod_spec.get('containers') or [])
    mem = sum(requests_of(c)[1] for c in pod_spec.get('containers') or [])
    short: dict[str, int] = {}
    for node in kube['nodes']:
        used_cpu = used_mem = 0
        for pod in kube['pods'].values():
            if pod['node'] == node['name'] and pod['name'] not in exclude:
                used_cpu += pod['cpu']
                used_mem += pod['mem']
        if used_cpu + cpu <= cpu_millis(node['cpu']) and used_mem + mem <= memory_mib(node['memory']):
            return node['name'], ''
        if used_cpu + cpu > cpu_millis(node['cpu']):
            short['Insufficient cpu'] = short.get('Insufficient cpu', 0) + 1
        else:
            short['Insufficient memory'] = short.get('Insufficient memory', 0) + 1
    detail = ', '.join(f'{n} {k}' for k, n in sorted(short.items()))
    return None, f'0/{len(kube["nodes"])} nodes are available: {detail}.'


def new_pod(world: dict, deployment: dict, rs_name: str, template: dict, index_seed: str, t: int) -> dict:
    kube = kube_state(world)
    name = f'{rs_name}-{pod_suffix(index_seed)}'
    spec = template.get('spec') or {}
    containers = spec.get('containers') or []
    status = container_status(world, containers[0])
    for other in containers[1:]:
        other_status = container_status(world, other)
        if other_status['ready_after'] is None:
            status = other_status
    node, why = schedule(world, spec, set())
    cpu = sum(requests_of(c)[0] for c in containers)
    mem = sum(requests_of(c)[1] for c in containers)
    pod = {
        'name': name, 'namespace': deployment['namespace'], 'replicaset': rs_name, 'deployment': deployment['name'],
        'labels': dict((template.get('metadata') or {}).get('labels') or {}), 'node': node, 'cpu': cpu if node else 0,
        'mem': mem if node else 0, 'image': containers[0]['image'] if containers else '', 'created_t': t,
        'created_at': world['clock'], 'ip': pod_ip(name) if node else None, 'restarts': status.get('restarts', 0),
        'status': 'Pending' if node is None else ('Running' if status['crash_after'] else status['reason']),
        'ready': False,
        'ready_t': t + status['ready_after'] if node and status['ready_after'] is not None else None,
        'serve_t': t + status['serve_after'] if node and status['serve_after'] is not None else None,
        'crash_t': t + status['crash_after'] if node and status['crash_after'] is not None else None,
        'message': why if node is None else status.get('message', ''), 'logs': status.get('logs', []),
        'containers': [{'name': c['name'], 'image': c['image'],
                        'ports': [p.get('containerPort') for p in c.get('ports') or []]} for c in containers],
        'probe': status.get('probe'),
    }
    kube['pods'][name] = pod
    obj = f'pod/{name}'
    if node is None:
        event(world, obj, 'FailedScheduling', why, 'Warning')
    else:
        event(world, obj, 'Scheduled', f'Successfully assigned {pod["namespace"]}/{name} to {node}')
        if pod['status'] == 'ImagePullBackOff':
            event(world, obj, 'Failed', status['message'], 'Warning')
        elif pod['status'] == 'CrashLoopBackOff':
            event(world, obj, 'BackOff', status['message'], 'Warning')
        elif status.get('message'):
            event(world, obj, 'Unhealthy', status['message'], 'Warning')
        else:
            event(world, obj, 'Started', f'Started container {containers[0]["name"]}')
    return pod


def ready(pod: dict, t: int) -> bool:
    """The kubelet reports the pod Ready at t (a crashing app without a readiness probe looks ready until it crashes)."""
    return (pod['ready_t'] is not None and pod['ready_t'] <= t
            and (pod.get('crash_t') is None or t < pod['crash_t']))


def serving(pod: dict, t: int) -> bool:
    """The pod receives traffic (Ready) and its app really answers it."""
    return ready(pod, t) and pod.get('serve_t') is not None and pod['serve_t'] <= t


def reconcile(world: dict, deployment: dict, change_cause: str | None) -> dict:
    """Roll the deployment to its current template, in TICK-second steps; returns the rollout record."""
    kube = kube_state(world)
    spec = deployment['spec']
    template = spec['template']
    replicas = int(spec.get('replicas', 1))
    strategy = spec.get('strategy') or {}
    kind = strategy.get('type', 'RollingUpdate')
    rolling = strategy.get('rollingUpdate') or {}
    surge = percent_or_int(rolling.get('maxSurge', '25%'), replicas, True) if kind == 'RollingUpdate' else 0
    unavailable = percent_or_int(rolling.get('maxUnavailable', '25%'), replicas, False) if kind == 'RollingUpdate' else replicas
    deadline = int(spec.get('progressDeadlineSeconds', 600))
    ns, dname = deployment['namespace'], deployment['name']
    thash = template_hash(template)
    rs_name = f'{dname}-{thash}'
    owned = {n: rs for n, rs in kube['replicasets'].items() if rs['deployment'] == dname and rs['namespace'] == ns}
    initial = not owned
    revision = max((rs['revision'] for rs in owned.values()), default=0)
    if rs_name not in kube['replicasets']:
        revision += 1
        kube['replicasets'][rs_name] = {'name': rs_name, 'namespace': ns, 'deployment': dname, 'revision': revision,
                                        'template': deepcopy(template), 'hash': thash,
                                        'change_cause': change_cause or '<none>', 'created_at': world['clock']}
        event(world, f'deployment/{dname}', 'ScalingReplicaSet', f'Created new replica set "{rs_name}"')
    elif kube['replicasets'][rs_name]['revision'] != revision:
        revision += 1
        kube['replicasets'][rs_name]['revision'] = revision
        kube['replicasets'][rs_name]['change_cause'] = change_cause or kube['replicasets'][rs_name]['change_cause']
    pods = lambda: [p for p in kube['pods'].values() if p['deployment'] == dname and p['namespace'] == ns]
    new_pods = lambda: [p for p in pods() if p['replicaset'] == rs_name]
    old_pods = lambda: [p for p in pods() if p['replicaset'] != rs_name]
    previous_image = next((p['image'] for p in old_pods()), None)
    base = worldlib.now(world)
    # Pods that existed before the rollout are in their steady state now.
    for pod in pods():
        steady_ready = ready(pod, 10 ** 9)
        pod['ready_t'] = -1000 if steady_ready else None
        pod['serve_t'] = -1000 if pod.get('serve_t') is not None else None
        pod['crash_t'] = None
        pod['created_t'] = -1000
    min_available = sum(serving(p, 0) for p in pods())
    timeline: list[str] = []
    seq = len(kube['pods']) + sum(len(rs['name']) for rs in owned.values())
    t = 0
    complete = False
    while t <= deadline:
        if kind == 'Recreate' and old_pods():
            for pod in old_pods():
                del kube['pods'][pod['name']]
            event(world, f'deployment/{dname}', 'ScalingReplicaSet', 'Scaled down old replica sets to 0 (Recreate)')
        total = len(pods())
        want_new = min(replicas + surge - total, replicas - len(new_pods()))
        if kind == 'Recreate':
            want_new = replicas - len(new_pods())
        for _ in range(max(0, want_new)):
            seq += 1
            new_pod(world, deployment, rs_name, template, f'{rs_name}-{seq}', t)
        # Scale down: unhealthy old pods first, then ready ones while availability allows.
        min_needed = replicas - unavailable
        for pod in sorted(old_pods(), key=lambda p: ready(p, t)):
            available = sum(ready(p, t) for p in pods())
            if not ready(pod, t):
                del kube['pods'][pod['name']]
                continue
            if available - 1 >= min_needed:
                del kube['pods'][pod['name']]
        # Scale down surplus new pods (scale-in).
        extra = len(new_pods()) - replicas
        for pod in sorted(new_pods(), key=lambda p: (ready(p, t), p['name']))[:max(0, extra)]:
            del kube['pods'][pod['name']]
        if not initial:
            min_available = min(min_available, sum(serving(p, t) for p in pods()))
        updated = sum(ready(p, t) for p in new_pods())
        line = (f'Waiting for deployment "{dname}" rollout to finish: {updated} of {replicas} updated replicas are '
                f'available...')
        if not timeline or timeline[-1] != line:
            timeline.append(line)
        if updated == replicas and not old_pods():
            complete = True
            break
        t += TICK
    end = max(t, max((p['crash_t'] or 0) for p in pods()) if pods() else t)
    for pod in pods():
        pod['ready'] = ready(pod, end)
        if pod.get('crash_t') is not None and end >= pod['crash_t']:
            pod['status'], pod['message'] = 'CrashLoopBackOff', 'Back-off restarting failed container'
    elapsed = min(t, deadline)
    worldlib.advance(world, elapsed + 2)
    if complete:
        timeline.append(f'deployment "{dname}" successfully rolled out')
        event(world, f'deployment/{dname}', 'RolloutComplete', f'revision {revision} is available')
    else:
        timeline.append(f'error: deployment "{dname}" exceeded its progress deadline')
        event(world, f'deployment/{dname}', 'ProgressDeadlineExceeded',
              f'ReplicaSet "{rs_name}" has timed out progressing.', 'Warning')
    record = {'deployment': dname, 'namespace': ns, 'revision': revision, 'strategy': kind, 'replicas': replicas,
              'max_surge': surge, 'max_unavailable': unavailable, 'from_image': previous_image,
              'to_image': (template.get('spec') or {}).get('containers', [{}])[0].get('image'),
              'min_available': None if initial else min_available, 'initial': initial, 'complete': complete,
              'seconds': elapsed, 'at': worldlib.format_time(base), 'timeline': timeline[-12:]}
    kube['rollouts'].append(record)
    del kube['rollouts'][:-50]
    deployment['status'] = {'revision': revision, 'complete': complete}
    return record


# ---- Services --------------------------------------------------------------------------------------------------------


def endpoints(world: dict, service: dict) -> list[str]:
    kube = kube_state(world)
    selector = (service['spec'].get('selector') or {})
    if not selector:
        return []
    out = []
    for pod in kube['pods'].values():
        if pod['namespace'] != service['namespace'] or not pod['ready']:
            continue
        if all(pod['labels'].get(k) == v for k, v in selector.items()):
            for port in service['spec'].get('ports') or []:
                target = port.get('targetPort', port.get('port'))
                if isinstance(target, str) and not target.isdigit():
                    rs = kube['replicasets'].get(pod['replicaset'])
                    containers = ((rs or {}).get('template') or {}).get('spec', {}).get('containers', [])
                    named = {p.get('name'): p.get('containerPort') for c in containers for p in c.get('ports') or []}
                    target = named.get(target)
                if target is not None:
                    out.append(f'{pod["ip"]}:{target}')
    return sorted(out)


def service_reachable(world: dict, service: dict) -> tuple[bool, str]:
    """Would a request to the service reach an app? (endpoints exist and target the port the app listens on)"""
    eps = endpoints(world, service)
    if not eps:
        return False, 'the service has no endpoints: no ready pod matches its selector'
    kube = kube_state(world)
    for endpoint in eps:
        ip, port = endpoint.rsplit(':', 1)
        pod = next((p for p in kube['pods'].values() if p['ip'] == ip), None)
        behaviour = image_behaviour(world, pod['image']) if pod else None
        if behaviour and int(behaviour.get('listens', 8080)) == int(port):
            return True, ''
    return False, f'the service sends traffic to port {eps[0].rsplit(":", 1)[1]}, where the app does not listen'


# ---- kubectl ---------------------------------------------------------------------------------------------------------


def age(world: dict, stamp: str) -> str:
    seconds = int((worldlib.now(world) - worldlib.parse_time(stamp)).total_seconds())
    if seconds < 120:
        return f'{max(seconds, 1)}s'
    if seconds < 7200:
        return f'{seconds // 60}m'
    return f'{seconds // 3600}h'


def table(rows: list[tuple]) -> str:
    widths = [max(len(str(r[i])) for r in rows) for i in range(len(rows[0]))]
    return '\n'.join('   '.join(str(v).ljust(w) for v, w in zip(row, widths)).rstrip() for row in rows) + '\n'


def apply(folder: Path, target: str, world: dict, namespace: str) -> tuple[str, dict]:
    """Apply every object in order; an object that fails is reported and the others still apply, as kubectl does."""
    from . import autoscale
    kube = kube_state(world)
    docs = read_manifests(folder, target)
    lines = []
    errors = []
    rollouts = []
    for source, doc, problem in docs:
        if problem:
            errors.append(problem)
            continue
        try:
            rollouts += apply_object(world, source, doc, namespace, lines)
        except KubeError as error:
            errors.append(str(error))
    autoscale.enforce_bounds(world)
    worldlib.advance(world, 1)
    text = '\n'.join(lines) + ('\n' if lines else '')
    if errors:
        text += RED + '\n'.join(errors) + RESET + '\n'
    return text, {'applied': len(docs) - len(errors), 'rollouts': len(rollouts), 'errors': len(errors)}


def apply_object(world: dict, source: str, doc: dict, namespace: str, lines: list[str]) -> list[dict]:
    kube = kube_state(world)
    rollouts = []
    kind = doc['kind']
    meta = doc.get('metadata') or {}
    name = meta['name']
    ns = meta.get('namespace') or namespace
    if kind == 'Namespace':
        ns = ''
    elif ns != 'default' and key('Namespace', '', ns) not in kube['objects']:
        raise KubeError(f'Error from server (NotFound): error when creating "{source}": namespaces "{ns}" not found')
    elif meta.get('namespace') and namespace != 'default' and meta['namespace'] != namespace:
        raise KubeError(f'error: the namespace from the provided object "{meta["namespace"]}" does not match the '
                        f'namespace "{namespace}". You must pass \'--namespace={meta["namespace"]}\' to perform '
                        'this operation.')
    k = key(kind, ns, name)
    existing = kube['objects'].get(k)
    stored = {'kind': kind, 'name': name, 'namespace': ns, 'labels': meta.get('labels') or {},
              'annotations': meta.get('annotations') or {}, 'spec': doc.get('spec') or {}, 'data': doc.get('data'),
              'source': source, 'created_at': existing['created_at'] if existing else world['clock']}
    noun = NOUNS[kind]
    if existing and existing['spec'] == stored['spec'] and existing.get('data') == stored['data'] \
            and existing['labels'] == stored['labels']:
        lines.append(f'{noun}/{name} unchanged')
        return rollouts
    if kind == 'Deployment' and existing:
        if existing['spec'].get('selector') != stored['spec'].get('selector'):
            raise KubeError(f'The Deployment "{name}" is invalid: spec.selector: Invalid value: '
                            f'{json.dumps(stored["spec"].get("selector"))}: field is immutable')
    kube['objects'][k] = stored
    lines.append(f'{noun}/{name} {"configured" if existing else "created"}')
    if kind == 'Deployment':
        old_template = (existing or {}).get('spec', {}).get('template')
        cause = stored['annotations'].get('kubernetes.io/change-cause')
        if old_template != stored['spec']['template'] or not existing:
            rollouts.append(reconcile(world, stored, cause))
        else:
            rollouts.append(scale_to(world, stored, int(stored['spec'].get('replicas', 1))))
    return rollouts


def scale_to(world: dict, deployment: dict, replicas: int) -> dict:
    deployment['spec']['replicas'] = replicas
    return reconcile(world, deployment, None)


def find_object(world: dict, kind: str, name: str, namespace: str) -> dict:
    obj = kube_state(world)['objects'].get(key(kind, '' if kind == 'Namespace' else namespace, name))
    if obj is None:
        raise KubeError(f'Error from server (NotFound): {PLURALS.get(kind, kind.lower() + "s")} "{name}" not found')
    return obj


def split_ref(ref: str, kind_hint: str | None = None) -> tuple[str, str]:
    if '/' in ref:
        noun, name = ref.split('/', 1)
        kind = RESOURCE_NAMES.get(noun.split('.')[0])
        if kind is None:
            raise KubeError(f'error: the server doesn\'t have a resource type "{noun}"')
        return kind, name
    if kind_hint is None:
        raise KubeError(f'error: arguments in resource/name form must have a single resource and name ({ref})')
    return kind_hint, ref


def get(world: dict, args: list[str], namespace: str, output: str | None, show_labels: bool = False,
        all_namespaces: bool = False) -> str:
    kube = kube_state(world)
    if all_namespaces:
        spaces = ['default'] + sorted(o['name'] for o in kube['objects'].values() if o['kind'] == 'Namespace')
        parts = []
        for ns in spaces:
            text = get(world, args, ns, output, show_labels)
            if text.startswith('No resources found'):
                continue
            head, _, body = text.partition('\n')
            parts.append((ns, head, body))
        if not parts:
            return 'No resources found\n'
        lines = ['NAMESPACE'.ljust(12) + parts[0][1]]
        for ns, head, body in parts:
            lines += [ns.ljust(12) + row for row in body.splitlines() if row and not row.startswith('NAME ')]
        return '\n'.join(lines) + '\n'
    if not args:
        raise KubeError('You must specify the type of resource to get. Use "kubectl api-resources" for a complete list.')
    kinds = args[0].split(',')
    name = args[1] if len(args) > 1 else None
    if '/' in args[0]:
        kind, name = split_ref(args[0])
        kinds = [kind]
    else:
        if args[0] == 'all':
            kinds = ['Pod', 'Service', 'Deployment', 'ReplicaSet', 'HorizontalPodAutoscaler']
        else:
            resolved = []
            for noun in kinds:
                if noun not in RESOURCE_NAMES:
                    raise KubeError(f'error: the server doesn\'t have a resource type "{noun}"')
                resolved.append(RESOURCE_NAMES[noun])
            kinds = resolved
    out = []
    for kind in kinds:
        if kind == 'Pod':
            items = [p for p in kube['pods'].values() if p['namespace'] == namespace and (not name or p['name'] == name)]
            if output == 'json':
                out.append(json.dumps(items, indent=2))
                continue
            rows = [('NAME', 'READY', 'STATUS', 'RESTARTS', 'AGE') + (('IP', 'NODE') if output == 'wide' else ())
                    + (('LABELS',) if show_labels else ())]
            for p in sorted(items, key=lambda p: p['name']):
                rows.append((p['name'], f'{int(p["ready"])}/1', p['status'], p['restarts'], age(world, p['created_at']))
                            + ((p['ip'] or '<none>', p['node'] or '<none>') if output == 'wide' else ())
                            + ((','.join(f'{k}={v}' for k, v in p['labels'].items()),) if show_labels else ()))
            out.append(table(rows) if len(rows) > 1 else f'No resources found in {namespace} namespace.\n')
        elif kind == 'Deployment':
            items = [o for o in kube['objects'].values() if o['kind'] == 'Deployment' and o['namespace'] == namespace
                     and (not name or o['name'] == name)]
            if name and not items:
                raise KubeError(f'Error from server (NotFound): deployments.apps "{name}" not found')
            rows = [('NAME', 'READY', 'UP-TO-DATE', 'AVAILABLE', 'AGE')]
            for d in items:
                pods = [p for p in kube['pods'].values() if p['deployment'] == d['name'] and p['namespace'] == namespace]
                current = f'{d["name"]}-{template_hash(d["spec"]["template"])}'
                replicas = int(d['spec'].get('replicas', 1))
                ready_count = sum(p['ready'] for p in pods)
                rows.append((d['name'], f'{ready_count}/{replicas}', sum(p['replicaset'] == current for p in pods),
                             ready_count, age(world, d['created_at'])))
            out.append(table(rows) if len(rows) > 1 else f'No resources found in {namespace} namespace.\n')
        elif kind == 'ReplicaSet':
            rows = [('NAME', 'DESIRED', 'CURRENT', 'READY', 'AGE')]
            for rs in kube['replicasets'].values():
                if rs['namespace'] != namespace or (name and rs['name'] != name):
                    continue
                pods = [p for p in kube['pods'].values() if p['replicaset'] == rs['name']]
                deployment = kube['objects'].get(key('Deployment', namespace, rs['deployment']))
                current = deployment and rs['hash'] == template_hash(deployment['spec']['template'])
                desired = int(deployment['spec'].get('replicas', 1)) if current else 0
                rows.append((rs['name'], desired, len(pods), sum(p['ready'] for p in pods), age(world, rs['created_at'])))
            out.append(table(rows) if len(rows) > 1 else f'No resources found in {namespace} namespace.\n')
        elif kind in ('Service', 'Endpoints'):
            items = [o for o in kube['objects'].values() if o['kind'] == 'Service' and o['namespace'] == namespace
                     and (not name or o['name'] == name)]
            if name and not items:
                raise KubeError(f'Error from server (NotFound): {"services" if kind == "Service" else "endpoints"} "{name}" not found')
            if kind == 'Service':
                rows = [('NAME', 'TYPE', 'CLUSTER-IP', 'EXTERNAL-IP', 'PORT(S)', 'AGE')]
                for s in items:
                    ports = ','.join(f'{p["port"]}/{p.get("protocol", "TCP")}' for p in s['spec'].get('ports') or [])
                    digest = hashlib.sha256(s['name'].encode()).digest()
                    stype = s['spec'].get('type', 'ClusterIP')
                    rows.append((s['name'], stype, f'10.0.{digest[0]}.{digest[1]}',
                                 '<pending>' if stype == 'LoadBalancer' else '<none>', ports, age(world, s['created_at'])))
            else:
                rows = [('NAME', 'ENDPOINTS', 'AGE')]
                for s in items:
                    eps = endpoints(world, s)
                    shown = ','.join(eps[:3]) + (f' + {len(eps) - 3} more...' if len(eps) > 3 else '')
                    rows.append((s['name'], shown or '<none>', age(world, s['created_at'])))
            out.append(table(rows) if len(rows) > 1 else f'No resources found in {namespace} namespace.\n')
        elif kind == 'Node':
            rows = [('NAME', 'STATUS', 'ROLES', 'CPU', 'MEMORY', 'PODS')]
            for node in kube['nodes']:
                count = sum(p['node'] == node['name'] for p in kube['pods'].values())
                rows.append((node['name'], 'Ready', '<none>', node['cpu'], node['memory'], count))
            out.append(table(rows))
        elif kind == 'ConfigMap':
            rows = [('NAME', 'DATA', 'AGE')]
            for o in kube['objects'].values():
                if o['kind'] == 'ConfigMap' and o['namespace'] == namespace:
                    rows.append((o['name'], len(o.get('data') or {}), age(world, o['created_at'])))
            out.append(table(rows) if len(rows) > 1 else f'No resources found in {namespace} namespace.\n')
        elif kind in ('Ingress', 'HorizontalPodAutoscaler', 'IngressClass'):
            from . import autoscale, ingress
            text = (ingress.get_rows(world, namespace, name) if kind == 'Ingress' else
                    ingress.class_rows(world) if kind == 'IngressClass' else autoscale.get_rows(world, namespace, name))
            if text is None:
                if kind != 'IngressClass' and name:
                    raise KubeError(f'Error from server (NotFound): {PLURALS[kind]} "{name}" not found')
                if args[0] != 'all':
                    out.append(f'No resources found in {namespace} namespace.\n')
            else:
                out.append(text)
        elif kind == 'Namespace':
            rows = [('NAME', 'STATUS', 'AGE'), ('default', 'Active', '30d')]
            rows += [(o['name'], 'Active', age(world, o['created_at'])) for o in kube['objects'].values() if o['kind'] == 'Namespace']
            out.append(table(rows))
        elif kind == 'Event':
            rows = [('LAST SEEN', 'TYPE', 'REASON', 'OBJECT', 'MESSAGE')]
            for e in kube['events'][-40:]:
                rows.append((age(world, e['at']), e['type'], e['reason'], e['object'], e['message'][:100]))
            out.append(table(rows))
    return '\n'.join(out)


def describe(world: dict, args: list[str], namespace: str) -> str:
    kube = kube_state(world)
    if not args:
        raise KubeError('error: You must specify the type of resource to describe.')
    kind, name = split_ref(args[0]) if '/' in args[0] else (RESOURCE_NAMES.get(args[0]), args[1] if len(args) > 1 else None)
    if kind is None or name is None:
        raise KubeError('error: describe needs a kind and a name, such as: kubectl describe pod NAME')
    if kind == 'Pod':
        pod = kube['pods'].get(name)
        if pod is None or pod['namespace'] != namespace:
            raise KubeError(f'Error from server (NotFound): pods "{name}" not found')
        rs = kube['replicasets'].get(pod['replicaset'], {})
        container = ((rs.get('template') or {}).get('spec') or {}).get('containers', [{}])[0]
        probe = container.get('readinessProbe')
        probe_text = '<none>'
        if probe and 'httpGet' in probe:
            probe_text = f'http-get http://:{probe["httpGet"].get("port")}{probe["httpGet"].get("path", "/")}'
        elif probe and 'tcpSocket' in probe:
            probe_text = f'tcp-socket :{probe["tcpSocket"].get("port")}'
        lines = [f'Name:         {pod["name"]}', f'Namespace:    {pod["namespace"]}', f'Node:         {pod["node"] or "<none>"}',
                 f'Labels:       {", ".join(f"{k}={v}" for k, v in pod["labels"].items())}',
                 f'Status:       {"Pending" if not pod["node"] else "Running"}', f'IP:           {pod["ip"] or "<none>"}',
                 f'Controlled By:  ReplicaSet/{pod["replicaset"]}', 'Containers:', f'  {container.get("name", "?")}:',
                 f'    Image:          {pod["image"]}',
                 f'    Port:           {", ".join(str(p) + "/TCP" for c in pod["containers"] for p in c["ports"] if p) or "<none>"}',
                 f'    State:          {"Waiting" if pod["status"] in ("CrashLoopBackOff", "ImagePullBackOff") else "Running"}'
                 + (f'\n      Reason:       {pod["status"]}' if pod['status'] in ('CrashLoopBackOff', 'ImagePullBackOff') else ''),
                 f'    Ready:          {pod["ready"]}', f'    Restart Count:  {pod["restarts"]}',
                 f'    Requests:       cpu: {pod["cpu"]}m, memory: {pod["mem"]}Mi' if pod['cpu'] or pod['mem'] else '    Requests:       <none>',
                 f'    Readiness:      {probe_text}', 'Conditions:', f'  Ready             {pod["ready"]}', 'Events:']
        events = [e for e in kube['events'] if e['object'] == f'pod/{name}']
        lines += [f'  {e["type"]:<8} {e["reason"]:<18} {e["message"]}' for e in events] or ['  <none>']
        return '\n'.join(lines) + '\n'
    if kind == 'Deployment':
        d = find_object(world, 'Deployment', name, namespace)
        spec = d['spec']
        strategy = spec.get('strategy') or {}
        rolling = strategy.get('rollingUpdate') or {}
        container = spec['template']['spec']['containers'][0]
        pods = [p for p in kube['pods'].values() if p['deployment'] == name and p['namespace'] == namespace]
        lines = [f'Name:                   {name}', f'Namespace:              {namespace}',
                 f'Selector:               {", ".join(f"{k}={v}" for k, v in spec["selector"]["matchLabels"].items())}',
                 f'Replicas:               {spec.get("replicas", 1)} desired | {sum(p["ready"] for p in pods)} available | {len(pods)} total',
                 f'StrategyType:           {strategy.get("type", "RollingUpdate")}',
                 f'RollingUpdateStrategy:  {rolling.get("maxUnavailable", "25%")} max unavailable, {rolling.get("maxSurge", "25%")} max surge'
                 if strategy.get('type', 'RollingUpdate') == 'RollingUpdate' else '',
                 'Pod Template:', f'  Labels:  {", ".join(f"{k}={v}" for k, v in (spec["template"]["metadata"].get("labels") or {}).items())}',
                 f'  Containers:', f'   {container["name"]}:', f'    Image:      {container["image"]}',
                 f'    Readiness:  {"set" if container.get("readinessProbe") else "<none>"}', 'Events:']
        events = [e for e in kube['events'] if e['object'] == f'deployment/{name}']
        lines += [f'  {e["type"]:<8} {e["reason"]:<24} {e["message"]}' for e in events[-10:]] or ['  <none>']
        return '\n'.join(l for l in lines if l) + '\n'
    if kind == 'Service':
        s = find_object(world, 'Service', name, namespace)
        eps = endpoints(world, s)
        lines = [f'Name:              {name}', f'Namespace:         {namespace}',
                 f'Selector:          {", ".join(f"{k}={v}" for k, v in (s["spec"].get("selector") or {}).items()) or "<none>"}',
                 f'Type:              {s["spec"].get("type", "ClusterIP")}']
        for p in s['spec'].get('ports') or []:
            lines.append(f'Port:              {p.get("name", "<unset>")}  {p["port"]}/TCP')
            lines.append(f'TargetPort:        {p.get("targetPort", p["port"])}/TCP')
        lines.append(f'Endpoints:         {",".join(eps) or "<none>"}')
        return '\n'.join(lines) + '\n'
    if kind in ('Ingress', 'HorizontalPodAutoscaler'):
        from . import autoscale, ingress
        obj = find_object(world, kind, name, namespace)
        return ingress.describe(world, obj) if kind == 'Ingress' else autoscale.describe(world, obj)
    raise KubeError(f'describe {kind} is not simulated (pod, deployment, service, ingress, hpa)')


def rollout(world: dict, args: list[str], namespace: str, opts: dict) -> tuple[str, int, dict]:
    kube = kube_state(world)
    if len(args) < 2:
        raise KubeError('Usage: kubectl rollout status|history|undo|restart deployment/NAME')
    verb = args[0]
    kind, name = split_ref(args[1], 'Deployment' if len(args) < 3 else None) if '/' in args[1] else (RESOURCE_NAMES.get(args[1]), args[2] if len(args) > 2 else None)
    if kind != 'Deployment' or not name:
        raise KubeError('error: the lab simulates rollouts of deployments: kubectl rollout status deployment/NAME')
    deployment = find_object(world, 'Deployment', name, namespace)
    records = [r for r in kube['rollouts'] if r['deployment'] == name and r['namespace'] == namespace]
    if verb == 'status':
        if not records:
            return f'deployment "{name}" successfully rolled out\n', 0, {}
        last = records[-1]
        return '\n'.join(last['timeline']) + '\n', 0 if last['complete'] else 1, {'complete': last['complete']}
    if verb == 'history':
        rows = [('REVISION', 'CHANGE-CAUSE')]
        for rs in sorted((r for r in kube['replicasets'].values() if r['deployment'] == name), key=lambda r: r['revision']):
            rows.append((rs['revision'], rs['change_cause']))
        return f'deployment.apps/{name}\n' + table(rows), 0, {}
    if verb == 'undo':
        owned = sorted((r for r in kube['replicasets'].values() if r['deployment'] == name), key=lambda r: r['revision'])
        current = template_hash(deployment['spec']['template'])
        wanted = opts.get('--to-revision')
        if wanted:
            target = next((r for r in owned if str(r['revision']) == str(wanted)), None)
        else:
            previous = [r for r in owned if r['hash'] != current]
            target = previous[-1] if previous else None
        if target is None:
            raise KubeError(f'error: no rollout history found for deployment "{name}"' if not wanted else
                            f'error: unable to find specified revision {wanted} in history')
        deployment['spec']['template'] = deepcopy(target['template'])
        record = reconcile(world, deployment, target['change_cause'])
        return f'deployment.apps/{name} rolled back\n', 0, {'rollout': record['revision']}
    if verb == 'restart':
        annotations = deployment['spec']['template'].setdefault('metadata', {}).setdefault('annotations', {})
        annotations['kubectl.kubernetes.io/restartedAt'] = world['clock']
        record = reconcile(world, deployment, None)
        return f'deployment.apps/{name} restarted\n', 0, {'rollout': record['revision']}
    raise KubeError(f'error: rollout {verb} is not simulated (status, history, undo, restart)')


def options(args: list[str]) -> tuple[dict[str, str], list[str]]:
    opts: dict[str, str] = {}
    positional: list[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ('-n', '--namespace', '-f', '--filename', '-o', '--output', '--replicas', '--to-revision', '-l',
                   '--selector', '--image') and i + 1 < len(args):
            opts[{'-n': '--namespace', '-f': '--filename', '-o': '--output', '-l': '--selector'}.get(arg, arg)] = args[i + 1]
            i += 2
            continue
        if arg.startswith('--') and '=' in arg:
            name, value = arg.split('=', 1)
            opts[{'--namespace': '--namespace', '--filename': '--filename', '--output': '--output'}.get(name, name)] = value
        elif arg.startswith('-o') and len(arg) > 2:
            opts['--output'] = arg[2:].lstrip('=')
        elif arg.startswith('-'):
            opts[arg] = 'true'
        else:
            positional.append(arg)
        i += 1
    return opts, positional


def kubectl(folder: Path, args: list[str], world: dict) -> tuple[str, int, dict]:
    if not args or args[0] in ('help', '-h', '--help'):
        return HELP, 0, {}
    kube = kube_state(world)
    if not kube['nodes']:
        raise KubeError('The connection to the server localhost:8080 was refused - did you specify the right host or '
                        'port? (this mission has no simulated cluster)')
    verb, rest = args[0], args[1:]
    opts, positional = options(rest)
    namespace = opts.get('--namespace', 'default')
    if namespace != 'default' and verb not in ('create', 'version', 'cluster-info') and \
            key('Namespace', '', namespace) not in kube['objects'] and not (verb == 'apply'):
        if verb == 'get':
            return f'No resources found in {namespace} namespace.\n', 0, {}
        raise KubeError(f'Error from server (NotFound): namespaces "{namespace}" not found')
    if verb == 'apply':
        target = opts.get('--filename')
        if not target:
            raise KubeError('error: must specify one of -f and -k')
        text, summary = apply(folder, target, world, namespace)
        return text, 1 if summary.get('errors') else 0, summary
    if verb == 'get':
        return get(world, positional, namespace, opts.get('--output'), '--show-labels' in opts,
                   '--all-namespaces' in opts or '-A' in opts), 0, {}
    if verb == 'create':
        if positional[:1] in (['namespace'], ['ns']) and len(positional) == 2:
            name = positional[1]
            if key('Namespace', '', name) in kube['objects']:
                raise KubeError(f'Error from server (AlreadyExists): namespaces "{name}" already exists')
            if not DNS_LABEL.fullmatch(name) or len(name) > 63:
                raise KubeError(f'The Namespace "{name}" is invalid: metadata.name: Invalid value: "{name}": a '
                                'lowercase RFC 1123 label must consist of lower case alphanumeric characters or \'-\'')
            kube['objects'][key('Namespace', '', name)] = {'kind': 'Namespace', 'name': name, 'namespace': '',
                                                            'labels': {}, 'annotations': {}, 'spec': {}, 'data': None,
                                                            'source': 'kubectl create', 'created_at': world['clock']}
            worldlib.advance(world, 1)
            return f'namespace/{name} created\n', 0, {}
        raise KubeError('error: the lab simulates kubectl create namespace NAME; write other objects in a manifest '
                        'and kubectl apply -f it')
    if verb == 'describe':
        return describe(world, positional, namespace), 0, {}
    if verb == 'rollout':
        return rollout(world, positional, namespace, opts)
    if verb == 'scale':
        if not positional or '--replicas' not in opts:
            raise KubeError('error: required flag(s) "replicas" not set')
        _, name = split_ref(positional[0], 'Deployment')
        deployment = find_object(world, 'Deployment', name, namespace)
        record = scale_to(world, deployment, int(opts['--replicas']))
        return f'deployment.apps/{name} scaled\n', 0, {'replicas': record['replicas']}
    if verb == 'set' and positional[:1] == ['image'] and len(positional) >= 3:
        _, name = split_ref(positional[1], 'Deployment')
        deployment = find_object(world, 'Deployment', name, namespace)
        changed = False
        for assignment in positional[2:]:
            cname, _, image = assignment.partition('=')
            for container in deployment['spec']['template']['spec']['containers']:
                if container['name'] == cname:
                    container['image'] = image
                    changed = True
        if not changed:
            raise KubeError(f'error: unable to find container named "{positional[2].split("=")[0]}"')
        reconcile(world, deployment, None)
        return f'deployment.apps/{name} image updated\n{DIM}(the manifest file was not changed: the cluster now differs from it){RESET}\n', 0, {}
    if verb == 'logs':
        if not positional:
            raise KubeError('error: expected a pod name: kubectl logs POD')
        name = positional[0].split('/', 1)[-1]
        pod = kube['pods'].get(name)
        if pod is not None and pod['namespace'] != namespace:
            pod = None
        if pod is None:
            deployment_pods = [p for p in kube['pods'].values() if p['deployment'] == name and p['namespace'] == namespace]
            pod = deployment_pods[0] if deployment_pods else None
        if pod is None:
            raise KubeError(f'Error from server (NotFound): pods "{name}" not found')
        if pod['status'] == 'ImagePullBackOff':
            raise KubeError(f'Error from server (BadRequest): container "{pod["containers"][0]["name"]}" in pod '
                            f'"{pod["name"]}" is waiting to start: trying and failing to pull image')
        return '\n'.join(pod['logs']) + '\n', 0, {}
    if verb == 'delete':
        if opts.get('--filename'):
            docs = load_manifests(folder, opts['--filename'])
            names = [(d['kind'], (d.get('metadata') or {}).get('name')) for _, d in docs]
        elif len(positional) >= 1:
            kind, name = split_ref(positional[0]) if '/' in positional[0] else (RESOURCE_NAMES.get(positional[0]), positional[1] if len(positional) > 1 else None)
            names = [(kind, name)]
        else:
            raise KubeError('error: resource(s) were provided, but no name was specified')
        lines = []
        for kind, name in names:
            if kind == 'Pod':
                if name not in kube['pods']:
                    raise KubeError(f'Error from server (NotFound): pods "{name}" not found')
                pod = kube['pods'].pop(name)
                if pod['namespace'] != namespace:
                    kube['pods'][name] = pod
                    raise KubeError(f'Error from server (NotFound): pods "{name}" not found')
                deployment = kube['objects'].get(key('Deployment', pod['namespace'], pod['deployment']))
                if deployment:
                    reconcile(world, deployment, None)
                lines.append(f'pod "{name}" deleted')
                continue
            if kind is None or kind not in KINDS:
                raise KubeError(f'error: the server doesn\'t have a resource type "{positional[0] if positional else kind}"')
            k = key(kind, '' if kind == 'Namespace' else namespace, name)
            if k not in kube['objects']:
                raise KubeError(f'Error from server (NotFound): {PLURALS.get(kind, kind.lower() + "s")} "{name}" not found')
            del kube['objects'][k]
            doomed = namespace if kind != 'Namespace' else name
            if kind == 'Namespace':
                for other in [o for o, v in kube['objects'].items() if v['namespace'] == name]:
                    del kube['objects'][other]
            if kind in ('Deployment', 'Namespace'):
                for pod in [p for p in kube['pods'].values() if p['namespace'] == doomed
                            and (kind == 'Namespace' or p['deployment'] == name)]:
                    del kube['pods'][pod['name']]
                for rs in [r for r in kube['replicasets'].values() if r['namespace'] == doomed
                           and (kind == 'Namespace' or r['deployment'] == name)]:
                    del kube['replicasets'][rs['name']]
            lines.append(f'{NOUNS[kind].split(".")[0]}{"." + NOUNS[kind].split(".", 1)[1] if "." in NOUNS[kind] else ""} "{name}" deleted')
        worldlib.advance(world, 3)
        return '\n'.join(lines) + '\n', 0, {}
    if verb in ('version', 'cluster-info'):
        return ('Client Version: v1.31.2 (simulated)\nServer Version: v1.31.2 (simulated cluster, Datapass)\n'
                if verb == 'version' else 'Kubernetes control plane is running at https://127.0.0.1:6443 (simulated)\n'), 0, {}
    raise KubeError(f'error: unknown command "{verb}" for "kubectl" (the lab simulates apply, get, describe, logs, '
                    'rollout, scale, set image, create namespace, delete)')


HELP = f"""kubectl controls the simulated cluster   {DIM}(simulated by Datapass: nothing is deployed){RESET}

  apply -f FILE_OR_FOLDER            Create or update objects (Deployment, Service, ConfigMap, Namespace, Ingress,
                                     HorizontalPodAutoscaler)
  get pods|deploy|rs|svc|endpoints|ingress|hpa|ingressclass|ns|nodes|events|all [NAME] [-o wide|json] [-A]
  describe pod|deployment|service|ingress|hpa NAME
  create namespace NAME
  logs POD
  rollout status|history|undo|restart deployment/NAME [--to-revision=N]
  scale deployment/NAME --replicas=N
  set image deployment/NAME CONTAINER=IMAGE
  delete -f FILE | delete pod|deployment|service NAME
  Flags: -n NAMESPACE, -A (every namespace)
  curl http://HOST/PATH              reaches the cluster through its ingress controller (lab shell)
  lab load replay                    replays the recorded load; HorizontalPodAutoscalers react to it
"""
