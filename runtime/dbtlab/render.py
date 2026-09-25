"""dbt-flavoured Jinja, rendered in jinja2's sandbox: templates cannot reach Python objects, files or modules.

The context is dbt's for the documented subset: ref, source, config, var, this, is_incremental, target,
run_started_at, return, exceptions.raise_compiler_error, log, and the project's own macros. Anything else
(packages such as dbt_utils, env_var, run_query, adapter calls) fails the node with a clear message instead of
being approximated.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from jinja2 import StrictUndefined, TemplateSyntaxError, UndefinedError
from jinja2.exceptions import SecurityError
from jinja2.sandbox import SandboxedEnvironment

MACRO_BLOCK = re.compile(r'{%-?\s*macro\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(', re.S)


class RenderError(ValueError):
    pass


class _Return(Exception):
    def __init__(self, value: Any):
        super().__init__()
        self.value = value


@dataclass(frozen=True)
class Relation:
    """What {{ ref() }}, {{ source() }} and {{ this }} render to: schema.identifier (or an ephemeral CTE name)."""
    schema: str
    identifier: str
    cte: bool = False

    def __str__(self) -> str:
        return self.identifier if self.cte else f'{self.schema}.{self.identifier}'

    @property
    def name(self) -> str:
        return self.identifier

    @property
    def table(self) -> str:
        return self.identifier


@dataclass
class Target:
    name: str = 'dev'
    schema: str = 'silver'
    type: str = 'duckdb'
    profile_name: str = 'datapass'
    threads: int = 1


class _Exceptions:
    @staticmethod
    def raise_compiler_error(message: str) -> None:
        raise RenderError(f'Compilation Error: {message}')

    @staticmethod
    def warn(message: str) -> str:
        return ''


@dataclass
class Hooks:
    """Callbacks the engine gives a render: resolve refs and sources, record config() calls."""
    ref: Callable[..., Relation]
    source: Callable[[str, str], Relation]
    config: Callable[..., str] = lambda **kwargs: ''
    this: Relation | None = None
    incremental: bool = False
    variables: dict[str, Any] = field(default_factory=dict)
    run_started_at: str = '2026-01-01 00:00:00'


class _Unsupported:
    def __init__(self, name: str, hint: str):
        self._name, self._hint = name, hint

    def __getattr__(self, attribute: str):
        raise RenderError(f'{self._name}.{attribute} is not available in the Datapass dbt emulation. {self._hint}')

    def __call__(self, *args, **kwargs):
        raise RenderError(f'{self._name}() is not available in the Datapass dbt emulation. {self._hint}')


class Renderer:
    def __init__(self, macros: list[tuple[str, str]], target: Target):
        self.env = SandboxedEnvironment(undefined=StrictUndefined, extensions=['jinja2.ext.do'],
                                        trim_blocks=False, lstrip_blocks=False, autoescape=False)
        self.target = target
        self.macro_sources = macros
        self.macro_names: list[str] = []
        for path, text in macros:
            self.macro_names += MACRO_BLOCK.findall(text)
        self._hooks: Hooks | None = None
        self._modules: list[Any] = []

    def has_macro(self, name: str) -> bool:
        return name in self.macro_names

    def _context(self, hooks: Hooks) -> dict[str, Any]:
        def var(name: str, default: Any = None):
            if name in hooks.variables:
                return hooks.variables[name]
            if default is None:
                raise RenderError(f"Required var '{name}' not found in dbt_project.yml vars or --vars")
            return default

        def return_(value: Any):
            raise _Return(value)

        def env_var(name: str, default: Any = None):
            raise RenderError('env_var() is not available in the Datapass dbt emulation: put the value in vars.')

        context: dict[str, Any] = {
            'ref': hooks.ref, 'source': hooks.source, 'config': hooks.config, 'var': var, 'this': hooks.this,
            'is_incremental': lambda: hooks.incremental, 'target': self.target, 'return': return_,
            'run_started_at': hooks.run_started_at, 'invocation_id': '00000000-0000-0000-0000-000000000000',
            'exceptions': _Exceptions(), 'log': lambda *args, **kwargs: '', 'env_var': env_var,
            'adapter': _Unsupported('adapter', 'Write the SQL directly.'),
            'run_query': _Unsupported('run_query', 'Queries at compile time are not emulated.'),
            'dbt_utils': _Unsupported('dbt_utils', 'Packages are not installed: write a project macro instead.'),
            'modules': _Unsupported('modules', 'Python modules are not exposed.'),
        }
        # Project macros, wrapped so {{ return(...) }} works as in dbt.
        for path, text in self.macro_sources:
            try:
                module = self.env.from_string(text).make_module(context)
            except TemplateSyntaxError as error:
                raise RenderError(f'{path}, line {error.lineno}: {error.message}') from error
            for name in MACRO_BLOCK.findall(text):
                macro = getattr(module, name, None)
                if macro is not None:
                    context[name] = _wrap(macro)
        return context

    def render(self, text: str, hooks: Hooks, where: str) -> str:
        try:
            template = self.env.from_string(text)
            return template.render(self._context(hooks))
        except _Return as returned:
            return str(returned.value)
        except TemplateSyntaxError as error:
            raise RenderError(f'{where}, line {error.lineno}: {error.message}') from error
        except UndefinedError as error:
            raise RenderError(f'{where}: {error.message}') from error
        except SecurityError as error:
            raise RenderError(f'{where}: not allowed in the sandbox ({error})') from error
        except RenderError as error:
            raise RenderError(f'{where}: {error}') from error

    def call_macro(self, name: str, hooks: Hooks, *args: Any) -> str:
        context = self._context(hooks)
        try:
            return str(context[name](*args)).strip()
        except RenderError as error:
            raise RenderError(f'macro {name}: {error}') from error


def _wrap(macro):
    def call(*args, **kwargs):
        try:
            return macro(*args, **kwargs)
        except _Return as returned:
            return returned.value
    return call
