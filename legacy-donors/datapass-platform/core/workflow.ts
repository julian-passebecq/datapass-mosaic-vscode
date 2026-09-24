import type {
  DiagramDensity,
  DiagramDirection,
  DiagramLayoutNode,
  DiagramRoutePoint,
  DiagramPort
} from './diagram';
import { createSemanticSnapshot, type EntitySnapshot, type SemanticSnapshot } from './entities';
import { isFlowKind, type FlowKind } from './flow';
import { isLocalizedText, type LocalizedText } from './localization';
import { planTransitions, type TransitionPlan } from './transitions';
import type { ExplanationTrack } from './explanation';
import {
  createValidationResult,
  formatValidationIssues,
  validationError,
  type ValidationIssue,
  type ValidationResult
} from './validation';

export type WorkflowPreset =
  | 'generic'
  | 'airflow'
  | 'fabric-data-factory'
  | 'azure-data-factory'
  | 'databricks-lakeflow';

export type WorkflowDependencyCondition = 'dependency' | 'success' | 'failure' | 'completion' | 'skip' | 'true' | 'false';
export type WorkflowStatus =
  | 'pending'
  | 'queued'
  | 'running'
  | 'success'
  | 'failed'
  | 'retrying'
  | 'skipped'
  | 'upstream_failed';

export interface WorkflowSchedule {
  readonly kind?: 'manual' | 'cron' | 'interval' | 'event';
  readonly expression?: string;
  readonly label?: LocalizedText;
}

export interface WorkflowNode {
  readonly id: string;
  readonly label: LocalizedText;
  readonly taskType?: string;
  readonly providerType?: string;
  readonly groupId?: string;
  readonly iconId?: string;
  readonly ports?: readonly DiagramPort[];
  readonly metadata?: Readonly<Record<string, unknown>>;
}

export interface WorkflowGroup {
  readonly id: string;
  readonly label: LocalizedText;
  readonly kind?: 'group' | 'foreach' | 'condition' | 'switch' | 'until' | 'task-group';
  readonly parentId?: string;
  readonly childNodeIds?: readonly string[];
  readonly childGroupIds?: readonly string[];
  readonly metadata?: Readonly<Record<string, unknown>>;
}

export interface WorkflowEdge {
  readonly id?: string;
  readonly from: string;
  readonly to: string;
  readonly fromPortId?: string;
  readonly toPortId?: string;
  readonly condition?: WorkflowDependencyCondition;
  readonly label?: LocalizedText;
  readonly dataFlowKind?: FlowKind;
  readonly metadata?: Readonly<Record<string, unknown>>;
}

export interface WorkflowTaskState {
  readonly status: WorkflowStatus;
  readonly attempt?: number;
  readonly durationMs?: number;
  readonly message?: LocalizedText;
}

export interface WorkflowRunFrame {
  readonly id: string;
  readonly at?: number;
  /** Partial declared state; omitted tasks retain their prior state, initially pending. */
  readonly states: Readonly<Record<string, WorkflowTaskState>>;
}

export interface WorkflowRun {
  readonly id: string;
  readonly label?: LocalizedText;
  readonly startedAt?: string;
  readonly frames: readonly WorkflowRunFrame[];
}

export interface WorkflowOverlay {
  readonly id: string;
  readonly kind: 'asset' | 'lineage' | 'data-flow' | 'warning' | 'annotation';
  readonly targetIds?: readonly string[];
  readonly metadata?: Readonly<Record<string, unknown>>;
}

export interface WorkflowSpec {
  readonly explanation?: ExplanationTrack;
  readonly kind: 'workflow';
  readonly version: string;
  readonly id: string;
  readonly title: LocalizedText;
  readonly description?: LocalizedText;
  readonly preset?: WorkflowPreset;
  readonly layout?: {
    readonly direction?: Extract<DiagramDirection, 'lr' | 'tb'>;
    readonly density?: DiagramDensity;
  };
  readonly schedule?: WorkflowSchedule;
  readonly parameters?: Readonly<Record<string, unknown>>;
  readonly groups?: readonly WorkflowGroup[];
  readonly nodes: readonly WorkflowNode[];
  readonly edges: readonly WorkflowEdge[];
  readonly runs?: readonly WorkflowRun[];
  readonly overlays?: readonly WorkflowOverlay[];
}

export interface CompiledWorkflowRunFrame {
  readonly workflowId: string;
  readonly runId: string;
  readonly frameId: string;
  readonly index: number;
  readonly at?: number;
  readonly states: Readonly<Record<string, WorkflowTaskState>>;
  readonly snapshot: SemanticSnapshot;
  readonly transition: TransitionPlan;
}

