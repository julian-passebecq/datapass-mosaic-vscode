"""The simulated Terraform CLI: init, validate, plan, apply, destroy, import, state, output, show.

The learner's `.tf` and `.tfvars` files are read by `hcl.py` and evaluated by `tfexpr.py` (never executed). Plans are
computed against `terraform.tfstate` (written in the folder, as Terraform does, and marked as simulated) and against
the simulated subscription in `.infralab/world.json`, which apply changes through the simulated azurerm provider
(`azurerm.py`). Output follows Terraform's wording so the learner reads what they will read at work; every command ends
with a reminder that nothing was provisioned.

Supported: terraform / provider / variable (type, default, validation, sensitive) / locals / resource / data /
output / moved / import blocks, `.tfvars`, `-var`, `-var-file`, count, for_each, depends_on, lifecycle
(prevent_destroy, create_before_destroy, ignore_changes). Refused with a message: modules, backends other than local,
provisioners, saved plan files, -target.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import difflib
import hashlib
import json
from pathlib import Path
from typing import Any
import uuid

from . import azurerm, hcl, tfexpr, world as worldlib
from .hcl import HclError
from .tfexpr import UNKNOWN, EvalError, Scope, is_unknown

STATE_FILE = 'terraform.tfstate'
TERRAFORM_VERSION = '1.9.8'
MAX_FILES = 40
META_ARGS = {'count', 'for_each', 'depends_on', 'provider', 'lifecycle'}
SIMULATED_FOOTER = '\x1b[2m[simulated: Terraform and azurerm are simulated by Datapass; nothing was provisioned in Azure]\x1b[0m'

BOLD, GREEN, YELLOW, RED, CYAN, DIM, RESET = '\x1b[1m', '\x1b[32m', '\x1b[33m', '\x1b[31m', '\x1b[36m', '\x1b[2m', '\x1b[0m'


class Diag(Exception):
    """A Terraform diagnostic (error or warning) with the place it points at."""

    def __init__(self, summary: str, detail: str = '', file: str = '', line: int = 0, context: str = '',
                 severity: str = 'error'):
        super().__init__(summary)
        self.summary, self.detail, self.file, self.line, self.context = summary, detail, file, line, context
        self.severity = severity

    def render(self) -> str:
        color = RED if self.severity == 'error' else YELLOW
        title = 'Error' if self.severity == 'error' else 'Warning'
        lines = [f'{color}╷{RESET}', f'{color}│{RESET} {BOLD}{title}: {self.summary}{RESET}', f'{color}│{RESET}']
        if self.file:
            where = f'  on {self.file} line {self.line}' + (f', in {self.context}' if self.context else '') + ':'
            lines += [f'{color}│{RESET} {where}', f'{color}│{RESET}']
        for line in (self.detail or '').splitlines():
            lines.append(f'{color}│{RESET} {line}')
        lines.append(f'{color}╵{RESET}')
        return '\n'.join(lines)


class Failed(Exception):
    def __init__(self, diags: list[Diag]):
        super().__init__('; '.join(d.summary for d in diags))
        self.diags = diags


def from_hcl(error: HclError, context: str = '') -> Diag:
    summary = 'Invalid expression' if isinstance(error, EvalError) else 'Invalid configuration syntax'
    return Diag(summary, error.message, error.file, error.line, context)


# ---- Configuration -----------------------------------------------------------------------------------------------


@dataclass
class Lifecycle:
    prevent_destroy: bool = False
    create_before_destroy: bool = False
    ignore_changes: list[str] | str = field(default_factory=list)


@dataclass
class ResourceConfig:
    mode: str               # managed or data
    type: str
    name: str
    body: hcl.Body
    file: str
    line: int
    count: hcl.Attribute | None = None
    for_each: hcl.Attribute | None = None
    depends_on: list[str] = field(default_factory=list)
    lifecycle: Lifecycle = field(default_factory=Lifecycle)

    @property
    def address(self) -> str:
        return f'data.{self.type}.{self.name}' if self.mode == 'data' else f'{self.type}.{self.name}'

    @property
    def context(self) -> str:
        kind = 'data' if self.mode == 'data' else 'resource'
        return f'{kind} "{self.type}" "{self.name}"'


@dataclass
class VariableConfig:
    name: str
    type: Any = 'any'
    default: hcl.Attribute | None = None
    sensitive: bool = False
    nullable: bool = True
    validations: list[tuple[hcl.Attribute, hcl.Attribute | None]] = field(default_factory=list)
    file: str = ''
    line: int = 0


@dataclass
class OutputConfig:
    name: str
    value: hcl.Attribute
    sensitive: bool = False
    file: str = ''
    line: int = 0


@dataclass
class Config:
    files: list[str] = field(default_factory=list)
    variables: dict[str, VariableConfig] = field(default_factory=dict)
    locals: dict[str, hcl.Attribute] = field(default_factory=dict)
    resources: dict[str, ResourceConfig] = field(default_factory=dict)
    outputs: dict[str, OutputConfig] = field(default_factory=dict)
    moved: list[tuple[str, str, str, int]] = field(default_factory=list)
    imports: list[tuple[str, hcl.Attribute]] = field(default_factory=list)
    providers: dict[str, str] = field(default_factory=dict)       # local name -> source
    provider_blocks: dict[str, hcl.Block] = field(default_factory=dict)
    warnings: list[Diag] = field(default_factory=list)


def literal_string(attr: hcl.Attribute | None) -> str | None:
    if attr is None:
        return None
    return attr.expr.value if isinstance(attr.expr, hcl.Literal) and isinstance(attr.expr.value, str) else None


def reference_address(node: hcl.Node, file: str) -> str:
    """`azurerm_x.name`, `azurerm_x.name[0]`, `azurerm_x.name["k"]` from an expression (moved, import, depends_on)."""
    parts: list[str] = []
    key = ''
    current = node
    if isinstance(current, hcl.Index):
        if not isinstance(current.key, hcl.Literal):
            raise HclError('an instance key here must be a literal', file, node.line, node.col)
        value = current.key.value
        key = f'[{value}]' if isinstance(value, int) else f'[{json.dumps(value)}]'
        current = current.target
    while isinstance(current, hcl.GetAttr):
        parts.insert(0, current.name)
        current = current.target
    if not isinstance(current, hcl.Var):
        raise HclError('expected a resource address such as azurerm_resource_group.main', file, node.line, node.col)
    parts.insert(0, current.name)
    if parts[0] == 'data' and len(parts) == 3 or len(parts) == 2:
        return '.'.join(parts) + key
    raise HclError('expected a resource address such as azurerm_resource_group.main', file, node.line, node.col)


def load_config(folder: Path) -> Config:
    files = sorted(p for p in folder.glob('*.tf') if p.is_file())
    if not files:
        raise Failed([Diag('No configuration files', 'There are no .tf files in this folder. Terraform reads every '
                                                    '.tf file of the folder it runs in.')])
    if len(files) > MAX_FILES:
        raise Failed([Diag('Too many configuration files', f'The lab reads at most {MAX_FILES} .tf files.')])
    config = Config(files=[p.name for p in files])
    diags: list[Diag] = []
    for path in files:
        try:
            body = hcl.parse(path.read_text(encoding='utf-8-sig'), path.name)
        except HclError as error:
            diags.append(from_hcl(error))
            continue
        except UnicodeDecodeError:
            diags.append(Diag('Invalid file encoding', f'{path.name} is not UTF-8 text.'))
            continue
        if body.attributes:
            attr = next(iter(body.attributes.values()))
            diags.append(Diag('Unsupported argument', f'An argument named "{attr.name}" is not expected here: a .tf '
                                                      'file holds blocks (resource, variable, output…).',
                              path.name, attr.line))
        for block in body.blocks:
            try:
                read_block(config, block)
            except Diag as diag:
                diags.append(diag)
            except HclError as error:
                diags.append(from_hcl(error))
    if diags:
        raise Failed(diags)
    return config


def read_block(config: Config, block: hcl.Block) -> None:
    kind, labels, file = block.type, block.labels, block.file

    def want(n: int, names: str) -> None:
        if len(labels) != n:
            raise Diag('Missing name for ' + kind if len(labels) < n else 'Extraneous label for ' + kind,
                       f'A {kind} block needs exactly {n} label(s): {names}.', file, block.line)

    if kind == 'terraform':
        for inner in block.body.blocks:
            if inner.type == 'required_providers':
                for local, attr in inner.body.attributes.items():
                    source = None
                    if isinstance(attr.expr, hcl.ObjectExpr):
                        for key, value in attr.expr.items:
                            if isinstance(key, hcl.Literal) and key.value == 'source' and isinstance(value, hcl.Literal):
                                source = value.value
                    elif isinstance(attr.expr, hcl.Literal):
                        source = f'hashicorp/{local}'
                    config.providers[local] = str(source or f'hashicorp/{local}')
            elif inner.type == 'backend':
                if inner.labels != ['local']:
                    raise Diag('Backend not simulated',
                               f'The "{inner.labels[0] if inner.labels else "?"}" backend is not simulated: this lab keeps '
                               'the state in terraform.tfstate next to your files (the local backend). Remove the '
                               'backend block.', file, inner.line)
            elif inner.type == 'cloud':
                raise Diag('HCP Terraform is not simulated', 'Remove the cloud block: the lab keeps a local state.',
                           file, inner.line)
        return
    if kind == 'provider':
        want(1, 'the provider name')
        config.provider_blocks[labels[0]] = block
        return
    if kind == 'variable':
        want(1, 'the variable name')
        attrs = block.body.attributes
        variable = VariableConfig(labels[0], file=file, line=block.line)
        if 'type' in attrs:
            variable.type = parse_type(attrs['type'].expr, file)
        variable.default = attrs.get('default')
        for flag in ('sensitive', 'nullable'):
            if flag in attrs:
                if not isinstance(attrs[flag].expr, hcl.Literal) or not isinstance(attrs[flag].expr.value, bool):
                    raise Diag('Invalid variable setting', f'{flag} must be true or false.', file, attrs[flag].line)
                setattr(variable, flag, attrs[flag].expr.value)
        for extra in set(attrs) - {'type', 'default', 'description', 'sensitive', 'nullable', 'ephemeral'}:
            raise Diag('Unsupported argument', f'An argument named "{extra}" is not expected in a variable block.',
                       file, attrs[extra].line)
        for inner in block.body.blocks:
            if inner.type != 'validation':
                raise Diag('Unsupported block type', f'Blocks of type "{inner.type}" are not expected in a variable.',
                           file, inner.line)
            condition = inner.body.attributes.get('condition')
            if condition is None:
                raise Diag('Missing required argument', 'A validation block needs a condition.', file, inner.line)
            variable.validations.append((condition, inner.body.attributes.get('error_message')))
        if variable.name in config.variables:
            raise Diag('Duplicate variable declaration', f'A variable named "{variable.name}" was already declared.',
                       file, block.line)
        config.variables[variable.name] = variable
        return
    if kind == 'locals':
        for name, attr in block.body.attributes.items():
            if name in config.locals:
                raise Diag('Duplicate local value definition', f'A local value named "{name}" was already defined.',
                           file, attr.line)
            config.locals[name] = attr
        return
    if kind == 'output':
        want(1, 'the output name')
        value = block.body.attributes.get('value')
        if value is None:
            raise Diag('Missing required argument', 'The argument "value" is required in an output block.', file,
                       block.line)
        sensitive = block.body.attributes.get('sensitive')
        config.outputs[labels[0]] = OutputConfig(
            labels[0], value, bool(sensitive and isinstance(sensitive.expr, hcl.Literal) and sensitive.expr.value),
            file, block.line)
        return
    if kind in ('resource', 'data'):
        want(2, 'the type and the name')
        rtype, name = labels
        mode = 'managed' if kind == 'resource' else 'data'
        if mode == 'managed' and rtype not in azurerm.RESOURCES:
            raise unsupported_type(rtype, file, block.line, 'resource')
        if mode == 'data' and rtype not in azurerm.DATA_SOURCES:
            raise unsupported_type(rtype, file, block.line, 'data source')
        resource = ResourceConfig(mode, rtype, name, block.body, file, block.line)
        attrs = block.body.attributes
        resource.count, resource.for_each = attrs.get('count'), attrs.get('for_each')
        if resource.count and resource.for_each:
            raise Diag('Invalid combination of "count" and "for_each"',
                       'The "count" and "for_each" meta-arguments are mutually-exclusive, only one should be used.',
                       file, resource.count.line, resource.context)
        if 'provider' in attrs:
            raise Diag('Provider aliases are not simulated', 'Remove the provider argument: the lab has one azurerm '
                                                             'provider configuration.', file, attrs['provider'].line)
        if 'depends_on' in attrs:
            expr = attrs['depends_on'].expr
            if not isinstance(expr, hcl.TupleExpr):
                raise Diag('Invalid depends_on', 'depends_on takes a list of resources, such as '
                                                 '[azurerm_resource_group.main].', file, attrs['depends_on'].line)
            resource.depends_on = [reference_address(item, file).split('[')[0] for item in expr.items]
        for inner in block.body.blocks:
            if inner.type == 'lifecycle':
                resource.lifecycle = read_lifecycle(inner, file)
            elif inner.type in ('provisioner', 'connection'):
                raise Diag('Provisioners are not simulated',
                           'Provisioners run commands on real machines; this lab never runs anything. Remove the '
                           f'{inner.type} block.', file, inner.line, resource.context)
        key = resource.address
        if key in config.resources:
            raise Diag(f'Duplicate {kind} "{rtype}" configuration',
                       f'A {kind} {rtype} named "{name}" was already declared.', file, block.line)
        config.resources[key] = resource
        return
    if kind == 'moved':
        frm, to = block.body.attributes.get('from'), block.body.attributes.get('to')
        if frm is None or to is None:
            raise Diag('Missing required argument', 'A moved block needs from and to.', file, block.line)
        config.moved.append((reference_address(frm.expr, file), reference_address(to.expr, file), file, block.line))
        return
    if kind == 'import':
        to, id_attr = block.body.attributes.get('to'), block.body.attributes.get('id')
        if to is None or id_attr is None:
            raise Diag('Missing required argument', 'An import block needs to and id.', file, block.line)
        config.imports.append((reference_address(to.expr, file), id_attr))
        return
    if kind == 'module':
        raise Diag('Modules are not simulated yet', 'This lab reads one root module: move the resources into this '
                                                    'folder instead of calling a module.', file, block.line)
    if kind == 'check' or kind == 'removed':
        raise Diag(f'{kind} blocks are not simulated', f'Remove the {kind} block.', file, block.line)
    raise Diag('Unsupported block type', f'Blocks of type "{kind}" are not expected here.', file, block.line)


def unsupported_type(rtype: str, file: str, line: int, what: str) -> Diag:
    known = sorted(azurerm.RESOURCES) if what == 'resource' else sorted(azurerm.DATA_SOURCES)
    close = difflib.get_close_matches(rtype, known, n=1)
    hint = f' Did you mean "{close[0]}"?' if close else ''
    provider = rtype.split('_', 1)[0]
    if provider != 'azurerm':
        return Diag('Provider not simulated', f'The {what} type "{rtype}" belongs to the "{provider}" provider; this lab '
                                              f'simulates the azurerm provider only.', file, line)
    return Diag(f'Invalid {what} type', f'The provider hashicorp/azurerm does not support {what} type "{rtype}" in '
                                        f'this lab.{hint} Simulated types: {", ".join(known)}.', file, line)


def read_lifecycle(block: hcl.Block, file: str) -> Lifecycle:
    out = Lifecycle()
    for name, attr in block.body.attributes.items():
        if name in ('prevent_destroy', 'create_before_destroy'):
            if not isinstance(attr.expr, hcl.Literal) or not isinstance(attr.expr.value, bool):
                raise Diag('Invalid lifecycle setting', f'{name} must be the literal true or false.', file, attr.line)
            setattr(out, name, attr.expr.value)
        elif name == 'ignore_changes':
            expr = attr.expr
            if isinstance(expr, hcl.Var) and expr.name == 'all':
                out.ignore_changes = 'all'
            elif isinstance(expr, hcl.TupleExpr):
                names = []
                for item in expr.items:
                    if isinstance(item, hcl.Var):
                        names.append(item.name)
                    elif isinstance(item, (hcl.Index, hcl.GetAttr)) and isinstance(item.target, hcl.Var):
                        names.append(item.target.name)
                    else:
                        raise Diag('Invalid ignore_changes', 'List attribute names, such as [tags].', file, attr.line)
                out.ignore_changes = names
            else:
                raise Diag('Invalid ignore_changes', 'ignore_changes takes a list of attribute names, or all.', file,
                           attr.line)
        else:
            raise Diag('Unsupported argument', f'An argument named "{name}" is not expected in lifecycle.', file,
                       attr.line)
    return out


# ---- Types ---------------------------------------------------------------------------------------------------------


def parse_type(node: hcl.Node, file: str) -> Any:
    if isinstance(node, hcl.Var) and node.name in ('string', 'number', 'bool', 'any'):
        return node.name
    if isinstance(node, hcl.Call) and node.name in ('list', 'set', 'map') and len(node.args) == 1:
        return (node.name, parse_type(node.args[0], file))
    if isinstance(node, hcl.Call) and node.name == 'tuple' and len(node.args) == 1 and isinstance(node.args[0], hcl.TupleExpr):
        return ('tuple', [parse_type(item, file) for item in node.args[0].items])
    if isinstance(node, hcl.Call) and node.name == 'object' and len(node.args) == 1 and isinstance(node.args[0], hcl.ObjectExpr):
        fields: dict[str, Any] = {}
        optional: dict[str, Any] = {}
        for key, value in node.args[0].items:
            if not isinstance(key, hcl.Literal):
                raise HclError('object attribute names must be plain names', file, key.line, key.col)
            if isinstance(value, hcl.Call) and value.name == 'optional' and value.args:
                fields[key.value] = parse_type(value.args[0], file)
                optional[key.value] = value.args[1] if len(value.args) > 1 else None
            else:
                fields[key.value] = parse_type(value, file)
        return ('object', fields, optional)
    raise HclError('unsupported type constraint (use string, number, bool, list(…), set(…), map(…), object({…}), '
                   'tuple([…]) or any)', file, node.line, node.col)


def type_label(t: Any) -> str:
    if isinstance(t, str):
        return t
    if t[0] in ('list', 'set', 'map'):
        return f'{t[0]}({type_label(t[1])})'
    if t[0] == 'tuple':
        return 'tuple([' + ', '.join(type_label(x) for x in t[1]) + '])'
    return 'object({' + ', '.join(f'{k} = {type_label(v)}' for k, v in t[1].items()) + '})'


def convert(value: Any, t: Any, path: str = '') -> Any:
    """Convert a value to a type constraint, as Terraform does, or raise ValueError."""
    where = f' at {path}' if path else ''
    if value is UNKNOWN or t == 'any':
        return value
    if value is None:
        return None
    if t == 'string':
        if isinstance(value, bool):
            return 'true' if value else 'false'
        if isinstance(value, (int, float)):
            return tfexpr.format_number(value)
        if isinstance(value, str):
            return value
        raise ValueError(f'string required{where}, got {tfexpr.type_name(value)}')
    if t == 'number':
        if isinstance(value, bool):
            raise ValueError(f'number required{where}, got bool')
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            try:
                return tfexpr.normalize(float(value)) if any(c in value for c in '.eE') else int(value)
            except ValueError:
                pass
        raise ValueError(f'number required{where}, got {tfexpr.type_name(value)}')
    if t == 'bool':
        if isinstance(value, bool):
            return value
        if value in ('true', 'false'):
            return value == 'true'
        raise ValueError(f'bool required{where}, got {tfexpr.type_name(value)}')
    kind = t[0]
    if kind in ('list', 'set'):
        if not isinstance(value, list):
            raise ValueError(f'{kind} of {type_label(t[1])} required{where}, got {tfexpr.type_name(value)}')
        items = [convert(v, t[1], f'{path}[{i}]') for i, v in enumerate(value)]
        return tfexpr.to_set(items) if kind == 'set' else items
    if kind == 'map':
        if not isinstance(value, dict):
            raise ValueError(f'map of {type_label(t[1])} required{where}, got {tfexpr.type_name(value)}')
        return {k: convert(v, t[1], f'{path}["{k}"]') for k, v in value.items()}
    if kind == 'tuple':
        if not isinstance(value, list) or len(value) != len(t[1]):
            raise ValueError(f'tuple of {len(t[1])} elements required{where}')
        return [convert(v, et, f'{path}[{i}]') for i, (v, et) in enumerate(zip(value, t[1]))]
    if kind == 'object':
        if not isinstance(value, dict):
            raise ValueError(f'object required{where}, got {tfexpr.type_name(value)}')
        fields, optional = t[1], t[2]
        out = {}
        for name, ft in fields.items():
            if name in value:
                out[name] = convert(value[name], ft, f'{path}.{name}' if path else name)
            elif name in optional:
                default = optional[name]
                out[name] = None if default is None else convert(tfexpr.evaluate(default, Scope({})), ft)
            else:
                raise ValueError(f'attribute "{name}" is required{where}')
        return out
    raise ValueError('unsupported type')


# ---- State ---------------------------------------------------------------------------------------------------------


@dataclass
class Instance:
    mode: str
    type: str
    name: str
    index_key: Any
    attributes: dict[str, Any]
    dependencies: list[str] = field(default_factory=list)

    @property
    def address(self) -> str:
        return instance_address(self.type, self.name, self.index_key, self.mode)


def instance_address(rtype: str, name: str, key: Any, mode: str = 'managed') -> str:
    base = f'data.{rtype}.{name}' if mode == 'data' else f'{rtype}.{name}'
    if key is None:
        return base
    return f'{base}[{key}]' if isinstance(key, int) else f'{base}[{json.dumps(key)}]'


def split_address(address: str) -> tuple[str, Any]:
    """`azurerm_x.a["k"]` -> ('azurerm_x.a', 'k'); `azurerm_x.a[0]` -> ('azurerm_x.a', 0)."""
    if '[' not in address:
        return address, None
    base, raw = address.split('[', 1)
    raw = raw.rstrip(']')
    try:
        return base, json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError(f'invalid instance key in {address}') from None


@dataclass
class State:
    serial: int = 0
    lineage: str = ''
    instances: dict[str, Instance] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    exists: bool = False


def read_state(folder: Path) -> State:
    path = folder / STATE_FILE
    state = State(lineage=str(uuid.uuid5(uuid.NAMESPACE_URL, f'datapass-infralab:{folder.name}')))
    if not path.is_file():
        return state
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as error:
        raise Failed([Diag('Failed to load state', f'terraform.tfstate is not valid JSON ({error.msg}). Do not edit the '
                                                   'state by hand: use terraform state commands.')]) from None
    state.exists = True
    state.serial = int(data.get('serial') or 0)
    state.lineage = str(data.get('lineage') or state.lineage)
    for resource in data.get('resources') or []:
        for instance in resource.get('instances') or []:
            inst = Instance(resource.get('mode', 'managed'), resource['type'], resource['name'],
                            instance.get('index_key'), dict(instance.get('attributes') or {}),
                            list(instance.get('dependencies') or []))
            state.instances[inst.address] = inst
    state.outputs = {name: out.get('value') for name, out in (data.get('outputs') or {}).items()}
    return state


def write_state(folder: Path, state: State, output_values: dict[str, tuple[Any, bool]]) -> None:
    state.serial += 1
    grouped: dict[tuple[str, str, str], list[Instance]] = {}
    for inst in state.instances.values():
        grouped.setdefault((inst.mode, inst.type, inst.name), []).append(inst)
    resources = []
    for (mode, rtype, name), instances in sorted(grouped.items()):
        entries = []
        for inst in sorted(instances, key=lambda i: json.dumps(i.index_key)):
            entry: dict[str, Any] = {}
            if inst.index_key is not None:
                entry['index_key'] = inst.index_key
            entry.update({'schema_version': 0, 'attributes': inst.attributes, 'sensitive_attributes': []})
            if inst.dependencies:
                entry['dependencies'] = sorted(set(inst.dependencies))
            entries.append(entry)
        resources.append({'mode': mode, 'type': rtype, 'name': name, 'provider': azurerm.PROVIDER_ADDRESS,
                          'instances': entries})
    outputs = {name: {'value': value, 'type': json_type(value), **({'sensitive': True} if sensitive else {})}
               for name, (value, sensitive) in sorted(output_values.items()) if value is not UNKNOWN}
    data = {'version': 4, 'terraform_version': TERRAFORM_VERSION, 'serial': state.serial, 'lineage': state.lineage,
            'datapass_simulated': worldlib.SIMULATED, 'outputs': outputs, 'resources': resources,
            'check_results': None}
    worldlib.write_json(folder / STATE_FILE, data)
    state.outputs = {k: v for k, (v, _) in output_values.items()}
    state.exists = True


def json_type(value: Any) -> Any:
    if isinstance(value, bool):
        return 'bool'
    if isinstance(value, (int, float)):
        return 'number'
    if isinstance(value, str):
        return 'string'
    if isinstance(value, list):
        return ['tuple', [json_type(v) for v in value]]
    if isinstance(value, dict):
        return ['object', {k: json_type(v) for k, v in value.items()}]
    return 'dynamic'


# ---- Planning ------------------------------------------------------------------------------------------------------


@dataclass
class Change:
    address: str
    resource: ResourceConfig | None
    type: str
    name: str
    index_key: Any
    action: str                     # create, update, replace, delete, noop
    before: dict | None
    after: dict | None
    replace_paths: list[str] = field(default_factory=list)
    importing: str | None = None
    moved_from: str | None = None
    reason: str = ''
    dependencies: list[str] = field(default_factory=list)


@dataclass
class Plan:
    changes: list[Change]
    outputs: dict[str, tuple[Any, bool]]
    drift: list[str]
    warnings: list[Diag]
    destroy: bool = False

    def counts(self) -> dict[str, int]:
        out = {'import': 0, 'add': 0, 'change': 0, 'destroy': 0}
        for c in self.changes:
            out['import'] += 1 if c.importing else 0
            out['add'] += 1 if c.action in ('create', 'replace') else 0
            out['change'] += 1 if c.action == 'update' else 0
            out['destroy'] += 1 if c.action in ('delete', 'replace') else 0
        return out

    def has_changes(self) -> bool:
        return any(c.action != 'noop' or c.importing or c.moved_from for c in self.changes) or self.outputs_changed

    outputs_changed: bool = False

    def fingerprint(self) -> str:
        data = [(c.address, c.action, c.importing, c.moved_from, json.dumps(c.after, default=repr, sort_keys=True))
                for c in self.changes]
        return hashlib.sha256(json.dumps(data).encode()).hexdigest()


class Evaluator:
    """Evaluates the configuration in dependency order, for a plan or for an apply."""

    def __init__(self, folder: Path, config: Config, variables: dict[str, Any], world: dict[str, Any]):
        self.folder, self.config, self.world = folder, config, world
        self.azure = world['azure']
        self.variables = variables
        self.local_values: dict[str, Any] = {}
        self.resolving: set[str] = set()
        self.resource_values: dict[str, dict[str, Any]] = {}
        self.data_values: dict[str, dict[str, Any]] = {}
        for resource in config.resources.values():
            if resource.mode == 'data':
                self.data_values.setdefault(resource.type, {})
            else:
                self.resource_values.setdefault(resource.type, {})

    def scope(self, file: str = '', extra: dict[str, Any] | None = None) -> Scope:
        roots: dict[str, Any] = {
            'var': self.variables,
            'local': {name: (lambda n=name: self.local(n)) for name in self.config.locals},
            'path': {'module': '.', 'root': '.', 'cwd': '.'},
            'terraform': {'workspace': 'default'},
            'data': self.data_values,
            **self.resource_values,
        }
        if extra:
            roots.update(extra)
        return Scope(roots, file)

    def local(self, name: str) -> Any:
        if name in self.local_values:
            return self.local_values[name]
        if name in self.resolving:
            raise EvalError(f'Cycle in local values: local.{name} refers to itself.', self.config.locals[name].file,
                            self.config.locals[name].line)
        self.resolving.add(name)
        attr = self.config.locals[name]
        value = tfexpr.evaluate(attr.expr, self.scope(attr.file))
        self.resolving.discard(name)
        self.local_values[name] = value
        return value

    def order(self) -> list[ResourceConfig]:
        """Resources and data sources in dependency order (references, depends_on, locals resolved through)."""
        resources = self.config.resources
        local_refs: dict[str, set[str]] = {}

        def refs_of(node_refs: list[tuple[str, ...]], seen: frozenset[str] = frozenset()) -> set[str]:
            out: set[str] = set()
            for ref in node_refs:
                if ref[0] == 'local' and len(ref) > 1 and ref[1] in self.config.locals and ref[1] not in seen:
                    if ref[1] not in local_refs:
                        local_refs[ref[1]] = refs_of(tfexpr.references(self.config.locals[ref[1]].expr), seen | {ref[1]})
                    out |= local_refs[ref[1]]
                elif ref[0] == 'data' and len(ref) == 3:
                    out.add('.'.join(ref))
                elif len(ref) == 2 and f'{ref[0]}.{ref[1]}' in resources:
                    out.add(f'{ref[0]}.{ref[1]}')
            return out

        deps: dict[str, set[str]] = {}
        for address, resource in resources.items():
            found = refs_of(tfexpr.body_references(resource.body))
            for dep in resource.depends_on:
                if dep not in resources:
                    raise Failed([Diag('Reference to undeclared resource', f'depends_on refers to {dep}, which is not '
                                                                           'declared.', resource.file, resource.line)])
                found.add(dep)
            found.discard(address)
            deps[address] = found
        ordered: list[ResourceConfig] = []
        state: dict[str, int] = {}

        def visit(address: str, path: list[str]) -> None:
            if state.get(address) == 2:
                return
            if state.get(address) == 1:
                cycle = path[path.index(address):] + [address]
                raise Failed([Diag('Cycle: ' + ', '.join(cycle), 'These resources refer to each other: Terraform cannot '
                                                                 'decide which one to create first.')])
            state[address] = 1
            for dep in sorted(deps[address]):
                visit(dep, path + [address])
            state[address] = 2
            ordered.append(resources[address])

        for address in resources:
            visit(address, [])
        self.deps = deps
        return ordered

    def instance_keys(self, resource: ResourceConfig) -> list[Any]:
        if resource.count is not None:
            value = tfexpr.evaluate(resource.count.expr, self.scope(resource.file))
            if value is UNKNOWN:
                raise Diag('Invalid count argument', 'The "count" value depends on resource attributes that cannot be '
                                                     'determined until apply.', resource.file, resource.count.line,
                           resource.context)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0 or int(value) != value:
                raise Diag('Invalid count argument', 'The count must be a whole number, zero or more.', resource.file,
                           resource.count.line, resource.context)
            return list(range(int(value)))
        if resource.for_each is not None:
            value = tfexpr.evaluate(resource.for_each.expr, self.scope(resource.file))
            if is_unknown(value):
                raise Diag('Invalid for_each argument', 'The "for_each" value depends on resource attributes that '
                                                        'cannot be determined until apply.', resource.file,
                           resource.for_each.line, resource.context)
            if isinstance(value, dict):
                return sorted(value)
            if isinstance(value, list):
                if not all(isinstance(v, str) for v in value):
                    raise Diag('Invalid for_each argument', 'The given "for_each" argument value is a list or set of '
                                                            'non-strings: use toset() on a list of strings, or a map.',
                               resource.file, resource.for_each.line, resource.context)
                expr = resource.for_each.expr
                declared = (self.config.variables.get(expr.name) if isinstance(expr, hcl.GetAttr)
                            and isinstance(expr.target, hcl.Var) and expr.target.name == 'var' else None)
                if isinstance(expr, hcl.TupleExpr) or (declared is not None and isinstance(declared.type, tuple)
                                                       and declared.type[0] in ('list', 'tuple')):
                    raise Diag('Invalid for_each argument', 'The given "for_each" argument value is unsuitable: the '
                                                            '"for_each" argument must be a map, or set of strings, and '
                                                            'you have provided a value of type list. Convert it with '
                                                            'toset(...), or declare the variable as set(string).',
                               resource.file, resource.for_each.line, resource.context)
                return sorted(set(value))
            raise Diag('Invalid for_each argument', 'The "for_each" meta-argument must be a map, or a set of strings.',
                       resource.file, resource.for_each.line, resource.context)
        return [None]

    def each_values(self, resource: ResourceConfig, key: Any) -> dict[str, Any]:
        if resource.count is not None:
            return {'count': {'index': key}}
        if resource.for_each is not None:
            value = tfexpr.evaluate(resource.for_each.expr, self.scope(resource.file))
            if key is None or is_unknown(value):
                return {'each': {'key': UNKNOWN, 'value': UNKNOWN}}
            return {'each': {'key': key, 'value': value[key] if isinstance(value, dict) else key}}
        return {}

    def arguments(self, resource: ResourceConfig, key: Any, diags: list[Diag]) -> dict[str, Any]:
        """The configured arguments of one instance, converted and validated against the simulated schema."""
        scope = self.scope(resource.file, self.each_values(resource, key))
        if resource.mode == 'data':
            values = {}
            for name, attr in resource.body.attributes.items():
                if name in META_ARGS:
                    continue
                values[name] = tfexpr.evaluate(attr.expr, scope)
            return values
        rtype = azurerm.RESOURCES[resource.type]
        attrs: dict[str, Any] = {}
        for name, attr in resource.body.attributes.items():
            if name in META_ARGS:
                continue
            spec = rtype.args.get(name)
            if spec is None:
                close = difflib.get_close_matches(name, list(rtype.args), n=1)
                hint = f' Did you mean "{close[0]}"?' if close else ''
                diags.append(Diag('Unsupported argument', f'An argument named "{name}" is not expected here.{hint}',
                                  resource.file, attr.line, resource.context))
                continue
            if spec.deprecated:
                diags.append(Diag('Argument is deprecated', spec.deprecated, resource.file, attr.line,
                                  resource.context, severity='error' if resource.type == 'azurerm_storage_container'
                                  else 'warning'))
            value = tfexpr.evaluate(attr.expr, scope)
            if value is not UNKNOWN and value is not None:
                try:
                    value = convert(value, parse_spec_type(spec.type))
                except ValueError as problem:
                    diags.append(Diag('Incorrect attribute value type',
                                      f'Inappropriate value for attribute "{name}": {problem}.', resource.file,
                                      attr.line, resource.context))
                    continue
                if name == 'location':
                    value = azurerm.normalize_location(value)
                problem_text = azurerm.check_value(rtype, name, spec, value)
                if problem_text:
                    diags.append(Diag(f'invalid value for {name}', problem_text, resource.file, attr.line,
                                      resource.context))
            attrs[name] = value
        for name, spec in rtype.args.items():
            if name not in attrs or attrs[name] is None:
                if spec.required:
                    diags.append(Diag('Missing required argument',
                                      f'The argument "{name}" is required, but no definition was found.',
                                      resource.file, resource.line, resource.context))
                elif not spec.computed_only:
                    attrs[name] = deepcopy(spec.default)
        for required in rtype.exactly_one_of:
            if attrs.get(required) is None:
                diags.append(Diag('Missing required argument', f'The argument "{required}" is required in this lab '
                                                               '(azurerm 4.x).', resource.file, resource.line,
                                  resource.context))
        for block in resource.body.blocks:
            if block.type == 'lifecycle':
                continue
            spec_block = rtype.blocks.get(block.type)
            if spec_block is None:
                diags.append(Diag('Unsupported block type', f'Blocks of type "{block.type}" are not expected here.',
                                  resource.file, block.line, resource.context))
                continue
            entry: dict[str, Any] = {}
            for name, attr in block.body.attributes.items():
                spec = spec_block.args.get(name)
                if spec is None:
                    diags.append(Diag('Unsupported argument', f'An argument named "{name}" is not expected in '
                                                              f'{block.type}.', resource.file, attr.line,
                                      resource.context))
                    continue
                value = tfexpr.evaluate(attr.expr, scope)
                if value is not UNKNOWN and value is not None:
                    try:
                        value = convert(value, parse_spec_type(spec.type))
                    except ValueError as problem:
                        diags.append(Diag('Incorrect attribute value type', f'{block.type}.{name}: {problem}.',
                                          resource.file, attr.line, resource.context))
                        continue
                    problem_text = azurerm.check_value(rtype, name, spec, value)
                    if problem_text:
                        diags.append(Diag(f'invalid value for {block.type}.{name}', problem_text, resource.file,
                                          attr.line, resource.context))
                entry[name] = value
            for name, spec in spec_block.args.items():
                if name not in entry:
                    if spec.required:
                        diags.append(Diag('Missing required argument', f'The argument "{name}" is required in '
                                                                       f'{block.type}.', resource.file, block.line,
                                          resource.context))
                    else:
                        entry[name] = deepcopy(spec.default)
            if block.type in attrs:
                diags.append(Diag('Too many blocks', f'No more than 1 "{block.type}" block is allowed.',
                                  resource.file, block.line, resource.context))
            attrs[block.type] = [entry]
        for name in rtype.blocks:
            attrs.setdefault(name, [])
        return attrs

    def register(self, resource: ResourceConfig, key: Any, value: dict[str, Any]) -> None:
        target = self.data_values[resource.type] if resource.mode == 'data' else self.resource_values[resource.type]
        if resource.count is not None:
            items = target.setdefault(resource.name, [])
            items.append(value)
        elif resource.for_each is not None:
            target.setdefault(resource.name, {})[key] = value
        else:
            target[resource.name] = value

    def empty_collection(self, resource: ResourceConfig) -> None:
        target = self.data_values[resource.type] if resource.mode == 'data' else self.resource_values[resource.type]
        if resource.count is not None:
            target.setdefault(resource.name, [])
        elif resource.for_each is not None:
            target.setdefault(resource.name, {})

    def outputs(self) -> dict[str, tuple[Any, bool]]:
        out = {}
        for name, output in self.config.outputs.items():
            value = tfexpr.evaluate(output.value.expr, self.scope(output.file))
            out[name] = (value, output.sensitive)
        return out


def parse_spec_type(label: str) -> Any:
    if label in ('string', 'number', 'bool'):
        return label
    kind, inner = label.split('(', 1)
    return (kind, inner.rstrip(')'))


def computed_attrs(rtype: azurerm.ResourceType, attrs: dict, azure: dict) -> dict[str, Any]:
    """The provider-computed attributes (id and endpoints) once every argument is known."""
    out = {'id': rtype.id(attrs, azure)}
    out.update(rtype.computed(attrs, azure))
    return out


def computed_names(rtype: azurerm.ResourceType) -> list[str]:
    sample = {name: 'x' for name in rtype.args}
    sample['storage_account_id'] = '/x/x'
    try:
        names = ['id'] + list(rtype.computed(sample, {'subscription_id': 'x'}))
    except (KeyError, TypeError):
        names = ['id']
    return names


def variable_values(config: Config, folder: Path, cli_vars: list[tuple[str, str]], var_files: list[str]) -> dict[str, Any]:
    """Variable values: defaults, then terraform.tfvars, *.auto.tfvars, -var-file, -var (later wins)."""
    raw: dict[str, tuple[Any, str]] = {}
    diags: list[Diag] = []
    files = []
    if (folder / 'terraform.tfvars').is_file():
        files.append('terraform.tfvars')
    files += sorted(p.name for p in folder.glob('*.auto.tfvars') if p.is_file())
    files += var_files
    for name in files:
        path = (folder / name).resolve()
        if not path.is_relative_to(folder.resolve()) or not path.is_file():
            diags.append(Diag('Failed to read variables file', f'Given variables file {name} does not exist in the '
                                                               'folder.'))
            continue
        try:
            body = hcl.parse(path.read_text(encoding='utf-8-sig'), name)
        except HclError as error:
            diags.append(from_hcl(error))
            continue
        if body.blocks:
            diags.append(Diag('Invalid variables file', f'{name} may only set variables (name = value).', name,
                              body.blocks[0].line))
        for key, attr in body.attributes.items():
            try:
                value = tfexpr.evaluate(attr.expr, Scope({}, name))
            except EvalError as error:
                diags.append(Diag('Variables not allowed', f'{error.message} A .tfvars file holds plain values: it '
                                                           'cannot refer to variables or resources.', name, attr.line))
                continue
            if key not in config.variables:
                config.warnings.append(Diag('Value for undeclared variable', f'The file {name} sets "{key}", which is '
                                                                             'not declared in the configuration.',
                                            name, attr.line, severity='warning'))
                continue
            raw[key] = (value, name)
    for key, text in cli_vars:
        if key not in config.variables:
            diags.append(Diag('Value for undeclared variable', f'A variable named "{key}" was assigned on the command '
                                                               'line, but the configuration does not declare it.'))
            continue
        variable = config.variables[key]
        if variable.type in ('string', 'any'):
            raw[key] = (text, '-var')
        else:
            try:
                raw[key] = (tfexpr.evaluate(hcl.parse_expression(text, '-var'), Scope({})), '-var')
            except HclError as error:
                diags.append(Diag('Invalid value for -var', f'{key}: {error.message}'))
    values: dict[str, Any] = {}
    for name, variable in config.variables.items():
        if name in raw:
            value, source = raw[name]
        elif variable.default is not None:
            try:
                value = tfexpr.evaluate(variable.default.expr, Scope({}, variable.file))
            except EvalError as error:
                diags.append(from_hcl(error, f'variable "{name}"'))
                continue
            source = 'default'
        else:
            diags.append(Diag('No value for required variable',
                              f'The root module input variable "{name}" is not set, and has no default value. Use a '
                              f'-var or -var-file command line argument, or a terraform.tfvars file, to provide it.',
                              variable.file, variable.line, f'variable "{name}"'))
            continue
        if value is None and not variable.nullable:
            diags.append(Diag('Required variable not set', f'The variable "{name}" is not nullable.', variable.file,
                              variable.line))
            continue
        try:
            value = convert(value, variable.type)
        except ValueError as problem:
            diags.append(Diag('Invalid value for input variable',
                              f'The value from {source} is not suitable for var.{name} ({type_label(variable.type)}): '
                              f'{problem}.', variable.file, variable.line, f'variable "{name}"'))
            continue
        for condition, message in variable.validations:
            scope = Scope({'var': {name: value}}, variable.file)
            try:
                ok = tfexpr.evaluate(condition.expr, scope)
            except EvalError as error:
                diags.append(from_hcl(error, f'variable "{name}"'))
                continue
            if ok is False:
                text = ''
                if message is not None:
                    try:
                        text = str(tfexpr.evaluate(message.expr, scope))
                    except EvalError:
                        text = ''
                diags.append(Diag('Invalid value for variable', f'{text}\n\nThis was checked by the validation rule '
                                                                f'at {condition.file}:{condition.line}.',
                                  variable.file, variable.line, f'var.{name}'))
            elif ok is not True:
                diags.append(Diag('Invalid variable validation result', 'The condition must be true or false.',
                                  condition.file, condition.line))
        values[name] = value
    if diags:
        raise Failed(diags)
    return values


def find_world_resource(azure: dict, rid: str) -> dict | None:
    return azure['resources'].get(rid)


def attrs_equal(a: Any, b: Any) -> bool:
    if a is UNKNOWN or b is UNKNOWN:
        return False
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def make_plan(folder: Path, config: Config, variables: dict[str, Any], world: dict[str, Any], state: State,
              destroy: bool = False) -> Plan:
    evaluator = Evaluator(folder, config, variables, world)
    azure = world['azure']
    diags: list[Diag] = []
    drift: list[str] = []
    prior: dict[str, Instance] = {}
    for address, inst in state.instances.items():
        if inst.mode != 'managed':
            continue
        remote = find_world_resource(azure, str(inst.attributes.get('id')))
        if remote is None:
            drift.append(f'{address} has been deleted outside of Terraform')
            continue
        refreshed = {**inst.attributes, **remote['attributes']}
        rtype = azurerm.RESOURCES.get(inst.type)
        if rtype and not attrs_equal({k: inst.attributes.get(k) for k in rtype.args},
                                     {k: refreshed.get(k) for k in rtype.args}):
            changed = [k for k in rtype.args if not attrs_equal(inst.attributes.get(k), refreshed.get(k))]
            drift.append(f'{address} has changed outside of Terraform ({", ".join(changed)})')
        prior[address] = Instance(inst.mode, inst.type, inst.name, inst.index_key, refreshed, inst.dependencies)
    moved_from: dict[str, str] = {}
    for frm, to, file, line in config.moved:
        sources = [a for a in prior if a == frm or split_address(a)[0] == frm]
        for source in sources:
            target = to + source[len(frm):] if split_address(source)[0] == frm and '[' not in frm else to
            if target in prior:
                diags.append(Diag('Moved object still exists', f'{target} already exists in the state: the move from '
                                                               f'{source} cannot happen.', file, line))
                continue
            base, key = split_address(target)
            rtype_name, name = base.split('.', 1)
            inst = prior.pop(source)
            prior[target] = Instance('managed', rtype_name, name, key, inst.attributes, inst.dependencies)
            moved_from[target] = source
    importing: dict[str, str] = {}
    if not destroy:
        for to, id_attr in config.imports:
            if to in prior:
                continue
            try:
                rid = tfexpr.evaluate(id_attr.expr, evaluator.scope(id_attr.file))
            except EvalError as error:
                diags.append(from_hcl(error, 'import'))
                continue
            base, key = split_address(to)
            resource = config.resources.get(base)
            if resource is None:
                diags.append(Diag('Configuration for import target does not exist',
                                  f'The configuration for the given import target {to} does not exist. All target '
                                  'instances must have an associated configuration to be imported.', id_attr.file,
                                  id_attr.line))
                continue
            remote = find_world_resource(azure, str(rid))
            if remote is None or remote.get('tf_type') != resource.type:
                diags.append(Diag('Cannot import non-existent remote object',
                                  f'While attempting to import an existing object to "{to}", the provider detected '
                                  f'that no object exists with the given id "{rid}". Only pre-existing objects can be '
                                  'imported; check that the id is correct.', id_attr.file, id_attr.line))
                continue
            prior[to] = Instance('managed', resource.type, resource.name, key, dict(remote['attributes']))
            importing[to] = str(rid)
    changes: list[Change] = []
    planned: set[str] = set()
    try:
        order = evaluator.order()
    except Failed as failed:
        raise Failed(diags + failed.diags) from None
    for resource in order if not destroy else []:
        try:
            keys = evaluator.instance_keys(resource)
        except Diag as diag:
            diags.append(diag)
            continue
        except EvalError as error:
            diags.append(from_hcl(error, resource.context))
            continue
        evaluator.empty_collection(resource)
        for key in keys:
            address = instance_address(resource.type, resource.name, key, resource.mode)
            instance_diags: list[Diag] = []
            try:
                args = evaluator.arguments(resource, key, instance_diags)
            except EvalError as error:
                diags.append(from_hcl(error, resource.context))
                evaluator.register(resource, key, {})
                continue
            errors = [d for d in instance_diags if d.severity == 'error']
            diags.extend(errors)
            config.warnings.extend(d for d in instance_diags if d.severity == 'warning')
            if resource.mode == 'data':
                if is_unknown(args):
                    evaluator.register(resource, key, UNKNOWN)
                    continue
                try:
                    value = azurerm.data_source(resource.type, args, azure)
                except LookupError as problem:
                    diags.append(Diag('Error: data source lookup failed', str(problem), resource.file, resource.line,
                                      resource.context))
                    value = {}
                evaluator.register(resource, key, value)
                continue
            rtype = azurerm.RESOURCES[resource.type]
            before_inst = prior.get(address)
            before = before_inst.attributes if before_inst else None
            deps = sorted(evaluator.deps.get(resource.address, set()))
            if errors:
                evaluator.register(resource, key, {**args, **{n: UNKNOWN for n in computed_names(rtype)}})
                planned.add(address)
                continue
            change = diff(rtype, resource, address, key, args, before, azure)
            change.importing = importing.get(address)
            change.moved_from = moved_from.get(address)
            change.dependencies = deps
            if change.action in ('replace',) and resource.lifecycle.prevent_destroy:
                diags.append(Diag('Instance cannot be destroyed',
                                  f'Resource {address} has lifecycle.prevent_destroy set, but the plan calls for this '
                                  'resource to be destroyed. To avoid this error and continue with the plan, either '
                                  'disable lifecycle.prevent_destroy or reduce the scope of the plan using the -target '
                                  'flag.', resource.file, resource.line, resource.context))
            changes.append(change)
            planned.add(address)
            evaluator.register(resource, key, change.after or {})
    for address, inst in sorted(prior.items()):
        if address in planned:
            continue
        base, _ = split_address(address)
        resource = config.resources.get(base)
        reason = ''
        if destroy:
            reason = ''
        elif resource is None:
            reason = f'because {base} is not in configuration'
        else:
            reason = f'because {address} is not in the configuration any more (count or for_each changed)'
        if resource is not None and resource.lifecycle.prevent_destroy:
            diags.append(Diag('Instance cannot be destroyed',
                              f'Resource {address} has lifecycle.prevent_destroy set, but the plan calls for this '
                              'resource to be destroyed.', resource.file, resource.line, resource.context))
        changes.append(Change(address, resource, inst.type, inst.name, inst.index_key, 'delete', inst.attributes,
                              None, reason=reason, moved_from=moved_from.get(address),
                              dependencies=inst.dependencies))
    outputs: dict[str, tuple[Any, bool]] = {}
    if not destroy and not diags:
        try:
            outputs = evaluator.outputs()
        except EvalError as error:
            diags.append(from_hcl(error, 'output'))
    if diags:
        raise Failed(diags)
    plan = Plan(changes, outputs, drift, list(config.warnings), destroy)
    plan.outputs_changed = not destroy and any(
        not attrs_equal(state.outputs.get(name), value) for name, (value, _) in outputs.items()) or (
        not destroy and set(state.outputs) - set(outputs) != set())
    return plan


def diff(rtype: azurerm.ResourceType, resource: ResourceConfig, address: str, key: Any, args: dict[str, Any],
         before: dict | None, azure: dict) -> Change:
    names = computed_names(rtype)
    if before is None:
        after = dict(args)
        after.update({n: UNKNOWN for n in names})
        return Change(address, resource, resource.type, resource.name, key, 'create', None, after)
    ignore = resource.lifecycle.ignore_changes
    after = {**before}
    replace: list[str] = []
    changed: list[str] = []
    for name, value in args.items():
        if ignore == 'all' or (isinstance(ignore, list) and name in ignore):
            continue
        if attrs_equal(before.get(name), value) and value is not UNKNOWN:
            continue
        after[name] = value
        spec = rtype.args.get(name)
        if spec is not None and spec.force_new or (spec is None and rtype.blocks.get(name, azurerm.BlockSpec({})).force_new):
            replace.append(name)
        else:
            changed.append(name)
    if replace:
        for n in names:
            after[n] = UNKNOWN
        return Change(address, resource, resource.type, resource.name, key, 'replace', before, after, replace)
    if changed:
        return Change(address, resource, resource.type, resource.name, key, 'update', before, after)
    return Change(address, resource, resource.type, resource.name, key, 'noop', before, after)


# ---- Rendering -----------------------------------------------------------------------------------------------------


def render_value(value: Any, indent: int) -> str:
    pad = ' ' * indent
    if value is UNKNOWN:
        return '(known after apply)'
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return tfexpr.format_number(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        if not value:
            return '[]'
        return '[\n' + ''.join(f'{pad}    {render_value(v, indent + 4)},\n' for v in value) + f'{pad}]'
    if isinstance(value, dict):
        if not value:
            return '{}'
        width = max(len(json.dumps(k)) for k in value)
        return '{\n' + ''.join(f'{pad}    {json.dumps(k).ljust(width)} = {render_value(v, indent + 4)}\n'
                               for k, v in sorted(value.items())) + f'{pad}}}'
    return str(value)


def render_signed(value: Any, sign: str) -> str:
    """A created (+) or destroyed (-) value; map entries carry the sign too, as in Terraform's plans."""
    tail = f' {DIM}-> null{RESET}' if sign == '-' else ''
    if isinstance(value, dict) and value:
        width = max(len(json.dumps(k)) for k in value)
        inner = ''.join(f'          {_symbol(sign)} {json.dumps(k).ljust(width)} = {render_value(v, 12)}{tail}\n'
                        for k, v in sorted(value.items()))
        return '{\n' + inner + '        }'
    if isinstance(value, list) and value and all(not isinstance(v, (dict, list)) for v in value):
        inner = ''.join(f'          {_symbol(sign)} {render_value(v, 12)},\n' for v in value)
        return '[\n' + inner + '        ]'
    return render_value(value, 8) + tail


