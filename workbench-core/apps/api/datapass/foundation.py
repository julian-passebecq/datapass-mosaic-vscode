"""Versioned design/view envelopes over the existing root; no second runtime or store.

The contracts discriminate dependency, derivation and relationship semantics. Imported
specifications are data only. They never supply code to the kernel manager.
"""
from __future__ import annotations
from collections import deque
from types import SimpleNamespace
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from .analytics_contracts import ProjectFile, ArtifactBundle, ModelDesign, ScdState, Board, PipelineIR

Id = Annotated[str, StringConstraints(pattern=r'^[A-Za-z0-9_-]{1,100}$')]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
Text = Annotated[str, StringConstraints(max_length=2000)]
AssetRef = Annotated[str, StringConstraints(min_length=1, max_length=160)]
RuntimeId = Literal['local.sql', 'local.sparklab', 'local.python', 'local.polars', 'local.dbt', 'remote.motherduck']


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)


class ResourceBase(Contract):
    schema_version: Literal[1]
    id: Id
    title: Title
    revision: int = Field(ge=0, le=2**53-1)


class NotebookResource(ResourceBase):
    kind: Literal['notebook']
    notebook_id: Id


class CatalogResource(ResourceBase):
    kind: Literal['catalog']


class EvidenceResource(ResourceBase):
    kind: Literal['evidence']


class WorkflowTask(Contract):
    id: Id
    label: Title
    runtime: RuntimeId
    notebook_resource_id: Id | None


class Dependency(Contract):
    id: Id
    source: Id
    target: Id
    condition: Literal['success', 'completion']


class WorkflowResource(ResourceBase):
    kind: Literal['workflow']
    tasks: list[WorkflowTask] = Field(max_length=200)
    dependencies: list[Dependency] = Field(max_length=500)


class LineageDataset(Contract):
    id: Id
    label: Title
    asset_ref: AssetRef | None


class Derivation(Contract):
    id: Id
    source: Id
    target: Id
    note: Text


class LineageResource(ResourceBase):
    kind: Literal['lineage']
    datasets: list[LineageDataset] = Field(max_length=200)
    derivations: list[Derivation] = Field(max_length=500)


class ModelColumn(Contract):
    id: Id
    data_type: Title
    key: Literal['none', 'primary', 'foreign']
    nullable: bool


class ModelTable(Contract):
    id: Id
    label: Title
    asset_ref: AssetRef | None
    grain: Text
    role: Literal['fact', 'dimension', 'table']
    scd: Literal[0, 1, 2, 3]
    columns: list[ModelColumn] = Field(max_length=200)


class Relationship(Contract):
    id: Id
    source: Id
    source_column: Id
    target: Id
    target_column: Id
    cardinality: Literal['one-to-many', 'many-to-one', 'one-to-one', 'many-to-many']


class DataModelResource(ResourceBase):
    kind: Literal['data-model']
    tables: list[ModelTable] = Field(max_length=200)
    relationships: list[Relationship] = Field(max_length=500)


class DbtProjectResource(ResourceBase):
    kind: Literal['dbt-project']
    files: list[ProjectFile] = Field(min_length=1,max_length=60)
    artifacts: ArtifactBundle | None = None
    last_run_id: Id | None = None

    @model_validator(mode='after')
    def paths(self):
        if len({f.path.casefold() for f in self.files}) != len(self.files):
            raise ValueError('Duplicate dbt source path.')
        if sum(len(f.source.encode('utf-8')) for f in self.files)>1_500_000:
            raise ValueError('dbt source exceeds the bounded project size.')
        return self

class ModelDesignResource(ResourceBase):
    kind: Literal['model-design']
    model: ModelDesign
    scd: ScdState

class ChartBoardResource(ResourceBase):
    kind: Literal['chart-board']
    board: Board

