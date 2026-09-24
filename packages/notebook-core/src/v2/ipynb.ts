import type { Layout } from 'react-grid-layout'
import type { NotebookCellMeta, PanelType, WorkbenchPanel } from '../types.ts'
import type { NotebookView } from './model.ts'

export interface JupyterOutputSnapshot {
  outputType: 'stream' | 'display_data' | 'execute_result' | 'error' | 'unknown'
  name?: string
  text?: string
  html?: string
  svg?: string
  imagePng?: string
  imageJpeg?: string
  json?: unknown
  latex?: string
  markdown?: string
  table?: { columns: string[]; rows: Array<Record<string, unknown>> }
  errorName?: string
  errorValue?: string
  traceback?: string[]
  executionCount?: number | null
  /** Original Jupyter output payload for high-fidelity export. */
  raw?: Record<string, unknown>
}

export interface ImportedNotebookInfo {
  fileName: string
  title: string
  language: string
  kernel?: string
  cellCount: number
  codeCellCount: number
  markdownCellCount: number
  outputBlockCount: number
  importedAt: string
  metadata?: Record<string, unknown>
}

export interface ImportedNotebookProject {
  blocks: WorkbenchPanel[]
  views: NotebookView[]
  blockState: Record<string, unknown>
  info: ImportedNotebookInfo
}

type IpynbCell = {
  id?: string
  cell_type?: string
  source?: string | string[]
  metadata?: Record<string, unknown>
  execution_count?: number | null
  outputs?: Array<Record<string, unknown>>
  attachments?: Record<string, Record<string, string | string[]>>
}

type IpynbDocument = {
  cells?: IpynbCell[]
  metadata?: Record<string, any>
  nbformat?: number
  nbformat_minor?: number
}

function sourceText(source: string | string[] | undefined) {
  if (Array.isArray(source)) return source.join('')
  return typeof source === 'string' ? source : ''
}

function slug(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 56) || 'cell'
}

function uniqueId(base: string, used: Set<string>) {
  let id = base
  let index = 2
  while (used.has(id)) {
    id = `${base}-${index}`
    index += 1
  }
  used.add(id)
  return id
}


function normalizeCellId(value: unknown, index: number, used: Set<string>) {
  const raw = typeof value === 'string' && value.trim() ? value.trim() : `cell-${index + 1}`
  const base = raw.replace(/[^A-Za-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 64) || `cell-${index + 1}`
  let id = base
  let suffix = 2
  while (used.has(id)) {
    const tail = `-${suffix}`
    id = `${base.slice(0, Math.max(1, 64 - tail.length))}${tail}`
    suffix += 1
  }
  used.add(id)
  return { id, original: raw }
}

function dataText(value: unknown): string | undefined {
  if (Array.isArray(value)) return value.join('')
  if (typeof value === 'string') return value
  return undefined
}

function outputData(output: Record<string, unknown>) {
  return (output.data && typeof output.data === 'object' ? output.data : {}) as Record<string, unknown>
}


function normalizeDataResource(value: unknown): JupyterOutputSnapshot['table'] {
  if (!value || typeof value !== 'object') return undefined
  const resource = value as Record<string, unknown>
  const data = Array.isArray(resource.data) ? resource.data : []
  const schema = resource.schema && typeof resource.schema === 'object' ? resource.schema as Record<string, unknown> : {}
  const fields = Array.isArray(schema.fields) ? schema.fields : []
  const columns = fields
    .map((field) => field && typeof field === 'object' ? String((field as Record<string, unknown>).name ?? '') : '')
    .filter(Boolean)
  const rows = data.filter((row): row is Record<string, unknown> => Boolean(row) && typeof row === 'object' && !Array.isArray(row))
  const inferred = columns.length ? columns : Array.from(new Set(rows.flatMap((row) => Object.keys(row))))
  if (!inferred.length && !rows.length) return undefined
  return { columns: inferred, rows }
}
function normalizeOutput(output: Record<string, unknown>): JupyterOutputSnapshot {
  const outputType = String(output.output_type ?? 'unknown') as JupyterOutputSnapshot['outputType']
  if (outputType === 'stream') {
    return { outputType, name: String(output.name ?? 'stdout'), text: dataText(output.text) ?? '', raw: output }
  }
  if (outputType === 'error') {
    return {
      outputType,
      errorName: String(output.ename ?? 'Error'),
      errorValue: String(output.evalue ?? ''),
      traceback: Array.isArray(output.traceback) ? output.traceback.map(String) : [],
      raw: output
    }
  }
  if (outputType === 'display_data' || outputType === 'execute_result') {
    const data = outputData(output)
    return {
      outputType,
      executionCount: typeof output.execution_count === 'number' ? output.execution_count : null,
      text: dataText(data['text/plain']),
      html: dataText(data['text/html']),
      svg: dataText(data['image/svg+xml']),
      imagePng: dataText(data['image/png']),
      imageJpeg: dataText(data['image/jpeg']),
      latex: dataText(data['text/latex']),
      markdown: dataText(data['text/markdown']),
      table: normalizeDataResource(data['application/vnd.dataresource+json']),
      json: data['application/json'] ?? data['application/vnd.plotly.v1+json'],
      raw: output
    }
  }
  return { outputType: 'unknown', text: JSON.stringify(output, null, 2), raw: output }
}

function attachmentDataUrl(bundle: Record<string, string | string[]> | undefined) {
  if (!bundle) return undefined
  const candidates = ['image/png', 'image/jpeg', 'image/svg+xml']
  for (const mime of candidates) {
    const value = dataText(bundle[mime])
    if (!value) continue
    if (mime === 'image/svg+xml') return `data:${mime};utf8,${encodeURIComponent(value)}`
    return `data:${mime};base64,${value}`
  }
  return undefined
}

function hydrateAttachments(markdown: string, attachments: IpynbCell['attachments']) {
  if (!attachments) return markdown
  return markdown.replace(/attachment:([^\s)]+)/g, (match, name: string) => attachmentDataUrl(attachments[name]) ?? match)
}

