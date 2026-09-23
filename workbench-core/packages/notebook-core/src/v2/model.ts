import type { Layout } from 'react-grid-layout'
import type { PanelType, WorkbenchPanel } from '../types.ts'

export type CorePanelType = Extract<PanelType, 'markdown' | 'sql' | 'python' | 'polars' | 'table' | 'chart' | 'catalog'>

export interface NotebookView {
  id: string
  label: string
  description: string
  blockIds: string[]
  layout: Layout
  defaultLayout?: Layout
  collapsedIds?: string[]
  expandedHeights?: Record<string, number>
}

export const coreBlockPalette: Array<{ type: CorePanelType; label: string; description: string }> = [
  { type: 'markdown', label: 'Text / notes', description: 'Explanation, assumptions and conclusions.' },
  { type: 'sql', label: 'SQL', description: 'SQL executed through the shared local runtime.' },
  { type: 'python', label: 'Python', description: 'Trusted local Python using shared catalog helpers.' },
  { type: 'polars', label: 'Polars', description: 'Optional local Polars for DataFrame transformations.' },
  { type: 'table', label: 'Table', description: 'Render the latest shared analytical result.' },
  { type: 'chart', label: 'Chart', description: 'Render the latest shared analytical result as a chart/KPI.' },
  { type: 'catalog', label: 'Data catalog', description: 'Files, DuckDB tables and import controls.' }
]

export const initialBlocks: WorkbenchPanel[] = [
  { id: 'notes', type: 'markdown', title: 'Analysis notes', subtitle: 'Text · explanation' },
  { id: 'sql-main', type: 'sql', title: 'SQL', subtitle: 'Shared SQL runtime' },
  { id: 'python-main', type: 'python', title: 'Python', subtitle: 'Trusted local Python' },
  { id: 'polars-main', type: 'polars', title: 'Polars', subtitle: 'Local Polars' },
  { id: 'result-table', type: 'table', title: 'Result table', subtitle: 'Shared analytical result' },
  { id: 'result-chart', type: 'chart', title: 'Result chart', subtitle: 'Shared analytical result' },
  { id: 'data-catalog', type: 'catalog', title: 'Data', subtitle: 'DuckDB · CSV · Parquet' }
]

export const initialViews: NotebookView[] = [
  {
    id: 'notebook',
    label: 'Notebook',
    description: 'Classic vertical notebook with code, notes and result.',
    blockIds: ['notes', 'sql-main', 'python-main', 'result-table'],
    layout: [
      { i: 'notes', x: 1, y: 0, w: 10, h: 6, minW: 5, minH: 4 },
      { i: 'sql-main', x: 1, y: 6, w: 10, h: 10, minW: 5, minH: 6 },
      { i: 'python-main', x: 1, y: 16, w: 10, h: 10, minW: 5, minH: 6 },
      { i: 'result-table', x: 1, y: 26, w: 10, h: 8, minW: 5, minH: 5 }
    ]
  },
  {
    id: 'split',
    label: 'Two-page',
    description: 'Two notebook columns with one shared result below.',
    blockIds: ['sql-main', 'python-main', 'result-table'],
    layout: [
      { i: 'sql-main', x: 0, y: 0, w: 6, h: 12, minW: 4, minH: 6 },
      { i: 'python-main', x: 6, y: 0, w: 6, h: 12, minW: 4, minH: 6 },
      { i: 'result-table', x: 0, y: 12, w: 12, h: 8, minW: 5, minH: 5 }
    ]
  },
  {
    id: 'explain',
    label: 'Code + explanation',
    description: 'Notebook code beside a persistent explanation panel.',
    blockIds: ['sql-main', 'notes', 'result-table'],
    layout: [
      { i: 'sql-main', x: 0, y: 0, w: 8, h: 13, minW: 4, minH: 6 },
      { i: 'notes', x: 8, y: 0, w: 4, h: 13, minW: 3, minH: 6 },
      { i: 'result-table', x: 0, y: 13, w: 12, h: 8, minW: 5, minH: 5 }
    ]
  },
  {
    id: 'two-plus-one',
    label: '2 + 1',
    description: 'Two compact notebooks above a large result or teaching pane.',
    blockIds: ['sql-main', 'python-main', 'result-chart'],
    layout: [
      { i: 'sql-main', x: 0, y: 0, w: 6, h: 10, minW: 4, minH: 6 },
      { i: 'python-main', x: 6, y: 0, w: 6, h: 10, minW: 4, minH: 6 },
      { i: 'result-chart', x: 0, y: 10, w: 12, h: 10, minW: 6, minH: 6 }
    ]
  },
  {
    id: 'dashboard',
    label: 'Dashboard',
    description: 'A presentation view over the same notebook result.',
    blockIds: ['data-catalog', 'result-chart', 'result-table'],
    layout: [
      { i: 'data-catalog', x: 0, y: 0, w: 3, h: 16, minW: 2, minH: 8 },
      { i: 'result-chart', x: 3, y: 0, w: 9, h: 9, minW: 5, minH: 6 },
      { i: 'result-table', x: 3, y: 9, w: 9, h: 7, minW: 5, minH: 5 }
    ]
  },
  {
    id: 'free',
    label: 'Free canvas',
    description: 'Arrange any project block spatially without changing its computation.',
    blockIds: ['notes', 'sql-main', 'python-main', 'result-chart', 'result-table'],
    layout: [
      { i: 'notes', x: 0, y: 0, w: 4, h: 8, minW: 3, minH: 4 },
      { i: 'sql-main', x: 4, y: 0, w: 8, h: 9, minW: 4, minH: 6 },
      { i: 'python-main', x: 0, y: 9, w: 6, h: 10, minW: 4, minH: 6 },
      { i: 'result-chart', x: 6, y: 9, w: 6, h: 10, minW: 4, minH: 6 },
      { i: 'result-table', x: 0, y: 19, w: 12, h: 8, minW: 5, minH: 5 }
    ]
  }
]

