"""Bounded workspace-owned analytics documents. These schemas never execute source."""
from __future__ import annotations
import re
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

class Document(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)

Identifier = Annotated[str, StringConstraints(min_length=1, max_length=100)]
Text = Annotated[str, StringConstraints(max_length=100_000)]
Scalar = str | int | float | bool | None
RESERVED = re.compile(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', re.I)

def source_path(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 220 or any(c in value for c in ('\\', ':', '\x00')):
        raise ValueError('Invalid dbt source path.')
    parts = value.split('/')
    if any(not part or part in ('.', '..') or part.startswith('.') or part.rstrip(' .') != part or RESERVED.match(part) for part in parts):
        raise ValueError('Unsafe dbt source path.')
    if value not in ('dbt_project.yml', 'dbt_charts.yml'):
        if len(parts) < 2 or parts[0] not in ('models', 'seeds', 'tests', 'macros', 'snapshots', 'charts'):
            raise ValueError('Only product-owned dbt source directories are allowed.')
        if not value.endswith(('.sql', '.yml', '.yaml', '.csv')):
            raise ValueError('Unsupported dbt source file type.')
    return value

class ProjectFile(Document):
    path: str
    source: Text
    _path = field_validator('path')(source_path)

class DbtNode(Document):
    id: str = Field(max_length=500)
    name: str = Field(max_length=250)
    kind: str = Field(max_length=50)
    path: str = Field(max_length=500)
    description: str = Field(max_length=20_000)
    materialization: str = Field(max_length=80)
    dependencies: list[str] = Field(max_length=400)
    columns: list[dict[str, str]] = Field(max_length=250)
    source: Text
    compiled: Text

class DbtResult(Document):
    id: str = Field(max_length=500)
    status: str = Field(max_length=100)
    seconds: float | int | None = Field(ge=0)
    message: str = Field(max_length=10_000)
    failures: float | int | None = Field(ge=0)

class ArtifactBundle(Document):
    schema: Literal[9,10,11,12]
    projectName: str = Field(max_length=200)
    generatedAt: str = Field(max_length=100)
    invocationId: str = Field(max_length=100)
    nodes: list[DbtNode] = Field(max_length=400)
    results: list[DbtResult] = Field(max_length=400)
    resultInvocationId: str | None = Field(default=None,max_length=100)
    resultGeneratedAt: str | None = Field(default=None,max_length=100)
    warnings: list[str] = Field(max_length=3000)
    provenance: Literal['imported-dbt-artifact']

    @model_validator(mode='after')
    def same_invocation(self):
        if self.results and (not self.invocationId or self.resultInvocationId != self.invocationId):
            raise ValueError('Artifact evidence must belong to one invocation.')
        ids = [n.id for n in self.nodes]
        results = [r.id for r in self.results]
        if len(set(ids)) != len(ids) or len(set(results)) != len(results) or not set(results).issubset(ids):
            raise ValueError('Invalid artifact node/result identity.')
        return self

class Column(Document):
    id: Identifier
    name: str = Field(pattern=r'^[A-Za-z_][A-Za-z0-9_]*$',max_length=100)
    type: str = Field(max_length=100)
    primary: bool
    nullable: bool

class AnalyticsModelTable(Document):
    id: Identifier
    name: str = Field(pattern=r'^[A-Za-z_][A-Za-z0-9_]*$',max_length=100)
    role: Literal['fact','dimension','source']
    grain: str = Field(max_length=500)
    columns: list[Column] = Field(max_length=60)
    x: float | int = Field(ge=0,le=4000)
    y: float | int = Field(ge=0,le=4000)

class Endpoints(Document):
    id: Identifier
    fromTable: Identifier
    fromColumn: Identifier
    toTable: Identifier
    toColumn: Identifier

class AnalyticsRelationship(Endpoints):
    cardinality: Literal['many-to-one','one-to-one','one-to-many','many-to-many']

class Mapping(Endpoints):
    expression: str = Field(max_length=2000)

class ModelDesign(Document):
    tables: list[AnalyticsModelTable] = Field(max_length=30)
    relationships: list[AnalyticsRelationship] = Field(max_length=120)
    mappings: list[Mapping] = Field(max_length=200)

    @model_validator(mode='after')
    def references(self):
        ids = [t.id for t in self.tables]
        if len(set(ids)) != len(ids):
            raise ValueError('Duplicate model table.')
        for table in self.tables:
            cols = [c.id for c in table.columns]
            if len(set(cols)) != len(cols):
                raise ValueError('Duplicate model column.')
        columns = {t.id:{c.id for c in t.columns} for t in self.tables}
        for group in (self.relationships, self.mappings):
            if len({e.id for e in group}) != len(group):
                raise ValueError('Duplicate relationship/mapping.')
            for edge in group:
                if edge.fromColumn not in columns.get(edge.fromTable,set()) or edge.toColumn not in columns.get(edge.toTable,set()):
                    raise ValueError('Dangling model relationship/mapping.')
        return self

class ScdState(Document):
    type: Literal[1,2,3]
    step: int = Field(ge=0,le=5)
    answer: str = Field(max_length=100)

class Snapshot(Document):
    label: str = Field(max_length=200)
    columns: list[str] = Field(max_length=100)
    rows: list[dict[str,Scalar]] = Field(max_length=1000)
    origin: Literal['sample','imported','real_local']
    query: Text
    importedAt: str | None = Field(default=None,max_length=100)
    run_id: str | None = Field(default=None,max_length=100)
    workspace_id: str | None = Field(default=None,max_length=100)
    input_versions: dict[str, str | None] | None = Field(default=None,max_length=200)

class Board(Document):
    title: str = Field(max_length=200)
    chartType: Literal['bar','line','table','kpi']
    x: str = Field(max_length=100)
    y: str = Field(max_length=100)
    aggregation: Literal['sum','mean','count']
    query: Text
    snapshot: Snapshot

class PipelineTask(Document):
    id: str = Field(pattern=r'^[A-Za-z_][A-Za-z0-9_]{0,63}$')
    kind: Literal['sql','quality','python','polars','dbt']
    source: str = Field(max_length=40000)
    retries: int = Field(ge=0,le=3)
    retry_delay: float | int = Field(ge=0,le=5)
    resource_id: str | None = Field(default=None,max_length=100)
    action: Literal['parse','compile','run','build','test','seed'] | None = None

class PipelineEdge(Document):
    source: Identifier
    target: Identifier

class PipelineIR(Document):
    schema_version: Literal[1]
    id: Identifier
    schedule: str | None = Field(max_length=100)
    tasks: list[PipelineTask] = Field(min_length=1,max_length=40)
    edges: list[PipelineEdge] = Field(max_length=120)
    source_hash: str = Field(pattern=r'^[a-f0-9]{64}$')

    @model_validator(mode='after')
    def coherent_dag(self):
        ids=[t.id for t in self.tasks]
        if len(set(ids))!=len(ids):raise ValueError('Duplicate pipeline task ID.')
        pairs=[(e.source,e.target) for e in self.edges]
        if len(set(pairs))!=len(pairs):raise ValueError('Duplicate pipeline dependency.')
        parents={id:set() for id in ids}
        for a,b in pairs:
            if a not in parents or b not in parents or a==b:raise ValueError('Invalid pipeline dependency endpoint.')
            parents[b].add(a)
        seen=set()
        while len(seen)<len(ids):
            ready={id for id in ids if id not in seen and parents[id].issubset(seen)}
            if not ready:raise ValueError('Pipeline dependency cycle.')
            seen.update(ready)
        for task in self.tasks:
            if task.kind=='dbt':
                if not task.resource_id or not task.action or task.source:raise ValueError('dbt tasks reference project resources, not shell/source payloads.')
            elif task.resource_id is not None or task.action is not None or not task.source.strip():
                raise ValueError('Non-dbt tasks need source, not dbt action fields.')
        return self
