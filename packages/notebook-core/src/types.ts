export type PanelType = 'sql' | 'python' | 'polars' | 'markdown' | 'table' | 'chart' | 'catalog' | 'notebook-output'

export type RuntimeState = 'idle' | 'loading' | 'ready' | 'error'
export type ExecutionRuntime = 'browser' | 'cloud' | 'native'
export type ResultOriginKind = 'demo' | 'sql' | 'python' | 'polars' | 'import'
export type ResultTransport = 'rows' | 'arrow-ipc'

export interface ResultOrigin {
  blockId: string
  label: string
  kind: ResultOriginKind
  runtime: ExecutionRuntime
  createdAt: string
  parentResultId?: string
}

export interface ResultField {
  name: string
  type: string
}

export interface ResultTable {
  id?: string
  revision?: number
  columns: string[]
  rows: Array<Record<string, unknown>>
  schema?: ResultField[]
  transport?: ResultTransport
  arrowIpc?: Uint8Array
  elapsedMs?: number
  totalRows?: number
  truncated?: boolean
  origin?: ResultOrigin
}

export type DatasetLayer = 'source' | 'bronze' | 'silver' | 'gold'

export interface DatasetInfo {
  id: string
  name: string
  tableName?: string
  kind: 'table' | 'view' | 'csv' | 'parquet' | 'cloud' | 'lakehouse'
  detail: string
  runtime: ExecutionRuntime
  layer?: DatasetLayer
  producedBy?: 'SQL' | 'Python' | 'Polars' | 'Import'
  quality?: 'unchecked' | 'passed' | 'failed'
  qualityDetail?: string
  assetFingerprint?: string
}

export interface NotebookCellMeta {
  source: 'ipynb'
  cellId: string
  /** Original raw Jupyter cell id when Mosaic had to normalize/deduplicate it. */
  originalCellId?: string
  cellType: 'code' | 'markdown' | 'raw' | 'output'
  originalIndex: number
  language?: string
  executionCount?: number | null
  parentCellId?: string
  /** Original cell source before Mosaic normalizes SQL magics or attachments. */
  originalSource?: string
  /** Exact editor source created at import time. Used to detect untouched cells on export. */
  importedEditorSource?: string
  /** Jupyter cell metadata is preserved for .ipynb round trips. */
  cellMetadata?: Record<string, unknown>
  /** Markdown attachments are kept even though Mosaic hydrates them for preview. */
  attachments?: Record<string, Record<string, string | string[]>>
}

export interface WorkbenchPanel {
  id: string
  type: PanelType
  title: string
  subtitle?: string
  notebook?: NotebookCellMeta
}
