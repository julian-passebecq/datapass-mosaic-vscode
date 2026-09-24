/** Additive foundation v1. Existing Notebook/Execution/Exercise wire formats are unchanged. */
import type {Asset, Capabilities, Execution, TruthKind} from './index.ts';
import type {ArtifactBundle, Board, ModelDesign, ProjectFile} from './analytics.ts';

export type EvidenceKind = 'real_local' | 'real_remote' | 'emulated' | 'simulated' | 'design_only' | 'imported_evidence' | 'unavailable';
export type RuntimeTargetId = 'local.sql' | 'local.sparklab' | 'local.python' | 'local.polars' | 'local.dbt' | 'remote.motherduck';
export type Persona = 'neutral' | 'fabric' | 'warehouse';
export interface ResourceBase {schema_version:1; id:string; title:string; revision:number}
export interface NotebookResource extends ResourceBase {kind:'notebook'; notebook_id:string}
export interface CatalogResource extends ResourceBase {kind:'catalog'}
export interface EvidenceResource extends ResourceBase {kind:'evidence'}
export interface Dependency {id:string; source:string; target:string; condition:'success'|'completion'}
export interface WorkflowTask {id:string; label:string; runtime:RuntimeTargetId; notebook_resource_id:string|null}
export interface WorkflowResource extends ResourceBase {kind:'workflow'; tasks:WorkflowTask[]; dependencies:Dependency[]}
export interface LineageDataset {id:string; label:string; asset_ref:string|null}
export interface Derivation {id:string; source:string; target:string; note:string}
export interface LineageResource extends ResourceBase {kind:'lineage'; datasets:LineageDataset[]; derivations:Derivation[]}
export interface ModelColumn {id:string; data_type:string; key:'none'|'primary'|'foreign'; nullable:boolean}
export interface ModelTable {id:string; label:string; asset_ref:string|null; grain:string; role:'fact'|'dimension'|'table'; scd:0|1|2|3; columns:ModelColumn[]}
export interface Relationship {id:string; source:string; source_column:string; target:string; target_column:string; cardinality:'one-to-many'|'many-to-one'|'one-to-one'|'many-to-many'}
export interface DataModelResource extends ResourceBase {kind:'data-model'; tables:ModelTable[]; relationships:Relationship[]}
export type GraphResource = WorkflowResource | LineageResource | DataModelResource;
export interface DbtProjectResource extends ResourceBase {kind:'dbt-project'; files:ProjectFile[]; artifacts?:ArtifactBundle; last_run_id?:string}
export interface ModelDesignResource extends ResourceBase {kind:'model-design'; model:ModelDesign; scd:{type:1|2|3;step:number;answer:string}}
export interface ChartBoardResource extends ResourceBase {kind:'chart-board'; board:Board}
export interface PipelineIR {schema_version:1; id:string; schedule:string|null; tasks:Array<{id:string;kind:'sql'|'quality'|'python'|'polars'|'dbt';source:string;retries:number;retry_delay:number;resource_id?:string|null;action?:string|null}>; edges:Array<{source:string;target:string}>; source_hash:string}
export interface PipelineResource extends ResourceBase {kind:'pipeline'; source:string; last_valid_ir?:PipelineIR|null; diagnostics?:string[]; last_run_id?:string}
export interface FigureResource extends ResourceBase {kind:'figure'; family:'join'|'partitions'|'workflow'|'lineage'; figure_version:1; description:string}
export interface ExerciseResource extends ResourceBase {kind:'exercise'; exercise_id:string; fixture_version:string; variant:'sql'|'python'|'polars'|'dbt'|'sparklab'}
export type Resource = NotebookResource | CatalogResource | EvidenceResource | GraphResource | DbtProjectResource | ModelDesignResource | ChartBoardResource | PipelineResource | FigureResource | ExerciseResource;
export interface StudioUI {theme:'fluent'|'neutral'|'dark';skin:'studio'|'fabric'|'databricks'|'arena';explorer_open:boolean;context_open:boolean}
export interface ResourceMigration {notebook_id:string;fingerprint:string;status:'migrated'|'recovery';resources:Record<string,string>;message:string}

