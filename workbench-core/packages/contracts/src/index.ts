import type {RootWorkbench} from './foundation.ts';
/** Root v1 contracts. Specialist modules consume these, never create a second runtime. */
export type KernelId = 'sql' | 'sparklab' | 'python' | 'polars' | 'dbt';
export type TruthKind = 'real' | 'semantic-emulation' | 'simulated' | 'unsupported' | 'design-only';
export interface ResultTable {columns:string[]; rows:Record<string,unknown>[]; total_rows:number|null; truncated:boolean}
export interface PartitionValueEvidence {value:string;file_count:number;size_bytes:number;record_count:number}
export interface PartitionColumnEvidence {key_index:number;column:string;column_type:string;transform:string;values:PartitionValueEvidence[]}
export interface PartitionEvidence {partitioned:boolean;partition_id:number|null;columns:PartitionColumnEvidence[];truth:string}
export interface PartitionPruningEvidence {eligible:boolean;asset?:string;column?:string;operator?:'=';value?:string;partition_transform?:'identity';total_files?:number;candidate_files?:number;pruned_files?:number;total_bytes?:number;candidate_bytes?:number;pruned_bytes?:number;candidate_records?:number;snapshot_id?:number|null;truth?:string;reason?:string}
export interface AssetStorageEvidence {format:'parquet';file_count:number;size_bytes:number;delete_file_count:number;small_file_count?:number;min_file_size_bytes?:number;max_file_size_bytes?:number;snapshot_id:number|null;partitioning?:PartitionEvidence;truth:'measured_ducklake_metadata'}
export interface Asset {name:string;layer:string;row_count:number;version?:string;inputs?:Record<string,string>;producer?:string;fresh:boolean;storage?:AssetStorageEvidence}
export interface LakehouseSnapshot {snapshot_id:number;snapshot_time:string;schema_version:number}
export interface LakehouseTableEvidence {name:string;rows:number;file_count:number;size_bytes:number;average_file_size_bytes:number;small_file_threshold_bytes:number;small_file_count:number;delete_file_count:number;snapshot_id:number|null;partitioning?:PartitionEvidence;compaction_advisory:'consider_merge_adjacent_files'|'none';truth:string}
export interface LakehouseOverview {active:boolean;truth:string;reason?:string;maintenance_capability?:string;small_file_threshold_truth?:string;snapshots:LakehouseSnapshot[];tables:LakehouseTableEvidence[]}
export interface Check {status:string;passed:boolean|null;fresh?:boolean;message:string;actual?:Record<string,unknown>[];expected?:Record<string,unknown>[]}
export interface SparkPlanNode {id:number;operation:string;source?:string;parents:number[];dependency:string;concept:string}
export interface SparkTask {task_id:number;partition_mb:number;duration_s:number;start_s:number;finish_s:number;worker_slot:number;spill_mb:number;skewed:boolean}
export interface SparkStage {stage_id:number;name:string;operator:string;duration_s:number;task_count:number;dependencies?:number[];tasks?:SparkTask[];notes?:string[];input_rows?:number;output_rows?:number;input_bytes?:number;output_bytes?:number;partitions?:number;shuffle_read_gb?:number;shuffle_write_gb?:number;spill_gb?:number;max_task_s?:number;p50_task_s?:number;p95_task_s?:number;straggler?:boolean;skewed_tasks?:number;broadcast_mb?:number;sort?:boolean;row_truth?:string;storage_pruning?:PartitionPruningEvidence|null}
export interface Simulation {status:string;reason?:string;truth?:string;physical_fixture_rows?:number;virtual_fact_rows?:number;profile_id?:string;aqe?:boolean;action?:string;logical_plan?:SparkPlanNode[];assumptions?:Record<string,unknown>;semantic_match?:boolean|null;comparisons?:Array<{profile_id:string;aqe:boolean;duration_s:number;credits:number;duration_delta_s:number;reason:string}>;datapass_credits?:{unit:string;fictional:boolean;total:number;contributors:Record<string,number>;formula:string;explanation:string};metrics?:{job_id?:string;total_duration_s:number;shuffle_gb:number;spill_gb:number;core_hours:number;cluster_utilization_pct?:number;startup_overhead_s?:number;scheduler_overhead_s?:number;stages:SparkStage[]};cost?:{sparklab:{scc:number;estimated_eur:number};fabric_like:{estimated_eur:number|null};databricks_like:{estimated_usd:number|null}};grade?:{pass:boolean;overall:number;feedback:string[]}}
export interface SparkSupport {schema_version:number;execution:string;supported:Array<{operation:string;scope:string}>;unsupported:string[]}
export interface Execution {guided_evidence?:GuidedEvidence;id:string;cell_id:string;notebook_id:string;source_hash:string;input_versions?:Record<string,string|null>;session_generation:string;sequence:number;created_at:string;engine:string;language:KernelId;status:'success'|'error'|'skipped';stdout?:string;error?:{type:string;message:string};reason?:string;result?:ResultTable;compiled_sql?:string;output_asset?:string|null;simulation?:Simulation|null;check?:Check|null;elapsed_ms?:number;workspace_revision?:number;catalog?:Asset[]}
export interface CaseStep {id:string;title:string;module:string;language:KernelId;code:string;solution:string;output_asset:string|null;depends_on:string[];concept:string;task:string;hint:string;truth_pack?:string;check?:{sql:string;expected:Record<string,unknown>[]} | null}
export interface CaseStudy {schema_version:1;id:string;title:string;subtitle:string;domain:string;difficulty:string;minutes:number;description:string;physical_data:string;scale_note?:string;modules:string[];steps:CaseStep[];status:string;version:string}
export interface ModuleManifest {id:string;title:string;kind:string;persona:string;status:string;contract_version:1}
export interface Workspace<T=unknown> {workbench?:RootWorkbench;id:string;case_id:string|null;title:string;revision:number;updated_at:string;schema_version:1;notebook:T|null;notebooks?:Record<string,T>;practice_resume?:Record<string,string>;practice_review?:Record<string,PracticeReview>;evidence:Record<string,Execution>;runs:Execution[]}
export interface LakehouseCapability {
 schema_version:1;active:boolean;table_format:'ducklake';compute_engine:'duckdb'|'sqlite';
 metadata_backend:string|null;metadata_file:string|null;data_format:'parquet'|null;data_directory:string|null;
 data_inlining_row_limit:number;truth:string;duckdb_version:string|null;ducklake_extension_version:string|null;
 ducklake_extension_installed?:boolean;sqlite_extension_version?:string|null;legacy_metadata:boolean;
}
export interface Capabilities {sparklab?:SparkSupport;storage:string;storage_truth:string;ducklake_active:boolean;lakehouse:LakehouseCapability;distributed_spark:boolean;session_generation:string;kernels:Array<{id:KernelId;available:boolean;truth:string}>;motherduck:{enabled:boolean;mode?:'optional_remote';reason:string}}
export interface Profile {schema_version:number;driver_cores:number;driver_memory_gb:number;executor_count:number;executor_cores:number;executor_memory_gb:number;total_virtual_cores:number;default_partitions:number;shuffle_partitions:number;broadcast_threshold_mb:number;aqe_default:boolean;cold_start_seconds:number;scan_mb_s_per_core:number;shuffle_mb_s_per_core:number;credits_per_core_hour:number;id:string;name:string;min_workers:number;max_workers:number;cores_per_worker:number;max_cores:number;memory_gb_per_worker:number;truth:string}
export interface AirflowRemoteCapabilities {schema_version:1;enabled:boolean;mode:'github_actions_ephemeral';airflow_version:string;repo:string;workflow:string;ref:string;public_repo:boolean;truth:string;scheduler_truth:string;privacy:string;limits:{dag_source_bytes:number;job_timeout_minutes:number;dag_test_timeout_seconds:number}}
export interface AirflowDispatchRequest {dag_id:string;logical_date:string;source:string}
export interface AirflowDispatch {request_id:string;status:'accepted';run_id:number|null;run_url:string|null;truth:string}
export interface AirflowRunStatus {status:string;conclusion:string|null;run_id:number;run_url:string|null;created_at?:string;run_started_at?:string;updated_at?:string;artifact_available:boolean;truth:string}
export interface AirflowRunResult {schema_version:1;request_id:string;dag_id:string;logical_date:string;status:'success'|'failed';exit_code:number;airflow_version:string;runner:string;execution_mode:string;persistent_scheduler:false;tasks:string[];run_id:number;run_url:string|null;log:string;log_truncated:boolean;truth:string}

