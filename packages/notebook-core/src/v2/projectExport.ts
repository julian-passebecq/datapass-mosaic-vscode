import type { Layout } from 'react-grid-layout'
import type { DatasetInfo, NotebookCellMeta, PanelType, ResultTable, WorkbenchPanel } from '../types.ts'
import type { ImportedNotebookInfo } from './ipynb.ts'
import type { NotebookView } from './model.ts'

export type StorageReader = { getItem: (key: string) => string | null }

export interface MosaicProjectSnapshot {
  format: 'mosaic-v2-notebook-project'
  version: string
  exportedAt?: string
  currentViewId: string
  blocks: WorkbenchPanel[]
  views: NotebookView[]
  datasets: DatasetInfo[]
  notebookInfo: ImportedNotebookInfo | null
  result: ResultTable
  blockState: Record<string, unknown>
}

/**
 * Collect only state owned by blocks that belong to the current project.
 * UI preferences and stale/deleted block keys are intentionally excluded.
 */
export function collectProjectBlockState(blocks: WorkbenchPanel[], storage: StorageReader) {
  const result: Record<string, unknown> = {}
  const namespaces = ['code', 'markdown', 'jupyter-output']
  for (const block of blocks) {
    for (const namespace of namespaces) {
      const key = `mosaic:v2:${namespace}:${block.id}`
      const raw = storage.getItem(key)
      if (raw === null) continue
      try { result[key] = JSON.parse(raw) } catch { result[key] = raw }
    }
  }
  return result
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function finiteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function finiteNonNegative(value: unknown): value is number {
  return finiteNumber(value) && value >= 0
}

const panelTypes = new Set<PanelType>(['sql', 'python', 'polars', 'markdown', 'table', 'chart', 'catalog', 'notebook-output'])
const datasetKinds = new Set<DatasetInfo['kind']>(['table', 'view', 'csv', 'parquet', 'cloud', 'lakehouse'])
const runtimes = new Set<DatasetInfo['runtime']>(['browser', 'cloud', 'native'])
const datasetLayers = new Set<NonNullable<DatasetInfo['layer']>>(['source', 'bronze', 'silver', 'gold'])
const producedByValues = new Set<NonNullable<DatasetInfo['producedBy']>>(['SQL', 'Python', 'Polars', 'Import'])
const qualityValues = new Set<NonNullable<DatasetInfo['quality']>>(['unchecked', 'passed', 'failed'])
const resultKinds = new Set<NonNullable<ResultTable['origin']>['kind']>(['demo', 'sql', 'python', 'polars', 'import'])
const notebookCellTypes = new Set<NotebookCellMeta['cellType']>(['code', 'markdown', 'raw', 'output'])

function cloneRecord(value: unknown): Record<string, unknown> | undefined {
  if (!isRecord(value)) return undefined
  try { return JSON.parse(JSON.stringify(value)) as Record<string, unknown> } catch { return undefined }
}

function sanitizeAttachments(value: unknown): NotebookCellMeta['attachments'] | undefined {
  if (!isRecord(value)) return undefined
  const attachments: NonNullable<NotebookCellMeta['attachments']> = {}
  for (const [name, bundle] of Object.entries(value)) {
    if (!isRecord(bundle)) continue
    const next: Record<string, string | string[]> = {}
    for (const [mime, payload] of Object.entries(bundle)) {
      if (typeof payload === 'string') next[mime] = payload
      else if (Array.isArray(payload) && payload.every((item) => typeof item === 'string')) next[mime] = [...payload] as string[]
    }
    if (Object.keys(next).length) attachments[name] = next
  }
  return Object.keys(attachments).length ? attachments : undefined
}

function sanitizeNotebookMeta(value: unknown): NotebookCellMeta | undefined {
  if (!isRecord(value) || value.source !== 'ipynb') return undefined
  if (typeof value.cellId !== 'string' || !value.cellId) return undefined
  if (typeof value.cellType !== 'string' || !notebookCellTypes.has(value.cellType as NotebookCellMeta['cellType'])) return undefined
  if (!finiteNonNegative(value.originalIndex)) return undefined

  const meta: NotebookCellMeta = {
    source: 'ipynb',
    cellId: value.cellId,
    cellType: value.cellType as NotebookCellMeta['cellType'],
    originalIndex: Math.floor(value.originalIndex)
  }
  if (typeof value.originalCellId === 'string' && value.originalCellId) meta.originalCellId = value.originalCellId
  if (typeof value.language === 'string') meta.language = value.language
  if (value.executionCount === null || finiteNumber(value.executionCount)) meta.executionCount = value.executionCount as number | null
  if (typeof value.parentCellId === 'string') meta.parentCellId = value.parentCellId
  if (typeof value.originalSource === 'string') meta.originalSource = value.originalSource
  if (typeof value.importedEditorSource === 'string') meta.importedEditorSource = value.importedEditorSource
  const cellMetadata = cloneRecord(value.cellMetadata)
  if (cellMetadata) meta.cellMetadata = cellMetadata
  const attachments = sanitizeAttachments(value.attachments)
  if (attachments) meta.attachments = attachments
  return meta
}

function sanitizePanel(value: unknown): WorkbenchPanel | null {
  if (!isRecord(value)) return null
  if (typeof value.id !== 'string' || !value.id) return null
  if (typeof value.type !== 'string' || !panelTypes.has(value.type as PanelType)) return null
  if (typeof value.title !== 'string') return null
  const panel: WorkbenchPanel = { id: value.id, type: value.type as PanelType, title: value.title }
  if (typeof value.subtitle === 'string') panel.subtitle = value.subtitle
  const notebook = sanitizeNotebookMeta(value.notebook)
  if (notebook) panel.notebook = notebook
  return panel
}

function sanitizeDataset(value: unknown): DatasetInfo | null {
  if (!isRecord(value)) return null
  if (typeof value.id !== 'string' || typeof value.name !== 'string' || typeof value.detail !== 'string') return null
  if (typeof value.kind !== 'string' || !datasetKinds.has(value.kind as DatasetInfo['kind'])) return null
  if (typeof value.runtime !== 'string' || !runtimes.has(value.runtime as DatasetInfo['runtime'])) return null
  const dataset: DatasetInfo = {
    id: value.id,
    name: value.name,
    kind: value.kind as DatasetInfo['kind'],
    detail: value.detail,
    runtime: value.runtime as DatasetInfo['runtime']
  }
  if (typeof value.tableName === 'string') dataset.tableName = value.tableName
  if (typeof value.layer === 'string' && datasetLayers.has(value.layer as NonNullable<DatasetInfo['layer']>)) dataset.layer = value.layer as NonNullable<DatasetInfo['layer']>
  if (typeof value.producedBy === 'string' && producedByValues.has(value.producedBy as NonNullable<DatasetInfo['producedBy']>)) dataset.producedBy = value.producedBy as NonNullable<DatasetInfo['producedBy']>
  if (typeof value.quality === 'string' && qualityValues.has(value.quality as NonNullable<DatasetInfo['quality']>)) dataset.quality = value.quality as NonNullable<DatasetInfo['quality']>
  if (typeof value.qualityDetail === 'string') dataset.qualityDetail = value.qualityDetail
  if (typeof value.assetFingerprint === 'string') dataset.assetFingerprint = value.assetFingerprint
  return dataset
}

function sanitizeOrigin(value: unknown): NonNullable<ResultTable['origin']> | undefined {
  if (!isRecord(value)) return undefined
  if (typeof value.blockId !== 'string' || typeof value.label !== 'string' || typeof value.createdAt !== 'string') return undefined
  if (typeof value.kind !== 'string' || !resultKinds.has(value.kind as NonNullable<ResultTable['origin']>['kind'])) return undefined
  if (typeof value.runtime !== 'string' || !runtimes.has(value.runtime as DatasetInfo['runtime'])) return undefined
  return {
    blockId: value.blockId,
    label: value.label,
    kind: value.kind as NonNullable<ResultTable['origin']>['kind'],
    runtime: value.runtime as NonNullable<ResultTable['origin']>['runtime'],
    createdAt: value.createdAt,
    ...(typeof value.parentResultId === 'string' ? { parentResultId: value.parentResultId } : {})
  }
}

/** Restore a row-backed result snapshot without trusting stale Arrow metadata. */
export function restoreResultSnapshot(value: unknown): ResultTable | null {
  if (!isRecord(value) || !Array.isArray(value.columns) || !Array.isArray(value.rows)) return null
  const schema = Array.isArray(value.schema)
    ? value.schema.filter((field): field is Record<string, unknown> => isRecord(field) && typeof field.name === 'string' && typeof field.type === 'string')
      .map((field) => ({ name: String(field.name), type: String(field.type) }))
    : undefined
  const rows = value.rows.filter(isRecord).map((row) => ({ ...row }))
  const totalRows = finiteNonNegative(value.totalRows) ? Math.floor(value.totalRows) : rows.length
  return {
    ...(typeof value.id === 'string' ? { id: value.id } : {}),
    ...(finiteNonNegative(value.revision) ? { revision: Math.floor(value.revision) } : {}),
    columns: value.columns.map(String),
    rows,
    ...(schema ? { schema } : {}),
    transport: 'rows',
    ...(finiteNonNegative(value.elapsedMs) ? { elapsedMs: value.elapsedMs } : {}),
    totalRows,
    truncated: Boolean(value.truncated || totalRows > rows.length),
    ...(sanitizeOrigin(value.origin) ? { origin: sanitizeOrigin(value.origin) } : {})
  }
}

function sanitizeNotebookInfo(value: unknown): ImportedNotebookInfo | null {
  if (!isRecord(value)) return null
  if (typeof value.fileName !== 'string' || typeof value.title !== 'string' || typeof value.language !== 'string') return null
  if (![value.cellCount, value.codeCellCount, value.markdownCellCount, value.outputBlockCount].every(finiteNonNegative)) return null
  if (typeof value.importedAt !== 'string') return null
  const info: ImportedNotebookInfo = {
    fileName: value.fileName,
    title: value.title,
    language: value.language,
    cellCount: Math.floor(value.cellCount as number),
    codeCellCount: Math.floor(value.codeCellCount as number),
    markdownCellCount: Math.floor(value.markdownCellCount as number),
    outputBlockCount: Math.floor(value.outputBlockCount as number),
    importedAt: value.importedAt
  }
  if (typeof value.kernel === 'string') info.kernel = value.kernel
  const metadata = cloneRecord(value.metadata)
  if (metadata) info.metadata = metadata
  return info
}

function validView(value: unknown): value is NotebookView {
  if (!isRecord(value)) return false
  return typeof value.id === 'string' && value.id.length > 0 && typeof value.label === 'string' && Array.isArray(value.blockIds) && Array.isArray(value.layout)
}

/**
 * Only accept geometry React Grid Layout can safely render. Imported projects
 * are user-controlled JSON, so malformed coordinates must not reach the grid.
 */
function sanitizeLayoutItem(value: unknown, allowedIds: Set<string>): Layout[number] | null {
  if (!isRecord(value) || typeof value.i !== 'string' || !allowedIds.has(value.i)) return null
  if (![value.x, value.y, value.w, value.h].every(finiteNumber)) return null
  const x = Math.max(0, Math.min(11, Math.floor(value.x as number)))
  const y = Math.max(0, Math.floor(value.y as number))
  const w = Math.max(1, Math.min(12 - x, Math.floor(value.w as number)))
  const h = Math.max(1, Math.floor(value.h as number))
  const item: Layout[number] = { i: value.i, x, y, w, h }
  if (finiteNumber(value.minW)) item.minW = Math.max(1, Math.min(w, Math.floor(value.minW)))
  if (finiteNumber(value.minH)) item.minH = Math.max(1, Math.min(h, Math.floor(value.minH)))
  if (finiteNumber(value.maxW)) item.maxW = Math.max(w, Math.min(12, Math.floor(value.maxW)))
  if (finiteNumber(value.maxH)) item.maxH = Math.max(h, Math.floor(value.maxH))
  if (typeof value.isDraggable === 'boolean') item.isDraggable = value.isDraggable
  if (typeof value.isResizable === 'boolean') item.isResizable = value.isResizable
  if (typeof value.static === 'boolean') item.static = value.static
  return item
}

function dedupeIds(values: unknown[], allowedIds: Set<string>) {
  const seen = new Set<string>()
  const result: string[] = []
  for (const value of values) {
    if (typeof value !== 'string' || !allowedIds.has(value) || seen.has(value)) continue
    seen.add(value)
    result.push(value)
  }
  return result
}

function sanitizeLayout(values: unknown[], visibleIds: string[]) {
  const allowedIds = new Set(visibleIds)
  const seen = new Set<string>()
  const result: Layout[number][] = []
  for (const value of values) {
    const item = sanitizeLayoutItem(value, allowedIds)
    if (!item || seen.has(item.i)) continue
    seen.add(item.i)
    result.push(item)
  }

  // A visible block without geometry would otherwise vanish from RGL. Recover
  // it at the bottom rather than silently losing it from the imported view.
  let bottom = result.reduce((max, item) => Math.max(max, item.y + item.h), 0)
  for (const id of visibleIds) {
    if (seen.has(id)) continue
    result.push({ i: id, x: 0, y: bottom, w: 12, h: 8, minW: 3, minH: 4 })
    bottom += 8
  }
  return result
}

function sanitizeOutputArray(value: unknown) {
  if (!Array.isArray(value)) return undefined
  const outputs = value.filter(isRecord).map((item) => ({ ...item }))
  return outputs
}

function sanitizeBlockState(value: unknown, blocks: WorkbenchPanel[]) {
  if (!isRecord(value)) return {}
  const result: Record<string, unknown> = {}
  for (const block of blocks) {
    const codeKey = `mosaic:v2:code:${block.id}`
    const markdownKey = `mosaic:v2:markdown:${block.id}`
    const outputKey = `mosaic:v2:jupyter-output:${block.id}`
    if (typeof value[codeKey] === 'string') result[codeKey] = value[codeKey]
    if (typeof value[markdownKey] === 'string') result[markdownKey] = value[markdownKey]
    const outputs = sanitizeOutputArray(value[outputKey])
    if (outputs) result[outputKey] = outputs
  }
  return result
}

export function parseProjectSnapshot(text: string): MosaicProjectSnapshot {
  const raw = JSON.parse(text) as unknown
  if (!isRecord(raw) || raw.format !== 'mosaic-v2-notebook-project') throw new Error('This JSON file is not a Mosaic V2 notebook project.')
  if (!Array.isArray(raw.blocks)) throw new Error('Invalid Mosaic project: blocks are missing or malformed.')
  const blocks = raw.blocks.map(sanitizePanel)
  if (blocks.some((block) => !block)) throw new Error('Invalid Mosaic project: blocks are missing or malformed.')
  const safeBlocks = blocks as WorkbenchPanel[]
  if (!Array.isArray(raw.views) || !raw.views.every(validView)) throw new Error('Invalid Mosaic project: views are missing or malformed.')

  const ids = new Set(safeBlocks.map((block) => block.id))
  if (ids.size !== safeBlocks.length) throw new Error('Invalid Mosaic project: duplicate block IDs detected.')

  const seenViewIds = new Set<string>()
  const views = (raw.views as NotebookView[]).map((view) => {
    if (seenViewIds.has(view.id)) throw new Error(`Invalid Mosaic project: duplicate view ID "${view.id}".`)
    seenViewIds.add(view.id)
    const blockIds = dedupeIds(view.blockIds as unknown[], ids)
    const layout = sanitizeLayout(view.layout as unknown[], blockIds)
    const defaultLayout = view.defaultLayout ? sanitizeLayout(view.defaultLayout as unknown[], blockIds) : layout.map((item) => ({ ...item }))
    const collapsedIds = dedupeIds((view.collapsedIds ?? []) as unknown[], new Set(blockIds))
    const expandedHeights = Object.fromEntries(
      Object.entries(view.expandedHeights ?? {}).filter(([id, height]) => blockIds.includes(id) && finiteNumber(height) && height > 0)
    )
    return { ...view, blockIds, layout, defaultLayout, collapsedIds, expandedHeights }
  })
  if (!views.length) throw new Error('Invalid Mosaic project: no usable views.')

  const result = restoreResultSnapshot(raw.result) ?? { columns: [], rows: [], totalRows: 0, truncated: false, transport: 'rows' as const }
  const currentViewId = typeof raw.currentViewId === 'string' && views.some((view) => view.id === raw.currentViewId)
    ? raw.currentViewId
    : views[0].id

  return {
    format: 'mosaic-v2-notebook-project',
    version: typeof raw.version === 'string' ? raw.version : 'unknown',
    exportedAt: typeof raw.exportedAt === 'string' ? raw.exportedAt : undefined,
    currentViewId,
    blocks: safeBlocks,
    views,
    datasets: Array.isArray(raw.datasets) ? raw.datasets.map(sanitizeDataset).filter((item): item is DatasetInfo => Boolean(item)) : [],
    notebookInfo: sanitizeNotebookInfo(raw.notebookInfo),
    result,
    blockState: sanitizeBlockState(raw.blockState, safeBlocks)
  }
}