class PipelineResource(ResourceBase):
    kind: Literal['pipeline']
    source: str = Field(max_length=80000)
    last_valid_ir: PipelineIR | None = None
    diagnostics: list[str] = Field(default_factory=list,max_length=20)
    last_run_id: Id | None = None

class FigureResource(ResourceBase):
    kind: Literal['figure']
    family: Literal['join','partitions','workflow','lineage']
    figure_version: Literal[1]
    description: Text

class ExerciseResource(ResourceBase):
    kind: Literal['exercise']
    exercise_id: Id
    fixture_version: Title
    variant: Literal['sql','python','polars','dbt','sparklab']

class StudioUI(Contract):
    theme: Literal['fluent','neutral','dark'] = 'fluent'
    skin: Literal['studio','fabric','databricks','arena'] = 'studio'
    explorer_open: bool = True
    context_open: bool = False

class ResourceMigration(Contract):
    notebook_id: Id
    fingerprint: str = Field(max_length=100)
    status: Literal['migrated','recovery']
    resources: dict[str,Id] = Field(max_length=12)
    message: str = Field(max_length=4000)

Resource = Annotated[NotebookResource | CatalogResource | EvidenceResource | WorkflowResource | LineageResource | DataModelResource | DbtProjectResource | ModelDesignResource | ChartBoardResource | PipelineResource | FigureResource | ExerciseResource,
                     Field(discriminator='kind')]


class Point(Contract):
    x: float = Field(ge=-100000, le=100000)
    y: float = Field(ge=-100000, le=100000)


class Viewport(Point):
    zoom: float = Field(ge=0.2, le=3)


class ViewInstance(Contract):
    id: Id
    resource_id: Id
    mode: Literal['visual', 'spec']
    state: dict[str, str | int | float | bool | None] = Field(default_factory=dict,max_length=20)
    positions: dict[Id, Point] = Field(max_length=200)
    viewport: Viewport | None
    selected_node: Id | None
    selected_edge: Id | None


class Pane(Contract):
    id: Id
    view_ids: list[Id] = Field(max_length=120)
    active_view_id: Id | None
    weight: float = Field(ge=0.25, le=4)


def unique(items, label):
    values = [item.id for item in items]
    if len(set(values)) != len(values):
        raise ValueError(f'Duplicate {label} ID.')
    return set(values)


def graph_items(resource):
    if resource.kind == 'pipeline' and resource.last_valid_ir:
        return resource.last_valid_ir.tasks, [SimpleNamespace(id=f'dependency-{i}',source=e.source,target=e.target) for i,e in enumerate(resource.last_valid_ir.edges)]
    if resource.kind == 'workflow':
        return resource.tasks, resource.dependencies
    if resource.kind == 'lineage':
        return resource.datasets, resource.derivations
    if resource.kind == 'data-model':
        return resource.tables, resource.relationships
    return [], []


def validate_graph(resource):
    nodes, edges = graph_items(resource)
    ids = unique(nodes, 'node')
    unique(edges, 'edge')
    pairs = set()
    for edge in edges:
        if edge.source not in ids or edge.target not in ids:
            raise ValueError('Graph edge endpoint does not exist.')
        pair = (edge.source, edge.target)
        if resource.kind == 'data-model':
            pair += (edge.source_column, edge.target_column)
        if pair in pairs:
            raise ValueError('Duplicate graph connection.')
        pairs.add(pair)
    if resource.kind == 'data-model':
        columns = {table.id: unique(table.columns, 'column') for table in nodes}
        for rel in edges:
            if rel.source_column not in columns[rel.source] or rel.target_column not in columns[rel.target]:
                raise ValueError('Relationship column does not exist.')
        return  # Valid relationships may be cyclic or self-referencing.
    if resource.kind not in ('workflow', 'lineage'):
        return
    degree = dict.fromkeys(ids, 0)
    children = {id: [] for id in ids}
    for edge in edges:
        degree[edge.target] += 1
        children[edge.source].append(edge.target)
    ready = deque(id for id, count in degree.items() if count == 0)
    visited = 0
    while ready:
        id = ready.popleft()
        visited += 1
        for child in children[id]:
            degree[child] -= 1
            if degree[child] == 0:
                ready.append(child)
    if visited != len(ids):
        raise ValueError(f'{resource.kind} cycle. For recurring lineage use distinct versioned datasets.')


