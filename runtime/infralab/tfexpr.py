"""Evaluation of HCL expressions over plain values, as Terraform does, with a whitelist of functions.

Values are Python `str`, `int`/`float`, `bool`, `None` (null), `list` (tuples, lists and sets, sets kept sorted and
unique), `dict` (objects and maps), and `UNKNOWN` for a value only known after apply (it propagates through every
operation, as Terraform's unknown values do). Nothing the learner writes is executed as code.
"""
from __future__ import annotations

import ipaddress
import json
import math
from typing import Any, Callable

from . import hcl
from .hcl import HclError


class _Unknown:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return '(known after apply)'


UNKNOWN = _Unknown()


def is_unknown(value: Any) -> bool:
    if value is UNKNOWN:
        return True
    if isinstance(value, list):
        return any(is_unknown(v) for v in value)
    if isinstance(value, dict):
        return any(is_unknown(v) for v in value.values())
    return False


class EvalError(HclError):
    pass


class Scope:
    """Names an expression may use. `roots` maps a first name (var, local, each, a resource type…) to its value, or
    to a callable that resolves it lazily (locals depend on each other)."""

    def __init__(self, roots: dict[str, Any], file: str = ''):
        self.roots = roots
        self.file = file
        self.vars: dict[str, Any] = {}   # for-expression variables

    def child(self, names: dict[str, Any]) -> 'Scope':
        scope = Scope(self.roots, self.file)
        scope.vars = {**self.vars, **names}
        return scope


def error(node: hcl.Node, message: str, scope: Scope) -> EvalError:
    return EvalError(message, scope.file, node.line, node.col)


def evaluate(node: hcl.Node, scope: Scope) -> Any:
    if isinstance(node, hcl.Literal):
        return node.value
    if isinstance(node, hcl.Template):
        out = []
        for part in node.parts:
            if isinstance(part, str):
                out.append(part)
                continue
            value = evaluate(part, scope)
            if value is UNKNOWN or is_unknown(value):
                return UNKNOWN
            out.append(to_string(value, part, scope))
        return ''.join(out)
    if isinstance(node, hcl.Var):
        if node.name in scope.vars:
            return scope.vars[node.name]
        if node.name in scope.roots:
            root = scope.roots[node.name]
            return root() if callable(root) else root
        raise error(node, f'Reference to undeclared name {node.name!r}.', scope)
    if isinstance(node, hcl.GetAttr):
        target = evaluate(node.target, scope)
        if target is UNKNOWN:
            return UNKNOWN
        if isinstance(target, dict):
            if node.name not in target:
                raise error(node, f'This object does not have an attribute named {node.name!r}.', scope)
            value = target[node.name]
            return value() if callable(value) else value
        if isinstance(target, list):
            raise error(node, f'A list has no attribute {node.name!r}: use an index such as [0] or a splat [*].', scope)
        raise error(node, f'Cannot read attribute {node.name!r} of {type_name(target)}.', scope)
    if isinstance(node, hcl.Index):
        target = evaluate(node.target, scope)
        key = evaluate(node.key, scope)
        if target is UNKNOWN or key is UNKNOWN:
            return UNKNOWN
        if isinstance(target, list):
            index = to_number(key, node, scope)
            if not isinstance(index, int) and not float(index).is_integer():
                raise error(node, 'A list index must be a whole number.', scope)
            index = int(index)
            if index < 0 or index >= len(target):
                raise error(node, f'Invalid index: the list has {len(target)} element(s), index {index} is out of range.', scope)
            return target[index]
        if isinstance(target, dict):
            name = to_string(key, node, scope)
            if name not in target:
                raise error(node, f'Invalid index: the map has no element {name!r}.', scope)
            value = target[name]
            return value() if callable(value) else value
        raise error(node, f'Cannot index {type_name(target)}.', scope)
    if isinstance(node, hcl.Splat):
        target = evaluate(node.target, scope)
        if target is UNKNOWN:
            return UNKNOWN
        items = target if isinstance(target, list) else ([] if target is None else [target])
        out = []
        for item in items:
            for name in node.names:
                if item is UNKNOWN:
                    break
                if not isinstance(item, dict) or name not in item:
                    raise error(node, f'An element has no attribute {name!r}.', scope)
                item = item[name]
            out.append(item)
        return out
    if isinstance(node, hcl.TupleExpr):
        return [evaluate(item, scope) for item in node.items]
    if isinstance(node, hcl.ObjectExpr):
        out: dict[str, Any] = {}
        for key_node, value_node in node.items:
            key = evaluate(key_node, scope)
            if key is UNKNOWN:
                return UNKNOWN
            out[to_string(key, key_node, scope)] = evaluate(value_node, scope)
        return out
    if isinstance(node, hcl.Conditional):
        cond = evaluate(node.cond, scope)
        if cond is UNKNOWN:
            return UNKNOWN
        if not isinstance(cond, bool):
            raise error(node, f'The condition must be true or false, not {type_name(cond)}.', scope)
        return evaluate(node.then if cond else node.other, scope)
    if isinstance(node, hcl.Unary):
        value = evaluate(node.operand, scope)
        if value is UNKNOWN:
            return UNKNOWN
        if node.op == '!':
            if not isinstance(value, bool):
                raise error(node, f'! needs true or false, not {type_name(value)}.', scope)
            return not value
        return -to_number(value, node, scope)
    if isinstance(node, hcl.Binary):
        return binary(node, scope)
    if isinstance(node, hcl.ForExpr):
        return for_expr(node, scope)
    if isinstance(node, hcl.Call):
        return call(node, scope)
    raise error(node, 'Unsupported expression.', scope)