export interface WorkflowLayoutGroup {
  readonly id: string;
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

export interface WorkflowLayoutResult {
  readonly version: string;
  readonly width: number;
  readonly height: number;
  readonly nodes: readonly DiagramLayoutNode[];
  readonly groups: readonly WorkflowLayoutGroup[];
  readonly edgeRoutes: Readonly<Record<string, readonly DiagramRoutePoint[]>>;
}

export interface WorkflowLayoutOptions {
  readonly focusedGroupId?: string;
  readonly direction?: Extract<DiagramDirection, 'lr' | 'tb'>;
  readonly density?: DiagramDensity;
}

export interface WorkflowLayoutContract {
  readonly id: string;
  readonly version: string;
  readonly deterministic: true;
  layout(spec: WorkflowSpec, options?: WorkflowLayoutOptions): WorkflowLayoutResult;
}

const WORKFLOW_STATUSES: readonly WorkflowStatus[] = [
  'pending', 'queued', 'running', 'success', 'failed', 'retrying', 'skipped', 'upstream_failed'
];

const WORKFLOW_PRESETS: readonly WorkflowPreset[] = [
  'generic', 'airflow', 'fabric-data-factory', 'azure-data-factory', 'databricks-lakeflow'
];

const WORKFLOW_CONDITIONS: readonly WorkflowDependencyCondition[] = [
  'dependency', 'success', 'failure', 'completion', 'skip', 'true', 'false'
];

const WORKFLOW_OVERLAY_KINDS: readonly WorkflowOverlay['kind'][] = [
  'asset', 'lineage', 'data-flow', 'warning', 'annotation'
];

const ALLOWED_STATUS_TRANSITIONS: Readonly<Record<WorkflowStatus, readonly WorkflowStatus[]>> = {
  pending: ['pending', 'queued', 'running', 'success', 'failed', 'skipped', 'upstream_failed'],
  queued: ['queued', 'running', 'success', 'failed', 'skipped', 'upstream_failed'],
  running: ['running', 'success', 'failed', 'retrying', 'skipped'],
  success: ['success'],
  failed: ['failed', 'retrying', 'queued', 'running', 'success'],
  retrying: ['retrying', 'queued', 'running', 'success', 'failed'],
  skipped: ['skipped'],
  upstream_failed: ['upstream_failed', 'queued', 'running', 'skipped']
};

export function isWorkflowStatus(value: unknown): value is WorkflowStatus {
  return typeof value === 'string' && WORKFLOW_STATUSES.includes(value as WorkflowStatus);
}

export function isWorkflowStatusTransitionAllowed(from: WorkflowStatus, to: WorkflowStatus): boolean {
  return ALLOWED_STATUS_TRANSITIONS[from].includes(to);
}

function edgePart(value: string | undefined): string {
  return encodeURIComponent(value ?? '');
}

export function getWorkflowEdgeId(edge: WorkflowEdge, _index = 0): string {
  return edge.id ?? `edge:${edgePart(edge.from)}:${edgePart(edge.fromPortId)}:${edgePart(edge.to)}:${edgePart(edge.toPortId)}:${edge.condition ?? 'dependency'}`;
}

interface IndexedRecord {
  readonly value: Record<string, unknown>;
  readonly index: number;
}

const WORKFLOW_SCHEDULE_KINDS: readonly NonNullable<WorkflowSchedule['kind']>[] = ['manual', 'cron', 'interval', 'event'];
const WORKFLOW_GROUP_KINDS: readonly NonNullable<WorkflowGroup['kind']>[] = ['group', 'foreach', 'condition', 'switch', 'until', 'task-group'];
const WORKFLOW_LAYOUT_DIRECTIONS: readonly Extract<DiagramDirection, 'lr' | 'tb'>[] = ['lr', 'tb'];
const WORKFLOW_LAYOUT_DENSITIES: readonly DiagramDensity[] = ['compact', 'comfortable'];
const WORKFLOW_PORT_SIDES: readonly NonNullable<DiagramPort['side']>[] = ['left', 'right', 'top', 'bottom'];

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}

function collectRecords(items: readonly unknown[], path: string, noun: string, issues: ValidationIssue[]): IndexedRecord[] {
  const records: IndexedRecord[] = [];
  items.forEach((value, index) => {
    if (!isRecord(value)) {
      issues.push(validationError(`workflow.${noun}.object.invalid`, `${path}[${index}]`, `${noun} must be an object.`));
      return;
    }
    records.push({ value, index });
  });
  return records;
}

