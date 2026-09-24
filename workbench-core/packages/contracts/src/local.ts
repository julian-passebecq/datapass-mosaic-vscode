/** Runtime evidence is workspace-owned; it is never duplicated into pane state. */
import type {ResultSnapshot} from './analytics.ts';
import type {PipelineIR} from './foundation.ts';
export interface PipelineCompilation {valid:boolean;ir:PipelineIR|null;diagnostics:Array<{line:number;column:number;message:string}>;truth:string}
export type DbtAction='parse'|'compile'|'seed'|'run'|'build'|'test';
export type JobStatus='queued'|'running'|'success'|'failed'|'cancelled'|'timed_out'|'unavailable'|'interrupted';
export interface LocalStart {resource_id:string;resource_revision:number;workspace_revision:number}
export interface ArtifactDescriptor {file:string;bytes:number;sha256:string}
export interface TaskAttempt {attempt:number;status:string;elapsed_ms:number;error?:string;run_id?:string}
export interface TaskRun {id:string;kind:string;status:string;attempts:TaskAttempt[];elapsed_ms:number;error?:string;result?:unknown}
export interface LocalJob {
 schema_version:1;id:string;workspace_id:string;resource_id:string;resource_revision:number;workspace_revision:number;
 source_hash:string;kind:'dbt'|'pipeline'|'query';action:string;status:JobStatus;truth:'real_local'|'unavailable';
 created_at:string;started_at:string|null;finished_at:string|null;elapsed_ms:number;log:string;log_truncated:boolean;
 runtime:Record<string,unknown>;artifacts:Record<string,ArtifactDescriptor>;steps:TaskRun[];error?:string;
 result?:{snapshot?:ResultSnapshot;engine?:string;invocation_id?:string|null;source_hash?:string;returncode?:number;warnings?:string[];files?:Record<string,ArtifactDescriptor>;[key:string]:unknown};
}
export interface LocalCapabilities {dbt:{available:boolean;truth:string;reason:string;actions:DbtAction[];versions:Record<string,string|null>;target:string;trusted_local:boolean;warning:string};runner:{name:string;manual_only:boolean;scheduler:boolean;max_tasks:number;max_retries:number;timeout_seconds:number}}
export const jobFinished=(job:LocalJob)=>!!job.finished_at&&!['queued','running'].includes(job.status);

export interface CatalogPreview {asset:string;schema:Array<{name:string;type:string}>;result:import('./index.ts').ResultTable;fresh:boolean;engine:string}
