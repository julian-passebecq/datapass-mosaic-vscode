"""One server registry; public definitions and grading files have distinct schemas."""
from copy import deepcopy
import json
from pathlib import Path
import math
import re
from typing import Any, Literal
from pydantic import Field
from .exercise_contracts import Contract, ExerciseDefinition, VersionRef


class PackManifest(Contract):
    schema_version: Literal[1] = 1
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]+$')
    version: str = Field(min_length=1)
    title: str
    enabled: bool = True
    provenance: dict[str, str] = Field(default_factory=dict)


class Fixture(Contract):
    id: str
    visibility: Literal['visible','hidden','edge']
    input_rows: list[dict[str, Any]]
    expected: list[dict[str, Any]]
    # Named fixture tables for multi-table SQL exercises. When present, the
    # public data_context declares one entry per table and input_rows is empty.
    tables: dict[str, list[dict[str, Any]]] | None = None
    # Airflow Lab fixtures: a simulation scenario instead of input rows.
    scenario: dict[str, Any] | None = None


# Declared fixture column types are interpolated into CAST(...); allowlist only.
COLUMN_TYPE = re.compile(r'^(INTEGER|BIGINT|DOUBLE|VARCHAR|BOOLEAN|DATE|TIMESTAMP|DECIMAL\(\d{1,2}, ?\d{1,2}\))$')
TABLE_NAME = re.compile(r'^[a-z][a-z0-9_]{0,40}$')
RESERVED_TABLES = {'source', 'bronze', 'silver', 'gold', 'warehouse', 'features', 'metrics',
                   # Python grading namespace names that a table must not shadow.
                   'input_rows', 'tables', 'display', 'query', 'publish'}
NAMED_TABLE_LANGUAGES = {'sql', 'python', 'polars', 'sparklab'}
CLUSTER_PROFILES = set(json.loads((Path(__file__).resolve().parents[1] / 'sparklab' / 'cluster_profiles.json').read_text(encoding='utf-8')))


class GradingDefinition(Contract):
    solution: str
    fixtures: list[Fixture]