export function blockLabel(type: CorePanelType) {
  return coreBlockPalette.find((item) => item.type === type)?.label ?? type
}

export function runtimeLabel(type: PanelType) {
  if (type === 'sql') return 'Shared SQL runtime'
  if (type === 'python') return 'Trusted local Python'
  if (type === 'polars') return 'Local Polars'
  if (type === 'table' || type === 'chart') return 'Shared result'
  if (type === 'notebook-output') return 'Saved Jupyter output'
  if (type === 'catalog') return 'DuckDB · files'
  return 'Presentation'
}

export function placeAtBottom(layout: Layout, id: string): Layout[number] {
  const bottom = layout.reduce((max, item) => Math.max(max, item.y + item.h), 0)
  return { i: id, x: 0, y: bottom, w: 12, h: 8, minW: 3, minH: 4 }
}

function overlapsHorizontally(a: Layout[number], b: Layout[number]) {
  return a.x < b.x + b.w && a.x + a.w > b.x
}

/**
 * Insert a new block directly after a selected block without stacking it on top
 * of existing content. Only blocks that share horizontal space with the selected
 * block are shifted, so Split/2-column layouts keep their other column stable.
 */
export function placeAfter(layout: Layout, selectedId: string | null, id: string): { item: Layout[number]; layout: Layout } {
  if (!selectedId) {
    const item = placeAtBottom(layout, id)
    return { item, layout: [...layout, item] }
  }

  const selected = layout.find((item) => item.i === selectedId)
  if (!selected) {
    const item = placeAtBottom(layout, id)
    return { item, layout: [...layout, item] }
  }

  const height = Math.max(6, Math.min(10, selected.h))
  const item: Layout[number] = {
    i: id,
    x: selected.x,
    y: selected.y + selected.h,
    w: selected.w,
    h: height,
    minW: Math.min(selected.minW ?? 3, selected.w),
    minH: 4
  }

  const shifted = layout.map((candidate) => {
    if (candidate.i === selected.i) return { ...candidate }
    if (candidate.y < item.y || !overlapsHorizontally(candidate, item)) return { ...candidate }
    return { ...candidate, y: candidate.y + item.h }
  })
  return { item, layout: [...shifted, item] }
}

export function insertIdAfter(ids: string[], selectedId: string | null, id: string) {
  if (!selectedId) return [...ids, id]
  const index = ids.indexOf(selectedId)
  if (index < 0) return [...ids, id]
  return [...ids.slice(0, index + 1), id, ...ids.slice(index + 1)]
}

export function runnableBlockIds(view: NotebookView, blocks: WorkbenchPanel[]) {
  const byId = new Map(blocks.map((block) => [block.id, block]))
  return view.blockIds.filter((id) => {
    const type = byId.get(id)?.type
    return type === 'sql' || type === 'python' || type === 'polars'
  })
}

