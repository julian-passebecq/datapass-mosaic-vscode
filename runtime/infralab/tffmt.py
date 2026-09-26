"""`terraform fmt` rules for the Infra Lab: what the canonical layout of a .tf file is, so `terraform fmt -check`
can list the files that differ and `-diff` can show how.

The lab never rewrites the learner's files: `terraform fmt` without `-check` is refused and the learner applies the
layout in the editor. The rules follow HashiCorp's hclwrite formatter for a documented subset:

- indentation: two spaces per open `{`, `[` or `(`; a line that starts with closing brackets is dedented;
- the `=` of consecutive single-line arguments is aligned (one space after the longest name); a blank line, a
  comment-only line, a block header, a closing bracket or an argument whose value opens a multi-line bracket ends
  the group; trailing comments of consecutive lines are aligned the same way;
- one space around `=` and `=>`, after a comma and inside single-line braces (`{ a = 1 }`); no space before a comma,
  after `(` or `[`, or before `)` or `]`; runs of spaces become one; no trailing whitespace;
- a block header is `type "label" "label" {` with single spaces.

Not covered (left as written): spacing around other operators, heredoc bodies and `/* */` comments.
"""
from __future__ import annotations

from dataclasses import dataclass
import difflib
import re

OPEN, CLOSE = '{[(', '}])'
HEREDOC = re.compile(r'<<-?([A-Za-z_][A-Za-z0-9_]*)\s*$')
HEADER = re.compile(r'^([A-Za-z_][\w-]*)((?:\s+(?:"(?:[^"\\]|\\.)*"|[A-Za-z_][\w-]*))*)\s*\{\s*(\}?)$')
LABEL = re.compile(r'"(?:[^"\\]|\\.)*"|[A-Za-z_][\w-]*')


def _skip_string(text: str, i: int) -> int:
    """Index after the string literal that starts at text[i] == '"' (interpolations included)."""
    i += 1
    n = len(text)
    while i < n:
        c = text[i]
        if c == '\\':
            i += 2
            continue
        if c == '"':
            return i + 1
        if text.startswith('$${', i) or text.startswith('%%{', i):
            i += 3
            continue
        if text.startswith('${', i) or text.startswith('%{', i):
            depth = 1
            i += 2
            while i < n and depth:
                if text[i] == '"':
                    i = _skip_string(text, i)
                    continue
                depth += {'{': 1, '}': -1}.get(text[i], 0)
                i += 1
            continue
        i += 1
    return n


@dataclass
class Line:
    code: str                 # the line without its indentation and trailing comment, spacing normalized
    comment: str | None       # a trailing comment (after code)
    net: int                  # brackets opened minus closed
    closers: int              # closing brackets the line starts with
    eq: int | None            # index in `code` of the top-level '=' of an argument
    heredoc: str | None       # marker of a heredoc the line opens
    block_comment: bool       # the line opens a /* comment that does not close on it


def _normalize(code: str) -> str:
    """Spacing between tokens (strings kept as written)."""
    out: list[str] = []
    i, n = 0, len(code)
    pending_space = False

    def last() -> str:
        return out[-1][-1] if out and out[-1] else ''

    while i < n:
        c = code[i]
        if c in ' \t':
            pending_space = True
            i += 1
            continue
        if c == '"':
            end = _skip_string(code, i)
            token = code[i:end]
            i = end
        elif code.startswith('=>', i) or code.startswith('==', i) or code.startswith('!=', i) or \
                code.startswith('<=', i) or code.startswith('>=', i) or code.startswith('&&', i) or \
                code.startswith('||', i) or code.startswith('...', i):
            token = code[i:i + (3 if code.startswith('...', i) else 2)]
            i += len(token)
        else:
            token = c
            i += 1
        prev = last()
        if token in (',', ')', ']', '...'):
            space = False
        elif prev in ('(', '['):
            space = False
        elif token in ('=', '=>') or prev in (',',) or (out and out[-1] in ('=', '=>')):
            space = bool(out)
        elif token == '}' and prev != '{':
            space = True
        elif prev == '{' and token != '}':
            space = True
        else:
            space = pending_space
        if space and out:
            out.append(' ')
        out.append(token)
        pending_space = False
    return ''.join(out)


