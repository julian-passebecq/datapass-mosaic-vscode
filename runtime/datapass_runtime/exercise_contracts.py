"""Canonical v1 exercise wire schemas; exported through FastAPI OpenAPI."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')


class VersionRef(Contract):
    id: str
    version: str


class Section(Contract):
    title: str
    body: str


class VisibleCheck(Contract):
    id: str
    description: str


class SolutionMetadata(Contract):
    available: bool
    reveal: Literal['explicit']


class Placement(Contract):
    domain: str
    topic: str


class Recommendation(Contract):
    rank: int
    reason: str


class RowValidation(Contract):
    kind: Literal['rows'] = 'rows'
    ordered: bool = False
    duplicate_sensitive: bool = True
    relative_tolerance: float = Field(default=1e-9, ge=0, allow_inf_nan=False)
    absolute_tolerance: float = Field(default=1e-8, ge=0, allow_inf_nan=False)
    required_columns: list[str] = Field(default_factory=list)
    exact_schema: list[str] | None = None
    forbidden_extra_columns: bool = True
    row_count: int | None = Field(default=None, ge=0)
    null_semantics: Literal['equal', 'forbidden'] = 'equal'
    aggregates: dict[str, Literal['sum','count','min','max']] = Field(default_factory=dict)
    source_contract: Literal['python-function-solve'] | None = None


class DataContext(Contract):
    name: str
    columns: dict[str, str]
    sample_rows: list[dict[str, Any]] = Field(default_factory=list)
    catalog_ref: str | None = None


class SemanticExercise(Contract):
    id: str
    version: str
    industry: str
    learning_objectives: list[str]
    variants: dict[str, str]
    supported_operations: list[str]
    figure_family: Literal['join','partitions','workflow','lineage'] | None = None
    optimization: str
    reflection: str


class SparkTableScale(Contract):
    """Authored size of one input table for the SparkLab plan model. Never processed."""
    rows: int = Field(ge=0, le=10**13)
    bytes: int = Field(ge=0, le=10**16)
    partitions: int = Field(ge=1, le=4096)
    catalog_statistics_available: bool = True
    hot_fraction: float = Field(default=0.0, ge=0, lt=1, allow_inf_nan=False)


class SparkPlanCheck(Contract):
    id: str = Field(pattern=r'^plan-[a-z0-9-]{1,60}$')
    description: str = Field(min_length=1)
    rule: Literal['max_exchanges', 'min_broadcast_joins', 'max_shuffle_joins', 'max_global_windows', 'max_output_partitions']
    value: int = Field(ge=0, le=4096)


class SparkPlanRequirements(Contract):
    """Checks on the submission's modeled Spark plan (SparkLab simulation, not Apache Spark)."""
    profile: str = 'generic_8x8'
    aqe: bool = True
    scale: dict[str, SparkTableScale] = Field(default_factory=dict)
    checks: list[SparkPlanCheck] = Field(min_length=1)


class ExerciseDefinition(Contract):
    schema_version: Literal[1]
    id: str
    version: str
    title: str
    difficulty: Literal['easy','medium','hard']
    topics: list[str]
    tags: list[str]
    origin: Literal['internal-demo','authored','migrated']
    language: Literal['sql','sparklab','python','polars','dbt','airflow','factory','factory-notebook','sqlpool']
    runtime: str
    semantic: SemanticExercise | None = None
    prompt: str
    sections: list[Section]
    starter_source: str
    fixtures: list[VersionRef]
    visible_checks: list[VisibleCheck]
    hidden_check_refs: list[str]
    edge_check_refs: list[str]
    hints: list[str]
    solution: SolutionMetadata
    explanation: str
    follow_ups: list[str]
    canonical_placement: Placement
    related_associations: list[str]
    recommendation: Recommendation | None = None
    validator_version: str
    validation: RowValidation = Field(default_factory=RowValidation)
    pack: VersionRef | None = None
    runtime_requirements: list[str] = Field(default_factory=list)
    provenance: dict[str, str] = Field(default_factory=dict)
    constraints: dict[str, str] = Field(default_factory=dict)
    data_context: list[DataContext] = Field(default_factory=list)
    output_schema: dict[str, str] = Field(default_factory=dict)
    context_refs: list[str] = Field(default_factory=list)
    truth: Literal['real','semantic-emulation','simulated','unsupported','design-only'] = 'real'
    spark_plan: SparkPlanRequirements | None = None


class RuntimeIdentity(Contract):
    adapter: str
    engine: str
    engine_version: str
    session_generation: str


class ExerciseCheck(Contract):
    id: str
    # 'plan' checks grade the modeled SparkLab plan, not result rows.
    kind: Literal['result','plan'] = 'result'
    visibility: Literal['visible','hidden','edge']
    passed: bool
    status: Literal['passed','failed']
    execution_id: str
    execution_status: str
    elapsed_ms: float
    message: str
    input_versions: dict[str,str | None]
    actual: list[dict[str,Any]] | None = None
    expected: list[dict[str,Any]] | None = None


class ExecutionError(Contract):
    type: str
    message: str


class ExerciseAttempt(Contract):
    schema_version: Literal[1]
    id: str
    created_at: str
    exercise_id: str
    exercise_version: str
    notebook_id: str
    cell_id: str
    source: str
    source_hash: str
    source_revision: int
    validator_version: str
    fixtures: list[VersionRef]
    language: Literal['sql','sparklab','python','polars','dbt','airflow','factory','factory-notebook','sqlpool']
    status: Literal['passed','failed','error']
    checks: list[ExerciseCheck]
    truth: Literal['real','semantic-emulation','simulated','unsupported','design-only']
    runtime: RuntimeIdentity
    elapsed_ms: float
    error: ExecutionError | None = None


class ExerciseResult(Contract):
    status: Literal['passed','failed','error']
    checks: list[ExerciseCheck]
    runs: list[dict[str,Any]]
    attempt: ExerciseAttempt | None = None
    workspace_revision: int
    truth: Literal['real','semantic-emulation','simulated','unsupported','design-only']
    runtime: RuntimeIdentity
    elapsed_ms: float
    error: ExecutionError | None = None