export interface Point {x:number; y:number}
export interface ViewInstance {id:string; resource_id:string; mode:'visual'|'spec'; state?:Record<string,string|number|boolean|null>; positions:Record<string,Point>; viewport:{x:number;y:number;zoom:number}|null; selected_node:string|null; selected_edge:string|null}
export interface Pane {id:string; view_ids:string[]; active_view_id:string|null; weight:number}
export interface RootWorkbench {schema_version:1; resources:Resource[]; views:ViewInstance[]; panes:Pane[]; active_pane_id:string; persona:Persona; direction:'horizontal'|'vertical'; resource_schema_version?:2;ui?:StudioUI;migrations?:ResourceMigration[]}

/** Display-only projection, not a universal domain graph or execution plan. */
export interface GraphProjection {nodes:Array<{id:string;label:string;detail:string;truth?:string}>; edges:Array<{id:string;source:string;target:string;label:string}>}
export function isGraph(resource:Resource):resource is GraphResource {return ['workflow','lineage','data-model'].includes(resource.kind)}
export function projectGraph(resource:GraphResource):GraphProjection {
 switch(resource.kind){
  case 'workflow': return {nodes:resource.tasks.map(t=>({id:t.id,label:t.label,detail:t.runtime})),edges:resource.dependencies.map(e=>({...e,label:e.condition}))};
  case 'lineage': return {nodes:resource.datasets.map(t=>({id:t.id,label:t.label,detail:t.asset_ref??'Unbound dataset'})),edges:resource.derivations.map(e=>({...e,label:e.note||'derives'}))};
  case 'data-model': return {nodes:resource.tables.map(t=>({id:t.id,label:t.label,detail:`${t.role} | ${t.columns.length} columns | ${t.grain||'Grain unspecified'}`})),edges:resource.relationships.map(e=>({...e,label:`${e.source_column} : ${e.target_column} (${e.cardinality})`}))};
 }
}
export function projectPipeline(resource:PipelineResource):GraphProjection {return {nodes:(resource.last_valid_ir?.tasks??[]).map(t=>({id:t.id,label:t.id,detail:`${t.kind} | retries ${t.retries}`,truth:'Compiled design'})),edges:(resource.last_valid_ir?.edges??[]).map((e,i)=>({...e,id:`dependency-${i}`,label:'success'}))};}
export interface RuntimeTarget {id:RuntimeTargetId; label:string; available:boolean; execution:EvidenceKind; reason:string}
export function runtimeTargets(capabilities:Capabilities|null):RuntimeTarget[] {
 const kernel=(id:string)=>capabilities?.kernels.find(k=>k.id===id)?.available??false;
 return [
  ...(['sql','sparklab','python','polars','dbt'] as const).map(id=>({id:`local.${id}` as RuntimeTargetId,label:id==='sparklab'?'SparkLab semantic subset':id.toUpperCase(),available:kernel(id),execution:(id==='sparklab'||id==='dbt'?'emulated':'real_local') as EvidenceKind,reason:!kernel(id)?'Kernel unavailable in this session':id==='sparklab'?'Local semantic results; cluster metrics are a separate simulation':id==='dbt'?'Bounded dbt SQL compilation, not a dbt CLI process':'Existing root kernel; no new executor'})),
  {id:'remote.motherduck',label:'MotherDuck (future adapter)',available:false,execution:'unavailable',reason:'No remote execution adapter is registered. No credentials or uploads are requested.'},
 ];
}
export const legacyTruth:Record<TruthKind,EvidenceKind> = {real:'real_local','semantic-emulation':'emulated',simulated:'simulated',unsupported:'unavailable','design-only':'design_only'};
export function evidenceOf(run:Execution):{semantic:EvidenceKind;simulation:EvidenceKind;measured_local_ms:number|null;modeled_duration_s:number|null} {
 return {semantic:run.status!=='success'?'unavailable':['sparklab','dbt'].includes(run.language)?'emulated':'real_local',
  simulation:run.guided_evidence||run.simulation?.status==='modeled'?'simulated':'unavailable',measured_local_ms:run.elapsed_ms??null,
  modeled_duration_s:run.simulation?.status==='modeled'?run.simulation.metrics?.total_duration_s??null:null};
}
export interface CatalogPort {catalog(workspaceId:string):Promise<Asset[]>}
