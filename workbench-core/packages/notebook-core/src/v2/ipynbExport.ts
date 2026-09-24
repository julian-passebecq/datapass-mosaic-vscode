import type { Layout } from 'react-grid-layout'
import type { WorkbenchPanel } from '../types.ts'
import type { ImportedNotebookInfo, JupyterOutputSnapshot } from './ipynb.ts'
import type { NotebookView } from './model.ts'
import type { StorageReader } from './projectExport.ts'

interface ExportCell {
  id: string
  cell_type: 'markdown' | 'raw' | 'code'
  metadata: Record<string, unknown>
  source: string[]
  execution_count?: number | null
  outputs?: Array<Record<string, unknown>>
  attachments?: Record<string, Record<string, string | string[]>>
}

export interface ExportedIpynbDocument {
  cells: ExportCell[]
  metadata: Record<string, unknown>
  nbformat: 4
  nbformat_minor: 5
}

type MosaicViewMetadata = {
  id: string
  label: string
  description: string
  blockRefs: string[]
  layout: Array<Record<string, unknown>>
  defaultLayout: Array<Record<string, unknown>>
  collapsedRefs: string[]
  expandedHeights: Array<{ ref: string; height: number }>
}

function slug(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 56) || 'cell'
}

function uniqueCellId(candidate: string, used: Set<string>) {
  let base = candidate.replace(/[^A-Za-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 64)
  if (!base) base = 'cell'
  let id = base
  let suffix = 2
  while (used.has(id)) {
    const tail = `-${suffix}`
    id = `${base.slice(0, Math.max(1, 64 - tail.length))}${tail}`
    suffix += 1
  }
  used.add(id)
  return id
}

function sourceLines(value: string) {
  if (!value) return []
  const pieces = value.split(/(?<=\n)/)
  return pieces.length ? pieces : [value]
}

function readState(storage: StorageReader, key: string, fallback = '') {
  const raw = storage.getItem(key)
  if (raw === null) return fallback
  try {
    const parsed = JSON.parse(raw)
    return typeof parsed === 'string' ? parsed : fallback
  } catch {
    return raw
  }
}

function readOutputs(storage: StorageReader, blockId: string): JupyterOutputSnapshot[] {
  const raw = storage.getItem(`mosaic:v2:jupyter-output:${blockId}`)
  if (raw === null) return []
  try {
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed as JupyterOutputSnapshot[] : []
  } catch {
    return []
  }
}

function normalizedOutputToJupyter(output: JupyterOutputSnapshot): Record<string, unknown> {
  if (output.raw && typeof output.raw === 'object' && !Array.isArray(output.raw)) return output.raw
  if (output.outputType === 'stream') {
    return { output_type: 'stream', name: output.name ?? 'stdout', text: sourceLines(output.text ?? '') }
  }
  if (output.outputType === 'error') {
    return {
      output_type: 'error',
      ename: output.errorName ?? 'Error',
      evalue: output.errorValue ?? '',
      traceback: output.traceback ?? []
    }
  }
  if (output.outputType === 'display_data' || output.outputType === 'execute_result') {
    const data: Record<string, unknown> = {}
    if (output.text !== undefined) data['text/plain'] = sourceLines(output.text)
    if (output.html !== undefined) data['text/html'] = sourceLines(output.html)
    if (output.svg !== undefined) data['image/svg+xml'] = sourceLines(output.svg)
    if (output.imagePng !== undefined) data['image/png'] = output.imagePng
    if (output.imageJpeg !== undefined) data['image/jpeg'] = output.imageJpeg
    if (output.latex !== undefined) data['text/latex'] = sourceLines(output.latex)
    if (output.markdown !== undefined) data['text/markdown'] = sourceLines(output.markdown)
    if (output.table !== undefined) {
      data['application/vnd.dataresource+json'] = {
        schema: { fields: output.table.columns.map((name) => ({ name })) },
        data: output.table.rows
      }
    }
    if (output.json !== undefined) data['application/json'] = output.json
    return {
      output_type: output.outputType,
      data,
      metadata: {},
      ...(output.outputType === 'execute_result' ? { execution_count: output.executionCount ?? null } : {})
    }
  }
  return { output_type: 'stream', name: 'stdout', text: sourceLines(output.text ?? '') }
}

function cloneMetadata(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
  try { return JSON.parse(JSON.stringify(value)) as Record<string, unknown> } catch { return {} }
}

function exportable(block: WorkbenchPanel) {
  return block.type === 'markdown' || block.type === 'sql' || block.type === 'python' || block.type === 'polars'
}

function preferredSource(block: WorkbenchPanel, storage: StorageReader) {
  const meta = block.notebook
  if (meta?.cellType === 'code' && block.type === 'markdown') return meta.originalSource ?? ''
  const namespace = block.type === 'markdown' ? 'markdown' : 'code'
  const current = readState(storage, `mosaic:v2:${namespace}:${block.id}`, meta?.importedEditorSource ?? meta?.originalSource ?? '')
  if (meta?.originalSource !== undefined && meta.importedEditorSource !== undefined && current === meta.importedEditorSource) {
    return meta.originalSource
  }
  if (block.type === 'sql') return `%%sql\n${current}`
  return current
}

function layoutRef(item: Layout[number], ref: string) {
  const result: Record<string, unknown> = { ref, x: item.x, y: item.y, w: item.w, h: item.h }
  for (const key of ['minW', 'minH', 'maxW', 'maxH', 'static', 'isDraggable', 'isResizable'] as const) {
    const value = item[key]
    if (value !== undefined) result[key] = value
  }
  return result
}

function exportMosaicViews(views: NotebookView[], refByBlockId: Map<string, string>): MosaicViewMetadata[] {
  return views.map((view) => {
    const blockRefs = view.blockIds.map((id) => refByBlockId.get(id)).filter((value): value is string => Boolean(value))
    const allowed = new Set(blockRefs)
    const encodeLayout = (layout: Layout | undefined) => (layout ?? [])
      .map((item) => {
        const ref = refByBlockId.get(item.i)
        return ref && allowed.has(ref) ? layoutRef(item, ref) : null
      })
      .filter((item): item is Record<string, unknown> => Boolean(item))
    return {
      id: view.id,
      label: view.label,
      description: view.description,
      blockRefs,
      layout: encodeLayout(view.layout),
      defaultLayout: encodeLayout(view.defaultLayout ?? view.layout),
      collapsedRefs: (view.collapsedIds ?? []).map((id) => refByBlockId.get(id)).filter((value): value is string => Boolean(value)),
      expandedHeights: Object.entries(view.expandedHeights ?? {})
        .map(([id, height]) => {
          const ref = refByBlockId.get(id)
          return ref && Number.isFinite(height) ? { ref, height } : null
        })
        .filter((item): item is { ref: string; height: number } => Boolean(item))
    }
  })
}

/**
 * Export the semantic Mosaic notebook to nbformat 4.5. Presentation-only
 * blocks (table/chart/catalog) stay in Mosaic project JSON; executable/text
 * cells and saved Jupyter outputs round-trip through .ipynb.
 */
export function buildIpynbDocument({
  blocks,
  views,
  notebookInfo,
  storage,
  exportedAt = new Date().toISOString()
}: {
  blocks: WorkbenchPanel[]
  views: NotebookView[]
  notebookInfo: ImportedNotebookInfo | null
  storage: StorageReader
  exportedAt?: string
}): ExportedIpynbDocument {
  const byId = new Map(blocks.map((block) => [block.id, block]))
  const notebookOrder = views.find((view) => view.id === 'notebook')?.blockIds
  // .ipynb represents the semantic notebook document, not every project-only
  // presentation block. Blocks that exist only in Split/Dashboard/Free Canvas
  // remain available in the full Mosaic project JSON export.
  const orderedIds = notebookOrder?.length ? notebookOrder : blocks.map((block) => block.id)
  const orderedBlocks = orderedIds.map((id) => byId.get(id)).filter((block): block is WorkbenchPanel => Boolean(block))

  const usedCellIds = new Set<string>()
  const cellIdByBlockId = new Map<string, string>()
  const resolvedByOriginalCellId = new Map<string, string>()

  for (const block of orderedBlocks) {
    if (!exportable(block)) continue
    const preferred = block.notebook?.cellId ?? `mosaic-${slug(block.id)}`
    const cellId = uniqueCellId(preferred, usedCellIds)
    cellIdByBlockId.set(block.id, cellId)
    if (block.notebook?.cellId && !resolvedByOriginalCellId.has(block.notebook.cellId)) resolvedByOriginalCellId.set(block.notebook.cellId, cellId)
  }

  const outputBlocksByParent = new Map<string, WorkbenchPanel[]>()
  for (const block of blocks) {
    if (block.type !== 'notebook-output' || !block.notebook?.parentCellId) continue
    const list = outputBlocksByParent.get(block.notebook.parentCellId) ?? []
    list.push(block)
    outputBlocksByParent.set(block.notebook.parentCellId, list)
  }

  const cells: ExportCell[] = []
  for (const block of orderedBlocks) {
    if (!exportable(block)) continue
    const id = cellIdByBlockId.get(block.id)
    if (!id) continue
    const meta = block.notebook
    const cellMetadata = cloneMetadata(meta?.cellMetadata)
    const source = preferredSource(block, storage)

    if (meta?.cellType === 'raw') {
      cells.push({ id, cell_type: 'raw', metadata: cellMetadata, source: sourceLines(source) })
      continue
    }
    if (meta?.cellType === 'markdown' || (!meta && block.type === 'markdown')) {
      cells.push({
        id,
        cell_type: 'markdown',
        metadata: cellMetadata,
        source: sourceLines(source),
        ...(meta?.attachments ? { attachments: meta.attachments } : {})
      })
      continue
    }

    const originalParentKey = meta?.cellId
    const outputBlocks = originalParentKey ? outputBlocksByParent.get(originalParentKey) ?? [] : []
    const outputs = outputBlocks.flatMap((outputBlock) => readOutputs(storage, outputBlock.id).map(normalizedOutputToJupyter))
    cells.push({
      id,
      cell_type: 'code',
      metadata: cellMetadata,
      source: sourceLines(source),
      execution_count: meta?.executionCount ?? null,
      outputs
    })
  }

  const refByBlockId = new Map<string, string>()
  for (const [blockId, cellId] of cellIdByBlockId) refByBlockId.set(blockId, `cell:${cellId}`)
  for (const block of blocks) {
    if (block.type !== 'notebook-output' || !block.notebook?.parentCellId) continue
    const parent = resolvedByOriginalCellId.get(block.notebook.parentCellId)
    if (parent) refByBlockId.set(block.id, `output:${parent}`)
  }

  const metadata = cloneMetadata(notebookInfo?.metadata)
  if (!metadata.language_info) metadata.language_info = { name: notebookInfo?.language ?? 'python' }
  if (!metadata.kernelspec && (notebookInfo?.kernel || notebookInfo?.language)) {
    metadata.kernelspec = { display_name: notebookInfo?.kernel ?? 'Python 3', language: notebookInfo?.language ?? 'python', name: 'python3' }
  }
  metadata.mosaic = {
    version: '2.1.7',
    exportedAt,
    note: 'Mosaic layout metadata for exported notebook cells. Jupyter ignores this namespace safely; use Mosaic project JSON for full project fidelity.',
    views: exportMosaicViews(views, refByBlockId)
  }

  return { cells, metadata, nbformat: 4, nbformat_minor: 5 }
}