function detectCodeLanguage(code: string, notebookLanguage: string) {
  const firstLine = code.split(/\r?\n/, 1)[0]?.trim().toLowerCase() ?? ''
  if (/^%%?(sql|duckdb)\b/.test(firstLine)) return 'sql'
  const cellMagic = firstLine.match(/^%%([a-z0-9_-]+)\b/)
  if (cellMagic) return cellMagic[1]
  if (/^[%!]/.test(firstLine)) return 'ipython-magic'
  if (notebookLanguage.toLowerCase().includes('python')) return 'python'
  return notebookLanguage.toLowerCase() || 'python'
}

function stripSqlMagic(code: string) {
  const lines = code.split(/\r?\n/)
  const first = lines[0]?.trim() ?? ''
  if (/^%%(sql|duckdb)\b/i.test(first)) return lines.slice(1).join('\n')
  const match = first.match(/^%(?:sql|duckdb)\s+(.+)$/i)
  if (match) return [match[1], ...lines.slice(1)].join('\n')
  return code
}

function blockHeight(type: PanelType, source = '') {
  if (type === 'markdown') return Math.max(5, Math.min(10, 4 + Math.ceil(source.split(/\r?\n/).length / 4)))
  if (type === 'notebook-output') return 7
  if (type === 'sql' || type === 'python' || type === 'polars') return 10
  return 8
}

function verticalLayout(blocks: WorkbenchPanel[], sourceById: Map<string, string>): Layout {
  let y = 0
  return blocks.map((block) => {
    const h = blockHeight(block.type, sourceById.get(block.id))
    const item = { i: block.id, x: 1, y, w: 10, h, minW: 4, minH: 4 }
    y += h
    return item
  })
}

function cellGroups(blocks: WorkbenchPanel[]) {
  const groups: WorkbenchPanel[][] = []
  const groupByCellId = new Map<string, WorkbenchPanel[]>()
  for (const block of blocks) {
    if (block.notebook?.cellType === 'output' && block.notebook.parentCellId) {
      const parentGroup = groupByCellId.get(block.notebook.parentCellId)
      if (parentGroup) {
        parentGroup.push(block)
        continue
      }
    }
    const group = [block]
    groups.push(group)
    if (block.notebook?.cellId && block.notebook.cellType !== 'output') groupByCellId.set(block.notebook.cellId, group)
  }
  return groups
}

