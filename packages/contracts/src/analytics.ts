/** Canonical analytics domain data. UI sessions and panes live elsewhere. */
export interface ProjectFile {path: string; source: string}
export interface DbtNode {
  id: string; name: string; kind: string; path: string; description: string; materialization: string;
  dependencies: string[]; columns: Array<{name: string; type: string; description: string}>;
  source: string; compiled: string;
}
export interface DbtResult {id: string; status: string; seconds: number | null; message: string; failures: number | null}
export interface ArtifactBundle {
  schema: number; projectName: string; generatedAt: string; invocationId: string;
  nodes: DbtNode[]; results: DbtResult[]; resultInvocationId?: string;
  resultGeneratedAt?: string; warnings: string[];
  /** Imported evidence is never treated as an authenticated execution by Datapass. */
  provenance: 'imported-dbt-artifact';
}
export interface GraphNode {id: string; label: string; kind: string; detail?: string}
export interface GraphEdge {id: string; from: string; to: string; label?: string}
export interface Graph {nodes: GraphNode[]; edges: GraphEdge[]; warnings: string[]; origin: 'draft-reference-scan' | 'imported-manifest' | 'authored-model'}
export interface Column {id: string; name: string; type: string; primary: boolean; nullable: boolean}
export interface ModelTable {id: string; name: string; role: 'fact' | 'dimension' | 'source'; grain: string; columns: Column[]; x: number; y: number}
export interface Relationship {id: string; fromTable: string; fromColumn: string; toTable: string; toColumn: string; cardinality: 'many-to-one' | 'one-to-one' | 'one-to-many' | 'many-to-many'}
export interface ColumnMapping {id: string; fromTable: string; fromColumn: string; toTable: string; toColumn: string; expression: string}
export interface ModelDesign {tables: ModelTable[]; relationships: Relationship[]; mappings: ColumnMapping[]}
export type Scalar = string | number | boolean | null;
export interface ResultSnapshot {label: string; columns: string[]; rows: Record<string, Scalar>[]; origin: 'sample' | 'imported' | 'real_local'; run_id?:string; workspace_id?:string; input_versions?:Record<string,string|null>; query: string; importedAt?: string}
export interface Board {title: string; chartType: 'bar' | 'line' | 'table' | 'kpi'; x: string; y: string; aggregation: 'sum' | 'mean' | 'count'; query: string; snapshot: ResultSnapshot}
