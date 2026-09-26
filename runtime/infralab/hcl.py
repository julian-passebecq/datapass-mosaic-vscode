"""A bounded reader for the HCL2 subset the Infra Lab's Terraform simulator accepts.

The learner's `.tf` and `.tfvars` files are parsed into a small syntax tree and never executed: there is no eval, no
exec and no import of anything they name. Expressions are evaluated later by `tfexpr.py` over plain values, with a
whitelist of functions. What the reader does not know is refused with the file, line and column.

Supported: blocks with string or identifier labels, attributes, one-line blocks, comments (`#`, `//`, `/* */`),
numbers, strings with `${...}` interpolation and escapes, heredocs (`<<EOT`, `<<-EOT`), tuples, objects, function
calls (with `...` expansion), attribute and index access, splats (`[*]`, `.*`), `for` expressions, conditionals and the
arithmetic, comparison and logical operators. Template directives (`%{if}`, `%{for}`) are refused.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any


class HclError(ValueError):
    def __init__(self, message: str, file: str = '', line: int = 0, col: int = 0):
        self.file, self.line, self.col, self.message = file, line, col, message
        where = f'{file}:{line}:{col}: ' if file else ''
        super().__init__(f'{where}{message}')


# ---- Syntax tree -------------------------------------------------------------------------------------------------


@dataclass
class Node:
    line: int
    col: int


@dataclass
class Literal(Node):
    value: Any


@dataclass
class Template(Node):
    # Strings and expressions, concatenated.
    parts: list


@dataclass
class Var(Node):
    name: str


@dataclass
class GetAttr(Node):
    target: Node
    name: str


@dataclass
class Index(Node):
    target: Node
    key: Node


@dataclass
class Splat(Node):
    target: Node
    # Attribute names applied to each element after the splat.
    names: list[str]


@dataclass
class Call(Node):
    name: str
    args: list[Node]
    expand: bool = False


@dataclass
class TupleExpr(Node):
    items: list[Node]


@dataclass
class ObjectExpr(Node):
    items: list[tuple[Node, Node]]


@dataclass
class ForExpr(Node):
    key_var: str | None
    value_var: str
    collection: Node
    key: Node | None       # set for object results ({for k, v in m : k => v})
    value: Node
    cond: Node | None
    group: bool = False


@dataclass
class Conditional(Node):
    cond: Node
    then: Node
    other: Node


@dataclass
class Unary(Node):
    op: str
    operand: Node


@dataclass
class Binary(Node):
    op: str
    left: Node
    right: Node


@dataclass
class Attribute:
    name: str
    expr: Node
    line: int
    file: str


@dataclass
class Block:
    type: str
    labels: list[str]
    body: 'Body'
    line: int
    file: str


@dataclass
class Body:
    attributes: dict[str, Attribute] = field(default_factory=dict)
    blocks: list[Block] = field(default_factory=list)

    def blocks_of(self, block_type: str) -> list[Block]:
        return [b for b in self.blocks if b.type == block_type]


# ---- Lexer ---------------------------------------------------------------------------------------------------------


@dataclass
class Token:
    kind: str      # ident, number, string, heredoc, op, nl, eof
    value: Any
    line: int
    col: int


OPERATORS = ['...', '=>', '==', '!=', '<=', '>=', '&&', '||', '=', '<', '>', '+', '-', '*', '/', '%', '!', '?', ':',
             '.', ',', '[', ']', '{', '}', '(', ')']
IDENT = re.compile(r'[A-Za-z_][A-Za-z0-9_-]*')
NUMBER = re.compile(r'\d+(\.\d+)?([eE][+-]?\d+)?')
MAX_SOURCE = 400_000


class Lexer:
    def __init__(self, text: str, file: str):
        if len(text) > MAX_SOURCE:
            raise HclError('file is too large for the lab', file)
        self.text, self.file = text.replace('\r\n', '\n'), file
        self.pos, self.line, self.col = 0, 1, 1
        self.tokens: list[Token] = []

    def error(self, message: str) -> HclError:
        return HclError(message, self.file, self.line, self.col)

    def advance(self, n: int = 1) -> None:
        for _ in range(n):
            if self.pos < len(self.text) and self.text[self.pos] == '\n':
                self.line, self.col = self.line + 1, 1
            else:
                self.col += 1
            self.pos += 1

    def add(self, kind: str, value: Any, line: int, col: int) -> None:
        self.tokens.append(Token(kind, value, line, col))

    def run(self) -> list[Token]:
        text = self.text
        while self.pos < len(text):
            ch = text[self.pos]
            if ch in ' \t\r':
                self.advance()
            elif ch == '\n':
                self.add('nl', None, self.line, self.col)
                self.advance()
            elif ch == '#' or text.startswith('//', self.pos):
                while self.pos < len(text) and text[self.pos] != '\n':
                    self.advance()
            elif text.startswith('/*', self.pos):
                end = text.find('*/', self.pos + 2)
                if end < 0:
                    raise self.error('unterminated /* comment')
                self.advance(end + 2 - self.pos)
            elif ch == '"':
                line, col = self.line, self.col
                self.add('string', self.read_string(), line, col)
            elif text.startswith('<<', self.pos) and re.match(r'<<-?[A-Za-z_][A-Za-z0-9_]*\n', text[self.pos:]):
                line, col = self.line, self.col
                self.add('heredoc', self.read_heredoc(), line, col)
            elif ch.isdigit():
                match = NUMBER.match(text, self.pos)
                assert match
                raw = match.group(0)
                value: Any = float(raw) if ('.' in raw or 'e' in raw.lower()) else int(raw)
                self.add('number', value, self.line, self.col)
                self.advance(len(raw))
            elif IDENT.match(text, self.pos):
                match = IDENT.match(text, self.pos)
                assert match
                self.add('ident', match.group(0), self.line, self.col)
                self.advance(len(match.group(0)))
            else:
                for op in OPERATORS:
                    if text.startswith(op, self.pos):
                        self.add('op', op, self.line, self.col)
                        self.advance(len(op))
                        break
                else:
                    raise self.error(f'unexpected character {ch!r}')
        self.add('nl', None, self.line, self.col)
        self.add('eof', None, self.line, self.col)
        return self.tokens

    def read_string(self) -> list:
        """A quoted template: a list of str parts and ('expr', source, line, col) parts."""
        self.advance()  # opening quote
        parts: list = []
        buf: list[str] = []
        text = self.text
        while True:
            if self.pos >= len(text) or text[self.pos] == '\n':
                raise self.error('unterminated string')
            ch = text[self.pos]
            if ch == '"':
                self.advance()
                break
            if ch == '\\':
                nxt = text[self.pos + 1:self.pos + 2]
                mapping = {'n': '\n', 't': '\t', 'r': '\r', '"': '"', '\\': '\\'}
                if nxt in mapping:
                    buf.append(mapping[nxt])
                    self.advance(2)
                    continue
                if nxt == 'u' and re.fullmatch(r'[0-9a-fA-F]{4}', text[self.pos + 2:self.pos + 6]):
                    buf.append(chr(int(text[self.pos + 2:self.pos + 6], 16)))
                    self.advance(6)
                    continue
                raise self.error(f'unknown escape \\{nxt}')
            if text.startswith('$${', self.pos) or text.startswith('%%{', self.pos):
                buf.append(text[self.pos + 1:self.pos + 3])
                self.advance(3)
                continue
            if text.startswith('%{', self.pos):
                raise self.error('template directives (%{if}, %{for}) are not supported in this lab')
            if text.startswith('${', self.pos):
                if buf:
                    parts.append(''.join(buf))
                    buf = []
                parts.append(self.read_interpolation())
                continue
            buf.append(ch)
            self.advance()
        if buf or not parts:
            parts.append(''.join(buf))
        return parts

    def read_interpolation(self) -> tuple:
        line, col = self.line, self.col + 2
        self.advance(2)
        start, depth = self.pos, 1
        text = self.text
        in_string = False
        while self.pos < len(text):
            ch = text[self.pos]
            if in_string:
                if ch == '\\':
                    self.advance(2)
                    continue
                if ch == '"':
                    in_string = False
            elif ch == '"':
                in_string = True
            elif ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    source = text[start:self.pos]
                    self.advance()
                    return ('expr', source.strip().removeprefix('~').removesuffix('~'), line, col)
            elif ch == '\n' and not in_string:
                pass
            self.advance()
        raise self.error('unterminated ${ interpolation')

    def read_heredoc(self) -> list:
        match = re.match(r'<<(-?)([A-Za-z_][A-Za-z0-9_]*)\n', self.text[self.pos:])
        assert match
        indent, marker = match.group(1) == '-', match.group(2)
        self.advance(len(match.group(0)))
        lines: list[str] = []
        while True:
            if self.pos >= len(self.text):
                raise self.error(f'heredoc {marker} is never closed')
            end = self.text.find('\n', self.pos)
            end = len(self.text) if end < 0 else end
            line = self.text[self.pos:end]
            self.advance(end - self.pos)
            if line.strip() == marker:
                break
            lines.append(line)
            self.advance()  # newline
        if indent:
            widths = [len(l) - len(l.lstrip(' ')) for l in lines if l.strip()]
            cut = min(widths) if widths else 0
            lines = [l[cut:] for l in lines]
        body = '\n'.join(lines) + ('\n' if lines else '')
        if '%{' in body.replace('%%{', ''):
            raise self.error('template directives (%{if}, %{for}) are not supported in this lab')
        # Heredocs interpolate like quoted strings.
        parts: list = []
        pos = 0
        for found in re.finditer(r'(?<!\$)\$\{', body):
            depth, i = 1, found.end()
            while i < len(body) and depth:
                depth += {'{': 1, '}': -1}.get(body[i], 0)
                i += 1
            if depth:
                raise self.error('unterminated ${ interpolation in heredoc')
            if found.start() > pos:
                parts.append(body[pos:found.start()].replace('$${', '${'))
            parts.append(('expr', body[found.end():i - 1].strip(), self.line, 1))
            pos = i
        if pos < len(body) or not parts:
            parts.append(body[pos:].replace('$${', '${'))
        return parts


# ---- Parser --------------------------------------------------------------------------------------------------------

PRECEDENCE = [('||',), ('&&',), ('==', '!='), ('<', '>', '<=', '>='), ('+', '-'), ('*', '/', '%')]
MAX_DEPTH = 60


class Parser:
    def __init__(self, tokens: list[Token], file: str):
        self.tokens, self.file, self.i = tokens, file, 0
        self.depth = 0
        # Newlines are insignificant inside brackets and parentheses.
        self.nesting = 0

    # -- token helpers
    def peek(self, offset: int = 0) -> Token:
        j = self.i
        seen = 0
        while True:
            tok = self.tokens[j]
            if tok.kind == 'nl' and self.nesting:
                j += 1
                continue
            if seen == offset:
                return tok
            seen += 1
            j += 1

    def next(self) -> Token:
        while self.tokens[self.i].kind == 'nl' and self.nesting:
            self.i += 1
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def error(self, message: str, tok: Token | None = None) -> HclError:
        tok = tok or self.peek()
        return HclError(message, self.file, tok.line, tok.col)

    def expect_op(self, op: str) -> Token:
        tok = self.next()
        if tok.kind != 'op' or tok.value != op:
            raise self.error(f'expected {op!r}, found {describe(tok)}', tok)
        return tok

    def at_op(self, op: str) -> bool:
        tok = self.peek()
        return tok.kind == 'op' and tok.value == op

    def skip_newlines(self) -> None:
        while self.tokens[self.i].kind == 'nl':
            self.i += 1

    # -- bodies
    def parse_file(self) -> Body:
        body = self.parse_body(top=True)
        if self.peek().kind != 'eof':
            raise self.error(f'unexpected {describe(self.peek())}')
        return body

    def parse_body(self, top: bool = False) -> Body:
        body = Body()
        saved, self.nesting = self.nesting, 0
        try:
            while True:
                self.skip_newlines()
                tok = self.tokens[self.i]
                if tok.kind == 'eof':
                    if not top:
                        raise self.error('a block is never closed with }', tok)
                    return body
                if tok.kind == 'op' and tok.value == '}':
                    if top:
                        raise self.error('unexpected }', tok)
                    return body
                if tok.kind != 'ident':
                    raise self.error(f'expected an attribute or a block, found {describe(tok)}', tok)
                self.i += 1
                after = self.tokens[self.i]
                if after.kind == 'op' and after.value == '=':
                    self.i += 1
                    if tok.value in body.attributes:
                        raise self.error(f'attribute {tok.value!r} is set twice', tok)
                    expr = self.parse_expr()
                    body.attributes[tok.value] = Attribute(tok.value, expr, tok.line, self.file)
                    end = self.tokens[self.i]
                    if end.kind == 'nl':
                        self.i += 1
                    elif not (end.kind == 'op' and end.value == '}') and end.kind != 'eof':
                        raise self.error(f'expected a new line after the value of {tok.value}, found {describe(end)}', end)
                    continue
                labels: list[str] = []
                while True:
                    lab = self.tokens[self.i]
                    if lab.kind == 'string':
                        if len(lab.value) != 1 or not isinstance(lab.value[0], str):
                            raise self.error('block labels cannot use interpolation', lab)
                        labels.append(lab.value[0])
                        self.i += 1
                    elif lab.kind == 'ident':
                        labels.append(lab.value)
                        self.i += 1
                    else:
                        break
                brace = self.tokens[self.i]
                if not (brace.kind == 'op' and brace.value == '{'):
                    raise self.error(f'expected = or {{ after {tok.value!r}, found {describe(brace)}', brace)
                self.i += 1
                self.depth += 1
                if self.depth > MAX_DEPTH:
                    raise self.error('blocks are nested too deeply', brace)
                inner = self.parse_body()
                self.depth -= 1
                self.i += 1  # }
                body.blocks.append(Block(tok.value, labels, inner, tok.line, self.file))
                end = self.tokens[self.i]
                if end.kind == 'nl':
                    self.i += 1
                elif not (end.kind == 'op' and end.value == '}') and end.kind != 'eof':
                    raise self.error(f'expected a new line after the {tok.value} block', end)
        finally:
            self.nesting = saved

    # -- expressions
    def parse_expr(self) -> Node:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise self.error('expression is nested too deeply')
        try:
            cond = self.parse_binary(0)
            if self.at_op('?'):
                tok = self.next()
                then = self.parse_expr()
                self.expect_op(':')
                other = self.parse_expr()
                return Conditional(tok.line, tok.col, cond, then, other)
            return cond
        finally:
            self.depth -= 1

    def parse_binary(self, level: int) -> Node:
        if level == len(PRECEDENCE):
            return self.parse_unary()
        left = self.parse_binary(level + 1)
        while True:
            tok = self.peek()
            if tok.kind == 'op' and tok.value in PRECEDENCE[level]:
                self.next()
                right = self.parse_binary(level + 1)
                left = Binary(tok.line, tok.col, tok.value, left, right)
            else:
                return left

    def parse_unary(self) -> Node:
        tok = self.peek()
        if tok.kind == 'op' and tok.value in ('!', '-'):
            self.next()
            return Unary(tok.line, tok.col, tok.value, self.parse_unary())
        return self.parse_postfix(self.parse_primary())

    def parse_postfix(self, node: Node) -> Node:
        while True:
            tok = self.peek()
            if tok.kind == 'op' and tok.value == '.':
                self.next()
                name = self.next()
                if name.kind == 'op' and name.value == '*':
                    node = Splat(tok.line, tok.col, node, self.splat_names())
                elif name.kind == 'ident':
                    node = GetAttr(tok.line, tok.col, node, name.value)
                elif name.kind == 'number' and isinstance(name.value, int):
                    node = Index(tok.line, tok.col, node, Literal(name.line, name.col, name.value))
                else:
                    raise self.error(f'expected an attribute name after ., found {describe(name)}', name)
            elif tok.kind == 'op' and tok.value == '[':
                self.next()
                self.nesting += 1
                if self.at_op('*'):
                    self.next()
                    self.expect_op(']')
                    self.nesting -= 1
                    node = Splat(tok.line, tok.col, node, self.splat_names())
                    continue
                key = self.parse_expr()
                self.expect_op(']')
                self.nesting -= 1
                node = Index(tok.line, tok.col, node, key)
            else:
                return node

    def splat_names(self) -> list[str]:
        names = []
        while self.at_op('.') and self.peek(1).kind == 'ident':
            self.next()
            names.append(self.next().value)
        return names

    def parse_primary(self) -> Node:
        tok = self.next()
        if tok.kind == 'number':
            return Literal(tok.line, tok.col, tok.value)
        if tok.kind in ('string', 'heredoc'):
            return self.template(tok)
        if tok.kind == 'ident':
            if tok.value in ('true', 'false'):
                return Literal(tok.line, tok.col, tok.value == 'true')
            if tok.value == 'null':
                return Literal(tok.line, tok.col, None)
            if self.at_op('(') and self.tokens[self.i].kind == 'op':
                return self.call(tok)
            return Var(tok.line, tok.col, tok.value)
        if tok.kind == 'op' and tok.value == '(':
            self.nesting += 1
            inner = self.parse_expr()
            self.expect_op(')')
            self.nesting -= 1
            return inner
        if tok.kind == 'op' and tok.value == '[':
            return self.tuple_or_for(tok)
        if tok.kind == 'op' and tok.value == '{':
            return self.object_or_for(tok)
        raise self.error(f'expected a value, found {describe(tok)}', tok)

    def call(self, name: Token) -> Node:
        self.expect_op('(')
        self.nesting += 1
        args: list[Node] = []
        expand = False
        while not self.at_op(')'):
            args.append(self.parse_expr())
            if self.at_op('...'):
                self.next()
                expand = True
                break
            if not self.at_op(')'):
                self.expect_op(',')
        self.expect_op(')')
        self.nesting -= 1
        return Call(name.line, name.col, name.value, args, expand)

    def tuple_or_for(self, open_tok: Token) -> Node:
        self.nesting += 1
        if self.peek().kind == 'ident' and self.peek().value == 'for':
            node = self.for_expr(open_tok, ']')
            self.nesting -= 1
            return node
        items: list[Node] = []
        while not self.at_op(']'):
            items.append(self.parse_expr())
            if not self.at_op(']'):
                self.expect_op(',')
        self.expect_op(']')
        self.nesting -= 1
        return TupleExpr(open_tok.line, open_tok.col, items)

    def object_or_for(self, open_tok: Token) -> Node:
        self.nesting += 1
        if self.peek().kind == 'ident' and self.peek().value == 'for':
            node = self.for_expr(open_tok, '}')
            self.nesting -= 1
            return node
        items: list[tuple[Node, Node]] = []
        while not self.at_op('}'):
            key_tok = self.peek()
            if key_tok.kind == 'ident' and self.peek(1).kind == 'op' and self.peek(1).value in ('=', ':'):
                self.next()
                key: Node = Literal(key_tok.line, key_tok.col, key_tok.value)
            else:
                key = self.parse_expr()
            sep = self.next()
            if sep.kind != 'op' or sep.value not in ('=', ':'):
                raise self.error(f'expected = or : in an object, found {describe(sep)}', sep)
            items.append((key, self.parse_expr()))
            if self.at_op(','):
                self.next()
        self.expect_op('}')
        self.nesting -= 1
        return ObjectExpr(open_tok.line, open_tok.col, items)

    def for_expr(self, open_tok: Token, close: str) -> Node:
        self.next()  # for
        first = self.next()
        if first.kind != 'ident':
            raise self.error('expected a variable name after for', first)
        key_var, value_var = None, first.value
        if self.at_op(','):
            self.next()
            second = self.next()
            if second.kind != 'ident':
                raise self.error('expected a second variable name', second)
            key_var, value_var = first.value, second.value
        in_tok = self.next()
        if in_tok.kind != 'ident' or in_tok.value != 'in':
            raise self.error('expected in', in_tok)
        collection = self.parse_expr()
        self.expect_op(':')
        key = None
        value = self.parse_expr()
        group = False
        if close == '}':
            self.expect_op('=>')
            key, value = value, self.parse_expr()
            if self.at_op('...'):
                self.next()
                group = True
        cond = None
        if self.peek().kind == 'ident' and self.peek().value == 'if':
            self.next()
            cond = self.parse_expr()
        self.expect_op(close)
        return ForExpr(open_tok.line, open_tok.col, key_var, value_var, collection, key, value, cond, group)

    def template(self, tok: Token) -> Node:
        parts: list = []
        for part in tok.value:
            if isinstance(part, str):
                parts.append(part)
            else:
                _, source, line, col = part
                parts.append(parse_expression(source, self.file, line, col))
        if len(parts) == 1 and isinstance(parts[0], str):
            return Literal(tok.line, tok.col, parts[0])
        return Template(tok.line, tok.col, parts)


def describe(tok: Token) -> str:
    if tok.kind == 'eof':
        return 'the end of the file'
    if tok.kind == 'nl':
        return 'a new line'
    if tok.kind in ('string', 'heredoc'):
        return 'a string'
    return repr(tok.value)


def parse(text: str, file: str = '') -> Body:
    return Parser(Lexer(text, file).run(), file).parse_file()


def parse_expression(source: str, file: str = '', line: int = 1, col: int = 1) -> Node:
    tokens = Lexer(source, file).run()
    for tok in tokens:
        tok.line += line - 1
        if tok.line == line:
            tok.col += col - 1
    parser = Parser(tokens, file)
    parser.nesting = 1
    expr = parser.parse_expr()
    if parser.peek().kind != 'eof':
        raise parser.error(f'unexpected {describe(parser.peek())} in expression')
    return expr