class PackRegistry:
    def __init__(self):
        self.packs = {}
        self.entries = {}

    def register(self, manifest, definitions, grading):
        manifest = PackManifest.model_validate(manifest)
        if manifest.id in self.packs:
            raise ValueError('Duplicate pack ID/version: '+manifest.id)
        candidate = {}
        for raw in definitions:
            definition = ExerciseDefinition.model_validate(raw)
            if definition.id in self.entries or definition.id in candidate:
                raise ValueError('Duplicate exercise ID/version: '+definition.id)
            if not definition.id or not definition.version or not definition.topics:
                raise ValueError('Exercise identity, version and topics are required')
            if not re.fullmatch(r'[A-Za-z0-9_-]+',definition.id+'-'+definition.version) or len('exercise-'+definition.id+'-'+definition.version)>100:
                raise ValueError('Exercise identity must fit a shared notebook ID')
            if definition.canonical_placement.topic not in definition.topics:
                raise ValueError('Canonical topic must belong to exercise topics')
            if definition.language not in {'sql','python','polars','sparklab','dbt','airflow'}:
                raise ValueError('No grading adapter for '+definition.language)
            private = GradingDefinition.model_validate(grading[definition.id])
            refs = {'visible': [c.id for c in definition.visible_checks], 'hidden': definition.hidden_check_refs, 'edge': definition.edge_check_refs}
            ids = [f.id for f in private.fixtures]
            if len(ids) != len(set(ids)) or not refs['visible']:
                raise ValueError('Unique checks and at least one visible check required')
            for visibility, required in refs.items():
                if len(required) != len(set(required)) or set(required) != {f.id for f in private.fixtures if f.visibility == visibility}:
                    raise ValueError('Public/private check references disagree')
            if any(len(f.input_rows)>200 or len(f.expected)>200 or any(len(t)>200 for t in (f.tables or {}).values()) for f in private.fixtures):
                raise ValueError('Exercise fixtures exceed shared bounded preview')
            for context in definition.data_context:
                if any(not COLUMN_TYPE.fullmatch(t) for t in context.columns.values()):
                    raise ValueError('Unsupported fixture column type in '+definition.id)
            multi = len(definition.data_context) > 1 or any(f.tables is not None for f in private.fixtures)
            if multi:
                names = [c.name for c in definition.data_context]
                if definition.language not in NAMED_TABLE_LANGUAGES:
                    raise ValueError('Named multi-table fixtures are unsupported for '+definition.language+': '+definition.id)
                if len(names) != len(set(names)) or any(not TABLE_NAME.fullmatch(n) or n in RESERVED_TABLES for n in names):
                    raise ValueError('Fixture table names must be unique lowercase identifiers: '+definition.id)
                for fixture in private.fixtures:
                    if fixture.input_rows or fixture.tables is None or set(fixture.tables) != set(names):
                        raise ValueError('Every fixture must supply exactly the declared tables: '+definition.id)
                    for context in definition.data_context:
                        if any(set(row) != set(context.columns) for row in fixture.tables[context.name]):
                            raise ValueError('Fixture table schema disagrees with data_context: '+definition.id+'.'+context.name)
            if definition.spark_plan is not None:
                plan = definition.spark_plan
                if definition.language != 'sparklab':
                    raise ValueError('spark_plan checks require a SparkLab exercise: '+definition.id)
                if not set(plan.scale) <= {c.name for c in definition.data_context} | {'input'}:
                    raise ValueError('spark_plan scale names a table the exercise does not read: '+definition.id)
                check_ids = [c.id for c in plan.checks]
                if len(check_ids) != len(set(check_ids)) or set(check_ids) & set(ids):
                    raise ValueError('spark_plan check ids must be unique and distinct from fixture ids: '+definition.id)
                if plan.profile not in CLUSTER_PROFILES:
                    raise ValueError('Unknown SparkLab cluster profile in '+definition.id)
            for fixture in private.fixtures:
                if (fixture.scenario is not None) != (definition.language == 'airflow'):
                    raise ValueError('Airflow fixtures, and only they, need a simulation scenario: '+definition.id)
                if fixture.scenario is not None:
                    from airflowlab.simulate import Scenario
                    Scenario.model_validate(fixture.scenario)
                    if fixture.input_rows or fixture.tables is not None:
                        raise ValueError('Airflow fixtures take a scenario, not input rows: '+definition.id)
            for fixture in private.fixtures:
                for rows in (fixture.input_rows,fixture.expected,*(fixture.tables or {}).values()):
                    if rows and any(set(row)!=set(rows[0]) for row in rows):
                        raise ValueError('Fixture tables must be rectangular')
                    if any(not isinstance(v,(str,int,float,bool,type(None))) or isinstance(v,float) and not math.isfinite(v) for row in rows for v in row.values()):
                        raise ValueError('Fixture values must be finite JSON scalars')
                if not multi and definition.data_context and any(set(row)!=set(definition.data_context[0].columns) for row in fixture.input_rows):
                    raise ValueError('Fixture input schema disagrees with public input schema')
            definition.pack = VersionRef(id=manifest.id, version=manifest.version)
            candidate[definition.id] = (definition, private, manifest.id)
        if set(grading) != set(candidate):
            raise ValueError('Unmatched grading definitions')
        self.packs[manifest.id] = manifest
        self.entries.update(candidate)

    def register_semantic(self, manifest, scenarios, grading):
        """One public scenario + one private fixture set, expanded at the adapter edge.

        Stable adapter IDs keep existing attempts/backends compatible. Fixtures and
        expected results are never copied into independently authored language packs.
        """
        from .semantic_packs import expand_scenarios
        definitions, private = expand_scenarios(scenarios, grading)
        self.register(manifest, definitions, private)

    def load(self, directory):
        directory = Path(directory)
        if (directory/'scenarios.json').exists():
            self.register_semantic(json.loads((directory/'manifest.json').read_text(encoding='utf-8')),
                                   json.loads((directory/'scenarios.json').read_text(encoding='utf-8')),
                                   json.loads((directory/'grading.server.json').read_text(encoding='utf-8')))
            return
        self.register(json.loads((directory/'manifest.json').read_text(encoding='utf-8')),
                      json.loads((directory/'exercises.json').read_text(encoding='utf-8')),
                      json.loads((directory/'grading.server.json').read_text(encoding='utf-8')))

    def get(self, id):
        definition, grading, pack = self.entries[id]
        if not self.packs[pack].enabled:
            raise KeyError('Exercise pack disabled')
        return deepcopy(definition), deepcopy(grading)

    def definitions(self):
        return [self.get(id)[0].model_dump(exclude_none=True) for id, (_, _, pack) in self.entries.items() if self.packs[pack].enabled]

    def discovery(self):
        return [m.model_dump() for m in self.packs.values()]