def _symbol(sign: str) -> str:
    color = {'+': GREEN, '~': YELLOW, '-': RED, '-/+': RED, '+/-': GREEN}.get(sign, '')
    return f'{color}{sign}{RESET}' if color else sign


def render_change(change: Change) -> str:
    lines: list[str] = []
    head = {'create': 'will be created', 'update': 'will be updated in-place', 'replace': 'must be replaced',
            'delete': 'will be destroyed', 'noop': 'will be imported' if change.importing else 'has moved'}
    title = head[change.action]
    if change.action == 'update' and change.importing:
        title = 'will be updated in-place'
    lines.append(f'  {BOLD}# {change.address}{RESET} {BOLD}{title}{RESET}')
    if change.moved_from:
        lines.append(f'  # (moved from {change.moved_from})')
    if change.importing and change.action != 'noop':
        lines.append(f'  # (imported from "{change.importing}")')
    if change.reason:
        lines.append(f'  # ({change.reason})')
    cbd = bool(change.resource and change.resource.lifecycle.create_before_destroy)
    sign = {'create': '+', 'update': '~', 'replace': '+/-' if cbd else '-/+', 'delete': '-', 'noop': ' '}[change.action]
    lines.append(f'{_symbol(sign).rjust(3 + (len(_symbol(sign)) - len(sign)))} resource "{change.type}" "{change.name}" {{')
    before, after = change.before or {}, change.after or {}
    keys = sorted(set(before) | set(after))
    rows: list[tuple[str, str, str]] = []   # sign, name, rendered
    hidden = 0
    for name in keys:
        old, new = before.get(name), after.get(name)
        if change.action == 'create':
            if new is None or new == [] or new == {}:
                continue
            rows.append(('+', name, render_signed(new, '+')))
        elif change.action == 'delete':
            if old is None or old == [] or old == {}:
                continue
            rows.append(('-', name, render_signed(old, '-')))
        elif change.action == 'noop':
            if name in ('id', 'name') or (change.importing and old not in (None, [], {})):
                rows.append((' ', name, render_value(old, 8)))
        else:
            if attrs_equal(old, new):
                if name in ('id', 'name'):
                    rows.append((' ', name, render_value(old, 8)))
                elif old not in (None, [], {}):
                    hidden += 1
                continue
            note = f' {RED}# forces replacement{RESET}' if name in change.replace_paths else ''
            if isinstance(old, dict) and isinstance(new, dict):
                inner = []
                for k in sorted(set(old) | set(new)):
                    if k in old and k in new and attrs_equal(old[k], new[k]):
                        continue
                    if k not in old:
                        inner.append(('+', json.dumps(k), render_value(new[k], 12)))
                    elif k not in new:
                        inner.append(('-', json.dumps(k), f'{render_value(old[k], 12)} {DIM}-> null{RESET}'))
                    else:
                        inner.append(('~', json.dumps(k), f'{render_value(old[k], 12)} -> {render_value(new[k], 12)}'))
                width = max(len(n) for _, n, _ in inner) if inner else 0
                body = ''.join(f'          {_symbol(s)} {n.ljust(width)} = {v}\n' for s, n, v in inner)
                rows.append(('~', name, '{\n' + body + '        }' + note))
            elif old in (None, [], {}):
                rows.append(('+', name, render_value(new, 8) + note))
            else:
                rows.append(('~', name, f'{render_value(old, 8)} -> {render_value(new, 8)}{note}'))
    width = max((len(n) for _, n, _ in rows), default=0)
    for s, name, rendered in rows:
        lines.append(f'      {_symbol(s)} {name.ljust(width)} = {rendered}' if s != ' ' else f'        {name.ljust(width)} = {rendered}')
    if hidden:
        lines.append(f'        {DIM}# ({hidden} unchanged attribute{"s" if hidden != 1 else ""} hidden){RESET}')
    lines.append('    }')
    return '\n'.join(lines)