function duplicateIdIssues(items: readonly IndexedRecord[], path: string, noun: string): ValidationIssue[] {
  const issues: ValidationIssue[] = [];
  const ids = new Set<string>();
  items.forEach(({ value, index }) => {
    const id = value.id;
    if (typeof id !== 'string' || !id.trim()) issues.push(validationError(`workflow.${noun}.id.required`, `${path}[${index}].id`, `${noun} id is required.`));
    else if (ids.has(id)) issues.push(validationError(`workflow.${noun}.id.duplicate`, `${path}[${index}].id`, `Duplicate ${noun} id "${id}".`));
    else ids.add(id);
  });
  return issues;
}

function optionalArray(value: unknown, path: string, code: string, message: string, issues: ValidationIssue[]): readonly unknown[] {
  if (value === undefined) return [];
  if (!Array.isArray(value)) {
    issues.push(validationError(code, path, message));
    return [];
  }
  return value;
}

function optionalStringArray(value: unknown, path: string, code: string, issues: ValidationIssue[]): readonly string[] {
  if (value === undefined) return [];
  if (!Array.isArray(value) || value.some((item) => typeof item !== 'string' || !item.trim())) {
    issues.push(validationError(code, path, 'Expected an array of non-empty strings.'));
    return [];
  }
  return value;
}

function idMap(records: readonly IndexedRecord[]): Map<string, Record<string, unknown>> {
  return new Map(records.flatMap(({ value }) =>
    typeof value.id === 'string' && value.id.trim() ? [[value.id, value] as const] : []
  ));
}

function workflowEdgeIdFromRecord(edge: Record<string, unknown>): string {
  if (typeof edge.id === 'string' && edge.id.trim()) return edge.id;
  return `edge:${edgePart(typeof edge.from === 'string' ? edge.from : undefined)}:${edgePart(typeof edge.fromPortId === 'string' ? edge.fromPortId : undefined)}:${edgePart(typeof edge.to === 'string' ? edge.to : undefined)}:${edgePart(typeof edge.toPortId === 'string' ? edge.toPortId : undefined)}:${typeof edge.condition === 'string' ? edge.condition : 'dependency'}`;
}

function hasDirectedCycle(ids: readonly string[], arcs: readonly (readonly [string, string])[]): boolean {
  const adjacency = new Map(ids.map((id) => [id, [] as string[]]));
  arcs.forEach(([from, to]) => adjacency.get(from)?.push(to));
  const visiting = new Set<string>();
  const visited = new Set<string>();
  const visit = (id: string): boolean => {
    if (visiting.has(id)) return true;
    if (visited.has(id)) return false;
    visiting.add(id);
    for (const child of adjacency.get(id) ?? []) if (visit(child)) return true;
    visiting.delete(id);
    visited.add(id);
    return false;
  };
  return ids.some(visit);
}