export function resolveSqlTarget(blocks: WorkbenchPanel[], views: NotebookView[], currentViewId: string, selectedBlockId: string | null) {
  const byId = new Map(blocks.map((block) => [block.id, block]))
  const currentView = views.find((view) => view.id === currentViewId)
  if (selectedBlockId && currentView?.blockIds.includes(selectedBlockId) && byId.get(selectedBlockId)?.type === 'sql') {
    return { blockId: selectedBlockId, viewId: currentViewId }
  }

  const visibleSql = currentView?.blockIds.find((id) => byId.get(id)?.type === 'sql')
  if (visibleSql) return { blockId: visibleSql, viewId: currentViewId }

  const notebookView = views.find((view) => view.id === 'notebook')
  const notebookSql = notebookView?.blockIds.find((id) => byId.get(id)?.type === 'sql')
  if (notebookSql) return { blockId: notebookSql, viewId: notebookView!.id }

  const anySql = blocks.find((block) => block.type === 'sql')
  if (anySql) {
    const containingView = views.find((view) => view.blockIds.includes(anySql.id))
    return { blockId: anySql.id, viewId: containingView?.id ?? currentViewId }
  }

  return { blockId: null, viewId: notebookView?.id ?? currentViewId }
}

/**
 * Collapse/expand a block inside one presentation view without changing the
 * underlying project block. The most recent expanded height is remembered per
 * view so a temporary collapse does not destroy a user's manual resize.
 */
export function toggleCollapsedBlock(view: NotebookView, blockId: string): NotebookView {
  const collapsed = new Set(view.collapsedIds ?? [])
  const expandedHeights = { ...(view.expandedHeights ?? {}) }
  const isCollapsed = collapsed.has(blockId)
  const baselineItem = view.defaultLayout?.find((item) => item.i === blockId)
  const nextLayout = view.layout.map((item) => {
    if (item.i !== blockId) return { ...item }
    if (!isCollapsed) {
      expandedHeights[blockId] = Math.max(4, item.h)
      return { ...item, h: 2, minH: 2, maxH: 2, isResizable: false }
    }
    const restoredHeight = expandedHeights[blockId] ?? baselineItem?.h ?? Math.max(6, item.h)
    const { maxH: _maxH, isResizable: _isResizable, ...rest } = item
    return { ...rest, h: restoredHeight, minH: baselineItem?.minH ?? 4 }
  })
  if (isCollapsed) collapsed.delete(blockId)
  else collapsed.add(blockId)
  return { ...view, layout: nextLayout, collapsedIds: [...collapsed], expandedHeights }
}

function rectanglesOverlap(a: Layout[number], b: Layout[number]) {
  return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y
}

/**
 * Place a newly pinned dashboard tile into the first free half-width slot.
 * This keeps dashboard pinning predictable even after the user has rearranged
 * existing tiles manually.
 */
export function placeDashboardTile(layout: Layout, id: string): Layout[number] {
  const width = 6
  const height = 9
  const maxBottom = layout.reduce((max, item) => Math.max(max, item.y + item.h), 0)
  for (let y = 0; y <= maxBottom + height; y += height) {
    for (const x of [0, 6]) {
      const candidate: Layout[number] = { i: id, x, y, w: width, h: height, minW: 4, minH: 5 }
      if (!layout.some((item) => rectanglesOverlap(item, candidate))) return candidate
    }
  }
  return { i: id, x: 0, y: maxBottom, w: width, h: height, minW: 4, minH: 5 }
}

function notebookGroups(view: NotebookView, blocks: WorkbenchPanel[]) {
  const byId = new Map(blocks.map((block) => [block.id, block]))
  const groups: string[][] = []
  for (const id of view.blockIds) {
    const block = byId.get(id)
    if (block?.notebook?.cellType === 'output' && block.notebook.parentCellId && groups.length) {
      const previous = groups[groups.length - 1]
      const parent = byId.get(previous[0])
      if (parent?.notebook?.cellId === block.notebook.parentCellId) {
        previous.push(id)
        continue
      }
    }
    groups.push([id])
  }
  return groups
}

/**
 * Reorder one notebook cell group (a code cell plus its saved Jupyter output)
 * while preserving every block's current height. This changes notebook/run
 * order intentionally; ordinary drag/resize still changes presentation only.
 */