def render_plan(plan: Plan, command: str) -> str:
    out: list[str] = []
    if plan.drift:
        out.append(f'\n{BOLD}Note: Objects have changed outside of Terraform{RESET}\n')
        out.append('Terraform detected the following changes made outside of Terraform since the last "terraform '
                   'apply":\n')
        out += [f'  # {line}' for line in plan.drift]
        out.append('\nUnless you have made equivalent changes to your configuration, or ignored the relevant '
                   'attributes using ignore_changes, the following plan may include actions to undo or respond to '
                   'these changes.\n')
        out.append('─' * 77)
    visible = [c for c in plan.changes if c.action != 'noop' or c.importing or c.moved_from]
    if not visible and not plan.outputs_changed:
        out.append(f'\n{GREEN}{BOLD}No changes.{RESET}{BOLD} Your infrastructure matches the configuration.{RESET}\n')
        out.append('Terraform has compared your real infrastructure against your configuration and found no '
                   'differences, so no changes are needed.')
        return '\n'.join(out)
    if visible:
        symbols = []
        actions = {c.action for c in visible}
        if 'create' in actions:
            symbols.append(f'  {_symbol("+")} create')
        if 'update' in actions:
            symbols.append(f'  {_symbol("~")} update in-place')
        if 'delete' in actions:
            symbols.append(f'  {_symbol("-")} destroy')
        if 'replace' in actions:
            symbols.append(f'{_symbol("-/+")} destroy and then create replacement')
        if any(c.importing for c in visible):
            symbols.append('    import')
        out.append('\nTerraform used the selected providers to generate the following execution plan. Resource '
                   'actions are indicated with the following symbols:')
        out += symbols
        out.append('\nTerraform will perform the following actions:\n')
        for change in visible:
            out.append(render_change(change))
            out.append('')
        counts = plan.counts()
        summary = f'{BOLD}Plan:{RESET} '
        if counts['import']:
            summary += f'{counts["import"]} to import, '
        summary += f'{counts["add"]} to add, {counts["change"]} to change, {counts["destroy"]} to destroy.'
        out.append(summary)
    changed_outputs = [(n, v) for n, (v, _) in plan.outputs.items()]
    if plan.outputs_changed and changed_outputs:
        out.append('\nChanges to Outputs:')
        width = max(len(n) for n, _ in changed_outputs)
        for name, value in changed_outputs:
            sensitive = plan.outputs[name][1]
            out.append(f'  {_symbol("+")} {name.ljust(width)} = {"(sensitive value)" if sensitive else render_value(value, 4)}')
    return '\n'.join(out)


