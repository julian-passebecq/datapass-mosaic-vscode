"""Parsed pipeline model and validation issues."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

CONDITIONS = ('Succeeded', 'Failed', 'Skipped', 'Completed')
PARAMETER_TYPES = {'String', 'Int', 'Float', 'Bool', 'Array', 'Object', 'SecureString'}
VARIABLE_TYPES = {'String', 'Boolean', 'Bool', 'Array', 'Integer', 'Int', 'Float'}
# The authoring UIs write lowercase types ("string", "int", "securestring"); samples often write "String".
TYPE_SPELLINGS = {t.lower(): t for t in PARAMETER_TYPES | VARIABLE_TYPES}


class FactoryLabError(ValueError):
    """A pipeline the simulator cannot run. Carries every validation issue found."""

    def __init__(self, issues: list['Issue']):
        self.issues = issues
        super().__init__('; '.join(f"{i.path}: {i.message}" if i.path else i.message for i in issues[:5])
                         + (f" (+{len(issues) - 5} more)" if len(issues) > 5 else ''))


@dataclass
class Issue:
    path: str
    message: str
    severity: str = 'error'  # error | warning


@dataclass
class Dependency:
    activity: str
    conditions: tuple[str, ...]


@dataclass
class Policy:
    timeout_s: float = 12 * 3600.0
    retry: int = 0
    retry_interval_s: float = 30.0
    secure_input: bool = False
    secure_output: bool = False


@dataclass
class Activity:
    name: str
    type: str
    path: str
    depends_on: list[Dependency]
    policy: Policy
    type_properties: dict[str, Any]
    inputs: list[Any]
    outputs: list[Any]
    children: dict[str, list['Activity']] = field(default_factory=dict)
    state: str = 'Active'
    on_inactive_mark_as: str = 'Succeeded'
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Parameter:
    name: str
    type: str
    default: Any


@dataclass
class Variable:
    name: str
    type: str
    default: Any


@dataclass
class Pipeline:
    name: str
    flavor: str
    description: str
    parameters: dict[str, Parameter]
    variables: dict[str, Variable]
    activities: list[Activity]
    warnings: list[Issue] = field(default_factory=list)

    def walk(self) -> list[Activity]:
        found: list[Activity] = []

        def visit(activities: list[Activity]) -> None:
            for activity in activities:
                found.append(activity)
                for inner in activity.children.values():
                    visit(inner)

        visit(self.activities)
        return found