export interface SparkRemoteCapabilities {enabled:boolean;runner_api_version?:number;mode:'github_actions_ephemeral';provider?:'github_actions'|string;lifecycle?:'ephemeral'|'persistent'|string;spark_version?:string;master?:string;job_id_scheme?:string;execution_target?:{provider:string;lifecycle:string;host_scope:string;master:string;spark_version:string};repo?:string;workflow?:string;ref?:string;public_repo?:boolean;truth:string;cluster_truth:string;privacy?:string;proxy_truth?:string;limits?:{code_bytes:number;tables_json_bytes:number;job_timeout_minutes:number;execution_timeout_seconds:number}}
export interface SparkRemoteDispatchRequest {notebook_id:string;code:string;collect_limit:number}
export interface SparkRemoteDispatch {request_id:string;status:'accepted';job_id:string;run_id?:number;run_url:string|null;truth:string;fixture_truth?:string;sources?:string[]}
export interface SparkRemoteRunStatus {status:string;conclusion:string|null;job_id:string;run_id?:number;run_url:string|null;created_at?:string;run_started_at?:string;updated_at?:string;artifact_available:boolean;truth:string}
export interface SparkRemoteMetrics {truth:string;event_count?:number;parse_errors?:number;stage_count:number;task_count:number;input_bytes?:number;shuffle_read_bytes:number;shuffle_write_bytes:number;memory_spill_bytes?:number;disk_spill_bytes?:number;stages?:Array<Record<string,unknown>>}
export interface SparkRemoteResult {schema_version:1;request_id:string;job_id:string;status:'success'|'failed';spark_version:string;master:string;runner:string;execution_mode:string;multi_machine_cluster:false;wall_elapsed_ms?:number;action?:string;row_count_truth?:string;rows:Record<string,unknown>[];columns:string[];total_rows:number|null;truncated:boolean;metrics:SparkRemoteMetrics;run_id?:number;run_url:string|null;logical_plan:string;physical_plan:string;formatted_plan:string;log:string;log_truncated:boolean;truth:string;error?:string;error_type?:string}

