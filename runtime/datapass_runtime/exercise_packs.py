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
            if definition.language not in {'sql','python','polars','sparklab','dbt'}:
                raise ValueError('No grading adapter for '+definition.language)
            private = GradingDefinition.model_validate(grading[definition.id])
            refs = {'visible': [c.id for c in definition.visible_checks], 'hidden': definition.hidden_check_refs, 'edge': definition.edge_check_refs}
            ids = [f.id for f in private.fixtures]
            if len(ids) != len(set(ids)) or not refs['visible']:
                raise ValueError('Unique checks and at least one visible check required')
            for visibility, required in refs.items():
                if len(required) != len(set(required)) or set(required) != {f.id for f in private.fixtures if f.visibility == visibility}:
                    raise ValueError('Public/private check references disagree')
            if any(len(f.input_rows)>200 or len(f.expected)>200 for f in private.fixtures):
                raise ValueError('Exercise fixtures exceed shared bounded preview')
            for fixture in private.fixtures:
                for rows in (fixture.input_rows,fixture.expected):
                    if rows and any(set(row)!=set(rows[0]) for row in rows):
                        raise ValueError('Fixture tables must be rectangular')
                    if any(not isinstance(v,(str,int,float,bool,type(None))) or isinstance(v,float) and not math.isfinite(v) for row in rows for v in row.values()):
                        raise ValueError('Fixture values must be finite JSON scalars')
                if definition.data_context and any(set(row)!=set(definition.data_context[0].columns) for row in fixture.input_rows):
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
