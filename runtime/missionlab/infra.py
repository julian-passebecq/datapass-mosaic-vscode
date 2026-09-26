"""Infra Lab missions: the fixture builder and the checks on the simulated world (runtime/infralab).

The learner types simulated terraform, docker, kubectl and az commands in the Infra Lab shell; nothing is provisioned,
built or deployed. This module builds the mission folder from the shipped pack (files, then the simulated world, then
the fixture's own simulated commands) and, when the learner asks, reads what their commands left behind: the simulated
terraform.tfstate, the simulated subscription, Docker engine and cluster in `.infralab/world.json`, the shell's
journal, and their files (read, never executed). Some checks re-run a simulation (a fresh `terraform plan`, the layer
cache after a pretend code change, an alert rule replayed over the metric scenario); none runs a real tool.
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
import shutil
import shlex
import tempfile
from typing import Any, Callable

from infralab import docker as dockerlib, kube as kubelib, monitor, shell, terraform, world as worldlib

from .model import (AzureAlertCheck, AzureResourceCheck, DockerBuildCheck, DockerContainerCheck, DockerImageCheck,
                    JournalCheck, K8sDeploymentCheck, K8sServiceCheck, Mission, TfConfigCheck, TfPlanCheck,
                    TfStateCheck)
from .terminal import FixtureError, _force_remove, _move, _rename, _write

TRUTH = ('Checked on the simulation: your files (read, never executed), the simulated terraform.tfstate, and the '
         'simulated subscription, Docker engine and cluster your commands changed. Nothing was provisioned, built or '
         'deployed.')
Outcome = tuple[bool, str]


# ---- Fixture -------------------------------------------------------------------------------------------------------


def build_fixture(mission: Mission, pack_dir: Path, workspace: Path) -> dict[str, Any]:
    """(Re)create `missions/<id>/` from the pack. An existing folder is moved to .datapass/missions/attic/, never
    deleted. The new one is built in a staging folder, its setup commands played there, then moved into place."""
    if mission.infra is None:
        raise ValueError(f'Mission {mission.id} has no infra fixture.')
    target = workspace / mission.folder
    staging = Path(tempfile.mkdtemp(prefix='datapass-infra-'))
    building = staging / mission.id
    building.mkdir()
    try:
        files = 0
        overlay = pack_dir / mission.id / 'project'
        if overlay.is_dir():
            for path in sorted(overlay.rglob('*')):
                if path.is_file() and not path.is_symlink():
                    destination = building / path.relative_to(overlay)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, destination)
                    files += 1
        for relative, spec in mission.infra.files.items():
            _write(building, relative, spec)
            files += 1
        worldlib.reset(building, mission.infra.world)
        try:
            shell.setup_commands(building, mission.infra.setup)
        except RuntimeError as error:
            raise FixtureError(str(error)) from None
        previous = None
        if target.exists():
            attic = workspace / '.datapass' / 'missions' / 'attic'
            attic.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            previous = attic / f'{mission.id}-{stamp}'
            counter = 1
            while previous.exists():
                counter += 1
                previous = attic / f'{mission.id}-{stamp}-{counter}'
            try:
                _rename(target, previous)
            except OSError as error:
                raise FixtureError(
                    f'{mission.folder} could not be moved aside ({error.strerror or error}): a program still has it '
                    'open. Close it, then start over again.') from None
        target.parent.mkdir(parents=True, exist_ok=True)
        _move(building, target)
    finally:
        shutil.rmtree(staging, onerror=_force_remove)
    return {'folder': mission.folder, 'files': files, 'commits': 0,
            'previous': previous.relative_to(workspace).as_posix() if previous else None}


# ---- Helpers ---------------------------------------------------------------------------------------------------------


def _folder(files) -> Path:
    return files.folder


def _world(files) -> dict[str, Any]:
    return worldlib.load(_folder(files))


def _equal(found: Any, expected: Any) -> bool:
    if isinstance(expected, dict) and isinstance(found, dict):
        return all(_equal(found.get(k), v) for k, v in expected.items())
    return json.dumps(found, sort_keys=True) == json.dumps(expected, sort_keys=True)


def _show(value: Any) -> str:
    text = json.dumps(value, sort_keys=True)
    return text if len(text) < 120 else text[:117] + '...'


# ---- Terraform -------------------------------------------------------------------------------------------------------


def _tf_state(check: TfStateCheck, files, _ctx: dict) -> Outcome:
    folder = _folder(files)
    if not (folder / terraform.STATE_FILE).is_file():
        return False, 'There is no terraform.tfstate yet: nothing was applied.'
    state = terraform.read_state(folder)
    missing = [a for a in check.includes if a not in state.instances]
    if missing:
        return False, f'The state has no {", ".join(missing)}.'
    present = [a for a in check.excludes if a in state.instances]
    if present:
        return False, f'The state still has {", ".join(present)}.'
    for address, expected in check.attributes.items():
        inst = state.instances.get(address)
        if inst is None:
            return False, f'The state has no {address}.'
        for name, value in expected.items():
            if not _equal(inst.attributes.get(name), value):
                return False, f'{address}.{name} is {_show(inst.attributes.get(name))}.'
    for base, keys in check.instance_keys.items():
        found = sorted((i.index_key for i in state.instances.values()
                        if f'{i.type}.{i.name}' == base), key=lambda k: json.dumps(k))
        if found != sorted(keys, key=lambda k: json.dumps(k)):
            return False, f'{base} has the instances {_show(found)}.'
    return True, f'terraform.tfstate holds {len(state.instances)} resource instance(s).'


def _last_apply_flags(folder: Path) -> tuple[list[tuple[str, str]], list[str]]:
    for entry in reversed(worldlib.read_journal(folder)):
        if entry.get('tool') == 'terraform' and entry.get('exit_code') == 0 and \
                str(entry.get('command', '')).startswith('apply'):
            try:
                flags, _ = terraform.parse_flags(shlex.split(entry['line'])[2:])
            except (terraform.Failed, ValueError):
                break
            return flags['var'], flags['var_file']
    return [], []


def _tf_plan(check: TfPlanCheck, files, _ctx: dict) -> Outcome:
    folder = _folder(files)
    world = _world(files)
    try:
        config = terraform.load_config(folder)
        terraform.require_init(world, config)
        cli_vars, var_files = _last_apply_flags(folder)
        variables = terraform.variable_values(config, folder, cli_vars, var_files)
        plan = terraform.make_plan(folder, config, variables, world, terraform.read_state(folder))
    except terraform.Failed as failed:
        return False, f'terraform plan fails: {failed.diags[0].summary}.'
    except terraform.Diag as diag:
        return False, f'terraform plan fails: {diag.summary}.'
    if not check.changes and plan.has_changes():
        counts = plan.counts()
        return False, (f'terraform plan still has changes ({counts["add"]} to add, {counts["change"]} to change, '
                       f'{counts["destroy"]} to destroy{", " + str(counts["import"]) + " to import" if counts["import"] else ""}).')
    return True, 'terraform plan: no changes.' if not plan.has_changes() else 'terraform plan succeeds.'


def _tf_config(check: TfConfigCheck, files, _ctx: dict) -> Outcome:
    folder = _folder(files)
    try:
        config = terraform.load_config(folder)
    except terraform.Failed as failed:
        return False, f'The configuration does not load: {failed.diags[0].summary}.'
    for shape in check.resources:
        resource = config.resources.get(shape.address)
        if resource is None:
            return False, f'The configuration declares no {shape.address}.'
        if shape.for_each is not None and (resource.for_each is not None) != shape.for_each:
            return False, f'{shape.address} {"does not use" if shape.for_each else "uses"} for_each.'
        if shape.count is not None and (resource.count is not None) != shape.count:
            return False, f'{shape.address} {"does not use" if shape.count else "uses"} count.'
        if shape.prevent_destroy is not None and resource.lifecycle.prevent_destroy != shape.prevent_destroy:
            return False, f'{shape.address} has prevent_destroy = {str(resource.lifecycle.prevent_destroy).lower()}.'
        if shape.references:
            refs = {'.'.join(r) for r in terraform.tfexpr.body_references(resource.body)}
            local_refs = set()
            for ref in list(refs):
                if ref.startswith('local.') and ref[6:] in config.locals:
                    local_refs |= {'.'.join(r) for r in terraform.tfexpr.references(config.locals[ref[6:]].expr)}
            missing = [r for r in shape.references if r not in refs | local_refs]
            if missing:
                return False, f'{shape.address} does not refer to {", ".join(missing)}.'
    present = [a for a in check.absent if a in config.resources]
    if present:
        return False, f'The configuration still declares {", ".join(present)}.'
    for shape in check.variables:
        variable = config.variables.get(shape.name)
        if variable is None:
            return False, f'There is no variable "{shape.name}".'
        if shape.type is not None and terraform.type_label(variable.type) != shape.type:
            return False, f'var.{shape.name} is declared as {terraform.type_label(variable.type)}.'
        if shape.validation is not None and bool(variable.validations) != shape.validation:
            return False, f'var.{shape.name} {"has no" if shape.validation else "has a"} validation block.'
        if shape.default is not None and (variable.default is not None) != shape.default:
            return False, f'var.{shape.name} {"has no" if shape.default else "has a"} default.'
    missing_outputs = [o for o in check.outputs if o not in config.outputs]
    if missing_outputs:
        return False, f'No output named {", ".join(missing_outputs)}.'
    return True, f'{len(config.resources)} resource block(s) as expected.'


def _azure_resource(check: AzureResourceCheck, files, _ctx: dict) -> Outcome:
    world = _world(files)
    found = [r for r in world['azure']['resources'].values()
             if r['type'].lower() == check.type.lower() and r['attributes'].get('name') == check.name
             and (check.group is None or monitor.resource_group_of(r['id']).lower() == check.group.lower())]
    if check.count is not None:
        same_type = [r for r in world['azure']['resources'].values() if r['type'].lower() == check.type.lower()]
        if len(same_type) != check.count:
            return False, f'The subscription has {len(same_type)} {check.type.rsplit("/", 1)[-1]}.'
    if not check.exists:
        return (not found), (f'{check.name} is gone.' if not found else f'{check.name} still exists.')
    if not found:
        return False, f'The subscription has no {check.type.rsplit("/", 1)[-1]} named {check.name}.'
    resource = found[0]
    if check.managed_by and resource.get('managed_by') != check.managed_by:
        return False, (f'{check.name} was created by {resource.get("managed_by")}' +
                       (' (it was deleted and created again)' if check.managed_by == 'portal' else '') + '.')
    for name, value in check.attributes.items():
        if not _equal(resource['attributes'].get(name), value):
            return False, f'{check.name}: {name} is {_show(resource["attributes"].get(name))}.'
    return True, f'{check.name} exists.'


def _journal(check: JournalCheck, files, _ctx: dict) -> Outcome:
    entries = worldlib.read_journal(_folder(files))
    usable = [e for e in entries if not check.successful_only or e.get('exit_code') == 0]
    lines = [str(e.get('line', '')) for e in usable]
    for pattern in check.includes:
        if not any(re.search(pattern, line) for line in lines):
            return False, 'A command the ticket asks for was not run (or did not succeed).'
    for pattern in check.excludes:
        if any(re.search(pattern, line) for line in lines):
            return False, 'A command the ticket rules out was run.'
    for first, second in check.before:
        a = [i for i, line in enumerate(lines) if re.search(first, line)]
        b = [i for i, line in enumerate(lines) if re.search(second, line)]
        if not a or not b or a[-1] > b[-1]:
            return False, 'The commands did not run in the expected order.'
    return True, f'{len(entries)} command(s) in the journal.'


# ---- Docker ----------------------------------------------------------------------------------------------------------


def _docker_image(check: DockerImageCheck, files, _ctx: dict) -> Outcome:
    world = _world(files)
    image = dockerlib.find_image(world, check.tag)
    if image is None:
        return False, f'There is no image {check.tag}.'
    folder = _folder(files)
    if check.current:
        path = folder / image.get('dockerfile', 'Dockerfile')
        current = dockerlib.hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        if current != image.get('dockerfile_sha256'):
            return False, f'{check.tag} was built from an older version of {image.get("dockerfile")}: build it again.'
    if check.base and not re.fullmatch(check.base, image.get('base', '')):
        return False, f'{check.tag} is based on {image.get("base")}.'
    user = str(image['config'].get('user', 'root'))
    if check.not_root and user in ('root', '0', ''):
        return False, f'{check.tag} runs as root.'
    if check.max_size_mb is not None and image['size_mb'] > check.max_size_mb:
        return False, f'{check.tag} weighs {image["size_mb"]:.0f} MB.'
    reported = {rule for rule, _line, _msg in image.get('lint', [])}
    bad = [rule for rule in check.no_lint if rule in reported]
    if bad:
        return False, f'The build still reports {", ".join(bad)}.'
    if check.healthcheck is not None and bool(image['config'].get('healthcheck')) != check.healthcheck:
        return False, f'{check.tag} {"has no" if check.healthcheck else "has a"} HEALTHCHECK.'
    return True, f'{check.tag}: {image["size_mb"]:.0f} MB, user {user}.'


def _docker_build(check: DockerBuildCheck, files, _ctx: dict) -> Outcome:
    folder = _folder(files)
    world = _world(files)
    context = folder if check.context == '.' else folder / check.context
    dockerfile = folder / check.dockerfile
    try:
        for pattern in check.context_excludes:
            sent = [p for p in dockerlib.context_files(context) if p == pattern or p.startswith(pattern.rstrip('/') + '/')]
            if sent:
                return False, f'{pattern} is still sent to the builder.'
        if check.changed:
            world['docker']['cache'] = []
            first = dockerlib.simulate_build(context, dockerfile, world)
            world['docker']['cache'] = [s.key for s in first.steps]
            changed = {path: f'# changed by the checker\n{path}' for path in check.changed}
            second = dockerlib.simulate_build(context, dockerfile, world, changed=changed)
            for needle in check.cached:
                steps = [s for s in second.steps if needle in s.text]
                if not steps:
                    return False, f'The Dockerfile has no step with {needle!r}.'
                if not all(s.cached for s in steps):
                    return False, (f'After a change to {", ".join(check.changed)}, the step "{steps[0].text[:60]}" runs '
                                   'again instead of coming from the cache.')
    except dockerlib.DockerError as error:
        return False, f'The build fails: {error}'
    return True, 'The build behaves as expected.'


def _docker_container(check: DockerContainerCheck, files, _ctx: dict) -> Outcome:
    world = _world(files)
    containers = list(world['docker']['containers'].values())
    if check.name:
        found = [c for c in containers if c['name'] == check.name]
    else:
        found = [c for c in containers if c.get('service') == check.service]
    label = check.name or f'the {check.service} service'
    if not found:
        return False, f'There is no container for {label}.'
    container = found[0]
    if check.running and container['status'] != 'running':
        return False, f'{label} exited with code {container["exit_code"]}: see its logs.'
    if check.health is not None:
        health = container['health'] or 'none'
        if health != check.health:
            reason = f' ({container["health_reason"]})' if container.get('health_reason') else ''
            return False, f'{label} is {health}{reason}.'
    if check.reachable:
        port, path = check.reachable
        text, code = dockerlib.curl(world, f'http://localhost:{port}{path}')
        if code != 0:
            return False, f'GET localhost:{port}{path} fails: {shell.strip_ansi(text).splitlines()[0]}'
    if check.waits_healthy:
        try:
            _name, data = dockerlib.load_compose(_folder(files))
        except dockerlib.DockerError as error:
            return False, str(error)
        depends = dockerlib.compose_depends((data['services'].get(check.service) or {}))
        loose = [d for d in check.waits_healthy if depends.get(d) != 'service_healthy']
        if loose:
            return False, f'{check.service} does not wait for {", ".join(loose)} to be healthy.'
    return True, f'{label} is {container["status"]}' + (f' ({container["health"]})' if container['health'] else '') + '.'


# ---- Monitoring ------------------------------------------------------------------------------------------------------


def _azure_alert(check: AzureAlertCheck, files, _ctx: dict) -> Outcome:
    world = _world(files)
    rules = [r for r in world['azure'].get('alerts', {}).values()
             if r['metric'] == check.metric
             and world['azure']['resources'].get(r['scope'], {}).get('attributes', {}).get('name') == check.scope]
    if not rules:
        return False, f'There is no alert rule on {check.metric} of {check.scope}.'
    problems = []
    for rule in rules:
        problem = alert_problem(check, rule, world)
        if problem is None:
            return True, f'{rule["name"]} pages as expected.'
        problems.append(f'{rule["name"]}: {problem}')
    return False, ' / '.join(problems)


def alert_problem(check: AzureAlertCheck, rule: dict, world: dict) -> str | None:
    if check.enabled and not rule['enabled']:
        return 'it is disabled'
    if check.max_severity is not None and rule['severity'] > check.max_severity:
        return f'its severity is {rule["severity"]}'
    if check.action_group:
        names = [world['azure']['resources'].get(a, {}).get('attributes', {}).get('name') for a in rule['actions']]
        if check.action_group not in names:
            return 'it notifies nobody from the expected action group'
    incidents = monitor.replay(rule, world['azure']['resources'][rule['scope']], world)
    fired = [worldlib.parse_time(i['fired']) for i in incidents]
    for start, end in check.fires:
        a, b = worldlib.parse_time(start), worldlib.parse_time(end)
        if not any(a <= t <= b for t in fired):
            return f'it does not fire between {start[11:16]} and {end[11:16]} UTC'
    for start, end in check.quiet:
        a, b = worldlib.parse_time(start), worldlib.parse_time(end)
        noisy = [t for t in fired if a <= t <= b]
        if noisy:
            return f'it fires at {worldlib.format_time(noisy[0])[11:16]} UTC, which should not page anyone'
    return None


# ---- Kubernetes -----------------------------------------------------------------------------------------------------


def _k8s_deployment(check: K8sDeploymentCheck, files, _ctx: dict) -> Outcome:
    world = _world(files)
    kube = kubelib.kube_state(world)
    obj = kube['objects'].get(kubelib.key('Deployment', check.namespace, check.name))
    if obj is None:
        return False, f'The cluster has no deployment {check.name}.'
    container = obj['spec']['template']['spec']['containers'][0]
    pods = [p for p in kube['pods'].values() if p['deployment'] == check.name and p['namespace'] == check.namespace]
    if check.image and container['image'] != check.image:
        return False, f'{check.name} runs {container["image"]}.'
    if check.ready is not None and sum(p['ready'] for p in pods) < check.ready:
        return False, f'{check.name} has {sum(p["ready"] for p in pods)} ready pod(s).'
    if check.readiness_probe is not None and bool(container.get('readinessProbe')) != check.readiness_probe:
        return False, f'{check.name} {"has no" if check.readiness_probe else "has a"} readiness probe.'
    strategy = (obj['spec'].get('strategy') or {}).get('type', 'RollingUpdate')
    if check.strategy and strategy != check.strategy:
        return False, f'{check.name} uses the {strategy} strategy.'
    if check.no_crashing_pods:
        bad = [p['name'] for p in pods if p['status'] in ('CrashLoopBackOff', 'ImagePullBackOff')]
        if bad:
            return False, f'{bad[0]} is in {kube["pods"][bad[0]]["status"]}.'
    if check.last_rollout:
        rollouts = [r for r in kube['rollouts'] if r['deployment'] == check.name and not r['initial']]
        if not rollouts:
            return False, f'{check.name} has not been rolled out since the mission started.'
        last = rollouts[-1]
        shape = check.last_rollout
        if shape.to_image and last['to_image'] != shape.to_image:
            return False, f'The last rollout of {check.name} went to {last["to_image"]}.'
        if shape.complete is not None and last['complete'] != shape.complete:
            return False, f'The last rollout of {check.name} {"did not complete" if shape.complete else "completed"}.'
        if shape.min_available is not None and (last['min_available'] or 0) < shape.min_available:
            return False, (f'During the last rollout only {last["min_available"]} pod(s) answered traffic at one point: '
                           'users saw errors.')
    return True, f'{check.name}: {sum(p["ready"] for p in pods)} ready pod(s) on {container["image"]}.'


def _k8s_service(check: K8sServiceCheck, files, _ctx: dict) -> Outcome:
    world = _world(files)
    kube = kubelib.kube_state(world)
    obj = kube['objects'].get(kubelib.key('Service', check.namespace, check.name))
    if obj is None:
        return False, f'The cluster has no service {check.name}.'
    eps = kubelib.endpoints(world, obj)
    if len(eps) < check.min_endpoints:
        return False, f'The service {check.name} has {len(eps)} endpoint(s).'
    if check.reachable:
        ok, why = kubelib.service_reachable(world, obj)
        if not ok:
            return False, f'Traffic to {check.name} does not reach the app: {why}.'
    return True, f'{check.name} has {len(eps)} endpoint(s).'


CHECKS: dict[str, Callable[[Any, Any, dict], Outcome]] = {
    'tf_state': _tf_state, 'tf_plan': _tf_plan, 'tf_config': _tf_config, 'azure_resource': _azure_resource,
    'journal': _journal, 'docker_image': _docker_image, 'docker_build': _docker_build,
    'docker_container': _docker_container, 'azure_alert': _azure_alert, 'k8s_deployment': _k8s_deployment,
    'k8s_service': _k8s_service,
}