def render_outputs(outputs: dict[str, tuple[Any, bool]]) -> str:
    if not outputs:
        return ''
    lines = [f'\n{GREEN}{BOLD}Outputs:{RESET}\n']
    for name, (value, sensitive) in sorted(outputs.items()):
        lines.append(f'{name} = {"<sensitive>" if sensitive else render_value(value, 0)}')
    return '\n'.join(lines)


def render_diags(diags: list[Diag]) -> str:
    return '\n'.join(d.render() for d in diags)


# ---- Apply ---------------------------------------------------------------------------------------------------------


class ApplyError(Exception):
    pass


def provider_create(rtype: azurerm.ResourceType, attrs: dict, world: dict) -> dict:
    azure = world['azure']
    parent = rtype.parent(attrs, azure)
    if parent and parent[0] not in azure['resources']:
        raise ApplyError(f'creating {rtype.name} {attrs.get("name")!r}: unexpected status 404 (404 Not Found) with '
                         f'error: ResourceNotFound: {parent[1]}')
    computed = computed_attrs(rtype, attrs, azure)
    rid = computed['id']
    if rid in azure['resources']:
        raise ApplyError(f'A resource with the ID "{rid}" already exists - to be managed via Terraform this resource '
                         f'needs to be imported into the State. Please see the resource documentation for '
                         f'"{rtype.name}" for more information.')
    if rtype.global_name:
        name = attrs.get('name')
        taken = set(azure['taken_names'].get(rtype.global_name, []))
        taken |= {r['attributes'].get('name') for r in azure['resources'].values() if r.get('tf_type') == rtype.name}
        if name in taken:
            code = 'StorageAccountAlreadyTaken' if rtype.global_name == 'storage_account' else 'VaultAlreadyExists'
            raise ApplyError(f'creating {rtype.name} {name!r}: unexpected status 409 (409 Conflict) with error: '
                             f'{code}: The name {name!r} is already taken: names of this resource type are unique '
                             'across all of Azure.')
    if rtype.name == 'azurerm_subnet':
        vnet = azure['resources'][parent[0]] if parent else None
        spaces = vnet['attributes'].get('address_space', []) if vnet else []
        import ipaddress
        for prefix in attrs.get('address_prefixes') or []:
            try:
                net = ipaddress.ip_network(prefix, strict=True)
            except ValueError:
                raise ApplyError(f'creating subnet {attrs.get("name")!r}: InvalidAddressPrefixFormat: {prefix!r} is '
                                 'not a valid CIDR prefix (host bits must be zero).') from None
            if not any(net.subnet_of(ipaddress.ip_network(space, strict=False)) for space in spaces):
                raise ApplyError(f'creating subnet {attrs.get("name")!r}: NetcfgSubnetRangeOutsideVnet: Subnet '
                                 f'{prefix} is not in the address space {spaces} of its virtual network.')
    full = {**attrs, **computed}
    azure['resources'][rid] = {'type': rtype.arm_type, 'tf_type': rtype.name, 'id': rid,
                               'managed_by': 'terraform', 'created_at': world['clock'], 'attributes': full}
    return full


