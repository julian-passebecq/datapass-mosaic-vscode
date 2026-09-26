"""The Infra Lab shell: one simulated command line at a time, routed to the simulators, and journaled.

The VS Code terminal the learner types in is a Pseudoterminal owned by the extension; it spawns no process and sends
each line here. The line is split like a POSIX shell would split it (quotes, no expansion), then routed to
`terraform`, `docker`, `kubectl`, `az`, `curl` or the lab's own `lab` command. Pipes, redirections, `&&`, variables
and command substitution are refused: nothing is handed to a real shell. Every command is appended to
`.infralab/journal.jsonl`, which the mission checker reads.
"""
from __future__ import annotations

from pathlib import Path
import re
import shlex
import threading
from typing import Any

from . import docker, kube, monitor, terraform, world as worldlib

BOLD, GREEN, YELLOW, RED, DIM, RESET = '\x1b[1m', '\x1b[32m', '\x1b[33m', '\x1b[31m', '\x1b[2m', '\x1b[0m'
MAX_LINE = 2000
MAX_CAT_BYTES = 200_000
SHELL_OPERATORS = {'|', '||', '&&', ';', '>', '>>', '<', '&', '2>', '2>&1', '1>'}
FOOTERS = {
    'terraform': terraform.SIMULATED_FOOTER,
    'docker': docker.FOOTER,
    'kubectl': f'{DIM}[simulated: the cluster is simulated by Datapass; nothing was deployed]{RESET}',
    'az': f'{DIM}[simulated: no Azure account is used; the subscription is simulated by Datapass]{RESET}',
}
MUTATING = {
    'terraform': {'apply', 'destroy', 'import'},
    'docker': {'build', 'run', 'compose'},
    'kubectl': {'apply', 'rollout', 'scale', 'set', 'delete'},
    'az': {'monitor', 'vm'},
}
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def lock_for(folder: Path) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(str(folder.resolve()).lower(), threading.Lock())


def strip_ansi(text: str) -> str:
    return re.sub(r'\x1b\[[0-9;]*m', '', text)


HELP = f"""{BOLD}Infra Lab shell{RESET} {DIM}(simulated: nothing is provisioned, built or deployed){RESET}

  terraform init | validate | plan | apply | destroy | import | state | output | show
  docker build | images | history | run | ps | logs | stop | rm | compose up/ps/logs/down
  kubectl apply -f | get | describe | logs | rollout | scale | set image | delete
  az vm … | az monitor metrics … | az monitor metrics alert …
  curl http://localhost:PORT/PATH   reach a simulated container through its published port
  lab status | lab alerts replay     {DIM}(Datapass lab commands){RESET}
  ls | cat FILE | pwd | clear | help

Each tool also answers --help. Edit your files in VS Code; this shell reads them when you run a command.
Pipes, redirections, && and variables are not simulated: one command at a time.
"""


def run_line(folder: Path, line: str, answer: str | None = None) -> dict[str, Any]:
    """Run one command line in `folder` (a mission folder or any lab folder) and return what the terminal shows."""
    line = line.strip()
    if not line:
        return {'output': '', 'exit_code': 0, 'prompt': None, 'tool': None}
    if len(line) > MAX_LINE:
        return {'output': f'{RED}The line is too long for the lab shell.{RESET}\n', 'exit_code': 2, 'prompt': None,
                'tool': None}
    try:
        args = shlex.split(line, posix=True)
    except ValueError as error:
        return {'output': f'{RED}lab shell: {error} (check your quotes){RESET}\n', 'exit_code': 2, 'prompt': None,
                'tool': None}
    if any(a in SHELL_OPERATORS for a in args) or re.search(r'\$\(|`|\$\{?[A-Za-z_]', line):
        return {'output': (f'{YELLOW}lab shell: pipes, redirections, &&, variables and command substitution are not '
                           f'simulated.{RESET} Run one command at a time; copy ids from the output.\n'),
                'exit_code': 2, 'prompt': None, 'tool': None}
    tool = args[0]
    with lock_for(folder):
        result = dispatch(folder, tool, args[1:], answer)
        if result.get('journal', True) and tool not in ('help', 'clear', 'pwd', 'ls', 'cat'):
            record(folder, line, tool, args[1:], result, answer)
    output = result['output']
    if (tool in FOOTERS and result['exit_code'] == 0 and not result.get('prompt')
            and args[1:2] and args[1] in MUTATING.get(tool, set())):
        output = output.rstrip('\n') + '\n' + FOOTERS[tool] + '\n'
    return {'output': output, 'exit_code': result['exit_code'], 'prompt': result.get('prompt'), 'tool': tool}