def _scan(text: str) -> Line:
    stripped = text.strip()
    i, n = 0, len(stripped)
    net = closers = 0
    level = 0
    seen = False
    eq = None
    comment_at = None
    heredoc = None
    block_comment = False
    while i < n:
        c = stripped[i]
        if c in ' \t':
            i += 1
            continue
        if c == '#' or stripped.startswith('//', i):
            comment_at = i
            break
        if stripped.startswith('/*', i):
            end = stripped.find('*/', i + 2)
            if end < 0:
                block_comment = True
                break
            i = end + 2
            continue
        if c == '"':
            i = _skip_string(stripped, i)
            seen = True
            continue
        if stripped.startswith('<<', i):
            match = HEREDOC.match(stripped[i:])
            if match:
                heredoc = match.group(1)
                break
        if c in OPEN:
            net += 1
            level += 1
            seen = True
        elif c in CLOSE:
            net -= 1
            level -= 1
            if not seen:
                closers += 1
        else:
            if c == '=' and eq is None and level == 0 and seen and closers == 0:
                before = stripped[i - 1] if i else ''
                after = stripped[i + 1] if i + 1 < n else ''
                if after not in '=>' and before not in '=!<>':
                    eq = i
            seen = True
        i += 1
    code_text = stripped[:comment_at].rstrip() if comment_at is not None else stripped
    comment = stripped[comment_at:].rstrip() if comment_at is not None and code_text else None
    if comment_at is not None and not code_text:
        code_text = stripped.rstrip()     # a comment-only line stays as written
        return Line(code_text, None, 0, 0, None, None, False)
    if block_comment or heredoc:
        code = code_text
        eq_at = None
        if eq is not None:
            name, value = code[:eq].rstrip(), code[eq + 1:].strip()
            code = f'{_normalize(name)} = {value}'
            eq_at = len(_normalize(name)) + 1
        return Line(code, comment, net, closers, eq_at, heredoc, block_comment)
    if eq is not None:
        name, value = code_text[:eq], code_text[eq + 1:]
        norm_name = _normalize(name)
        code = f'{norm_name} = {_normalize(value)}'.rstrip()
        eq_at = len(norm_name) + 1
    else:
        header = HEADER.match(code_text)
        if header and header.group(1) not in ('for', 'if'):
            labels = ' '.join(LABEL.findall(header.group(2)))
            code = f'{header.group(1)} ' + (labels + ' ' if labels else '') + '{' + ('}' if header.group(3) else '')
        else:
            code = _normalize(code_text)
        eq_at = None
    return Line(code, comment, net, closers, eq_at, None, False)


def format_text(text: str) -> str:
    """The file as `terraform fmt` would lay it out (for the rules above)."""
    raw = text.split('\n')
    out: list[str | None] = []
    cells: list[Line | None] = []      # the scanned line, or None where a line takes no part in alignment
    depth = 0
    in_heredoc: str | None = None
    in_comment = False
    for text_line in raw:
        if in_heredoc is not None:
            out.append(text_line)
            cells.append('transparent')  # type: ignore[arg-type]
            if text_line.strip() == in_heredoc:
                in_heredoc = None
            continue
        if in_comment:
            out.append(text_line.rstrip())
            cells.append(None)
            if '*/' in text_line:
                in_comment = False
            continue
        if not text_line.strip():
            out.append('')
            cells.append(None)
            continue
        line = _scan(text_line)
        indent = '  ' * max(0, depth - line.closers)
        depth = max(0, depth + line.net)
        out.append(indent + line.code)
        cells.append(line)
        if line.heredoc:
            in_heredoc = line.heredoc
        if line.block_comment:
            in_comment = True
    # Align the '=' of chains of single-line arguments.
    chain: list[int] = []

    def close_assign() -> None:
        if chain:
            width = max(out[j].index(cells[j].code) + cells[j].eq for j in chain)  # type: ignore[union-attr]
            for j in chain:
                line = cells[j]
                indent = out[j][:out[j].index(line.code)]  # type: ignore[union-attr]
                name = line.code[:line.eq].rstrip()  # type: ignore[union-attr,index]
                rest = line.code[line.eq + 1:]  # type: ignore[union-attr,index]
                padded = (indent + name).ljust(width - 1) + ' =' + rest
                out[j] = padded
            chain.clear()

    for index, line in enumerate(cells):
        if line == 'transparent':
            continue
        if isinstance(line, Line) and line.eq is not None and line.net == 0:
            chain.append(index)
        else:
            close_assign()
    close_assign()
    # Trailing comments: aligned over consecutive lines that have one.
    group: list[int] = []

    def close_comments() -> None:
        if group:
            width = max(len(out[j]) for j in group)
            for j in group:
                out[j] = out[j].ljust(width) + ' ' + cells[j].comment  # type: ignore[union-attr,operator]
            group.clear()

    for index, line in enumerate(cells):
        if line == 'transparent':
            continue
        if isinstance(line, Line) and line.comment:
            group.append(index)
        else:
            close_comments()
    close_comments()
    return '\n'.join(o.rstrip() if isinstance(o, str) and not isinstance(cells[k], str) else o
                     for k, o in enumerate(out))


def unified_diff(name: str, before: str, after: str) -> str:
    lines = difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                                 fromfile=f'old/{name}', tofile=f'new/{name}')
    return ''.join(line if line.endswith('\n') else line + '\n' for line in lines)