export function validateWorkflowSpec(input: unknown): ValidationResult {
  const issues: ValidationIssue[] = [];
  if (!isRecord(input)) {
    return createValidationResult([validationError('workflow.object.required', '$', 'WorkflowSpec must be an object.')]);
  }
  const spec = input;
  if (spec.kind !== 'workflow') issues.push(validationError('workflow.kind', 'kind', 'Workflow kind must be "workflow".'));
  if (typeof spec.version !== 'string' || !spec.version.trim()) issues.push(validationError('workflow.version.required', 'version', 'Workflow version is required.'));
  if (typeof spec.id !== 'string' || !spec.id.trim()) issues.push(validationError('workflow.id.required', 'id', 'Workflow id is required.'));
  if (!isLocalizedText(spec.title)) issues.push(validationError('workflow.title.invalid', 'title', 'Workflow title must be localized text.'));
  if (spec.description !== undefined && !isLocalizedText(spec.description)) {
    issues.push(validationError('workflow.description.invalid', 'description', 'Workflow description must be localized text.'));
  }
  if (spec.preset !== undefined && !WORKFLOW_PRESETS.includes(spec.preset as WorkflowPreset)) {
    issues.push(validationError('workflow.preset.invalid', 'preset', `Unknown workflow preset "${String(spec.preset)}".`));
  }
  if (spec.layout !== undefined) {
    if (!isRecord(spec.layout)) {
      issues.push(validationError('workflow.layout.invalid', 'layout', 'Workflow layout must be an object.'));
    } else {
      if (spec.layout.direction !== undefined && !WORKFLOW_LAYOUT_DIRECTIONS.includes(spec.layout.direction as Extract<DiagramDirection, 'lr' | 'tb'>)) {
        issues.push(validationError('workflow.layout.direction.invalid', 'layout.direction', `Unknown workflow layout direction "${String(spec.layout.direction)}".`));
      }
      if (spec.layout.density !== undefined && !WORKFLOW_LAYOUT_DENSITIES.includes(spec.layout.density as DiagramDensity)) {
        issues.push(validationError('workflow.layout.density.invalid', 'layout.density', `Unknown workflow layout density "${String(spec.layout.density)}".`));
      }
    }
  }
  if (spec.schedule !== undefined) {
    if (!isRecord(spec.schedule)) {
      issues.push(validationError('workflow.schedule.invalid', 'schedule', 'Workflow schedule must be an object.'));
    } else {
      if (spec.schedule.kind !== undefined && !WORKFLOW_SCHEDULE_KINDS.includes(spec.schedule.kind as NonNullable<WorkflowSchedule['kind']>)) {
        issues.push(validationError('workflow.schedule.kind.invalid', 'schedule.kind', `Unknown workflow schedule kind "${String(spec.schedule.kind)}".`));
      }
      if (spec.schedule.expression !== undefined && (typeof spec.schedule.expression !== 'string' || !spec.schedule.expression.trim())) {
        issues.push(validationError('workflow.schedule.expression.invalid', 'schedule.expression', 'Schedule expression must be a non-empty string.'));
      }
      if (spec.schedule.label !== undefined && !isLocalizedText(spec.schedule.label)) {
        issues.push(validationError('workflow.schedule.label.invalid', 'schedule.label', 'Schedule label must be localized text.'));
      }
    }
  }
  if (spec.parameters !== undefined && !isRecord(spec.parameters)) {
    issues.push(validationError('workflow.parameters.invalid', 'parameters', 'Workflow parameters must be an object.'));
  }
  if (!Array.isArray(spec.nodes)) issues.push(validationError('workflow.nodes.required', 'nodes', 'Workflow nodes must be an array.'));
  if (!Array.isArray(spec.edges)) issues.push(validationError('workflow.edges.required', 'edges', 'Workflow edges must be an array.'));
  if (spec.groups !== undefined && !Array.isArray(spec.groups)) issues.push(validationError('workflow.groups.invalid', 'groups', 'Workflow groups must be an array.'));
  if (spec.runs !== undefined && !Array.isArray(spec.runs)) issues.push(validationError('workflow.runs.invalid', 'runs', 'Workflow runs must be an array.'));
  if (spec.overlays !== undefined && !Array.isArray(spec.overlays)) issues.push(validationError('workflow.overlays.invalid', 'overlays', 'Workflow overlays must be an array.'));
  const nodeRecords = collectRecords(Array.isArray(spec.nodes) ? spec.nodes : [], 'nodes', 'node', issues);
  const edgeRecords = collectRecords(Array.isArray(spec.edges) ? spec.edges : [], 'edges', 'edge', issues);
  const groupRecords = collectRecords(Array.isArray(spec.groups) ? spec.groups : [], 'groups', 'group', issues);
  const runRecords = collectRecords(Array.isArray(spec.runs) ? spec.runs : [], 'runs', 'run', issues);
  const overlayRecords = collectRecords(Array.isArray(spec.overlays) ? spec.overlays : [], 'overlays', 'overlay', issues);
  issues.push(...duplicateIdIssues(nodeRecords, 'nodes', 'node'));
  issues.push(...duplicateIdIssues(groupRecords, 'groups', 'group'));
  issues.push(...duplicateIdIssues(runRecords, 'runs', 'run'));
  issues.push(...duplicateIdIssues(overlayRecords, 'overlays', 'overlay'));
  const nodeById = idMap(nodeRecords);
  const groupById = idMap(groupRecords);
  const targetIds = new Set([...nodeById.keys(), ...groupById.keys()]);
  const portsByNode = new Map<string, Set<string>>();

  for (const groupId of groupById.keys()) {
    if (nodeById.has(groupId)) {
      issues.push(validationError('workflow.target.id.duplicate', 'groups', `Node and group ids must be distinct; "${groupId}" is used by both.`));
    }
  }

  nodeRecords.forEach(({ value: node, index: nodeIndex }) => {
    if (!isLocalizedText(node.label)) issues.push(validationError('workflow.node.label.invalid', `nodes[${nodeIndex}].label`, 'Node label must be localized text.'));
    if (node.groupId !== undefined && (typeof node.groupId !== 'string' || !node.groupId.trim())) {
      issues.push(validationError('workflow.node.group.invalid', `nodes[${nodeIndex}].groupId`, 'Node group id must be a non-empty string.'));
    } else if (typeof node.groupId === 'string' && !groupById.has(node.groupId)) {
      issues.push(validationError('workflow.node.group.unknown', `nodes[${nodeIndex}].groupId`, `Unknown group "${node.groupId}".`));
    }
    const rawPorts = optionalArray(node.ports, `nodes[${nodeIndex}].ports`, 'workflow.node.ports.invalid', 'Node ports must be an array.', issues);
    const portRecords = collectRecords(rawPorts, `nodes[${nodeIndex}].ports`, 'port', issues);
    issues.push(...duplicateIdIssues(portRecords, `nodes[${nodeIndex}].ports`, 'port'));
    const portIds = new Set<string>();
    portRecords.forEach(({ value: port, index: portIndex }) => {
      if (typeof port.id === 'string' && port.id.trim()) portIds.add(port.id);
      if (port.label !== undefined && !isLocalizedText(port.label)) {
        issues.push(validationError('workflow.port.label.invalid', `nodes[${nodeIndex}].ports[${portIndex}].label`, 'Port label must be localized text.'));
      }
      if (port.side !== undefined && !WORKFLOW_PORT_SIDES.includes(port.side as NonNullable<DiagramPort['side']>)) {
        issues.push(validationError('workflow.port.side.invalid', `nodes[${nodeIndex}].ports[${portIndex}].side`, `Unknown port side "${String(port.side)}".`));
      }
    });
    if (typeof node.id === 'string' && node.id.trim()) portsByNode.set(node.id, portIds);
  });

  const nodeOwner = new Map<string, string>();
  groupRecords.forEach(({ value: group, index: groupIndex }) => {
    if (!isLocalizedText(group.label)) issues.push(validationError('workflow.group.label.invalid', `groups[${groupIndex}].label`, 'Group label must be localized text.'));
    if (group.kind !== undefined && !WORKFLOW_GROUP_KINDS.includes(group.kind as NonNullable<WorkflowGroup['kind']>)) {
      issues.push(validationError('workflow.group.kind.invalid', `groups[${groupIndex}].kind`, `Unknown workflow group kind "${String(group.kind)}".`));
    }
    if (group.parentId !== undefined && (typeof group.parentId !== 'string' || !group.parentId.trim())) {
      issues.push(validationError('workflow.group.parent.invalid', `groups[${groupIndex}].parentId`, 'Parent group id must be a non-empty string.'));
    } else if (typeof group.parentId === 'string' && !groupById.has(group.parentId)) {
      issues.push(validationError('workflow.group.parent.unknown', `groups[${groupIndex}].parentId`, `Unknown parent group "${group.parentId}".`));
    }
    const groupId = typeof group.id === 'string' ? group.id : '';
    const childNodeIds = optionalStringArray(group.childNodeIds, `groups[${groupIndex}].childNodeIds`, 'workflow.group.childNodeIds.invalid', issues);
    for (const nodeId of childNodeIds) {
      if (!nodeById.has(nodeId)) {
        issues.push(validationError('workflow.group.node.unknown', `groups[${groupIndex}].childNodeIds`, `Unknown child node "${nodeId}".`));
      } else if (nodeOwner.has(nodeId) && nodeOwner.get(nodeId) !== groupId) {
        issues.push(validationError('workflow.group.node.multiple', `groups[${groupIndex}].childNodeIds`, `Node "${nodeId}" belongs to multiple groups.`));
      } else if (groupId) nodeOwner.set(nodeId, groupId);
    }
    const childGroupIds = optionalStringArray(group.childGroupIds, `groups[${groupIndex}].childGroupIds`, 'workflow.group.childGroupIds.invalid', issues);
    for (const childGroupId of childGroupIds) {
      if (!groupById.has(childGroupId)) {
        issues.push(validationError('workflow.group.child.unknown', `groups[${groupIndex}].childGroupIds`, `Unknown child group "${childGroupId}".`));
      }
    }
  });
  nodeRecords.forEach(({ value: node, index: nodeIndex }) => {
    if (typeof node.id !== 'string') return;
    const owner = nodeOwner.get(node.id);
    if (owner && typeof node.groupId === 'string' && owner !== node.groupId) {
      issues.push(validationError('workflow.node.group.conflict', `nodes[${nodeIndex}].groupId`, `Node "${node.id}" has conflicting group ownership.`));
    }
  });
  const groupArcs: Array<readonly [string, string]> = [];
  groupRecords.forEach(({ value: group }) => {
    const groupId = typeof group.id === 'string' ? group.id : '';
    if (typeof group.parentId === 'string' && groupById.has(group.parentId) && groupId) groupArcs.push([group.parentId, groupId]);
    if (groupId) for (const childId of Array.isArray(group.childGroupIds) ? group.childGroupIds : []) {
      if (typeof childId === 'string' && groupById.has(childId)) groupArcs.push([groupId, childId]);
    }
  });
  if (hasDirectedCycle([...groupById.keys()], groupArcs)) {
    issues.push(validationError('workflow.group.cycle', 'groups', 'Workflow groups must not contain a parent/child cycle.'));
  }

  const derivedEdgeIds = new Set<string>();
  const nodeArcs: Array<readonly [string, string]> = [];
  edgeRecords.forEach(({ value: edge, index: edgeIndex }) => {
    if (edge.id !== undefined && (typeof edge.id !== 'string' || !edge.id.trim())) {
      issues.push(validationError('workflow.edge.id.invalid', `edges[${edgeIndex}].id`, 'Explicit edge id must be a non-empty string.'));
    }
    const edgeId = workflowEdgeIdFromRecord(edge);
    if (derivedEdgeIds.has(edgeId)) issues.push(validationError('workflow.edge.id.duplicate', `edges[${edgeIndex}].id`, `Duplicate or ambiguous edge id "${edgeId}".`));
    derivedEdgeIds.add(edgeId);
    const fromNode = typeof edge.from === 'string' ? nodeById.get(edge.from) : undefined;
    const toNode = typeof edge.to === 'string' ? nodeById.get(edge.to) : undefined;
    if (typeof edge.from !== 'string' || !edge.from.trim()) issues.push(validationError('workflow.edge.from.required', `edges[${edgeIndex}].from`, 'Source node id is required.'));
    else if (!fromNode) issues.push(validationError('workflow.edge.from.unknown', `edges[${edgeIndex}].from`, `Unknown source node "${edge.from}".`));
    if (typeof edge.to !== 'string' || !edge.to.trim()) issues.push(validationError('workflow.edge.to.required', `edges[${edgeIndex}].to`, 'Target node id is required.'));
    else if (!toNode) issues.push(validationError('workflow.edge.to.unknown', `edges[${edgeIndex}].to`, `Unknown target node "${edge.to}".`));
    if (edge.condition !== undefined && !WORKFLOW_CONDITIONS.includes(edge.condition as WorkflowDependencyCondition)) {
      issues.push(validationError('workflow.edge.condition.invalid', `edges[${edgeIndex}].condition`, `Unknown dependency condition "${String(edge.condition)}".`));
    }
    if (edge.dataFlowKind !== undefined && !isFlowKind(edge.dataFlowKind)) {
      issues.push(validationError('workflow.edge.dataFlowKind.invalid', `edges[${edgeIndex}].dataFlowKind`, `Unknown data-flow kind "${String(edge.dataFlowKind)}".`));
    }
    if (edge.label !== undefined && !isLocalizedText(edge.label)) {
      issues.push(validationError('workflow.edge.label.invalid', `edges[${edgeIndex}].label`, 'Edge label must be localized text.'));
    }
    if (edge.fromPortId !== undefined && (typeof edge.fromPortId !== 'string' || !edge.fromPortId.trim())) {
      issues.push(validationError('workflow.edge.fromPort.invalid', `edges[${edgeIndex}].fromPortId`, 'Source port id must be a non-empty string.'));
    } else if (fromNode && typeof edge.from === 'string' && typeof edge.fromPortId === 'string' && !portsByNode.get(edge.from)?.has(edge.fromPortId)) {
      issues.push(validationError('workflow.edge.fromPort.unknown', `edges[${edgeIndex}].fromPortId`, `Unknown source port "${edge.fromPortId}".`));
    }
    if (edge.toPortId !== undefined && (typeof edge.toPortId !== 'string' || !edge.toPortId.trim())) {
      issues.push(validationError('workflow.edge.toPort.invalid', `edges[${edgeIndex}].toPortId`, 'Target port id must be a non-empty string.'));
    } else if (toNode && typeof edge.to === 'string' && typeof edge.toPortId === 'string' && !portsByNode.get(edge.to)?.has(edge.toPortId)) {
      issues.push(validationError('workflow.edge.toPort.unknown', `edges[${edgeIndex}].toPortId`, `Unknown target port "${edge.toPortId}".`));
    }
    if (fromNode && toNode && typeof edge.from === 'string' && typeof edge.to === 'string') nodeArcs.push([edge.from, edge.to]);
  });
  if (hasDirectedCycle([...nodeById.keys()], nodeArcs)) {
    issues.push(validationError('workflow.edge.cycle', 'edges', 'Workflow dependency edges must form an acyclic graph.'));
  }

  const overlayTargetIds = new Set([...targetIds, ...derivedEdgeIds]);
  overlayRecords.forEach(({ value: overlay, index: overlayIndex }) => {
    if (!WORKFLOW_OVERLAY_KINDS.includes(overlay.kind as WorkflowOverlay['kind'])) {
      issues.push(validationError('workflow.overlay.kind.invalid', `overlays[${overlayIndex}].kind`, `Unknown overlay kind "${String(overlay.kind)}".`));
    }
    const overlayTargets = optionalStringArray(overlay.targetIds, `overlays[${overlayIndex}].targetIds`, 'workflow.overlay.targetIds.invalid', issues);
    overlayTargets.forEach((targetId, targetIndex) => {
      if (!overlayTargetIds.has(targetId)) {
        issues.push(validationError('workflow.overlay.target.unknown', `overlays[${overlayIndex}].targetIds[${targetIndex}]`, `Unknown overlay target "${targetId}".`));
      }
    });
  });

  runRecords.forEach(({ value: run, index: runIndex }) => {
    if (run.label !== undefined && !isLocalizedText(run.label)) {
      issues.push(validationError('workflow.run.label.invalid', `runs[${runIndex}].label`, 'Run label must be localized text.'));
    }
    if (run.startedAt !== undefined && (typeof run.startedAt !== 'string' || !run.startedAt.trim() || !Number.isFinite(Date.parse(run.startedAt)))) {
      issues.push(validationError('workflow.run.startedAt.invalid', `runs[${runIndex}].startedAt`, 'Run start must be a valid date/time string.'));
    }
    if (!Array.isArray(run.frames)) issues.push(validationError('workflow.run.frames.required', `runs[${runIndex}].frames`, 'Run frames must be an array.'));
    const frameRecords = collectRecords(Array.isArray(run.frames) ? run.frames : [], `runs[${runIndex}].frames`, 'frame', issues);
    issues.push(...duplicateIdIssues(frameRecords, `runs[${runIndex}].frames`, 'frame'));
    let previousAt = -Infinity;
    const priorStates: Record<string, WorkflowStatus> = {};
    frameRecords.forEach(({ value: frame, index: frameIndex }) => {
      if (frame.at !== undefined && (typeof frame.at !== 'number' || !Number.isFinite(frame.at) || frame.at < previousAt)) {
        issues.push(validationError('workflow.run.frame.at', `runs[${runIndex}].frames[${frameIndex}].at`, 'Frame time must be finite and non-decreasing.'));
      }
      if (typeof frame.at === 'number' && Number.isFinite(frame.at)) previousAt = frame.at;
      if (!isRecord(frame.states)) {
        issues.push(validationError('workflow.run.frame.states.required', `runs[${runIndex}].frames[${frameIndex}].states`, 'Frame states must be an object keyed by target id.'));
        return;
      }
      for (const [targetId, state] of Object.entries(frame.states)) {
        const statePath = `runs[${runIndex}].frames[${frameIndex}].states.${targetId}`;
        if (!targetIds.has(targetId)) issues.push(validationError('workflow.run.state.target.unknown', statePath, `Unknown run-state target "${targetId}".`));
        if (!isRecord(state)) {
          issues.push(validationError('workflow.run.state.object.invalid', statePath, 'Workflow task state must be an object.'));
          continue;
        }
        if (!isWorkflowStatus(state.status)) issues.push(validationError('workflow.run.state.status.invalid', `${statePath}.status`, `Invalid workflow status "${String(state.status)}".`));
        if (state.attempt !== undefined && (!Number.isInteger(state.attempt) || (state.attempt as number) < 1)) {
          issues.push(validationError('workflow.run.state.attempt.invalid', `${statePath}.attempt`, 'Attempt must be a positive integer.'));
        }
        if (state.durationMs !== undefined && (typeof state.durationMs !== 'number' || !Number.isFinite(state.durationMs) || state.durationMs < 0)) {
          issues.push(validationError('workflow.run.state.duration.invalid', `${statePath}.durationMs`, 'Duration must be a non-negative finite number.'));
        }
        if (state.message !== undefined && !isLocalizedText(state.message)) {
          issues.push(validationError('workflow.run.state.message.invalid', `${statePath}.message`, 'State message must be localized text.'));
        }
        const previous = priorStates[targetId] ?? 'pending';
        if (isWorkflowStatus(state.status) && !isWorkflowStatusTransitionAllowed(previous, state.status)) {
          issues.push(validationError('workflow.run.state.transition.invalid', `${statePath}.status`, `Invalid workflow transition ${previous} -> ${state.status}.`));
        }
        if (isWorkflowStatus(state.status)) priorStates[targetId] = state.status;
      }
    });
  });

  return createValidationResult(issues);
}