export interface ExecuteRequest {notebook_id:string;cell_id:string;step_id?:string;language:KernelId;code:string;output_asset?:string|null;profile:string;aqe:boolean}
export interface RuntimeClient {execute(workspaceId:string,request:ExecuteRequest):Promise<Execution>;exercise(workspaceId:string,request:ExerciseRequest):Promise<ExerciseResult>;catalog(workspaceId:string):Promise<Asset[]>;lakehouse(workspaceId:string):Promise<LakehouseOverview>;airflowCapabilities():Promise<AirflowRemoteCapabilities>;airflowDispatch(request:AirflowDispatchRequest):Promise<AirflowDispatch>;airflowStatus(runId:number):Promise<AirflowRunStatus>;airflowResult(runId:number,requestId:string):Promise<AirflowRunResult>;sparkRemoteCapabilities():Promise<SparkRemoteCapabilities>;sparkRemoteDispatch(workspaceId:string,request:SparkRemoteDispatchRequest):Promise<SparkRemoteDispatch>;sparkRemoteStatus(workspaceId:string,jobId:string):Promise<SparkRemoteRunStatus>;sparkRemoteResult(workspaceId:string,jobId:string,requestId:string):Promise<SparkRemoteResult>;restart(workspaceId:string):Promise<unknown>}
export interface WorkflowResult {status:'success'|'failed';runs:Execution[];catalog:Asset[];workspace_revision:number;scheduler_truth:string}