function groupHeight(group: WorkbenchPanel[], sourceById: Map<string, string>) {
  return group.reduce((sum, block) => sum + blockHeight(block.type, sourceById.get(block.id)), 0)
}

function balancedSplitIndex(groups: WorkbenchPanel[][], sourceById: Map<string, string>) {
  if (groups.length <= 1) return groups.length
  const heights = groups.map((group) => groupHeight(group, sourceById))
  const total = heights.reduce((sum, value) => sum + value, 0)
  let left = 0
  let bestIndex = 1
  let bestDelta = Number.POSITIVE_INFINITY
  for (let index = 1; index < groups.length; index += 1) {
    left += heights[index - 1]
    const delta = Math.abs(left - (total - left))
    if (delta < bestDelta) {
      bestDelta = delta
      bestIndex = index
    }
  }
  return bestIndex
}

function splitLayout(blocks: WorkbenchPanel[], sourceById: Map<string, string>): Layout {
  const groups = cellGroups(blocks)
  // Keep notebook order intact, but choose the break based on estimated visual
  // height instead of raw cell count. Long markdown/code cells therefore do not
  // leave one "page" almost empty while the other scrolls far below it.
  const splitAt = balancedSplitIndex(groups, sourceById)
  const columns = [groups.slice(0, splitAt), groups.slice(splitAt)]
  const layout: Layout[number][] = []
  columns.forEach((column, columnIndex) => {
    let y = 0
    column.forEach((group) => {
      group.forEach((block) => {
        const h = blockHeight(block.type, sourceById.get(block.id))
        layout.push({ i: block.id, x: columnIndex * 6, y, w: 6, h, minW: 3, minH: 4 })
        y += h
      })
    })
  })
  return layout
}

function explainLayout(blocks: WorkbenchPanel[], sourceById: Map<string, string>): Layout {
  const layout: Layout[number][] = []
  let leftY = 0
  let rightY = 0
  for (const block of blocks) {
    const h = blockHeight(block.type, sourceById.get(block.id))
    const isExplanation = block.type === 'markdown'
    if (isExplanation) {
      layout.push({ i: block.id, x: 8, y: rightY, w: 4, h, minW: 3, minH: 4 })
      rightY += h
    } else {
      layout.push({ i: block.id, x: 0, y: leftY, w: 8, h, minW: 4, minH: 4 })
      leftY += h
    }
  }
  return layout
}

function twoPlusOneLayout(blocks: WorkbenchPanel[], sourceById: Map<string, string>): Layout {
  const groups = cellGroups(blocks)
  const layout: Layout[number][] = []
  let bottomY = 10
  groups.forEach((group, groupIndex) => {
    if (groupIndex < 2) {
      let y = 0
      for (const block of group) {
        const h = Math.min(10, blockHeight(block.type, sourceById.get(block.id)))
        layout.push({ i: block.id, x: groupIndex * 6, y, w: 6, h, minW: 3, minH: 4 })
        y += h
      }
      return
    }
    for (const block of group) {
      const h = blockHeight(block.type, sourceById.get(block.id))
      layout.push({ i: block.id, x: 0, y: bottomY, w: 12, h, minW: 4, minH: 4 })
      bottomY += h
    }
  })
  return layout
}

function dashboardLayout(blocks: WorkbenchPanel[]): Layout {
  const outputs = blocks.filter((block) => block.type === 'notebook-output')
  const visible = outputs.length ? outputs : blocks.filter((block) => block.type === 'table' || block.type === 'chart')
  return visible.map((block, index) => ({
    i: block.id,
    x: (index % 2) * 6,
    y: Math.floor(index / 2) * 9,
    w: 6,
    h: 9,
    minW: 4,
    minH: 5
  }))
}

