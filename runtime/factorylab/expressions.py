"""The Data Factory expression language ("dynamic content"), read and evaluated safely.

Covers what pipeline authors use daily: `@pipeline().parameters.x`,
`@variables('v')`, `@activity('A').output.firstRow.col`, `@item()`, string
interpolation `@{...}`, the `@@` escape, `?.` safe navigation, and a bounded
function library (string, collection, logical, math, conversion and date
functions with .NET-style date formats). Expressions are tokenized and parsed
into a small AST; nothing is ever passed to Python eval.

Simplifications, stated so lessons do not depend on them: booleans stringify
as True/False (.NET), objects and arrays stringify as compact JSON (Data Factory
indents them), and time zones other than UTC are not supported.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

_MISSING = object()


class ExpressionError(ValueError):
    pass


# -- tokens and AST ------------------------------------------------------------------------------
_TOKEN = re.compile(r"\s*(?:(?P<number>-?\d+(?:\.\d+)?)|(?P<string>'(?:''|[^'])*')|(?P<ident>[A-Za-z_][A-Za-z0-9_]*)|(?P<punct>\?\.|\?\[|[().,\[\]]))")


@dataclass
class Node:
    kind: str  # lit | call | prop | index
    value: Any = None
    args: list['Node'] = field(default_factory=list)
    base: 'Node | None' = None
    safe: bool = False


def _tokenize(text: str) -> list[tuple[str, str]]:
    tokens, position = [], 0
    text = text.rstrip()
    while position < len(text):
        match = _TOKEN.match(text, position)
        if not match or match.end() == position:
            raise ExpressionError(f"Unexpected character {text[position:position + 12]!r} in expression")
        kind = match.lastgroup
        tokens.append((kind, match.group(kind)))
        position = match.end()
    return tokens


class _Parser:
    def __init__(self, text: str):
        self.text = text
        self.tokens = _tokenize(text)
        self.position = 0

    def peek(self) -> tuple[str, str] | None:
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def take(self, expected: str | None = None) -> tuple[str, str]:
        token = self.peek()
        if token is None or (expected is not None and token[1] != expected):
            raise ExpressionError(f"Expected {expected or 'more input'} in expression '{self.text}'")
        self.position += 1
        return token

    def parse(self) -> Node:
        node = self.expression()
        if self.peek() is not None:
            raise ExpressionError(f"Unexpected {self.peek()[1]!r} in expression '{self.text}'")
        return node

    def expression(self) -> Node:
        node = self.primary()
        while (token := self.peek()) and token[1] in {'.', '?.', '[', '?['}:
            self.take()
            safe = token[1].startswith('?')
            if token[1] in {'.', '?.'}:
                name = self.take()
                if name[0] != 'ident':
                    raise ExpressionError(f"Expected a property name after '.' in '{self.text}'")
                node = Node('prop', name[1], base=node, safe=safe)
            else:
                index = self.expression()
                self.take(']')
                node = Node('index', base=node, args=[index], safe=safe)
        return node

    def primary(self) -> Node:
        kind, value = self.take()
        if kind == 'number':
            return Node('lit', float(value) if '.' in value else int(value))
        if kind == 'string':
            return Node('lit', value[1:-1].replace("''", "'"))
        if kind == 'ident':
            if value in {'true', 'false'}:
                return Node('lit', value == 'true')
            if value == 'null':
                return Node('lit', None)
            self.take('(')
            args: list[Node] = []
            if self.peek() and self.peek()[1] != ')':
                args.append(self.expression())
                while self.peek() and self.peek()[1] == ',':
                    self.take(',')
                    args.append(self.expression())
            self.take(')')
            return Node('call', value, args=args)
        raise ExpressionError(f"Unexpected {value!r} in expression '{self.text}'")


def parse(text: str) -> Node:
    return _Parser(text).parse()


# -- scope ---------------------------------------------------------------------------------------
@dataclass
class Scope:
    parameters: dict[str, Any]
    variables: dict[str, Any]
    activities: dict[str, dict[str, Any]]  # name -> {'output': ..., 'error': ...}
    pipeline: dict[str, Any]  # RunId, Pipeline, TriggerTime, TriggerType, ...
    now: datetime
    item: Any = _MISSING

    def with_item(self, item: Any) -> 'Scope':
        return Scope(self.parameters, self.variables, self.activities, self.pipeline, self.now, item)


# -- conversions ---------------------------------------------------------------------------------
def type_name(value: Any) -> str:
    if value is None:
        return 'Null'
    if isinstance(value, bool):
        return 'Boolean'
    if isinstance(value, int):
        return 'Integer'
    if isinstance(value, float):
        return 'Float'
    if isinstance(value, str):
        return 'String'
    if isinstance(value, list):
        return 'Array'
    return 'Object'


def to_text(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'True' if value else 'False'
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(',', ':'))
    return str(value)


def _number(value: Any, function: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExpressionError(f"The function '{function}' expects numbers; got {type_name(value)}")
    return value


def _string(value: Any, function: str) -> str:
    if not isinstance(value, str):
        raise ExpressionError(f"The function '{function}' expects a string; got {type_name(value)}")
    return value


def _array(value: Any, function: str) -> list:
    if not isinstance(value, list):
        raise ExpressionError(f"The function '{function}' expects an array; got {type_name(value)}")
    return value


def _equal(a: Any, b: Any) -> bool:
    if type_name(a) in {'Integer', 'Float'} and type_name(b) in {'Integer', 'Float'}:
        return a == b
    if type_name(a) != type_name(b):
        return False
    return a == b


# -- dates ---------------------------------------------------------------------------------------
_DATE = re.compile(r'^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,7}))?)?)?\s*(Z|[+-]00:?00)?$')
MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October',
          'November', 'December']
DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']


def parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    match = _DATE.match(str(value).strip()) if isinstance(value, str) else None
    if not match:
        raise ExpressionError(f"'{value}' is not a valid timestamp; use ISO 8601 such as 2026-03-05T00:00:00Z")
    year, month, day, hour, minute, second, fraction, _ = match.groups()
    micro = int((fraction or '0').ljust(6, '0')[:6])
    try:
        return datetime(int(year), int(month), int(day), int(hour or 0), int(minute or 0), int(second or 0), micro,
                        tzinfo=timezone.utc)
    except ValueError as exc:
        raise ExpressionError(f"'{value}' is not a valid timestamp: {exc}") from exc


_STANDARD_FORMATS = {
    'o': "yyyy-MM-dd'T'HH:mm:ss.fffffffK", 'O': "yyyy-MM-dd'T'HH:mm:ss.fffffffK",
    's': "yyyy-MM-dd'T'HH:mm:ss", 'u': "yyyy-MM-dd HH:mm:ss'Z'",
    'd': 'MM/dd/yyyy', 'D': 'dddd, dd MMMM yyyy', 'R': "ddd, dd MMM yyyy HH:mm:ss 'GMT'",
    'r': "ddd, dd MMM yyyy HH:mm:ss 'GMT'",
}
_FORMAT_TOKEN = re.compile(r"'[^']*'|\"[^\"]*\"|\\.|yyyy|yy|MMMM|MMM|MM|M|dddd|ddd|dd|d|HH|H|hh|h|mm|m|ss|s|f{1,7}|F{1,7}|tt|K|.",
                           re.S)


def format_timestamp(value: datetime, fmt: str = 'o') -> str:
    """.NET date formatting for the specifiers pipelines commonly use (invariant culture, UTC)."""
    if len(fmt) == 1:
        if fmt not in _STANDARD_FORMATS:
            raise ExpressionError(f"Standard date format '{fmt}' is not simulated; use a custom format such as 'yyyy-MM-dd'")
        fmt = _STANDARD_FORMATS[fmt]
    out = []
    for token in _FORMAT_TOKEN.findall(fmt):
        if token[0] in "'\"" and len(token) >= 2:
            out.append(token[1:-1])
        elif token.startswith('\\') and len(token) == 2:
            out.append(token[1])
        elif token == 'yyyy':
            out.append(f"{value.year:04d}")
        elif token == 'yy':
            out.append(f"{value.year % 100:02d}")
        elif token == 'MMMM':
            out.append(MONTHS[value.month - 1])
        elif token == 'MMM':
            out.append(MONTHS[value.month - 1][:3])
        elif token == 'MM':
            out.append(f"{value.month:02d}")
        elif token == 'M':
            out.append(str(value.month))
        elif token == 'dddd':
            out.append(DAYS[value.weekday()])
        elif token == 'ddd':
            out.append(DAYS[value.weekday()][:3])
        elif token == 'dd':
            out.append(f"{value.day:02d}")
        elif token == 'd':
            out.append(str(value.day))
        elif token == 'HH':
            out.append(f"{value.hour:02d}")
        elif token == 'H':
            out.append(str(value.hour))
        elif token == 'hh':
            out.append(f"{(value.hour % 12) or 12:02d}")
        elif token == 'h':
            out.append(str((value.hour % 12) or 12))
        elif token == 'mm':
            out.append(f"{value.minute:02d}")
        elif token == 'm':
            out.append(str(value.minute))
        elif token == 'ss':
            out.append(f"{value.second:02d}")
        elif token == 's':
            out.append(str(value.second))
        elif token[0] in 'fF':
            digits = f"{value.microsecond:06d}0"[:len(token)]
            out.append(digits.rstrip('0') if token[0] == 'F' else digits)
        elif token == 'tt':
            out.append('AM' if value.hour < 12 else 'PM')
        elif token == 'K':
            out.append('Z')
        else:
            out.append(token)
    return ''.join(out)


def _shift(unit: str) -> Callable[..., str]:
    def shifted(stamp: Any, amount: Any, fmt: str = 'o') -> str:
        _number(amount, f'add{unit}')
        moment = parse_timestamp(_string(stamp, f'add{unit}'))
        return format_timestamp(moment + timedelta(**{unit.lower(): amount}), fmt)
    return shifted


# -- functions -----------------------------------------------------------------------------------
def _contains(collection: Any, value: Any) -> bool:
    if isinstance(collection, str):
        return _string(value, 'contains') in collection
    if isinstance(collection, list):
        return any(_equal(item, value) for item in collection)
    if isinstance(collection, dict):
        return _string(value, 'contains') in collection
    raise ExpressionError(f"The function 'contains' expects a string, array or object; got {type_name(collection)}")


def _length(value: Any) -> int:
    if isinstance(value, (str, list)):
        return len(value)
    raise ExpressionError(f"The function 'length' expects a string or an array; got {type_name(value)}")


def _empty(value: Any) -> bool:
    return value is None or (isinstance(value, (str, list, dict)) and len(value) == 0)


def _int(value: Any) -> int:
    if isinstance(value, bool):
        raise ExpressionError("The function 'int' cannot convert a Boolean")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    try:
        return int(str(value).strip())
    except ValueError as exc:
        raise ExpressionError(f"The function 'int' cannot convert '{value}' to an integer") from exc


def _float(value: Any) -> float:
    if isinstance(value, bool):
        raise ExpressionError("The function 'float' cannot convert a Boolean")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ExpressionError(f"The function 'float' cannot convert '{value}' to a number") from exc


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str) and value.strip().lower() in {'true', 'false'}:
        return value.strip().lower() == 'true'
    raise ExpressionError(f"The function 'bool' cannot convert '{value}' to a Boolean")


def _json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ExpressionError(f"The function 'json' received invalid JSON: {exc.msg}") from exc


def _compare(name: str, op: Callable[[Any, Any], bool]) -> Callable[[Any, Any], bool]:
    def compare(a: Any, b: Any) -> bool:
        numbers = all(type_name(v) in {'Integer', 'Float'} for v in (a, b))
        if not numbers and not all(isinstance(v, str) for v in (a, b)):
            raise ExpressionError(f"The function '{name}' compares two numbers or two strings; got "
                                  f"{type_name(a)} and {type_name(b)}")
        return op(a, b)
    return compare


def _div(a: Any, b: Any) -> int | float:
    a, b = _number(a, 'div'), _number(b, 'div')
    if b == 0:
        raise ExpressionError("The function 'div' cannot divide by zero")
    if isinstance(a, int) and isinstance(b, int):
        return int(a / b)  # integer division truncates toward zero
    return a / b


def _mod(a: Any, b: Any) -> int | float:
    a, b = _number(a, 'mod'), _number(b, 'mod')
    if b == 0:
        raise ExpressionError("The function 'mod' cannot divide by zero")
    return math.fmod(a, b) if isinstance(a, float) or isinstance(b, float) else int(math.fmod(a, b))


def _substring(text: Any, start: Any, length: Any = None) -> str:
    text = _string(text, 'substring')
    start = _number(start, 'substring')
    length = len(text) - start if length is None else _number(length, 'substring')
    if start < 0 or length < 0 or start + length > len(text):
        raise ExpressionError("The function 'substring' index and length must refer to a location within the string")
    return text[start:start + length]


def _start_of(unit: str) -> Callable[..., str]:
    def start_of(stamp: Any, fmt: str = 'o') -> str:
        moment = parse_timestamp(_string(stamp, f'startOf{unit}'))
        moment = moment.replace(hour=0, minute=0, second=0, microsecond=0)
        if unit == 'Month':
            moment = moment.replace(day=1)
        return format_timestamp(moment, fmt)
    return start_of


def _union(*collections: Any) -> Any:
    if all(isinstance(c, list) for c in collections):
        out: list = []
        for collection in collections:
            for item in collection:
                if not any(_equal(item, seen) for seen in out):
                    out.append(item)
        return out
    if all(isinstance(c, dict) for c in collections):
        merged: dict = {}
        for collection in collections:
            merged.update(collection)
        return merged
    raise ExpressionError("The function 'union' expects arrays or objects of the same kind")


FUNCTIONS: dict[str, Callable[..., Any]] = {
    'concat': lambda *parts: ''.join(to_text(p) for p in parts),
    'substring': _substring,
    'replace': lambda text, old, new: _string(text, 'replace').replace(_string(old, 'replace'), _string(new, 'replace')),
    'toLower': lambda text: _string(text, 'toLower').lower(),
    'toUpper': lambda text: _string(text, 'toUpper').upper(),
    'trim': lambda text: _string(text, 'trim').strip(),
    'indexOf': lambda text, part: _string(text, 'indexOf').lower().find(_string(part, 'indexOf').lower()),
    'lastIndexOf': lambda text, part: _string(text, 'lastIndexOf').lower().rfind(_string(part, 'lastIndexOf').lower()),
    'startsWith': lambda text, part: _string(text, 'startsWith').lower().startswith(_string(part, 'startsWith').lower()),
    'endsWith': lambda text, part: _string(text, 'endsWith').lower().endswith(_string(part, 'endsWith').lower()),
    'split': lambda text, sep: _string(text, 'split').split(_string(sep, 'split')),
    'contains': _contains,
    'length': _length,
    'empty': _empty,
    'coalesce': lambda *values: next((v for v in values if v is not None), None),
    'string': to_text,
    'int': _int,
    'float': _float,
    'bool': _bool,
    'json': _json,
    'createArray': lambda *items: list(items),
    'first': lambda c: (c[0] if c else None) if isinstance(c, (list, str)) else _array(c, 'first'),
    'last': lambda c: (c[-1] if c else None) if isinstance(c, (list, str)) else _array(c, 'last'),
    'join': lambda items, sep: _string(sep, 'join').join(to_text(i) for i in _array(items, 'join')),
    'union': _union,
    'intersection': lambda a, b: [i for i in _array(a, 'intersection') if any(_equal(i, j) for j in _array(b, 'intersection'))],
    'skip': lambda items, n: _array(items, 'skip')[_number(n, 'skip'):],
    'take': lambda items, n: _array(items, 'take')[:_number(n, 'take')],
    'range': lambda start, count: list(range(_number(start, 'range'), _number(start, 'range') + _number(count, 'range'))),
    'equals': _equal,
    'not': lambda value: not _bool_strict(value, 'not'),
    'greater': _compare('greater', lambda a, b: a > b),
    'greaterOrEquals': _compare('greaterOrEquals', lambda a, b: a >= b),
    'less': _compare('less', lambda a, b: a < b),
    'lessOrEquals': _compare('lessOrEquals', lambda a, b: a <= b),
    'add': lambda a, b: _number(a, 'add') + _number(b, 'add'),
    'sub': lambda a, b: _number(a, 'sub') - _number(b, 'sub'),
    'mul': lambda a, b: _number(a, 'mul') * _number(b, 'mul'),
    'div': _div,
    'mod': _mod,
    'min': lambda *v: min(_number(x, 'min') for x in (v[0] if len(v) == 1 and isinstance(v[0], list) else v)),
    'max': lambda *v: max(_number(x, 'max') for x in (v[0] if len(v) == 1 and isinstance(v[0], list) else v)),
    'formatDateTime': lambda stamp, fmt='o': format_timestamp(parse_timestamp(_string(stamp, 'formatDateTime')), fmt),
    'addDays': _shift('Days'),
    'addHours': _shift('Hours'),
    'addMinutes': _shift('Minutes'),
    'addSeconds': _shift('Seconds'),
    'startOfDay': _start_of('Day'),
    'startOfMonth': _start_of('Month'),
    'dayOfWeek': lambda stamp: (parse_timestamp(_string(stamp, 'dayOfWeek')).weekday() + 1) % 7,
    'dayOfMonth': lambda stamp: parse_timestamp(_string(stamp, 'dayOfMonth')).day,
    'dayOfYear': lambda stamp: parse_timestamp(_string(stamp, 'dayOfYear')).timetuple().tm_yday,
}
LAZY = {'if', 'and', 'or'}
SCOPE_FUNCTIONS = {'pipeline', 'variables', 'activity', 'item', 'utcNow'}
UNSUPPORTED = {
    'trigger': "trigger() outputs are not simulated; pass trigger values as pipeline parameters",
    'dataset': "dataset() parameters are not simulated",
    'linkedService': "linkedService() parameters are not simulated",
    'guid': "guid() is random; the simulator keeps runs deterministic",
    'rand': "rand() is random; the simulator keeps runs deterministic",
    'convertTimeZone': "time zones other than UTC are not simulated",
    'convertFromUtc': "time zones other than UTC are not simulated",
}


def _bool_strict(value: Any, function: str) -> bool:
    if not isinstance(value, bool):
        raise ExpressionError(f"The function '{function}' expects a Boolean; got {type_name(value)}")
    return value


def _evaluate(node: Node, scope: Scope, source: str) -> Any:
    if node.kind == 'lit':
        return node.value
    if node.kind == 'prop':
        base = _evaluate(node.base, scope, source)
        if base is None and node.safe:
            return None
        if not isinstance(base, dict):
            raise ExpressionError(f"The expression '{source}' cannot be evaluated: property '{node.value}' is read "
                                  f"on a {type_name(base)}")
        if node.value in base:
            return base[node.value]
        folded = {k.lower(): k for k in base}
        if node.value.lower() in folded:
            return base[folded[node.value.lower()]]
        if node.safe:
            return None
        available = ', '.join(sorted(base)) or 'none'
        raise ExpressionError(f"The expression '{source}' cannot be evaluated because property '{node.value}' "
                              f"doesn't exist, available properties are '{available}'")
    if node.kind == 'index':
        base = _evaluate(node.base, scope, source)
        key = _evaluate(node.args[0], scope, source)
        if base is None and node.safe:
            return None
        if isinstance(base, list) and isinstance(key, int) and not isinstance(key, bool):
            if 0 <= key < len(base):
                return base[key]
            raise ExpressionError(f"The expression '{source}' cannot be evaluated: index {key} is out of range")
        if isinstance(base, dict) and isinstance(key, str):
            return _evaluate(Node('prop', key, base=Node('lit', base), safe=node.safe), scope, source)
        raise ExpressionError(f"The expression '{source}' cannot index a {type_name(base)} with {type_name(key)}")
    name = node.value
    if name in LAZY:
        if name == 'if':
            if len(node.args) != 3:
                raise ExpressionError("The function 'if' takes a condition and two values")
            condition = _bool_strict(_evaluate(node.args[0], scope, source), 'if')
            return _evaluate(node.args[1 if condition else 2], scope, source)
        if len(node.args) < 2:
            raise ExpressionError(f"The function '{name}' takes at least two conditions")
        for arg in node.args:
            value = _bool_strict(_evaluate(arg, scope, source), name)
            if name == 'and' and not value:
                return False
            if name == 'or' and value:
                return True
        return name == 'and'
    if name in UNSUPPORTED:
        raise ExpressionError(UNSUPPORTED[name])
    args = [_evaluate(arg, scope, source) for arg in node.args]
    if name == 'pipeline':
        return {'parameters': scope.parameters, **scope.pipeline}
    if name == 'variables':
        variable = _string(args[0] if args else None, 'variables')
        if variable not in scope.variables:
            raise ExpressionError(f"The variable '{variable}' is not declared in this pipeline")
        return scope.variables[variable]
    if name == 'activity':
        activity = _string(args[0] if args else None, 'activity')
        if activity not in scope.activities:
            raise ExpressionError(f"The output of activity '{activity}' is not available here: it has not run "
                                  "before this point of the pipeline")
        return scope.activities[activity]
    if name == 'item':
        if scope.item is _MISSING:
            raise ExpressionError("item() is only available inside a ForEach activity")
        return scope.item
    if name == 'utcNow':
        return format_timestamp(scope.now, args[0] if args else 'o')
    function = FUNCTIONS.get(name)
    if function is None:
        raise ExpressionError(f"The template function '{name}' is not simulated")
    try:
        return function(*args)
    except TypeError as exc:
        raise ExpressionError(f"Wrong number of arguments for '{name}'") from exc


def evaluate(text: str, scope: Scope) -> Any:
    """Evaluate one expression body (the text after '@')."""
    return _evaluate(parse(text), scope, text)


_INTERPOLATION = re.compile(r'@\{((?:[^{}\']|\'(?:\'\'|[^\'])*\')*)\}')


def evaluate_string(text: str, scope: Scope) -> Any:
    """A JSON string value: literal, '@expression', '@@literal' or text with '@{...}' interpolation."""
    if text.startswith('@@'):
        return text[1:]
    if '@{' in text:
        return _INTERPOLATION.sub(lambda m: to_text(evaluate(m.group(1), scope)), text)
    if text.startswith('@'):
        return evaluate(text[1:], scope)
    return text


def is_expression_object(value: Any) -> bool:
    return isinstance(value, dict) and value.get('type') == 'Expression' and 'value' in value and set(value) <= {'value', 'type'}


def resolve(value: Any, scope: Scope) -> Any:
    """Resolve dynamic content anywhere in a JSON value (typeProperties, parameters, ...)."""
    if is_expression_object(value):
        return evaluate_string(str(value['value']), scope)
    if isinstance(value, dict):
        return {key: resolve(item, scope) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve(item, scope) for item in value]
    if isinstance(value, str):
        return evaluate_string(value, scope)
    return value


def references(value: Any) -> dict[str, set[str]]:
    """Static references in dynamic content: activities, variables and parameters named with literals."""
    found = {'activity': set(), 'variables': set(), 'parameters': set(), 'item': set()}

    def walk(node: Node) -> None:
        if node.kind == 'call':
            if node.value in {'activity', 'variables'} and node.args and node.args[0].kind == 'lit':
                found[node.value].add(str(node.args[0].value))
            if node.value == 'item':
                found['item'].add('item')
        if node.kind == 'prop' and node.base is not None and node.base.kind == 'prop' and node.base.value == 'parameters' \
                and node.base.base is not None and node.base.base.kind == 'call' and node.base.base.value == 'pipeline':
            found['parameters'].add(node.value)
        for child in [node.base, *node.args]:
            if child is not None:
                walk(child)

    def expressions_in(text: str) -> list[str]:
        if text.startswith('@@'):
            return []
        if '@{' in text:
            return [m.group(1) for m in _INTERPOLATION.finditer(text)]
        return [text[1:]] if text.startswith('@') else []

    def visit(item: Any) -> None:
        if is_expression_object(item):
            item = str(item['value'])
        if isinstance(item, dict):
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)
        elif isinstance(item, str):
            for body in expressions_in(item):
                walk(parse(body))

    visit(value)
    return found