def binary(node: hcl.Binary, scope: Scope) -> Any:
    op = node.op
    left = evaluate(node.left, scope)
    if op in ('&&', '||'):
        if left is UNKNOWN:
            return UNKNOWN
        if not isinstance(left, bool):
            raise error(node, f'{op} needs true or false, not {type_name(left)}.', scope)
        if op == '&&' and not left:
            return False
        if op == '||' and left:
            return True
        right = evaluate(node.right, scope)
        if right is UNKNOWN:
            return UNKNOWN
        if not isinstance(right, bool):
            raise error(node, f'{op} needs true or false, not {type_name(right)}.', scope)
        return right
    right = evaluate(node.right, scope)
    if left is UNKNOWN or right is UNKNOWN:
        return UNKNOWN
    if op == '==':
        return equal(left, right)
    if op == '!=':
        return not equal(left, right)
    a, b = to_number(left, node, scope), to_number(right, node, scope)
    if op == '+':
        return normalize(a + b)
    if op == '-':
        return normalize(a - b)
    if op == '*':
        return normalize(a * b)
    if op == '/':
        if b == 0:
            raise error(node, 'Division by zero.', scope)
        return normalize(a / b)
    if op == '%':
        if b == 0:
            raise error(node, 'Division by zero.', scope)
        return normalize(math.fmod(a, b))
    return {'<': a < b, '>': a > b, '<=': a <= b, '>=': a >= b}[op]


def for_expr(node: hcl.ForExpr, scope: Scope) -> Any:
    collection = evaluate(node.collection, scope)
    if collection is UNKNOWN:
        return UNKNOWN
    if isinstance(collection, dict):
        pairs = sorted(collection.items())
    elif isinstance(collection, list):
        pairs = list(enumerate(collection))
    else:
        raise error(node, f'A for expression needs a list, set or map, not {type_name(collection)}.', scope)
    results_list: list = []
    results_map: dict[str, Any] = {}
    for key, value in pairs:
        names = {node.value_var: value}
        if node.key_var:
            names[node.key_var] = key
        inner = scope.child(names)
        if node.cond is not None:
            keep = evaluate(node.cond, inner)
            if keep is UNKNOWN:
                return UNKNOWN
            if not isinstance(keep, bool):
                raise error(node, 'The if clause of a for expression must be true or false.', scope)
            if not keep:
                continue
        if node.key is None:
            results_list.append(evaluate(node.value, inner))
        else:
            out_key = evaluate(node.key, inner)
            if out_key is UNKNOWN:
                return UNKNOWN
            out_key = to_string(out_key, node, scope)
            out_value = evaluate(node.value, inner)
            if node.group:
                results_map.setdefault(out_key, []).append(out_value)
            elif out_key in results_map:
                raise error(node, f'Duplicate key {out_key!r} in a for expression (add ... to group).', scope)
            else:
                results_map[out_key] = out_value
    return results_list if node.key is None else results_map