def provider_update(rtype: azurerm.ResourceType, attrs: dict, world: dict) -> dict:
    azure = world['azure']
    rid = attrs['id']
    resource = azure['resources'].get(rid)
    if resource is None:
        raise ApplyError(f'updating {rid}: 404 Not Found')
    resource['attributes'] = dict(attrs)
    return dict(attrs)


def provider_delete(rtype: azurerm.ResourceType, attrs: dict, world: dict) -> None:
    azure = world['azure']
    rid = str(attrs.get('id'))
    if rid not in azure['resources']:
        return
    if rtype.name == 'azurerm_resource_group':
        inside = sorted(r for r in azure['resources'] if r.startswith(rid + '/'))
        if inside:
            listing = '\n'.join(f'* `{r}`' for r in inside[:8])
            raise ApplyError(f'deleting Resource Group {attrs.get("name")!r}: the Resource Group still contains '
                             f'Resources.\n\nTerraform is configured to check for Resources within the Resource Group '
                             f'when deleting the Resource Group - and raise an error if nested Resources still exist '
                             f'to avoid unintentionally deleting these Resources.\n\nTerraform has detected that the '
                             f'following Resources still exist within the Resource Group:\n\n{listing}')
    for other in [r for r in azure['resources'] if r.startswith(rid + '/')]:
        del azure['resources'][other]
    del azure['resources'][rid]