function freeLayout(blocks: WorkbenchPanel[], sourceById: Map<string, string>): Layout {
  let leftY = 0
  let rightY = 0
  return blocks.map((block, index) => {
    const h = Math.max(6, Math.min(11, blockHeight(block.type, sourceById.get(block.id))))
    const useLeft = leftY <= rightY
    const y = useLeft ? leftY : rightY
    if (useLeft) leftY += h
    else rightY += h
    return { i: block.id, x: useLeft ? 0 : 6, y, w: 6, h, minW: 3, minH: 4 }
  })
}

function withDefault(view: NotebookView): NotebookView {
  return { ...view, defaultLayout: view.layout.map((item) => ({ ...item })) }
}

export function createImportedViews(blocks: WorkbenchPanel[], sourceById: Map<string, string>): NotebookView[] {
  const allIds = blocks.map((block) => block.id)
  const dashboard = dashboardLayout(blocks)
  const dashboardIds = dashboard.map((item) => item.i)
  return [
    withDefault({ id: 'notebook', label: 'Notebook', description: 'Original notebook order with saved outputs.', blockIds: allIds, layout: verticalLayout(blocks, sourceById) }),
    withDefault({ id: 'split', label: 'Two-page', description: 'The same notebook reorganized into two columns.', blockIds: allIds, layout: splitLayout(blocks, sourceById) }),
    withDefault({ id: 'explain', label: 'Code + explanation', description: 'Code and outputs on the left, markdown explanations on the right.', blockIds: allIds, layout: explainLayout(blocks, sourceById) }),
    withDefault({ id: 'two-plus-one', label: '2 + 1', description: 'Two compact notebook sections above the remaining document.', blockIds: allIds, layout: twoPlusOneLayout(blocks, sourceById) }),
    withDefault({ id: 'dashboard', label: 'Dashboard', description: 'Saved notebook outputs arranged as presentation tiles.', blockIds: dashboardIds, layout: dashboard }),
    withDefault({ id: 'free', label: 'Free canvas', description: 'All imported cells on a free two-column canvas.', blockIds: allIds, layout: freeLayout(blocks, sourceById) })
  ]
}