def dispatch(folder: Path, tool: str, args: list[str], answer: str | None) -> dict[str, Any]:
    if tool in ('help', '-h', '--help'):
        return {'output': HELP, 'exit_code': 0, 'journal': False}
    if tool == 'pwd':
        return {'output': f'{folder.name} (the mission folder)\n', 'exit_code': 0}
    if tool == 'ls':
        return list_folder(folder, args)
    if tool == 'cat':
        return cat(folder, args)
    if tool == 'terraform':
        result = terraform.command(folder, args, answer)
        return {'output': result.output, 'exit_code': result.exit_code, 'prompt': result.prompt,
                'summary': result.summary}
    try:
        world = worldlib.load(folder)
    except worldlib.WorldError as error:
        return {'output': f'{RED}{error}{RESET}\n', 'exit_code': 1}
    try:
        if tool == 'docker':
            output, code, summary = docker.command(folder, args, world)
        elif tool == 'kubectl':
            output, code, summary = kube.kubectl(folder, args, world)
        elif tool == 'az':
            output, code, summary = monitor.az(args, world)
        elif tool == 'curl':
            urls = [a for a in args if not a.startswith('-')]
            if not urls:
                return {'output': 'curl: try \'curl http://localhost:8080/health\'\n', 'exit_code': 2}
            output, code = docker.curl(world, urls[0])
            summary = {'url': urls[0]}
            worldlib.save(folder, world)
            return {'output': output, 'exit_code': code, 'summary': summary}
        elif tool == 'lab':
            if args[:1] == ['status']:
                return {'output': status_text(folder, world), 'exit_code': 0}
            output, code, summary = monitor.lab(args, world)
        elif tool in ('bash', 'sh', 'pwsh', 'powershell', 'cmd', 'python', 'python3', 'node', 'npm', 'pip', 'git',
                      'ssh', 'sudo', 'helm', 'minikube', 'kind', 'tofu', 'podman'):
            return {'output': (f'{YELLOW}{tool} is not part of the Infra Lab shell.{RESET} This terminal only '
                               'simulates terraform, docker, kubectl, az and curl; nothing typed here reaches a real '
                               'program. Use a normal VS Code terminal for real commands.\n'), 'exit_code': 127}
        else:
            return {'output': f'{tool}: command not found in the Infra Lab shell (type help)\n', 'exit_code': 127}
    except (docker.DockerError, kube.KubeError, monitor.AzError) as error:
        prefix = {'docker': 'ERROR: ', 'kubectl': '', 'az': 'ERROR: '}.get(tool, '')
        worldlib.save(folder, world)
        return {'output': f'{RED}{prefix}{error}{RESET}\n', 'exit_code': 1}
    worldlib.save(folder, world)
    return {'output': output, 'exit_code': code, 'summary': summary}


def record(folder: Path, line: str, tool: str, args: list[str], result: dict[str, Any], answer: str | None) -> None:
    if result.get('prompt'):
        return  # the answered command is journaled once, with its outcome
    try:
        clock = worldlib.load(folder)['clock']
    except worldlib.WorldError:
        clock = ''
    entries = worldlib.read_journal(folder)
    worldlib.append_journal(folder, {
        'n': (entries[-1]['n'] + 1) if entries else 1, 'at': clock, 'line': line, 'tool': tool,
        'command': ' '.join(a for a in args[:3] if not a.startswith('-'))[:80], 'exit_code': result['exit_code'],
        'answer': answer if answer is not None else None, 'summary': result.get('summary') or {},
    })


def list_folder(folder: Path, args: list[str]) -> dict[str, Any]:
    target = folder
    names = [a for a in args if not a.startswith('-')]
    if names:
        target = (folder / names[0]).resolve()
        if not target.is_relative_to(folder.resolve()) or not target.exists():
            return {'output': f'ls: cannot access \'{names[0]}\': No such file or directory\n', 'exit_code': 2}
    show_all = any(a.startswith('-') and 'a' in a for a in args)
    if target.is_file():
        return {'output': target.name + '\n', 'exit_code': 0}
    entries = []
    for child in sorted(target.iterdir(), key=lambda p: p.name.lower()):
        if child.name.startswith('.') and not show_all:
            continue
        entries.append(child.name + ('/' if child.is_dir() else ''))
    return {'output': '  '.join(entries) + ('\n' if entries else ''), 'exit_code': 0}


def cat(folder: Path, args: list[str]) -> dict[str, Any]:
    if not args:
        return {'output': 'cat: give a file name\n', 'exit_code': 2}
    out = []
    for name in args:
        path = (folder / name).resolve()
        if not path.is_relative_to(folder.resolve()) or not path.is_file():
            return {'output': f'cat: {name}: No such file or directory\n', 'exit_code': 1}
        if path.stat().st_size > MAX_CAT_BYTES:
            return {'output': f'cat: {name}: too large to show here; open it in the editor\n', 'exit_code': 1}
        out.append(path.read_text(encoding='utf-8', errors='replace'))
    return {'output': ''.join(out) if ''.join(out).endswith('\n') else ''.join(out) + '\n', 'exit_code': 0}


# ---- Views ---------------------------------------------------------------------------------------------------------