class RootWorkbench(Contract):
    schema_version: Literal[1]
    resources: list[Resource] = Field(max_length=60)
    views: list[ViewInstance] = Field(max_length=120)
    panes: list[Pane] = Field(min_length=1, max_length=3)
    active_pane_id: Id
    persona: Literal['neutral', 'fabric', 'warehouse']
    direction: Literal['horizontal', 'vertical']
    resource_schema_version: Literal[2] = 2
    ui: StudioUI = Field(default_factory=StudioUI)
    migrations: list[ResourceMigration] = Field(default_factory=list,max_length=300)

    @model_validator(mode='after')
    def references(self):
        resource_ids = unique(self.resources, 'resource')
        view_ids = unique(self.views, 'view')
        pane_ids = unique(self.panes, 'pane')
        resources = {r.id: r for r in self.resources}
        if self.active_pane_id not in pane_ids:
            raise ValueError('Active pane does not exist.')
        # One canonical notebook resource per notebook. Extra panes create views, not copies.
        notebooks = [r.notebook_id for r in self.resources if r.kind == 'notebook']
        if len(set(notebooks)) != len(notebooks):
            raise ValueError('A notebook may only have one canonical resource reference.')
        for resource in self.resources:
            validate_graph(resource)
            if resource.kind == 'pipeline' and resource.last_valid_ir:
                for task in resource.last_valid_ir.tasks:
                    if task.kind=='dbt' and getattr(resources.get(task.resource_id),'kind',None)!='dbt-project':
                        raise ValueError('Pipeline dbt task references a missing project resource.')
            if resource.kind == 'workflow':
                for task in resource.tasks:
                    if task.notebook_resource_id and getattr(resources.get(task.notebook_resource_id), 'kind', None) != 'notebook':
                        raise ValueError('Workflow task references a missing notebook resource.')
        for migration in self.migrations:
            if migration.status == 'migrated' and not set(migration.resources.values()).issubset(resource_ids):
                raise ValueError('Migration journal references a missing resource.')
        for view in self.views:
            if view.resource_id not in resource_ids:
                raise ValueError('View references a missing resource.')
            nodes, edges = graph_items(resources[view.resource_id])
            if not set(view.positions).issubset({n.id for n in nodes}):
                raise ValueError('Layout references an unknown graph node.')
            if view.selected_node and view.selected_node not in {n.id for n in nodes}:
                raise ValueError('Selected graph node does not exist.')
            if view.selected_edge and view.selected_edge not in {e.id for e in edges}:
                raise ValueError('Selected graph edge does not exist.')
        placed = [id for pane in self.panes for id in pane.view_ids]
        if set(placed) != view_ids or len(placed) != len(view_ids):
            raise ValueError('Each view must belong to exactly one pane.')
        for pane in self.panes:
            if (pane.view_ids and not pane.active_view_id) or (pane.active_view_id and pane.active_view_id not in pane.view_ids):
                raise ValueError('Active tab must belong to its pane.')
        return self


def validate_workspace_references(workbench: RootWorkbench, workspace: dict):
    """Do not silently import notebooks or mutate the catalog when a layout is loaded."""
    notebook_ids = set(workspace.get('notebooks', {}))
    current = workspace.get('notebook')
    if current and current.get('id'):
        notebook_ids.add(current['id'])
    for resource in workbench.resources:
        if resource.kind == 'notebook' and resource.notebook_id not in notebook_ids:
            raise ValueError(f'Notebook {resource.notebook_id} is not saved in this workspace. Open/save it first.')