export function assertValidWorkflowSpec(spec: unknown): WorkflowSpec {
  const result = validateWorkflowSpec(spec);
  if (!result.valid) throw new Error(`Invalid WorkflowSpec:\n${formatValidationIssues(result)}`);
  return spec as WorkflowSpec;
}

function runFor(spec: WorkflowSpec, runId: string): WorkflowRun {
  const run = spec.runs?.find((candidate) => candidate.id === runId);
  if (!run) throw new Error(`Unknown workflow run "${runId}" in workflow "${spec.id}".`);
  return run;
}

function runFrameIndex(run: WorkflowRun, frame: number | string): number {
  const index = typeof frame === 'number' ? frame : run.frames.findIndex((candidate) => candidate.id === frame);
  if (!Number.isInteger(index) || index < 0 || index >= run.frames.length) {
    throw new Error(`Unknown workflow frame "${String(frame)}" in run "${run.id}".`);
  }
  return index;
}

function snapshotForWorkflow(spec: WorkflowSpec, run: WorkflowRun, frame: WorkflowRunFrame, states: Readonly<Record<string, WorkflowTaskState>>): SemanticSnapshot {
  const entities: EntitySnapshot[] = [];
  for (const group of spec.groups ?? []) {
    const state = states[group.id] ?? { status: 'pending' as const };
    entities.push({ id: `${spec.id}:group:${group.id}`, kind: 'group', role: group.kind ?? 'group', label: group.label, state: state.status, data: { groupId: group.id, ...state } });
  }
  for (const node of spec.nodes) {
    const state = states[node.id] ?? { status: 'pending' as const };
    entities.push({
      id: `${spec.id}:task:${node.id}`,
      kind: 'task',
      role: node.taskType ?? 'generic',
      label: node.label,
      parentId: node.groupId ? `${spec.id}:group:${node.groupId}` : undefined,
      state: state.status,
      emphasized: state.status === 'running' || state.status === 'failed' || state.status === 'retrying',
      data: { nodeId: node.id, iconId: node.iconId, providerType: node.providerType, ...state }
    });
  }
  spec.edges.forEach((edge, edgeIndex) => {
    entities.push({
      id: `${spec.id}:edge:${edgePart(getWorkflowEdgeId(edge, edgeIndex))}`,
      kind: 'edge',
      role: edge.condition ?? 'dependency',
      state: 'declared',
      data: { from: edge.from, to: edge.to, condition: edge.condition ?? 'dependency', dataFlowKind: edge.dataFlowKind }
    });
  });
  return createSemanticSnapshot(`${spec.id}:${run.id}:${frame.id}`, entities, { workflowId: spec.id, runId: run.id, frameId: frame.id });
}