def state_view(folder: Path) -> dict[str, Any]:
    """What the simulated world of a folder holds, for the Workbench panel and `lab status`."""
    world = worldlib.load(folder)
    try:
        tf_state = terraform.read_state(folder)
        tf_resources = sorted(tf_state.instances)
        tf_outputs = tf_state.outputs
    except terraform.Failed:
        tf_resources, tf_outputs = [], {}
    azure = world['azure']
    kube_world = kube.kube_state(world)
    deployments = []
    for obj in kube_world['objects'].values():
        if obj['kind'] != 'Deployment':
            continue
        pods = [p for p in kube_world['pods'].values() if p['deployment'] == obj['name'] and p['namespace'] == obj['namespace']]
        container = obj['spec']['template']['spec']['containers'][0]
        rollouts = [r for r in kube_world['rollouts'] if r['deployment'] == obj['name']]
        deployments.append({'name': obj['name'], 'namespace': obj['namespace'], 'image': container['image'],
                            'replicas': int(obj['spec'].get('replicas', 1)), 'ready': sum(p['ready'] for p in pods),
                            'strategy': (obj['spec'].get('strategy') or {}).get('type', 'RollingUpdate'),
                            'last_rollout': ({k: rollouts[-1][k] for k in ('revision', 'complete', 'min_available', 'to_image')}
                                             if rollouts else None)})
    services = [{'name': o['name'], 'namespace': o['namespace'], 'endpoints': len(kube.endpoints(world, o))}
                for o in kube_world['objects'].values() if o['kind'] == 'Service']
    journal = worldlib.read_journal(folder)
    return {
        'clock': world['clock'],
        'simulated': worldlib.SIMULATED,
        'terraform': {'initialized': bool(world['terraform'].get('initialized')), 'resources': tf_resources,
                      'configured': any(folder.glob('*.tf')),
                      'outputs': {k: v for k, v in tf_outputs.items() if isinstance(v, (str, int, float, bool))}},
        'azure': {'resources': [{'name': r['attributes'].get('name'), 'type': r['type'],
                                 'group': monitor.resource_group_of(r['id']), 'managed_by': r.get('managed_by')}
                                for r in sorted(azure['resources'].values(), key=lambda r: r['id'])][:60],
                  'alerts': [{'name': a['name'], 'severity': a['severity'], 'metric': a['metric'],
                              'enabled': a['enabled'], 'actions': len(a['actions'])}
                             for a in sorted(azure.get('alerts', {}).values(), key=lambda a: a['name'])]},
        'docker': {'images': [{'tags': i['tags'], 'size_mb': i['size_mb'], 'user': i['config'].get('user')}
                              for i in world['docker']['images'].values()],
                   'containers': [{'name': c['name'], 'image': c['image'], 'status': c['status'], 'health': c['health'],
                                   'ports': c['ports']} for c in world['docker']['containers'].values()]},
        'kube': {'nodes': len(kube_world['nodes']), 'deployments': deployments, 'services': services},
        'journal': [{'n': e.get('n'), 'line': e.get('line'), 'exit_code': e.get('exit_code'), 'at': e.get('at')}
                    for e in journal[-12:]],
    }


def status_text(folder: Path, world: dict) -> str:
    view = state_view(folder)
    lines = [f'{BOLD}Simulated world of {folder.name}{RESET} {DIM}(clock {view["clock"]}){RESET}']
    tf = view['terraform']
    lines.append(f'  Terraform: {"initialized" if tf["initialized"] else "not initialized"}, '
                 f'{len(tf["resources"])} resource(s) in terraform.tfstate')
    lines.append(f'  Azure (simulated subscription): {len(view["azure"]["resources"])} resource(s), '
                 f'{len(view["azure"]["alerts"])} alert rule(s)')
    lines.append(f'  Docker: {len(view["docker"]["images"])} image(s), '
                 f'{sum(c["status"] == "running" for c in view["docker"]["containers"])} running container(s)')
    lines.append(f'  Kubernetes: {view["kube"]["nodes"]} node(s), {len(view["kube"]["deployments"])} deployment(s), '
                 f'{len(view["kube"]["services"])} service(s)')
    lines.append(f'{DIM}{worldlib.SIMULATED}{RESET}')
    del world
    return '\n'.join(lines) + '\n'


def setup_commands(folder: Path, commands: list[str]) -> list[dict[str, Any]]:
    """Commands a mission fixture plays before the learner starts (for example: deploy yesterday's version). They are
    not journaled as the learner's."""
    results = []
    for line in commands:
        args = shlex.split(line)
        with lock_for(folder):
            result = dispatch(folder, args[0], args[1:], 'yes')
        if result['exit_code'] != 0:
            raise RuntimeError(f'fixture command failed: {line}\n{strip_ansi(result["output"])}')
        results.append({'line': line, 'exit_code': result['exit_code']})
    return results