# ---- Conversions -------------------------------------------------------------------------------------------------


def type_name(value: Any) -> str:
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'bool'
    if isinstance(value, (int, float)):
        return 'number'
    if isinstance(value, str):
        return 'string'
    if isinstance(value, list):
        return 'list'
    if isinstance(value, dict):
        return 'object'
    return 'unknown'


def normalize(value: float | int) -> float | int:
    if isinstance(value, float) and value.is_integer() and abs(value) < 2 ** 53:
        return int(value)
    return value


def to_number(value: Any, node: hcl.Node, scope: Scope) -> float | int:
    if isinstance(value, bool) or value is None:
        raise error(node, f'A number is required, not {type_name(value)}.', scope)
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            return normalize(float(value)) if any(c in value for c in '.eE') else int(value)
        except ValueError:
            raise error(node, f'Cannot convert {value!r} to a number.', scope) from None
    raise error(node, f'A number is required, not {type_name(value)}.', scope)


def to_string(value: Any, node: hcl.Node, scope: Scope) -> str:
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return format_number(value)
    if isinstance(value, str):
        return value
    if value is None:
        raise error(node, 'Invalid template interpolation value: the value is null.', scope)
    raise error(node, f'Cannot include {type_name(value)} in a string: a string is required.', scope)


def format_number(value: float | int) -> str:
    value = normalize(value)
    return str(value) if isinstance(value, int) else repr(value)