export function compileWorkflowRunFrame(spec: WorkflowSpec, runId: string, frame: number | string): CompiledWorkflowRunFrame {
  assertValidWorkflowSpec(spec);
  const run = runFor(spec, runId);
  const index = runFrameIndex(run, frame);
  const states: Record<string, WorkflowTaskState> = {};
  for (const node of spec.nodes) states[node.id] = { status: 'pending' };
  for (const group of spec.groups ?? []) states[group.id] = { status: 'pending' };
  for (let current = 0; current <= index; current += 1) Object.assign(states, run.frames[current].states);
  const source = run.frames[index];
  const snapshot = snapshotForWorkflow(spec, run, source, states);
  let previousSnapshot: SemanticSnapshot | undefined;
  if (index > 0) {
    const previousStates: Record<string, WorkflowTaskState> = {};
    for (const node of spec.nodes) previousStates[node.id] = { status: 'pending' };
    for (const group of spec.groups ?? []) previousStates[group.id] = { status: 'pending' };
    for (let current = 0; current < index; current += 1) Object.assign(previousStates, run.frames[current].states);
    previousSnapshot = snapshotForWorkflow(spec, run, run.frames[index - 1], previousStates);
  }
  return {
    workflowId: spec.id,
    runId,
    frameId: source.id,
    index,
    ...(source.at == null ? {} : { at: source.at }),
    states,
    snapshot,
    transition: planTransitions(previousSnapshot, snapshot)
  };
}

export function compileWorkflowRun(spec: WorkflowSpec, runId: string): readonly CompiledWorkflowRunFrame[] {
  const run = runFor(assertValidWorkflowSpec(spec), runId);
  return run.frames.map((_, index) => compileWorkflowRunFrame(spec, runId, index));
}
