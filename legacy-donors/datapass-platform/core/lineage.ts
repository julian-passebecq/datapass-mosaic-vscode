import { isLocalizedText, type LocalizedText } from './localization';
import {
  createValidationResult,
  formatValidationIssues,
  validationError,
  type ValidationIssue,
  type ValidationResult
} from './validation';

export interface SourcePosition {
  readonly line: number;
  readonly column: number;
  readonly offset?: number;
}

export interface SourceSpan {
  readonly start: SourcePosition;
  readonly end?: SourcePosition;
  readonly sourceId?: string;
}

export interface LineageColumn {
  readonly id: string;
  readonly label: LocalizedText;
  readonly dataType?: string;
  readonly role?: 'source' | 'target' | 'derived' | 'key' | 'measure' | string;
  readonly metadata?: Readonly<Record<string, unknown>>;
}

export interface LineageAsset {
  readonly id: string;
  readonly label: LocalizedText;
  readonly type?: string;
  readonly layer?: string;
  readonly iconId?: string;
  readonly columns?: readonly LineageColumn[];
  readonly source?: Readonly<Record<string, unknown>>;
  readonly target?: Readonly<Record<string, unknown>>;
  readonly metadata?: Readonly<Record<string, unknown>>;
  /** Optional teaching semantics; facts require an explicit business grain. */
  readonly model?: { readonly kind: 'fact'; readonly grain: LocalizedText }
    | { readonly kind: 'dimension'; readonly grain?: LocalizedText };
}

export interface LineageEndpoint {
  readonly assetId: string;
  readonly columnId?: string;
}

export type LineageStatementType = 'select' | 'insert' | 'update' | 'merge' | 'create-table-as' | 'create-view' | 'unknown';
export type LineageChangeType = 'copy' | 'rename' | 'derive' | 'aggregate' | 'filter' | 'join' | 'unknown';

export interface LineageRelation {
  readonly id: string;
  readonly sources: readonly LineageEndpoint[];
  readonly target: LineageEndpoint;
  readonly label?: LocalizedText;
  readonly derivation?: LocalizedText;
  readonly expression?: string;
  readonly statementType?: LineageStatementType;
  readonly changeType?: LineageChangeType;
  readonly sourceSpan?: SourceSpan;
  readonly metadata?: Readonly<Record<string, unknown>>;
  /** A model relationship, not a derivation: source FK -> target dimension PK. */
  readonly relationship?: {
    readonly cardinality: 'many-to-one';
    readonly filterDirection: 'dimension-to-fact' | 'both' | 'none';
  };
}

export interface LineageSpec {
  readonly kind: 'lineage';
  readonly version: string;
  readonly id: string;
  readonly title: LocalizedText;
  readonly description?: LocalizedText;
  readonly assets: readonly LineageAsset[];
  readonly relations: readonly LineageRelation[];
  /** Omitted preserves historical permissiveness. Checks exact derivation endpoints. */
  readonly cyclePolicy?: 'allow' | 'reject';
  /** Opt-in shared semantic layout; presentation dimensions remain renderer-owned. */
  readonly layout?: { readonly provider: 'layered'; readonly direction?: 'lr' | 'tb' };
}

interface IndexedRecord {
  readonly value: Record<string, unknown>;
  readonly index: number;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}

function collectRecords(items: readonly unknown[], path: string, noun: string, issues: ValidationIssue[]): IndexedRecord[] {
  const records: IndexedRecord[] = [];
  items.forEach((value, index) => {
    if (!isRecord(value)) {
      issues.push(validationError(`lineage.${noun}.object.invalid`, `${path}[${index}]`, `${noun} must be an object.`));
      return;
    }
    records.push({ value, index });
  });
  return records;
}

function duplicateIdIssues(items: readonly IndexedRecord[], path: string, noun: string): ValidationIssue[] {
  const seen = new Set<string>();
  const issues: ValidationIssue[] = [];
  items.forEach(({ value, index }) => {
    const id = value.id;
    if (typeof id !== 'string' || !id.trim()) issues.push(validationError(`lineage.${noun}.id.required`, `${path}[${index}].id`, `${noun} id is required.`));
    else if (seen.has(id)) issues.push(validationError(`lineage.${noun}.id.duplicate`, `${path}[${index}].id`, `Duplicate ${noun} id "${id}".`));
    else seen.add(id);
  });
  return issues;
}

function validPosition(position: unknown): position is SourcePosition {
  return Boolean(
    isRecord(position)
    && Number.isInteger(position.line)
    && (position.line as number) >= 1
    && Number.isInteger(position.column)
    && (position.column as number) >= 1
    && (position.offset === undefined || (Number.isInteger(position.offset) && (position.offset as number) >= 0))
  );
}