def equal(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    return a == b


def to_set(values: list) -> list:
    out: list = []
    for value in values:
        if not any(equal(value, seen) for seen in out):
            out.append(value)
    try:
        return sorted(out, key=lambda v: json.dumps(v, sort_keys=True))
    except TypeError:
        return out


# ---- Functions -------------------------------------------------------------------------------------------------


def call(node: hcl.Call, scope: Scope) -> Any:
    name = node.name
    if name in ('try', 'can'):
        return lazy_call(node, scope)
    fn = FUNCTIONS.get(name)
    if fn is None:
        raise error(node, f'Call to unknown function {name!r}: the lab supports {", ".join(sorted(FUNCTIONS))}, try '
                          'and can.', scope)
    args = [evaluate(arg, scope) for arg in node.args]
    if node.expand:
        last = args.pop() if args else []
        if last is UNKNOWN:
            return UNKNOWN
        if not isinstance(last, list):
            raise error(node, 'Only a list can be expanded with ...', scope)
        args += last
    if any(arg is UNKNOWN for arg in args):
        return UNKNOWN
    try:
        return fn(*args)
    except EvalError:
        raise
    except TypeError:
        raise error(node, f'Wrong number or type of arguments for {name}().', scope) from None
    except (ValueError, KeyError, IndexError) as problem:
        raise error(node, f'{name}(): {problem}', scope) from None


def lazy_call(node: hcl.Call, scope: Scope) -> Any:
    if node.name == 'can':
        if len(node.args) != 1:
            raise error(node, 'can() takes one argument.', scope)
        try:
            value = evaluate(node.args[0], scope)
        except EvalError:
            return False
        return UNKNOWN if value is UNKNOWN else True
    for arg in node.args:
        try:
            return evaluate(arg, scope)
        except EvalError:
            continue
    raise error(node, 'try(): no argument could be evaluated without an error.', scope)


def _need(value: Any, kind: type | tuple, what: str) -> Any:
    if isinstance(value, bool) and kind in (int, (int, float)):
        raise ValueError(f'{what} must be a number')
    if not isinstance(value, kind):
        raise ValueError(f'{what} must be a {getattr(kind, "__name__", "number")}')
    return value


def _format(spec: str, *args: Any) -> str:
    out, i, arg = [], 0, 0
    while i < len(spec):
        ch = spec[i]
        if ch != '%':
            out.append(ch)
            i += 1
            continue
        verb = spec[i + 1:i + 2]
        if verb == '%':
            out.append('%')
            i += 2
            continue
        # Width and precision for %d / %f / %s, as in Go's fmt (the part Terraform documents).
        j = i + 1
        while j < len(spec) and (spec[j].isdigit() or spec[j] in '.-0'):
            j += 1
        verb, flags = spec[j:j + 1], spec[i + 1:j]
        if arg >= len(args):
            raise ValueError('not enough arguments for the format string')
        value = args[arg]
        arg += 1
        if verb == 's':
            text = value if isinstance(value, str) else json.dumps(value) if isinstance(value, (list, dict)) else \
                ('true' if value is True else 'false' if value is False else format_number(value))
            out.append(('%' + flags + 's') % text)
        elif verb == 'd':
            out.append(('%' + flags + 'd') % int(value if not isinstance(value, str) else float(value)))
        elif verb == 'f':
            out.append(('%' + flags + 'f') % float(value))
        elif verb == 'v':
            out.append(value if isinstance(value, str) else json.dumps(value))
        elif verb == 'q':
            out.append(json.dumps(value))
        else:
            raise ValueError(f'unsupported verb %{verb}')
        i = j + 1
    return ''.join(out)


def _cidrsubnet(prefix: str, newbits: int, netnum: int) -> str:
    network = ipaddress.ip_network(_need(prefix, str, 'prefix'), strict=False)
    new_prefix = network.prefixlen + int(newbits)
    if new_prefix > network.max_prefixlen:
        raise ValueError(f'not enough bits: /{network.prefixlen} + {newbits} is more than {network.max_prefixlen}')
    subnets = 2 ** int(newbits)
    if not 0 <= int(netnum) < subnets:
        raise ValueError(f'netnum {netnum} does not fit in {newbits} bits')
    size = 2 ** (network.max_prefixlen - new_prefix)
    address = int(network.network_address) + int(netnum) * size
    return str(ipaddress.ip_network((address, new_prefix)))


def _lookup(mapping: dict, key: str, *default: Any) -> Any:
    if key in mapping:
        return mapping[key]
    if default:
        return default[0]
    raise KeyError(f'the map has no key {key!r} and no default was given')


def _merge(*maps: dict) -> dict:
    out: dict = {}
    for mapping in maps:
        if mapping is None:
            continue
        out.update(_need(mapping, dict, 'every argument of merge'))
    return out


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value is not None and value != '':
            return value
    raise ValueError('no non-null, non-empty argument')


def _element(items: list, index: int) -> Any:
    if not items:
        raise ValueError('cannot use element() on an empty list')
    return items[int(index) % len(items)]


def _flatten(items: list) -> list:
    out: list = []
    for item in items:
        out.extend(_flatten(item) if isinstance(item, list) else [item])
    return out


def _substr(text: str, offset: int, length: int) -> str:
    offset, length = int(offset), int(length)
    if offset < 0:
        offset = max(0, len(text) + offset)
    return text[offset:] if length < 0 else text[offset:offset + length]


def _tomap(value: dict) -> dict:
    return dict(_need(value, dict, 'the argument of tomap'))


def _tonumber(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError('cannot convert a bool to a number')
    if isinstance(value, (int, float)):
        return value
    try:
        return normalize(float(value)) if any(c in str(value) for c in '.eE') else int(value)
    except ValueError:
        raise ValueError(f'cannot convert {value!r} to a number') from None


def _tostring(value: Any) -> Any:
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return format_number(value)
    raise ValueError('only a primitive value can be converted to a string')


FUNCTIONS: dict[str, Callable[..., Any]] = {
    'abs': lambda n: abs(_need(n, (int, float), 'the argument')),
    'ceil': lambda n: math.ceil(_need(n, (int, float), 'the argument')),
    'cidrsubnet': _cidrsubnet,
    'coalesce': _coalesce,
    'concat': lambda *lists: [item for items in lists for item in _need(items, list, 'every argument of concat')],
    'contains': lambda items, value: any(equal(item, value) for item in _need(items, list, 'the first argument')),
    'distinct': lambda items: [v for i, v in enumerate(items) if not any(equal(v, w) for w in items[:i])],
    'element': _element,
    'endswith': lambda text, suffix: _need(text, str, 'the text').endswith(suffix),
    'flatten': _flatten,
    'floor': lambda n: math.floor(_need(n, (int, float), 'the argument')),
    'format': lambda spec, *args: _format(_need(spec, str, 'the format'), *args),
    'join': lambda sep, items: _need(sep, str, 'the separator').join(_tostring(v) for v in _need(items, list, 'the list')),
    'jsonencode': lambda value: json.dumps(value, separators=(',', ':'), sort_keys=True),
    'keys': lambda mapping: sorted(_need(mapping, dict, 'the argument')),
    'length': lambda value: len(_need(value, (str, list, dict), 'the argument')),
    'lookup': _lookup,
    'lower': lambda text: _need(text, str, 'the argument').lower(),
    'max': lambda *numbers: normalize(max(numbers)),
    'merge': _merge,
    'min': lambda *numbers: normalize(min(numbers)),
    'replace': lambda text, old, new: _need(text, str, 'the text').replace(old, new),
    'split': lambda sep, text: _need(text, str, 'the text').split(sep),
    'startswith': lambda text, prefix: _need(text, str, 'the text').startswith(prefix),
    'substr': _substr,
    'title': lambda text: _need(text, str, 'the argument').title(),
    'tolist': lambda items: list(_need(items, list, 'the argument')),
    'tomap': _tomap,
    'tonumber': _tonumber,
    'toset': lambda items: to_set(_need(items, list, 'the argument')),
    'tostring': _tostring,
    'trimspace': lambda text: _need(text, str, 'the argument').strip(),
    'upper': lambda text: _need(text, str, 'the argument').upper(),
    'values': lambda mapping: [mapping[k] for k in sorted(_need(mapping, dict, 'the argument'))],
    'zipmap': lambda ks, vs: dict(zip(ks, vs)),
}


# ---- References ----------------------------------------------------------------------------------------------------


def references(node: Any) -> list[tuple[str, ...]]:
    """The names an expression refers to, as tuples: ('var', 'x'), ('local', 'x'), ('azurerm_x', 'name'),
    ('data', 'type', 'name'), ('count',), ('each',). For-expression variables are left out."""
    found: list[tuple[str, ...]] = []

    def chain(n: Any) -> list[str] | None:
        if isinstance(n, hcl.Var):
            return [n.name]
        if isinstance(n, hcl.GetAttr):
            inner = chain(n.target)
            return None if inner is None else inner + [n.name]
        if isinstance(n, (hcl.Index, hcl.Splat)):
            return chain(n.target)
        return None

    def walk(n: Any, bound: frozenset[str]) -> None:
        if isinstance(n, (hcl.Var, hcl.GetAttr)):
            names = chain(n)
            if names and names[0] not in bound:
                if names[0] == 'data':
                    found.append(tuple(names[:3]))
                elif names[0] in ('count', 'each', 'path', 'terraform', 'self'):
                    found.append((names[0],))
                else:
                    found.append(tuple(names[:2]))
            if isinstance(n, hcl.GetAttr) and names is None:
                walk(n.target, bound)
            return
        if isinstance(n, hcl.Index):
            walk(n.target, bound)
            walk(n.key, bound)
        elif isinstance(n, hcl.Splat):
            walk(n.target, bound)
        elif isinstance(n, hcl.Template):
            for part in n.parts:
                if not isinstance(part, str):
                    walk(part, bound)
        elif isinstance(n, hcl.TupleExpr):
            for item in n.items:
                walk(item, bound)
        elif isinstance(n, hcl.ObjectExpr):
            for key, value in n.items:
                walk(key, bound)
                walk(value, bound)
        elif isinstance(n, hcl.Conditional):
            walk(n.cond, bound)
            walk(n.then, bound)
            walk(n.other, bound)
        elif isinstance(n, hcl.Unary):
            walk(n.operand, bound)
        elif isinstance(n, hcl.Binary):
            walk(n.left, bound)
            walk(n.right, bound)
        elif isinstance(n, hcl.Call):
            for arg in n.args:
                walk(arg, bound)
        elif isinstance(n, hcl.ForExpr):
            walk(n.collection, bound)
            inner = bound | {n.value_var} | ({n.key_var} if n.key_var else set())
            for part in (n.key, n.value, n.cond):
                if part is not None:
                    walk(part, inner)

    walk(node, frozenset())
    return found


def body_references(body: hcl.Body) -> list[tuple[str, ...]]:
    found: list[tuple[str, ...]] = []
    for attribute in body.attributes.values():
        found += references(attribute.expr)
    for block in body.blocks:
        found += body_references(block.body)
    return found