/** Public, versionable exercise metadata; hidden answers and solutions are server-owned. */
export interface SemanticExercise {id:string;version:string;industry:string;learning_objectives:string[];variants:Partial<Record<KernelId,string>>;supported_operations:string[];figure_family?:'join'|'partitions'|'workflow'|'lineage';optimization:string;reflection:string}
export interface ExerciseDefinition {
 schema_version:1;id:string;version:string;title:string;difficulty:'easy'|'medium'|'hard';topics:string[];tags:string[];
 origin:'internal-demo'|'authored'|'migrated';language:KernelId;runtime:string;semantic?:SemanticExercise;prompt:string;
 sections:Array<{title:string;body:string}>;starter_source:string;fixtures:Array<{id:string;version:string}>;
 visible_checks:Array<{id:string;description:string}>;hidden_check_refs:string[];edge_check_refs:string[];
 hints:string[];solution:{available:boolean;reveal:'explicit'};explanation:string;follow_ups:string[];
 canonical_placement:{domain:string;topic:string};related_associations:string[];
 recommendation?:{rank:number;reason:string};validator_version:string;
 validation:{kind:'rows';ordered:boolean;duplicate_sensitive:boolean;relative_tolerance:number;absolute_tolerance:number;required_columns?:string[];exact_schema?:string[];forbidden_extra_columns?:boolean;row_count?:number;null_semantics?:'equal'|'forbidden';aggregates?:Record<string,'sum'|'count'|'min'|'max'>;source_contract?:'python-function-solve'};
 pack?:{id:string;version:string};runtime_requirements?:string[];provenance?:Record<string,string>;constraints?:Record<string,string>;
 data_context?:Array<{name:string;columns:Record<string,string>;sample_rows:Record<string,unknown>[];catalog_ref?:string}>;
 output_schema?:Record<string,string>;context_refs?:string[];truth?:TruthKind;
}
export interface ExerciseProgress {exercise_id:string;version:string;attempt_count:number;solved:boolean;latest_result:'passed'|'failed'|'error'|null;last_attempted:string|null;best_status:'passed'|'failed'|'error'|null;review:boolean}
export interface PracticeProgress {exercises:Record<string,ExerciseProgress>;topics:Record<string,{total:number;solved:number}>;difficulty:Record<string,{total:number;solved:number}>}
export interface PracticeReview {review:boolean;confidence:'low'|'medium'|'high';difficulty:'easy'|'medium'|'hard'}
export interface ExerciseRequest {remote_consent?:boolean;exercise_id:string;exercise_version:string;notebook_id:string;cell_id:string;code:string;language:KernelId;source_revision:number;profile?:string;aqe?:boolean;mode:'run'|'submit'}
export interface ExerciseCheck {id:string;visibility:'visible'|'hidden'|'edge';passed:boolean;status:'passed'|'failed';execution_id:string;execution_status:string;elapsed_ms:number;message:string;input_versions:Record<string,string|null>;actual?:Record<string,unknown>[];expected?:Record<string,unknown>[]}
export interface ExerciseAttempt {schema_version:1;id:string;created_at:string;exercise_id:string;exercise_version:string;notebook_id:string;cell_id:string;source:string;source_hash:string;source_revision:number;validator_version:string;fixtures:Array<{id:string;version:string}>;language:KernelId;status:'passed'|'failed'|'error';checks:ExerciseCheck[];truth:TruthKind;runtime:{adapter:string;engine:string;engine_version:string;session_generation:string};elapsed_ms:number;error?:{type:string;message:string}}
export interface ExerciseResult {status:'passed'|'failed'|'error';checks:ExerciseCheck[];runs:Execution[];attempt?:ExerciseAttempt;workspace_revision:number;truth:TruthKind;runtime:ExerciseAttempt['runtime'];elapsed_ms:number;error?:{type:string;message:string}}

export function topologicalOrder(steps:Array<{id:string;depends_on:string[]}>):string[] {
 const byId=new Map(steps.map(s=>[s.id,s]));
 if(byId.size!==steps.length) throw new Error('Duplicate step IDs');
 const active=new Set<string>(),done=new Set<string>(),out:string[]=[];
 const visit=(id:string)=>{if(active.has(id))throw new Error('Dependency cycle');if(done.has(id))return;const s=byId.get(id);if(!s)throw new Error(`Unknown dependency: ${id}`);active.add(id);s.depends_on.forEach(visit);active.delete(id);done.add(id);out.push(id)};
 steps.forEach(s=>visit(s.id));return out;
}
export function requireModuleCompatibility(module:ModuleManifest):void {if(module.contract_version!==1)throw new Error(`Unsupported module contract for ${module.id}`)}

/** Saved output is evidence, not an assertion that its dependencies are still current. */
export function isExecutionFresh(run:Execution,assets:Asset[]):boolean {
 if(run.status!=='success'||!run.input_versions)return false;
 const current=new Map(assets.map(a=>[a.name,a]));
 return Object.entries(run.input_versions).every(([name,version])=>{
  const asset=current.get(name);return !!asset&&asset.fresh&&asset.version===version;
 });
}

export interface GuidedCapabilities {configured:boolean;available:boolean;service_version:string;source_commit:string;adapter:string;reason:string;location:string;privacy:string;limits:{operations:number;result_rows:number;fixture_rows:number;timeout_seconds:number};limitations:string[]}
export interface GuidedEvidence {adapter:string;service_version:string;source_commit:string;execution_id:string;fixture_version:string;physical_engine:string;engine_version:string;truth:string;metrics:{runtime_id:string;total_duration_ms:number;total_tasks:number;total_shuffle_bytes:number;total_spill_bytes:number;simulated_credits:number;disclaimer:string;stages:Array<{stage_id:number;tasks:number;duration_ms:number;shuffle_read_bytes:number;shuffle_write_bytes:number;spill_bytes:number}>}}