function positionAfterOrEqual(end: SourcePosition, start: SourcePosition): boolean {
  if (end.offset !== undefined && start.offset !== undefined) return end.offset >= start.offset;
  return end.line > start.line || (end.line === start.line && end.column >= start.column);
}

const STATEMENT_TYPES: readonly LineageStatementType[] = ['select', 'insert', 'update', 'merge', 'create-table-as', 'create-view', 'unknown'];
const CHANGE_TYPES: readonly LineageChangeType[] = ['copy', 'rename', 'derive', 'aggregate', 'filter', 'join', 'unknown'];

export function getLineagePortId(endpoint: LineageEndpoint): string {
  const asset = encodeURIComponent(endpoint.assetId);
  const column = endpoint.columnId ? `column:${encodeURIComponent(endpoint.columnId)}` : 'asset';
  return `lineage-port:${asset}:${column}`;
}

export function validateLineageSpec(input: unknown): ValidationResult {
  const issues: ValidationIssue[] = [];
  if (!isRecord(input)) {
    return createValidationResult([validationError('lineage.object.required', '$', 'LineageSpec must be an object.')]);
  }
  const spec = input;
  if (spec.cyclePolicy !== undefined && !['allow', 'reject'].includes(spec.cyclePolicy as string)) {
    issues.push(validationError('lineage.cyclePolicy.invalid', 'cyclePolicy', 'Cycle policy must be allow or reject.'));
  }
  if (spec.layout !== undefined && (!isRecord(spec.layout) || spec.layout.provider !== 'layered'
    || (spec.layout.direction !== undefined && !['lr', 'tb'].includes(spec.layout.direction as string)))) {
    issues.push(validationError('lineage.layout.invalid', 'layout', 'Use the layered layout with lr or tb direction.'));
  }
  if (spec.kind !== 'lineage') issues.push(validationError('lineage.kind', 'kind', 'Lineage kind must be "lineage".'));
  if (typeof spec.version !== 'string' || !spec.version.trim()) issues.push(validationError('lineage.version.required', 'version', 'Lineage version is required.'));
  if (typeof spec.id !== 'string' || !spec.id.trim()) issues.push(validationError('lineage.id.required', 'id', 'Lineage id is required.'));
  if (!isLocalizedText(spec.title)) issues.push(validationError('lineage.title.invalid', 'title', 'Lineage title must be localized text.'));
  if (spec.description !== undefined && !isLocalizedText(spec.description)) {
    issues.push(validationError('lineage.description.invalid', 'description', 'Lineage description must be localized text.'));
  }
  if (!Array.isArray(spec.assets)) issues.push(validationError('lineage.assets.required', 'assets', 'Lineage assets must be an array.'));
  if (!Array.isArray(spec.relations)) issues.push(validationError('lineage.relations.required', 'relations', 'Lineage relations must be an array.'));
  const assetRecords = collectRecords(Array.isArray(spec.assets) ? spec.assets : [], 'assets', 'asset', issues);
  const relationRecords = collectRecords(Array.isArray(spec.relations) ? spec.relations : [], 'relations', 'relation', issues);
  issues.push(...duplicateIdIssues(assetRecords, 'assets', 'asset'));
  issues.push(...duplicateIdIssues(relationRecords, 'relations', 'relation'));
  const assetById = new Map(assetRecords.flatMap(({ value }) =>
    typeof value.id === 'string' && value.id.trim() ? [[value.id, value] as const] : []
  ));
  const columnIdsByAsset = new Map<string, Set<string>>();
  assetRecords.forEach(({ value: asset, index: assetIndex }) => {
    if (asset.model !== undefined) {
      const model = asset.model;
      if (!isRecord(model) || !['fact', 'dimension'].includes(model.kind as string)) {
        issues.push(validationError('lineage.model.kind.invalid', `assets[${assetIndex}].model`, 'Model kind must be fact or dimension.'));
      } else if ((model.kind === 'fact' || model.grain !== undefined) && !isLocalizedText(model.grain)) {
        issues.push(validationError('lineage.model.grain.required', `assets[${assetIndex}].model.grain`, 'A fact requires a non-empty localized grain.'));
      }
    }
    if (!isLocalizedText(asset.label)) issues.push(validationError('lineage.asset.label.invalid', `assets[${assetIndex}].label`, 'Asset label must be localized text.'));
    if (asset.source !== undefined && !isRecord(asset.source)) {
      issues.push(validationError('lineage.asset.source.invalid', `assets[${assetIndex}].source`, 'Asset source metadata must be an object.'));
    }
    if (asset.target !== undefined && !isRecord(asset.target)) {
      issues.push(validationError('lineage.asset.target.invalid', `assets[${assetIndex}].target`, 'Asset target metadata must be an object.'));
    }
    if (asset.columns !== undefined && !Array.isArray(asset.columns)) {
      issues.push(validationError('lineage.asset.columns.invalid', `assets[${assetIndex}].columns`, 'Asset columns must be an array.'));
    }
    const columnRecords = collectRecords(Array.isArray(asset.columns) ? asset.columns : [], `assets[${assetIndex}].columns`, 'column', issues);
    issues.push(...duplicateIdIssues(columnRecords, `assets[${assetIndex}].columns`, 'column'));
    columnRecords.forEach(({ value: column, index: columnIndex }) => {
      if (!isLocalizedText(column.label)) {
        issues.push(validationError('lineage.column.label.invalid', `assets[${assetIndex}].columns[${columnIndex}].label`, 'Column label must be localized text.'));
      }
    });
    if (typeof asset.id === 'string' && asset.id.trim()) {
      columnIdsByAsset.set(asset.id, new Set(columnRecords.flatMap(({ value: column }) =>
        typeof column.id === 'string' && column.id.trim() ? [column.id] : []
      )));
    }
  });

  const validateEndpoint = (endpoint: unknown, path: string): void => {
    if (!isRecord(endpoint)) {
      issues.push(validationError('lineage.endpoint.object.invalid', path, 'Lineage endpoint must be an object.'));
      return;
    }
    if (typeof endpoint.assetId !== 'string' || !endpoint.assetId.trim()) {
      issues.push(validationError('lineage.endpoint.asset.required', `${path}.assetId`, 'Lineage asset id is required.'));
      return;
    }
    if (!assetById.has(endpoint.assetId)) {
      issues.push(validationError('lineage.endpoint.asset.unknown', `${path}.assetId`, `Unknown lineage asset "${endpoint.assetId}".`));
      return;
    }
    if (endpoint.columnId !== undefined && (typeof endpoint.columnId !== 'string' || !endpoint.columnId.trim())) {
      issues.push(validationError('lineage.endpoint.column.invalid', `${path}.columnId`, 'Lineage column id must be a non-empty string.'));
    } else if (typeof endpoint.columnId === 'string' && !columnIdsByAsset.get(endpoint.assetId)?.has(endpoint.columnId)) {
      issues.push(validationError('lineage.endpoint.column.unknown', `${path}.columnId`, `Unknown column "${endpoint.columnId}" on asset "${endpoint.assetId}".`));
    }
  };

  relationRecords.forEach(({ value: relation, index: relationIndex }) => {
    if (!Array.isArray(relation.sources) || relation.sources.length === 0) {
      issues.push(validationError('lineage.relation.sources.required', `relations[${relationIndex}].sources`, 'A lineage relation requires at least one source endpoint.'));
    }
    (Array.isArray(relation.sources) ? relation.sources : []).forEach((endpoint, sourceIndex) => validateEndpoint(endpoint, `relations[${relationIndex}].sources[${sourceIndex}]`));
    validateEndpoint(relation.target, `relations[${relationIndex}].target`);
    if (relation.relationship !== undefined) {
      const relationship = relation.relationship;
      const relationshipPath = `relations[${relationIndex}].relationship`;
      if (!isRecord(relationship) || relationship.cardinality !== 'many-to-one'
        || !['dimension-to-fact', 'both', 'none'].includes(relationship.filterDirection as string)) {
        issues.push(validationError('lineage.relationship.invalid', relationshipPath, 'Declare many-to-one and dimension-to-fact, both or none filtering.'));
      }
      const matches = (endpoint: unknown, kind: string, role: string): boolean => {
        if (!isRecord(endpoint) || typeof endpoint.assetId !== 'string' || typeof endpoint.columnId !== 'string') return false;
        const asset = assetById.get(endpoint.assetId);
        return Boolean(asset && isRecord(asset.model) && asset.model.kind === kind
          && Array.isArray(asset.columns) && asset.columns.some(column => isRecord(column) && column.id === endpoint.columnId && column.role === role));
      };
      if (!Array.isArray(relation.sources) || relation.sources.length !== 1
        || !matches(relation.sources[0], 'fact', 'fk') || !matches(relation.target, 'dimension', 'pk')) {
        issues.push(validationError('lineage.relationship.endpoints.invalid', relationshipPath, 'A model relationship requires one fact FK source and one dimension PK target.'));
      }
      if (['derivation', 'expression', 'changeType', 'statementType', 'sourceSpan'].some(key => relation[key] !== undefined)) {
        issues.push(validationError('lineage.relationship.derivation.conflict', relationshipPath, 'Keep model relationships separate from data derivation metadata.'));
      }
    }
    if (relation.label !== undefined && !isLocalizedText(relation.label)) {
      issues.push(validationError('lineage.relation.label.invalid', `relations[${relationIndex}].label`, 'Relation label must be localized text.'));
    }
    if (relation.derivation !== undefined && !isLocalizedText(relation.derivation)) {
      issues.push(validationError('lineage.relation.derivation.invalid', `relations[${relationIndex}].derivation`, 'Derivation must be localized text.'));
    }
    if (relation.statementType !== undefined && !STATEMENT_TYPES.includes(relation.statementType as LineageStatementType)) {
      issues.push(validationError('lineage.relation.statementType.invalid', `relations[${relationIndex}].statementType`, `Unknown statement type "${relation.statementType}".`));
    }
    if (relation.changeType !== undefined && !CHANGE_TYPES.includes(relation.changeType as LineageChangeType)) {
      issues.push(validationError('lineage.relation.changeType.invalid', `relations[${relationIndex}].changeType`, `Unknown change type "${relation.changeType}".`));
    }
    if (relation.sourceSpan !== undefined) {
      if (!isRecord(relation.sourceSpan)) {
        issues.push(validationError('lineage.sourceSpan.object.invalid', `relations[${relationIndex}].sourceSpan`, 'Source span must be an object.'));
        return;
      }
      if (relation.sourceSpan.sourceId !== undefined && (typeof relation.sourceSpan.sourceId !== 'string' || !relation.sourceSpan.sourceId.trim())) {
        issues.push(validationError('lineage.sourceSpan.sourceId.invalid', `relations[${relationIndex}].sourceSpan.sourceId`, 'Source id must be a non-empty string.'));
      }
      if (!validPosition(relation.sourceSpan.start)) {
        issues.push(validationError('lineage.sourceSpan.start.invalid', `relations[${relationIndex}].sourceSpan.start`, 'Source span start must use one-based integer line and column values.'));
      }
      if (relation.sourceSpan.end !== undefined && !validPosition(relation.sourceSpan.end)) {
        issues.push(validationError('lineage.sourceSpan.end.invalid', `relations[${relationIndex}].sourceSpan.end`, 'Source span end must use one-based integer line and column values.'));
      } else if (validPosition(relation.sourceSpan.end) && validPosition(relation.sourceSpan.start) && !positionAfterOrEqual(relation.sourceSpan.end, relation.sourceSpan.start)) {
        issues.push(validationError('lineage.sourceSpan.order.invalid', `relations[${relationIndex}].sourceSpan.end`, 'Source span end must not precede its start.'));
      }
    }
  });
  if (spec.cyclePolicy === 'reject' && issues.length === 0) {
    // Model filter directions are not data derivations. Exact endpoint identities
    // allow a -> b within one asset without inventing an asset-level self-cycle.
    const outgoing = new Map<string, Set<string>>();
    const incoming = new Map<string, number>();
    for (const { value } of relationRecords) {
      const relation = value as unknown as LineageRelation;
      if (relation.relationship) continue;
      const target = getLineagePortId(relation.target);
      if (!incoming.has(target)) incoming.set(target, 0);
      for (const endpoint of relation.sources) {
        const source = getLineagePortId(endpoint);
        if (!incoming.has(source)) incoming.set(source, 0);
        const targets = outgoing.get(source) ?? new Set<string>();
        if (!targets.has(target)) incoming.set(target, incoming.get(target)! + 1);
        targets.add(target);
        outgoing.set(source, targets);
      }
    }
    const queue = [...incoming].filter(([, degree]) => degree === 0).map(([id]) => id);
    for (let index = 0; index < queue.length; index++) {
      for (const target of outgoing.get(queue[index]) ?? []) {
        incoming.set(target, incoming.get(target)! - 1);
        if (incoming.get(target) === 0) queue.push(target);
      }
    }
    if (queue.length !== incoming.size) issues.push(validationError('lineage.relation.cycle', 'relations', 'Derivation endpoints must form an acyclic graph when cyclePolicy is reject.'));
  }
  return createValidationResult(issues);
}

export function assertValidLineageSpec(spec: unknown): LineageSpec {
  const result = validateLineageSpec(spec);
  if (!result.valid) throw new Error(`Invalid LineageSpec:\n${formatValidationIssues(result)}`);
  return spec as LineageSpec;
}