function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function finite(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function restoreMosaicLayout(values: unknown, blockIds: string[], refToBlockId: Map<string, string>): Layout {
  const allowed = new Set(blockIds)
  const seen = new Set<string>()
  const layout: Layout[number][] = []
  if (Array.isArray(values)) {
    for (const value of values) {
      if (!isRecord(value) || typeof value.ref !== 'string') continue
      const id = refToBlockId.get(value.ref)
      if (!id || !allowed.has(id) || seen.has(id) || ![value.x, value.y, value.w, value.h].every(finite)) continue
      const x = Math.max(0, Math.min(11, Math.floor(value.x as number)))
      const y = Math.max(0, Math.floor(value.y as number))
      const w = Math.max(1, Math.min(12 - x, Math.floor(value.w as number)))
      const h = Math.max(1, Math.floor(value.h as number))
      const item: Layout[number] = { i: id, x, y, w, h }
      if (finite(value.minW)) item.minW = Math.max(1, Math.min(w, Math.floor(value.minW)))
      if (finite(value.minH)) item.minH = Math.max(1, Math.min(h, Math.floor(value.minH)))
      if (finite(value.maxW)) item.maxW = Math.max(w, Math.min(12, Math.floor(value.maxW)))
      if (finite(value.maxH)) item.maxH = Math.max(h, Math.floor(value.maxH))
      if (typeof value.static === 'boolean') item.static = value.static
      if (typeof value.isDraggable === 'boolean') item.isDraggable = value.isDraggable
      if (typeof value.isResizable === 'boolean') item.isResizable = value.isResizable
      layout.push(item)
      seen.add(id)
    }
  }
  let bottom = layout.reduce((max, item) => Math.max(max, item.y + item.h), 0)
  for (const id of blockIds) {
    if (seen.has(id)) continue
    layout.push({ i: id, x: 0, y: bottom, w: 12, h: 8, minW: 3, minH: 4 })
    bottom += 8
  }
  return layout
}

/** Restore Mosaic's namespaced layout metadata when an exported notebook is reopened. */
export function restoreMosaicViews(metadata: unknown, blocks: WorkbenchPanel[]): NotebookView[] | null {
  if (!isRecord(metadata) || !Array.isArray(metadata.views)) return null
  const refToBlockId = new Map<string, string>()
  for (const block of blocks) {
    if (!block.notebook) continue
    if (block.notebook.cellType === 'output' && block.notebook.parentCellId) refToBlockId.set(`output:${block.notebook.parentCellId}`, block.id)
    else refToBlockId.set(`cell:${block.notebook.cellId}`, block.id)
  }
  const seenViewIds = new Set<string>()
  const restored: NotebookView[] = []
  for (const raw of metadata.views) {
    if (!isRecord(raw) || typeof raw.id !== 'string' || !raw.id || seenViewIds.has(raw.id)) continue
    if (!Array.isArray(raw.blockRefs)) continue
    const blockIds: string[] = []
    const seenBlocks = new Set<string>()
    for (const ref of raw.blockRefs) {
      if (typeof ref !== 'string') continue
      const id = refToBlockId.get(ref)
      if (!id || seenBlocks.has(id)) continue
      seenBlocks.add(id)
      blockIds.push(id)
    }
    if (!blockIds.length && raw.id !== 'dashboard') continue
    const layout = restoreMosaicLayout(raw.layout, blockIds, refToBlockId)
    const defaultLayout = restoreMosaicLayout(raw.defaultLayout, blockIds, refToBlockId)
    const collapsedIds = Array.isArray(raw.collapsedRefs)
      ? raw.collapsedRefs.map((ref) => typeof ref === 'string' ? refToBlockId.get(ref) : undefined).filter((id): id is string => Boolean(id) && blockIds.includes(id!))
      : []
    const expandedHeights: Record<string, number> = {}
    if (Array.isArray(raw.expandedHeights)) {
      for (const entry of raw.expandedHeights) {
        if (!isRecord(entry) || typeof entry.ref !== 'string' || !finite(entry.height)) continue
        const id = refToBlockId.get(entry.ref)
        if (id && blockIds.includes(id) && entry.height > 0) expandedHeights[id] = entry.height
      }
    }
    restored.push({
      id: raw.id,
      label: typeof raw.label === 'string' ? raw.label : raw.id,
      description: typeof raw.description === 'string' ? raw.description : '',
      blockIds,
      layout,
      defaultLayout,
      collapsedIds,
      expandedHeights
    })
    seenViewIds.add(raw.id)
  }
  return restored.some((view) => view.id === 'notebook') ? restored : null
}

export function parseIpynb(text: string, fileName: string): ImportedNotebookProject {
  const document = JSON.parse(text) as IpynbDocument
  if (!Array.isArray(document.cells)) throw new Error('Invalid .ipynb: missing cells array.')
  if (document.nbformat && document.nbformat < 4) throw new Error(`Unsupported notebook format ${document.nbformat}. Mosaic expects nbformat 4.`)

  const language = String(document.metadata?.language_info?.name ?? document.metadata?.kernelspec?.language ?? 'python')
  const kernel = document.metadata?.kernelspec?.display_name ? String(document.metadata.kernelspec.display_name) : undefined
  const used = new Set<string>()
  const usedCellIds = new Set<string>()
  const blocks: WorkbenchPanel[] = []
  const blockState: Record<string, unknown> = {}
  const sourceById = new Map<string, string>()
  let codeCellCount = 0
  let markdownCellCount = 0
  let outputBlockCount = 0

  document.cells.forEach((cell, index) => {
    const normalizedCell = normalizeCellId(cell.id, index, usedCellIds)
    const originalCellId = normalizedCell.original
    const effectiveCellId = normalizedCell.id
    const cellBase = uniqueId(`ipynb-${slug(effectiveCellId)}`, used)
    const rawSource = sourceText(cell.source)
    const metaBase: Omit<NotebookCellMeta, 'cellType'> = {
      source: 'ipynb',
      cellId: effectiveCellId,
      ...(effectiveCellId !== originalCellId ? { originalCellId } : {}),
      originalIndex: index,
      language,
      executionCount: typeof cell.execution_count === 'number' ? cell.execution_count : null,
      originalSource: rawSource,
      cellMetadata: cell.metadata ?? {}
    }

    if (cell.cell_type === 'markdown') {
      const source = hydrateAttachments(rawSource, cell.attachments)
      const block: WorkbenchPanel = {
        id: cellBase,
        type: 'markdown',
        title: `Markdown ${markdownCellCount + 1}`,
        subtitle: `Notebook cell ${index + 1}`,
        notebook: { ...metaBase, cellType: 'markdown', importedEditorSource: source, attachments: cell.attachments }
      }
      blocks.push(block)
      blockState[`mosaic:v2:markdown:${block.id}`] = source
      sourceById.set(block.id, source)
      markdownCellCount += 1
      return
    }

    if (cell.cell_type === 'raw') {
      const source = rawSource
      const block: WorkbenchPanel = {
        id: cellBase,
        type: 'markdown',
        title: `Raw cell ${index + 1}`,
        subtitle: 'Imported raw notebook cell',
        notebook: { ...metaBase, cellType: 'raw', importedEditorSource: source }
      }
      blocks.push(block)
      blockState[`mosaic:v2:markdown:${block.id}`] = source
      sourceById.set(block.id, source)
      return
    }

    if (cell.cell_type !== 'code') return
    codeCellCount += 1
    const cellLanguage = detectCodeLanguage(rawSource, language)
    const executable = cellLanguage === 'python' || cellLanguage === 'sql'
    const blockType: PanelType = executable ? cellLanguage : 'markdown'
    const source = cellLanguage === 'sql' ? stripSqlMagic(rawSource) : rawSource
    const notebookMeta: NotebookCellMeta = { ...metaBase, cellType: 'code', language: cellLanguage, importedEditorSource: source }
    const block: WorkbenchPanel = {
      id: cellBase,
      type: blockType,
      title: executable ? `${cellLanguage === 'sql' ? 'SQL' : 'Python'} cell ${codeCellCount}` : `${cellLanguage || 'Code'} cell ${codeCellCount}`,
      subtitle: executable
        ? `${cellLanguage === 'sql' ? 'DuckDB' : 'Python'} · imported${cell.execution_count != null ? ` · [${cell.execution_count}]` : ''}`
        : `Read-only import · ${cellLanguage || 'unknown language'}`,
      notebook: notebookMeta
    }
    blocks.push(block)
    sourceById.set(block.id, source)
    if (executable) blockState[`mosaic:v2:code:${block.id}`] = source
    else blockState[`mosaic:v2:markdown:${block.id}`] = `> Imported ${cellLanguage || 'unsupported'} code cell (execution is not available in Mosaic V2)\n\n\`\`\`${cellLanguage}\n${source}\n\`\`\``

    const outputs = Array.isArray(cell.outputs) ? cell.outputs.map(normalizeOutput) : []
    if (outputs.length) {
      const outputId = uniqueId(`${cellBase}-output`, used)
      const outputBlock: WorkbenchPanel = {
        id: outputId,
        type: 'notebook-output',
        title: `Saved output ${codeCellCount}`,
        subtitle: `Jupyter output · ${outputs.length} item${outputs.length === 1 ? '' : 's'}`,
        notebook: { ...metaBase, cellType: 'output', parentCellId: effectiveCellId, language: cellLanguage }
      }
      blocks.push(outputBlock)
      blockState[`mosaic:v2:jupyter-output:${outputId}`] = outputs
      outputBlockCount += 1
    }
  })

  if (!blocks.length) throw new Error('The notebook contains no importable cells.')
  const title = fileName.replace(/\.ipynb$/i, '') || 'Imported notebook'
  const generatedViews = createImportedViews(blocks, sourceById)
  const restoredViews = restoreMosaicViews(document.metadata?.mosaic, blocks)
  return {
    blocks,
    views: restoredViews ?? generatedViews,
    blockState,
    info: {
      fileName,
      title,
      language,
      kernel,
      cellCount: document.cells.length,
      codeCellCount,
      markdownCellCount,
      outputBlockCount,
      importedAt: new Date().toISOString(),
      metadata: document.metadata ?? {}
    }
  }
}