export function moveNotebookGroup(view: NotebookView, blocks: WorkbenchPanel[], blockId: string, direction: -1 | 1): NotebookView {
  const groups = notebookGroups(view, blocks)
  const groupIndex = groups.findIndex((group) => group.includes(blockId))
  const targetIndex = groupIndex + direction
  if (groupIndex < 0 || targetIndex < 0 || targetIndex >= groups.length) return view

  const reordered = groups.map((group) => [...group])
  const temp = reordered[groupIndex]
  reordered[groupIndex] = reordered[targetIndex]
  reordered[targetIndex] = temp
  const blockIds = reordered.flat()

  const layoutById = new Map(view.layout.map((item) => [item.i, item]))
  const nextLayout: Layout[number][] = []
  let y = 0
  for (const id of blockIds) {
    const current = layoutById.get(id)
    if (!current) continue
    const next = { ...current, y }
    nextLayout.push(next)
    y += next.h
  }
  for (const item of view.layout) {
    if (!blockIds.includes(item.i)) nextLayout.push({ ...item })
  }

  return { ...view, blockIds, layout: nextLayout }
}


export function projectRemovalIds(blocks: WorkbenchPanel[], blockId: string) {
  const selected = blocks.find((block) => block.id === blockId)
  if (!selected) return [blockId]
  if (selected.notebook?.cellType !== 'code' && !['sql','python','polars'].includes(selected.type)) return [blockId]
  const outputIds = blocks
    .filter((block) => block.notebook?.cellType === 'output' && block.notebook.parentCellId === (selected.notebook?.cellId??selected.id))
    .map((block) => block.id)
  return [blockId, ...outputIds]
}

export function viewRemovalIds(blocks: WorkbenchPanel[], view: NotebookView, blockId: string) {
  const removal = new Set(projectRemovalIds(blocks, blockId))
  return view.blockIds.filter((id) => removal.has(id))
}

/**
 * Change the dashboard presentation width without overlapping existing tiles.
 * Wide tiles are moved to a clean full-width row; compact tiles return to the
 * first available half-width slot. Computation/block identity is unchanged.
 */
export function setDashboardTileWidth(view: NotebookView, blockId: string, mode: 'half' | 'wide'): NotebookView {
  if (view.id !== 'dashboard' || !view.blockIds.includes(blockId)) return view
  const current = view.layout.find((item) => item.i === blockId)
  if (!current) return view
  const others = view.layout.filter((item) => item.i !== blockId).map((item) => ({ ...item }))
  if (mode === 'half') {
    const placed = placeDashboardTile(others, blockId)
    return { ...view, layout: [...others, { ...placed, h: current.h }] }
  }
  const y = others.reduce((max, item) => Math.max(max, item.y + item.h), 0)
  const wide: Layout[number] = { ...current, x: 0, y, w: 12, minW: 6 }
  return { ...view, layout: [...others, wide] }
}
export function canMoveNotebookGroup(view: NotebookView, blocks: WorkbenchPanel[], blockId: string, direction: -1 | 1) {
  const groups = notebookGroups(view, blocks)
  const index = groups.findIndex((group) => group.includes(blockId))
  return index >= 0 && index + direction >= 0 && index + direction < groups.length
}

/**
 * Reset presentation geometry without changing notebook/document order.
 * Notebook order is semantic (it drives Run view), so reset must not visually
 * revert a user-reordered notebook back to the import-time order.
 */
export function resetViewLayoutGeometry(view: NotebookView, baseline: Layout): NotebookView {
  const baselineById = new Map(baseline.map((item) => [item.i, item]))
  const currentById = new Map(view.layout.map((item) => [item.i, item]))
  const nextLayout: Layout[number][] = []

  if (view.id === 'notebook') {
    let y = 0
    for (const id of view.blockIds) {
      const template = baselineById.get(id) ?? currentById.get(id) ?? placeAtBottom(nextLayout, id)
      const item = { ...template, y }
      nextLayout.push(item)
      y += item.h
    }
  } else {
    for (const id of view.blockIds) {
      const baselineItem = baselineById.get(id)
      if (baselineItem) nextLayout.push({ ...baselineItem })
      else if (view.id === 'dashboard') nextLayout.push(placeDashboardTile(nextLayout, id))
      else nextLayout.push(placeAtBottom(nextLayout, id))
    }
  }

  return { ...view, layout: nextLayout, collapsedIds: [], expandedHeights: {} }
}