def duration(seconds: int) -> str:
    return f'{seconds // 60}m{seconds % 60}s' if seconds >= 60 else f'{seconds}s'


def run_apply(folder: Path, config: Config, variables: dict[str, Any], world: dict, state: State, plan: Plan) -> tuple[str, bool, dict]:
    """Carry out a plan against the simulated subscription, in dependency order, saving the state as it goes."""
    lines: list[str] = []
    evaluator = Evaluator(folder, config, variables, world)
    counts = {'import': 0, 'add': 0, 'change': 0, 'destroy': 0}
    by_address = {c.address: c for c in plan.changes}
    ok = True
    # Moves and imports first (they only touch the state).
    for change in plan.changes:
        if change.moved_from and change.moved_from in state.instances:
            inst = state.instances.pop(change.moved_from)
            state.instances[change.address] = Instance('managed', change.type, change.name, change.index_key,
                                                       inst.attributes, inst.dependencies)
        if change.importing:
            lines.append(f'{BOLD}{change.address}: Importing... [id={change.importing}]{RESET}')
            lines.append(f'{BOLD}{change.address}: Import complete [id={change.importing}]{RESET}')
            state.instances[change.address] = Instance('managed', change.type, change.name, change.index_key,
                                                       dict(change.before or {}), change.dependencies)
            counts['import'] += 1
    # Destroys: dependents before what they depend on.
    deletes = [c for c in plan.changes if c.action == 'delete']
    deletes.sort(key=lambda c: -len(c.dependencies))  # stable: the second sort keeps this order for ties
    order_index = {r.address: i for i, r in enumerate(evaluator.order())}
    deletes.sort(key=lambda c: -order_index.get(split_address(c.address)[0], len(order_index)))
    try:
        for change in deletes:
            rtype = azurerm.RESOURCES[change.type]
            rid = (change.before or {}).get('id')
            lines.append(f'{BOLD}{change.address}: Destroying... [id={rid}]{RESET}')
            provider_delete(rtype, change.before or {}, world)
            seconds = max(1, rtype.seconds // 2)
            worldlib.advance(world, seconds)
            lines.append(f'{BOLD}{change.address}: Destruction complete after {duration(seconds)}{RESET}')
            state.instances.pop(change.address, None)
            counts['destroy'] += 1
        if not plan.destroy:
            for resource in evaluator.order():
                keys = evaluator.instance_keys(resource)
                evaluator.empty_collection(resource)
                for key in keys:
                    address = instance_address(resource.type, resource.name, key, resource.mode)
                    args = evaluator.arguments(resource, key, [])
                    if resource.mode == 'data':
                        evaluator.register(resource, key, azurerm.data_source(resource.type, args, world['azure']))
                        continue
                    rtype = azurerm.RESOURCES[resource.type]
                    planned = by_address.get(address)
                    current = state.instances.get(address)
                    action = planned.action if planned else 'noop'
                    deps = sorted(evaluator.deps.get(resource.address, set()))
                    if action == 'noop':
                        attrs = current.attributes if current else {}
                        evaluator.register(resource, key, attrs)
                        continue
                    if action == 'update':
                        new = {**current.attributes} if current else {}
                        ignore = resource.lifecycle.ignore_changes
                        for name, value in args.items():
                            if ignore == 'all' or (isinstance(ignore, list) and name in ignore):
                                continue
                            new[name] = value
                        rid = new.get('id')
                        lines.append(f'{BOLD}{address}: Modifying... [id={rid}]{RESET}')
                        attrs = provider_update(rtype, new, world)
                        seconds = max(1, rtype.seconds // 3)
                        worldlib.advance(world, seconds)
                        lines.append(f'{BOLD}{address}: Modifications complete after {duration(seconds)} [id={rid}]{RESET}')
                        counts['change'] += 1
                    else:
                        if action == 'replace' and current:
                            if not resource.lifecycle.create_before_destroy:
                                lines.append(f'{BOLD}{address}: Destroying... [id={current.attributes.get("id")}]{RESET}')
                                provider_delete(rtype, current.attributes, world)
                                worldlib.advance(world, max(1, rtype.seconds // 2))
                                lines.append(f'{BOLD}{address}: Destruction complete after '
                                             f'{duration(max(1, rtype.seconds // 2))}{RESET}')
                                state.instances.pop(address, None)
                                counts['destroy'] += 1
                        lines.append(f'{BOLD}{address}: Creating...{RESET}')
                        seconds = rtype.seconds
                        elapsed = 10
                        while elapsed < seconds:
                            lines.append(f'{BOLD}{address}: Still creating... [{duration(elapsed)} elapsed]{RESET}')
                            elapsed += 10
                        attrs = provider_create(rtype, args, world)
                        worldlib.advance(world, seconds)
                        lines.append(f'{BOLD}{address}: Creation complete after {duration(seconds)} [id={attrs["id"]}]{RESET}')
                        counts['add'] += 1
                        if action == 'replace' and current and resource.lifecycle.create_before_destroy:
                            lines.append(f'{BOLD}{address} (deposed object): Destroying... [id={current.attributes.get("id")}]{RESET}')
                            provider_delete(rtype, current.attributes, world)
                            lines.append(f'{BOLD}{address} (deposed object): Destruction complete{RESET}')
                            counts['destroy'] += 1
                    state.instances[address] = Instance('managed', resource.type, resource.name, key, attrs, deps)
                    evaluator.register(resource, key, attrs)
    except (ApplyError, LookupError) as problem:
        ok = False
        text = str(problem)
        first, _, rest = text.partition('\n')
        lines.append('')
        lines.append(Diag(first, rest.strip()).render())
    outputs = {}
    if ok and not plan.destroy:
        try:
            outputs = evaluator.outputs()
        except EvalError:
            outputs = {}
    write_state(folder, state, outputs)
    worldlib.save(folder, world)
    if ok:
        verb = 'Destroy' if plan.destroy else 'Apply'
        if plan.destroy:
            summary = f'Resources: {counts["destroy"]} destroyed.'
        else:
            summary = ('Resources: ' + (f'{counts["import"]} imported, ' if counts['import'] else '') +
                       f'{counts["add"]} added, {counts["change"]} changed, {counts["destroy"]} destroyed.')
        lines.append(f'\n{GREEN}{BOLD}{verb} complete! {summary}{RESET}')
        lines.append(render_outputs(outputs))
    return '\n'.join(l for l in lines if l is not None), ok, counts


# ---- Commands ------------------------------------------------------------------------------------------------------


@dataclass
class Result:
    output: str
    exit_code: int
    prompt: str | None = None
    summary: dict = field(default_factory=dict)


def parse_flags(args: list[str]) -> tuple[dict[str, Any], list[str]]:
    flags: dict[str, Any] = {'var': [], 'var_file': []}
    positional: list[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith('--'):
            arg = arg[1:]
        if arg in ('-var', '-var-file') and i + 1 < len(args):
            value = args[i + 1]
            i += 1
            arg = f'{arg}={value}'
        if arg.startswith('-var='):
            text = arg[5:]
            if '=' not in text:
                raise Failed([Diag('Invalid -var option', f'The given -var option "{text}" is not correctly specified. '
                                                          'It must be a variable name and value separated by an equals '
                                                          'sign, like -var="key=value".')])
            key, value = text.split('=', 1)
            flags['var'].append((key.strip(), value))
        elif arg.startswith('-var-file='):
            flags['var_file'].append(arg[10:])
        elif arg in ('-auto-approve', '-destroy', '-json', '-raw', '-no-color', '-refresh=true', '-input=false',
                     '-compact-warnings', '-upgrade', '-reconfigure', '-lock=false'):
            flags[arg.lstrip('-').split('=')[0]] = True
        elif arg.startswith('-out'):
            raise Failed([Diag('Saved plans are not simulated', 'Run terraform plan to review, then terraform apply and '
                                                                'answer yes: the lab re-plans and applies the same '
                                                                'changes.')])
        elif arg.startswith('-target') or arg.startswith('-replace') or arg.startswith('-refresh-only'):
            raise Failed([Diag(f'{arg.split("=")[0]} is not simulated', 'The lab plans the whole configuration.')])
        elif arg.startswith('-'):
            raise Failed([Diag('Unsupported option', f'The option {arg} is not simulated in this lab.')])
        else:
            positional.append(args[i])
        i += 1
    return flags, positional


def require_init(world: dict, config: Config) -> None:
    if not world['terraform'].get('initialized'):
        raise Failed([Diag('Inconsistent dependency lock file',
                           'The following dependency selections recorded in the lock file are inconsistent with the '
                           'current configuration:\n  - provider registry.terraform.io/hashicorp/azurerm: required by '
                           'this configuration but no version is selected\n\nTo make the initial dependency '
                           'selections that will initialize the dependency lock file, run:\n  terraform init')])
    if 'azurerm' not in config.provider_blocks:
        raise Failed([Diag('Missing required provider configuration',
                           'The azurerm provider needs a provider "azurerm" block with an empty features {} block, '
                           'for example:\n\n  provider "azurerm" {\n    features {}\n  }')])
    block = config.provider_blocks['azurerm']
    if not block.body.blocks_of('features'):
        raise Failed([Diag('Insufficient features blocks', 'At least 1 "features" blocks are required.', block.file,
                           block.line, 'provider "azurerm"')])


def command(folder: Path, args: list[str], answer: str | None = None) -> Result:
    if not args or args[0] in ('-help', '--help', 'help', '-h'):
        return Result(HELP, 0)
    sub, rest = args[0], args[1:]
    handler = COMMANDS.get(sub)
    if handler is None:
        return Result(f'{RED}Terraform has no command named "{sub}".{RESET}\n\n{HELP}', 1)
    world = worldlib.load(folder)
    try:
        result = handler(folder, rest, world, answer)
    except Failed as failed:
        return Result(render_diags(failed.diags) + '\n', 1)
    except Diag as diag:
        return Result(diag.render() + '\n', 1)
    return result


def cmd_init(folder: Path, args: list[str], world: dict, answer: str | None) -> Result:
    parse_flags(args)
    config = load_config(folder)
    sources = dict(config.providers)
    used = {r.type.split('_', 1)[0] for r in config.resources.values()} | set(config.provider_blocks)
    for local in used:
        sources.setdefault(local, f'hashicorp/{local}')
    unsupported = sorted(f'{local} ({source})' for local, source in sources.items() if source != azurerm.PROVIDER_SOURCE)
    lines = [f'\n{BOLD}Initializing the backend...{RESET}', f'{BOLD}Initializing provider plugins...{RESET}',
             '- Finding hashicorp/azurerm versions matching "~> 4.0"...']
    if unsupported:
        return Result('\n'.join(lines) + '\n' + Diag('Failed to query available provider packages',
                      'This lab simulates the hashicorp/azurerm provider only; it cannot install: '
                      + ', '.join(unsupported) + '.').render() + '\n', 1)
    lines += [f'- Installing hashicorp/azurerm v{azurerm.PROVIDER_VERSION} (simulated)...',
              f'- Installed hashicorp/azurerm v{azurerm.PROVIDER_VERSION} (simulated, nothing was downloaded)',
              '', f'{GREEN}{BOLD}Terraform has been successfully initialized!{RESET}', '',
              f'{GREEN}You may now begin working with Terraform. Try running "terraform plan" to see any changes '
              f'that are required for your infrastructure.{RESET}']
    world['terraform'] = {'initialized': True, 'providers': {'azurerm': azurerm.PROVIDER_VERSION}}
    worldlib.advance(world, 6)
    worldlib.save(folder, world)
    return Result('\n'.join(lines) + '\n', 0)


def cmd_validate(folder: Path, args: list[str], world: dict, answer: str | None) -> Result:
    parse_flags(args)
    config = load_config(folder)
    require_init(world, config)
    evaluator = Evaluator(folder, config, {name: UNKNOWN for name in config.variables}, world)
    diags: list[Diag] = []
    for resource in evaluator.order():
        evaluator.empty_collection(resource)
        try:
            keys = evaluator.instance_keys(resource) if (resource.count or resource.for_each) else [None]
        except (Diag, EvalError):
            keys = [None]
        for key in keys[:1]:
            instance_diags: list[Diag] = []
            try:
                args_values = evaluator.arguments(resource, key, instance_diags)
            except EvalError as error:
                if 'undeclared' in error.message or 'unknown function' in error.message:
                    diags.append(from_hcl(error, resource.context))
                args_values = {}
            diags += [d for d in instance_diags if d.severity == 'error']
            rtype = azurerm.RESOURCES.get(resource.type)
            value = {**args_values, **({n: UNKNOWN for n in computed_names(rtype)} if rtype else {})}
            if resource.mode == 'data':
                value = UNKNOWN
            evaluator.register(resource, key if not resource.for_each else (key or 'k'), value)
    if diags:
        raise Failed(diags)
    return Result(f'{GREEN}{BOLD}Success!{RESET} The configuration is valid.\n', 0)


def _plan(folder: Path, args: list[str], world: dict, destroy: bool = False) -> tuple[Config, dict, State, Plan, dict]:
    flags, positional = parse_flags(args)
    if positional:
        raise Failed([Diag('Too many command line arguments', 'Saved plan files are not simulated: run '
                                                              'terraform apply without a file name.')])
    config = load_config(folder)
    require_init(world, config)
    variables = variable_values(config, folder, flags['var'], flags['var_file'])
    state = read_state(folder)
    plan = make_plan(folder, config, variables, world, state, destroy or bool(flags.get('destroy')))
    return config, variables, state, plan, flags


def refreshing(state: State) -> str:
    return '\n'.join(f'{inst.address}: Refreshing state... [id={inst.attributes.get("id")}]'
                     for inst in state.instances.values() if inst.mode == 'managed')


def cmd_plan(folder: Path, args: list[str], world: dict, answer: str | None) -> Result:
    config, _variables, state, plan, _flags = _plan(folder, args, world)
    worldlib.advance(world, 3 + len(state.instances))
    worldlib.save(folder, world)
    text = '\n'.join(filter(None, [refreshing(state), render_plan(plan, 'plan')]))
    warnings = render_diags(plan.warnings)
    tail = ('\n\n' + DIM + 'Note: You didn\'t use the -out option to save this plan, so Terraform can\'t guarantee to '
            'take exactly these actions if you run "terraform apply" now.' + RESET) if plan.has_changes() else ''
    return Result(text + tail + ('\n' + warnings if warnings else '') + '\n', 0,
                  summary={**plan.counts(), 'changes': plan.has_changes(), 'drift': len(plan.drift)})


def cmd_apply(folder: Path, args: list[str], world: dict, answer: str | None, destroy: bool = False) -> Result:
    config, variables, state, plan, flags = _plan(folder, args, world, destroy)
    header = '\n'.join(filter(None, [refreshing(state), render_plan(plan, 'apply')]))
    if destroy and not plan.changes:
        worldlib.save(folder, world)
        return Result(header + f'\n\n{GREEN}{BOLD}Destroy complete! Resources: 0 destroyed.{RESET}\n', 0,
                      summary={**plan.counts(), 'changes': False})
    if not plan.has_changes():
        text, ok, counts = run_apply(folder, config, variables, world, state, plan)
        return Result(header + '\n' + text + '\n', 0 if ok else 1, summary={**counts, 'changes': False})
    if not flags.get('auto-approve'):
        if answer is None:
            question = ('Do you really want to destroy all resources?\n  Terraform will destroy all your managed '
                        'infrastructure, as shown above.\n  There is no undo. Only \'yes\' will be accepted to confirm.'
                        if plan.destroy else
                        'Do you want to perform these actions?\n  Terraform will perform the actions described above.'
                        '\n  Only \'yes\' will be accepted to approve.')
            return Result(header + '\n', 0, prompt=f'\n{BOLD}{question}{RESET}\n\n  {BOLD}Enter a value:{RESET} ',
                          summary={'fingerprint': plan.fingerprint()})
        if answer.strip() != 'yes':
            verb = 'Destroy' if plan.destroy else 'Apply'
            return Result(f'\n{verb} cancelled.\n', 1, summary={'cancelled': True})
        header = ''
    text, ok, counts = run_apply(folder, config, variables, world, state, plan)
    return Result((header + '\n' if header else '') + text + '\n', 0 if ok else 1, summary={**counts, 'changes': True})


def cmd_destroy(folder: Path, args: list[str], world: dict, answer: str | None) -> Result:
    return cmd_apply(folder, args, world, answer, destroy=True)


def cmd_import(folder: Path, args: list[str], world: dict, answer: str | None) -> Result:
    flags, positional = parse_flags(args)
    if len(positional) != 2:
        return Result('Usage: terraform import ADDRESS ID\n\n  Import an existing resource into the Terraform state, '
                      'for example:\n  terraform import azurerm_resource_group.main /subscriptions/<id>/resourceGroups/'
                      '<name>\n', 1)
    address, rid = positional
    config = load_config(folder)
    require_init(world, config)
    base, key = split_address(address)
    resource = config.resources.get(base)
    if resource is None or resource.mode != 'managed':
        raise Failed([Diag('Resource address does not exist in the configuration',
                           f'Before importing this resource, please create its configuration in the root module. For '
                           f'example:\n\nresource "{base.split(".")[0]}" "{base.split(".")[-1]}" {{\n  # (resource '
                           'arguments)\n}}')])
    variables = variable_values(config, folder, flags['var'], flags['var_file'])
    state = read_state(folder)
    if address in state.instances:
        raise Failed([Diag('Resource already managed by Terraform',
                           f'Terraform is already managing a remote object for {address}. To import to this address '
                           'you must first remove the existing object from the state.')])
    remote = find_world_resource(world['azure'], rid)
    if remote is None or remote.get('tf_type') != resource.type:
        raise Failed([Diag('Cannot import non-existent remote object',
                           f'While attempting to import an existing object to "{address}", the provider detected that '
                           f'no object exists with the given id. Only pre-existing objects can be imported; check that '
                           f'the id is correct and that it is associated with the provider\'s configured region or '
                           f'endpoint, or use "terraform apply" to create a new remote object for this resource.')])
    del variables
    state.instances[address] = Instance('managed', resource.type, resource.name, key, dict(remote['attributes']))
    write_state(folder, state, {name: (value, False) for name, value in state.outputs.items()})
    worldlib.advance(world, 3)
    worldlib.save(folder, world)
    text = (f'{BOLD}{address}: Importing from ID "{rid}"...{RESET}\n'
            f'{BOLD}{address}: Import prepared!{RESET}\n  Prepared {resource.type} for import\n'
            f'{BOLD}{address}: Refreshing state... [id={rid}]{RESET}\n\n'
            f'{GREEN}{BOLD}Import successful!{RESET}\n\n{GREEN}The resources that were imported are shown above. These '
            f'resources are now in\nyour Terraform state and will henceforth be managed by Terraform.{RESET}\n')
    return Result(text, 0, summary={'import': 1})


def cmd_state(folder: Path, args: list[str], world: dict, answer: str | None) -> Result:
    if not args:
        return Result('Usage: terraform state <list|show|mv|rm> [options] [args]\n', 1)
    sub, rest = args[0], args[1:]
    state = read_state(folder)
    if sub == 'list':
        addresses = sorted(state.instances)
        if rest:
            addresses = [a for a in addresses if any(a == r or a.startswith(r + '[') or a.startswith(r + '.') for r in rest)]
        return Result(''.join(a + '\n' for a in addresses), 0)
    if sub == 'show':
        if len(rest) != 1 or rest[0] not in state.instances:
            return Result(f'{RED}No instance found for the given address!{RESET}\n\nThis command requires that the '
                          'address references one specific instance.\nTo view the available instances, use '
                          '"terraform state list".\n', 1)
        inst = state.instances[rest[0]]
        return Result(render_resource(inst) + '\n', 0)
    if sub == 'mv':
        if len(rest) != 2:
            return Result('Usage: terraform state mv SOURCE DESTINATION\n', 1)
        source, target = rest
        if source not in state.instances:
            return Result(Diag('Invalid source address', f'Cannot move {source}: it does not exist in the '
                                                         'state.').render() + '\n', 1)
        if target in state.instances:
            return Result(Diag('Invalid target address', f'Cannot move to {target}: there is already a resource '
                                                         'instance at that address in the current state.').render() + '\n', 1)
        base, key = split_address(target)
        if base.count('.') != 1 or base.split('.')[0] != state.instances[source].type:
            return Result(Diag('Invalid target address', f'Cannot move {source} to {target}: the resource types '
                                                         'must match.').render() + '\n', 1)
        inst = state.instances.pop(source)
        state.instances[target] = Instance('managed', inst.type, base.split('.')[1], key, inst.attributes,
                                           inst.dependencies)
        write_state(folder, state, {k: (v, False) for k, v in state.outputs.items()})
        return Result(f'Move "{source}" to "{target}"\n{GREEN}Successfully moved 1 object(s).{RESET}\n', 0,
                      summary={'moved': 1})
    if sub == 'rm':
        if not rest:
            return Result('Usage: terraform state rm ADDRESS...\n', 1)
        removed = [a for a in list(state.instances) if any(a == r or a.startswith(r + '[') for r in rest)]
        if not removed:
            return Result(Diag('Invalid target address', 'No matching objects found. To view the available '
                                                         'instances, use "terraform state list".').render() + '\n', 1)
        for address in removed:
            del state.instances[address]
        write_state(folder, state, {k: (v, False) for k, v in state.outputs.items()})
        return Result(''.join(f'Removed {a}\n' for a in removed) +
                      f'{GREEN}Successfully removed {len(removed)} resource instance(s).{RESET}\n', 0,
                      summary={'removed': len(removed)})
    return Result(f'{RED}terraform state {sub} is not simulated.{RESET} Use list, show, mv or rm.\n', 1)


def render_resource(inst: Instance) -> str:
    lines = [f'# {inst.address}:', f'resource "{inst.type}" "{inst.name}" {{']
    items = [(k, v) for k, v in sorted(inst.attributes.items()) if v not in (None, [], {})]
    width = max((len(k) for k, _ in items), default=0)
    for key, value in items:
        lines.append(f'    {key.ljust(width)} = {render_value(value, 4)}')
    lines.append('}')
    return '\n'.join(lines)


def cmd_show(folder: Path, args: list[str], world: dict, answer: str | None) -> Result:
    state = read_state(folder)
    if not state.instances:
        return Result('The state file is empty. No resources are represented.\n', 0)
    body = '\n\n'.join(render_resource(inst) for inst in state.instances.values())
    outs = render_outputs({k: (v, False) for k, v in state.outputs.items()})
    return Result(body + '\n' + outs + '\n', 0)


def cmd_output(folder: Path, args: list[str], world: dict, answer: str | None) -> Result:
    flags, positional = parse_flags(args)
    state = read_state(folder)
    if positional:
        name = positional[0]
        if name not in state.outputs:
            return Result(Diag('Output "' + name + '" not found', 'The output variable requested could not be found '
                                                                  'in the state file.').render() + '\n', 1)
        value = state.outputs[name]
        if flags.get('json'):
            return Result(json.dumps(value) + '\n', 0)
        if flags.get('raw') and isinstance(value, (str, int, float, bool)):
            return Result(tfexpr._tostring(value), 0)
        return Result(render_value(value, 0) + '\n', 0)
    if flags.get('json'):
        return Result(json.dumps({k: {'value': v, 'type': json_type(v), 'sensitive': False}
                                  for k, v in state.outputs.items()}, indent=2) + '\n', 0)
    if not state.outputs:
        return Result(f'{YELLOW}╷\n│ Warning: No outputs found\n╵{RESET}\n', 0)
    return Result(''.join(f'{k} = {render_value(v, 0)}\n' for k, v in sorted(state.outputs.items())), 0)


def cmd_fmt(folder: Path, args: list[str], world: dict, answer: str | None) -> Result:
    return Result(f'{YELLOW}terraform fmt is not simulated in this lab{RESET}: it rewrites files, and the lab only '
                  'reads yours. Keep two-space indentation and align the = signs of consecutive arguments.\n', 1)


def cmd_version(folder: Path, args: list[str], world: dict, answer: str | None) -> Result:
    return Result(f'Terraform v{TERRAFORM_VERSION} (simulated by Datapass)\non windows_amd64\n+ provider '
                  f'registry.terraform.io/hashicorp/azurerm v{azurerm.PROVIDER_VERSION} (simulated)\n', 0)


COMMANDS = {
    'init': cmd_init, 'validate': cmd_validate, 'plan': cmd_plan, 'apply': cmd_apply, 'destroy': cmd_destroy,
    'import': cmd_import, 'state': cmd_state, 'show': cmd_show, 'output': cmd_output, 'fmt': cmd_fmt,
    'version': cmd_version, '-version': cmd_version, '--version': cmd_version,
}

HELP = f"""Usage: terraform [global options] <subcommand> [args]   {DIM}(simulated by Datapass){RESET}

Main commands:
  init          Prepare your working directory (the azurerm provider is simulated)
  validate      Check whether the configuration is valid
  plan          Show changes required by the current configuration
  apply         Create or update infrastructure (in the simulated subscription)
  destroy       Destroy previously-created infrastructure

Other commands:
  import        Associate existing infrastructure with a Terraform resource
  output        Show output values from your root module
  show          Show the current state
  state         list, show, mv, rm
  version       Show the current Terraform version

Options for plan, apply and destroy: -var 'name=value', -var-file=FILE, -auto-approve (apply, destroy).
"""
