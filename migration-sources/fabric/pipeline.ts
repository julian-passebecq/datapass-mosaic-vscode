import type { ActivityType, CaseStudy, PipelineEdge, PipelineNode, PipelineParameter, PipelineRun, PipelineVariable, RunStatus, TutorialStep } from '../types/app';
import { evaluateExpression, expressionLooksValid } from './expressions';
import { nestedActivityCount } from './nestedActivities';
import { parseCopyMapping } from './copyMapping';

export const activityLabels: Record<ActivityType, string> = {
  copy: 'Copy data',
  copyJob: 'Copy job',
  notebook: 'Notebook',
  storedProcedure: 'Stored procedure',
  dataflow: 'Dataflow Gen2',
  dbt: 'dbt Job',
  lookup: 'Lookup',
  foreach: 'ForEach',
  if: 'If Condition',
  script: 'Script',
  invokePipeline: 'Invoke pipeline',
  web: 'Web',
  delete: 'Delete',
  wait: 'Wait',
  setVariable: 'Set variable',
  appendVariable: 'Append variable',
  until: 'Until',
  eventstream: 'Eventstream',
  kql: 'KQL',
  databricks: 'Azure Databricks',
};

export const activityCategory: Record<ActivityType, string> = {
  copy: 'Move & transform',
  copyJob: 'Move & transform',
  notebook: 'Transform',
  storedProcedure: 'Transform',
  dataflow: 'Transform',
  dbt: 'Transform',
  lookup: 'General',
  foreach: 'Iteration & conditionals',
  if: 'Iteration & conditionals',
  script: 'General',
  invokePipeline: 'General',
  web: 'General',
  delete: 'General',
  wait: 'General',
  setVariable: 'Iteration & conditionals',
  appendVariable: 'Iteration & conditionals',
  until: 'Iteration & conditionals',
  eventstream: 'Real-Time',
  kql: 'Real-Time',
  databricks: 'External',
};

export const fabricPalette: ActivityType[] = [
  'copy', 'copyJob', 'dataflow', 'dbt', 'notebook', 'storedProcedure', 'script',
  'lookup', 'foreach', 'if', 'until', 'setVariable', 'appendVariable', 'invokePipeline', 'web', 'delete', 'wait',
  'eventstream', 'kql', 'databricks'
];

export const azurePalette: ActivityType[] = [
  'copy', 'dataflow', 'storedProcedure', 'script', 'lookup', 'foreach', 'if', 'until', 'setVariable', 'appendVariable',
  'invokePipeline', 'web', 'delete', 'wait', 'databricks'
];

export interface DebugPlanStep {
  nodeId: string;
  finalStatus: Extract<RunStatus, 'Succeeded' | 'Failed' | 'Skipped'>;
}

function dependencyMatches(condition: PipelineEdge['condition'], sourceStatus: RunStatus): boolean {
  if (condition === 'Succeeded') return sourceStatus === 'Succeeded';
  if (condition === 'Failed') return sourceStatus === 'Failed';
  if (condition === 'Skipped') return sourceStatus === 'Skipped';
  return sourceStatus === 'Succeeded' || sourceStatus === 'Failed' || sourceStatus === 'Skipped';
}

export function buildDebugPlan(nodes: PipelineNode[], edges: PipelineEdge[]): DebugPlanStep[] {
  const remaining = new Set(nodes.map((node) => node.id));
  const terminal = new Map<string, RunStatus>();
  const plan: DebugPlanStep[] = [];

  while (remaining.size) {
    let progressed = false;
    for (const node of nodes) {
      if (!remaining.has(node.id)) continue;
      const incoming = edges.filter((edge) => edge.to === node.id);
      if (incoming.some((edge) => remaining.has(edge.from))) continue;

      const dependenciesSatisfied = incoming.every((edge) => dependencyMatches(edge.condition, terminal.get(edge.from) ?? 'Not run'));
      const simulateFailure = Boolean(node.config.simulateFailure);
      const finalStatus: DebugPlanStep['finalStatus'] = dependenciesSatisfied ? (simulateFailure ? 'Failed' : 'Succeeded') : 'Skipped';
      plan.push({ nodeId: node.id, finalStatus });
      terminal.set(node.id, finalStatus);
      remaining.delete(node.id);
      progressed = true;
    }

    if (!progressed) {
      // Validation should prevent this path, but mark cyclic/unreachable nodes skipped
      // so the learning simulator can never hang.
      for (const nodeId of remaining) plan.push({ nodeId, finalStatus: 'Skipped' });
      break;
    }
  }
  return plan;
}

function hasDependencyCycle(nodes: PipelineNode[], edges: PipelineEdge[]): boolean {
  const indegree = new Map(nodes.map((node) => [node.id, 0]));
  edges.forEach((edge) => {
    if (indegree.has(edge.to) && indegree.has(edge.from)) indegree.set(edge.to, (indegree.get(edge.to) ?? 0) + 1);
  });
  const queue = nodes.filter((node) => (indegree.get(node.id) ?? 0) === 0).map((node) => node.id);
  let visited = 0;
  while (queue.length) {
    const id = queue.shift()!;
    visited += 1;
    edges.filter((edge) => edge.from === id).forEach((edge) => {
      const next = (indegree.get(edge.to) ?? 0) - 1;
      indegree.set(edge.to, next);
      if (next === 0) queue.push(edge.to);
    });
  }
  return visited !== nodes.length;
}

export function defaultConfig(type: ActivityType): Record<string, string | number | boolean> {
  const policy = { timeout: '12:00:00', retry: 0, retryIntervalSeconds: 30, retryIntervalType: 'Fixed', maxRetryIntervalSeconds: 3600, retryConditionField: 'Any failure', retryConditionOperator: 'Contains', retryConditionValue: '', secureInput: false, secureOutput: false, simulateFailure: false, simulateFailureType: 'System error', simulateErrorCode: '429', simulateErrorMessage: 'Transient service throttling' };
  switch (type) {
    case 'copy': return { ...policy, source: '', sourceQuery: '', sourceFormat: 'Auto', destination: '', sinkFormat: 'Delta', writeMode: 'Append', mapping: 'Auto map by name', parallelCopies: 4, preCopyScript: '' };
    case 'copyJob': return { ...policy, source: '', destination: '', mode: 'Full', watermarkColumn: '', watermarkValue: '' };
    case 'notebook': return { ...policy, workspace: 'DE_Learning', notebook: '', parameters: '' };
    case 'storedProcedure': return { ...policy, connection: '', procedure: '', parametersJson: '[]' };
    case 'dataflow': return { ...policy, dataflow: '', query: '', destination: '', compute: 'Standard' };
    case 'dbt': return { ...policy, project: 'dbt_training', command: 'dbt build', target: 'dev', select: '', exclude: '', fullRefresh: false, failFast: false, threads: 4, variables: '{}' };
    case 'lookup': return { ...policy, connection: '', lookupMode: 'Query', query: '', storedProcedure: '', table: '', firstRowOnly: true };
    case 'foreach': return { ...policy, items: '', sequential: false, batchCount: 20, innerActivities: '' };
    case 'if': return { ...policy, expression: '', trueActivities: '', falseActivities: '' };
    case 'script': return { ...policy, connection: '', script: 'SELECT 1;', logDestination: 'Activity output', logPath: '' };
    case 'invokePipeline': return { ...policy, invokeSource: 'Fabric', authenticationKind: 'Workspace identity', connection: '', workspace: '', pipeline: '', waitOnCompletion: true, parametersJson: '{}' };
    case 'web': return { ...policy, url: '', method: 'GET', headers: '', body: '' };
    case 'delete': return { ...policy, source: '', recursive: true };
    case 'wait': return { ...policy, seconds: 5 };
    case 'setVariable': return { ...policy, variableName: '', value: '' };
    case 'appendVariable': return { ...policy, variableName: '', value: '' };
    case 'until': return { ...policy, expression: '', innerActivities: '' };
    case 'eventstream': return { ...policy, source: '', destination: '', mode: 'Continuous' };
    case 'kql': return { ...policy, database: '', command: '' };
    case 'databricks': return { ...policy, workspace: '', jobId: '', parameters: '' };
  }
}

export function makeNode(type: ActivityType, index: number): PipelineNode {
  return {
    id: `${type}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    type,
    name: `${activityLabels[type].replaceAll(' ', '_')}_${index + 1}`,
    x: 70 + (index % 4) * 250,
    y: 110 + Math.floor(index / 4) * 150,
    status: 'Not run',
    config: defaultConfig(type),
  };
}

const byType = (nodes: PipelineNode[], type: ActivityType) => nodes.find((n) => n.type === type);
const connected = (edges: PipelineEdge[], a?: PipelineNode, b?: PipelineNode) => !!a && !!b && edges.some((e) => e.from === a.id && e.to === b.id);
const hasText = (v: unknown, part: string) => String(v ?? '').toLowerCase().includes(part.toLowerCase());

export function validateTutorialStep(step: TutorialStep, nodes: PipelineNode[], edges: PipelineEdge[], runs: PipelineRun[]): { ok: boolean; message: string } {
  const copy = byType(nodes, 'copy');
  const notebook = byType(nodes, 'notebook');
  const dataflow = byType(nodes, 'dataflow');
  const dbt = byType(nodes, 'dbt');
  const sp = byType(nodes, 'storedProcedure');
  const eventstream = byType(nodes, 'eventstream');
  const cond = byType(nodes, 'if');
  const lookup = byType(nodes, 'lookup');
  const foreach = byType(nodes, 'foreach');
  const copyJob = byType(nodes, 'copyJob');

  switch (step.validateKey) {
    case 'has-copy':
      return copy ? { ok: true, message: 'Copy activity found.' } : { ok: false, message: 'Add a Copy data activity to the canvas.' };
    case 'copy-retail-config':
      return copy && hasText(copy.config.source, 'sales') && hasText(copy.config.destination, 'bronze.sales_raw') && hasText(copy.config.writeMode, 'append')
        ? { ok: true, message: 'Copy source, sink and mode are correct.' }
        : { ok: false, message: 'Check source, destination and Append mode in Copy Settings.' };
    case 'retail-notebook':
      return notebook && hasText(notebook.config.notebook, 'NB_Sales_Bronze_To_Silver') && connected(edges, copy, notebook)
        ? { ok: true, message: 'Notebook is configured after Copy.' }
        : { ok: false, message: 'Configure NB_Sales_Bronze_To_Silver and connect Copy → Notebook.' };
    case 'retail-dataflow':
      return dataflow && hasText(dataflow.config.dataflow, 'DF_Conform_Sales') && hasText(dataflow.config.destination, 'staging.sales_ready') && connected(edges, notebook, dataflow)
        ? { ok: true, message: 'Dataflow Gen2 is correctly placed and configured.' }
        : { ok: false, message: 'Configure DF_Conform_Sales, staging.sales_ready, and connect Notebook → Dataflow.' };
    case 'retail-sp':
      return sp && hasText(sp.config.procedure, 'usp_merge_fact_sales') && hasText(sp.config.parametersJson ?? sp.config.parameter, 'batch_date') && connected(edges, dataflow, sp)
        ? { ok: true, message: 'Stored procedure configuration is correct.' }
        : { ok: false, message: 'Select dw.usp_merge_fact_sales, set @batch_date, and connect Dataflow → Stored procedure.' };
    case 'turbine-eventstream':
      return eventstream && hasText(eventstream.config.source, 'iot') && hasText(eventstream.config.destination, 'turbine_events')
        ? { ok: true, message: 'Streaming ingress is configured.' }
        : { ok: false, message: 'Configure IoT telemetry → Lakehouse iot.turbine_events.' };
    case 'turbine-notebook':
      return notebook && hasText(notebook.config.notebook, 'NB_Turbine_Features') && connected(edges, eventstream, notebook)
        ? { ok: true, message: 'Feature notebook is connected after Eventstream.' }
        : { ok: false, message: 'Configure NB_Turbine_Features and connect Eventstream → Notebook.' };
    case 'turbine-if':
      return cond && hasText(cond.config.expression, 'greater') && hasText(cond.config.expression, '0.8') && connected(edges, notebook, cond)
        ? { ok: true, message: 'Risk condition is configured.' }
        : { ok: false, message: 'Set a > 0.8 risk expression and connect Notebook → If Condition.' };
    case 'turbine-sp':
      return sp && hasText(sp.config.procedure, 'usp_open_maintenance_alert') && connected(edges, cond, sp)
        ? { ok: true, message: 'Alert procedure is correctly configured.' }
        : { ok: false, message: 'Configure ops.usp_open_maintenance_alert and connect If Condition → Stored procedure.' };
    case 'erp-lookup':
      return lookup && hasText(lookup.config.query, 'control.watermarks')
        ? { ok: true, message: 'Lookup reads the orchestration watermark table.' }
        : { ok: false, message: 'Set the Lookup query to read control.watermarks.' };
    case 'erp-foreach':
      return foreach && hasText(foreach.config.items, 'Lookup_Watermarks') && connected(edges, lookup, foreach)
        ? { ok: true, message: 'ForEach is driven by Lookup output.' }
        : { ok: false, message: 'Use Lookup output as ForEach items and connect Lookup → ForEach.' };
    case 'erp-copyjob':
      return copyJob && hasText(copyJob.config.mode, 'incremental') && hasText(copyJob.config.watermarkColumn, 'modified_at') && connected(edges, foreach, copyJob)
        ? { ok: true, message: 'Incremental Copy Job is configured.' }
        : { ok: false, message: 'Set mode Incremental, watermark modified_at, and connect ForEach → Copy Job.' };
    case 'erp-dataflow':
      return dataflow && hasText(dataflow.config.destination, 'staging.customer_changes') && connected(edges, copyJob, dataflow)
        ? { ok: true, message: 'Incremental changes are conformed before serving.' }
        : { ok: false, message: 'Configure staging.customer_changes and connect Copy Job → Dataflow.' };
    case 'erp-sp':
      return sp && hasText(sp.config.procedure, 'usp_merge_customer_scd2') && connected(edges, dbt, sp)
        ? { ok: true, message: 'SCD2 procedure is connected correctly.' }
        : { ok: false, message: 'Configure dw.usp_merge_customer_scd2 and connect Dataflow → Stored procedure.' };
    case 'successful-run':
      return runs.some((r) => r.status === 'Succeeded')
        ? { ok: true, message: 'A successful debug run is recorded.' }
        : { ok: false, message: 'Run Debug and complete one successful pipeline execution.' };
    default:
      return { ok: false, message: 'No validator is defined for this step.' };
  }
}

function jsonIsValid(value: unknown, expected: 'array' | 'object'): boolean {
  if (value === undefined || value === null || String(value).trim() === '') return true;
  try {
    const parsed = JSON.parse(String(value));
    return expected === 'array' ? Array.isArray(parsed) : Boolean(parsed) && typeof parsed === 'object' && !Array.isArray(parsed);
  } catch {
    return false;
  }
}

function expressionReferenceProblems(label: string, expression: string, parameters: PipelineParameter[], variables: PipelineVariable[], nodes: PipelineNode[]): string[] {
  const problems: string[] = [];
  if (!expressionLooksValid(expression)) problems.push(`${label} contains an unrecognized dynamic-content expression.`);

  const missing = (pattern: RegExp, exists: (name: string) => boolean, kind: string) => {
    for (const match of expression.matchAll(pattern)) {
      const name = match[1];
      if (name && !exists(name)) problems.push(`${label} references missing ${kind} ${name}.`);
    }
  };
  missing(/pipeline\(\)\.parameters\.([A-Za-z_][A-Za-z0-9_]*)/g, (name) => parameters.some((candidate) => candidate.name === name), 'pipeline parameter');
  missing(/variables\(['"]([^'"]+)['"]\)/g, (name) => variables.some((candidate) => candidate.name === name), 'pipeline variable');
  missing(/activity\(['"]([^'"]+)['"]\)/g, (name) => nodes.some((candidate) => candidate.name === name), 'activity');
  return [...new Set(problems)];
}

function nestedExpressionStrings(value: unknown): string[] {
  if (typeof value === 'string') return value.trim().startsWith('@') ? [value.trim()] : [];
  if (Array.isArray(value)) return value.flatMap(nestedExpressionStrings);
  if (value && typeof value === 'object') return Object.values(value as Record<string, unknown>).flatMap(nestedExpressionStrings);
  return [];
}

export function validatePipeline(nodes: PipelineNode[], edges: PipelineEdge[], parameters: PipelineParameter[] = [], variables: PipelineVariable[] = []): string[] {
  const problems: string[] = [];
  if (!nodes.length) problems.push('Pipeline contains no activities.');
  const names = new Set<string>();
  nodes.forEach((node) => {
    if (names.has(node.name.trim().toLowerCase())) problems.push(`Duplicate activity name: ${node.name}`);
    names.add(node.name.trim().toLowerCase());
    if (!node.name.trim()) problems.push('An activity has no name.');

    const retry = Number(node.config.retry ?? 0);
    const retryInterval = Number(node.config.retryIntervalSeconds ?? 30);
    const maxRetryInterval = Number(node.config.maxRetryIntervalSeconds ?? 3600);
    const retryIntervalType = String(node.config.retryIntervalType ?? 'Fixed');
    if (!Number.isFinite(retry) || retry < 0 || retry > 1000) problems.push(`${node.name}: retry must be between 0 and 1000.`);
    if (retry > 0 && (!Number.isFinite(retryInterval) || retryInterval < 30)) problems.push(`${node.name}: retry interval must be at least 30 seconds.`);
    if (retry > 0 && !['Fixed', 'Increasing Delay'].includes(retryIntervalType)) problems.push(`${node.name}: retry interval type must be Fixed or Increasing Delay.`);
    if (retry > 0 && retryIntervalType === 'Increasing Delay' && (!Number.isFinite(maxRetryInterval) || maxRetryInterval < retryInterval)) problems.push(`${node.name}: max retry interval must be at least the base retry interval.`);
    if (retry > 0 && String(node.config.retryConditionField ?? 'Any failure') !== 'Any failure' && !String(node.config.retryConditionValue ?? '').trim()) problems.push(`${node.name}: retry condition value is required when a conditional retry field is selected.`);

    if (node.type === 'copy' && (!node.config.source || !node.config.destination)) problems.push(`${node.name}: source and destination are required.`);
    if (node.type === 'copyJob' && (!node.config.source || !node.config.destination)) problems.push(`${node.name}: source and destination are required.`);
    if (node.type === 'notebook' && !node.config.notebook) problems.push(`${node.name}: choose a notebook.`);
    if (node.type === 'storedProcedure') {
      if (!node.config.connection) problems.push(`${node.name}: choose a SQL connection.`);
      if (!node.config.procedure) problems.push(`${node.name}: choose a stored procedure.`);
      if (!jsonIsValid(node.config.parametersJson, 'array')) problems.push(`${node.name}: stored procedure parameters must be a JSON array.`);
    }
    if (node.type === 'dataflow' && !node.config.dataflow) problems.push(`${node.name}: choose a Dataflow Gen2 item.`);
    if (node.type === 'dbt') {
      if (!String(node.config.project ?? '').trim()) problems.push(`${node.name}: choose a dbt project.`);
      const command = String(node.config.command ?? 'dbt build');
      if (!['dbt build', 'dbt run', 'dbt compile', 'dbt test'].includes(command)) problems.push(`${node.name}: unsupported dbt command.`);
      const threads = Number(node.config.threads ?? 4);
      if (!Number.isFinite(threads) || threads < 1 || threads > 64) problems.push(`${node.name}: dbt threads must be between 1 and 64.`);
    }
    if (node.type === 'lookup') {
      if (!node.config.connection) problems.push(`${node.name}: choose a lookup connection.`);
      const mode = String(node.config.lookupMode ?? 'Query');
      if (mode === 'Query' && !node.config.query) problems.push(`${node.name}: query is required.`);
      if (mode === 'Stored procedure' && !node.config.storedProcedure) problems.push(`${node.name}: stored procedure is required.`);
      if (mode === 'Table' && !node.config.table) problems.push(`${node.name}: table is required.`);
    }
    if (node.type === 'script') {
      if (!node.config.connection) problems.push(`${node.name}: choose a script connection.`);
      if (!String(node.config.script ?? '').trim()) problems.push(`${node.name}: script text is required.`);
      if (String(node.config.logDestination ?? '') === 'External store' && !String(node.config.logPath ?? '').trim()) problems.push(`${node.name}: external log path is required.`);
    }
    if (node.type === 'invokePipeline') {
      if (!node.config.pipeline) problems.push(`${node.name}: choose the pipeline to invoke.`);
      if (!jsonIsValid(node.config.parametersJson, 'object')) problems.push(`${node.name}: invoked pipeline parameters must be a JSON object.`);
      if (String(node.config.invokeSource ?? 'Fabric') === 'Fabric' && !node.config.workspace) problems.push(`${node.name}: choose a Fabric workspace.`);
    }
    if (node.type === 'foreach' && !node.config.items) problems.push(`${node.name}: items expression is required.`);
    if (node.type === 'if' && !node.config.expression) problems.push(`${node.name}: condition expression is required.`);
    if (node.type === 'until' && !node.config.expression) problems.push(`${node.name}: until expression is required.`);
    if ((node.type === 'setVariable' || node.type === 'appendVariable') && !node.config.variableName) problems.push(`${node.name}: choose a pipeline variable.`);
    if ((node.type === 'setVariable' || node.type === 'appendVariable') && !node.config.value) problems.push(`${node.name}: variable value is required.`);
    if ((node.type === 'setVariable' || node.type === 'appendVariable') && node.config.variableName) {
      const selectedVariable = variables.find((variable) => variable.name === String(node.config.variableName));
      if (!selectedVariable) problems.push(`${node.name}: pipeline variable ${node.config.variableName} does not exist.`);
      if (node.type === 'appendVariable' && selectedVariable && selectedVariable.type !== 'Array') problems.push(`${node.name}: Append Variable requires an Array variable.`);
    }
    Object.entries(node.config).forEach(([key, value]) => {
      if (typeof value !== 'string' || !value.trim().startsWith('@')) return;
      problems.push(...expressionReferenceProblems(`${node.name}: ${key}`, value, parameters, variables, nodes));
    });
    if (node.config.parametersJson) {
      try {
        const parsed = JSON.parse(String(node.config.parametersJson));
        nestedExpressionStrings(parsed).forEach((expression) => problems.push(...expressionReferenceProblems(`${node.name}: parameter mapping`, expression, parameters, variables, nodes)));
      } catch {
        // Activity-specific JSON validation above reports the parse error.
      }
    }
  });
  const edgePairs = new Set<string>();
  edges.forEach((edge) => {
    if (!nodes.some((n) => n.id === edge.from) || !nodes.some((n) => n.id === edge.to)) problems.push(`Dependency ${edge.id} references a missing activity.`);
    if (edge.from === edge.to) problems.push(`Dependency ${edge.id} cannot point an activity to itself.`);
    const pair = `${edge.from}->${edge.to}`;
    if (edgePairs.has(pair)) problems.push(`Duplicate dependency: ${pair}.`);
    edgePairs.add(pair);
  });
  if (nodes.length && hasDependencyCycle(nodes, edges)) problems.push('Pipeline contains a dependency cycle. Data Factory pipelines must be acyclic.');
  return problems;
}

function procedureParameterCount(node: PipelineNode): number {
  if (node.config.parametersJson) {
    try {
      const parsed = JSON.parse(String(node.config.parametersJson));
      if (Array.isArray(parsed)) return parsed.length;
    } catch {
      return 0;
    }
  }
  return node.config.parameter ? 1 : 0;
}

function outputFor(node: PipelineNode, c: CaseStudy, parameters: PipelineParameter[], variables: PipelineVariable[], nodes: PipelineNode[]): string {
  const type = node.type;
  if (type === 'copy') return c.id === 'retail-medallion' ? '4 rows read · 4 rows written · 18.2 KB · 0 skipped' : 'Rows copied successfully · copy diagnostics available';
  if (type === 'copyJob') return '3 incremental rows copied · watermark predicate applied';
  if (type === 'notebook') return c.id === 'turbine-realtime' ? 'Notebook completed · 3 events scored · maxRisk=0.91 · 1 anomaly' : 'Notebook completed · output table committed';
  if (type === 'dataflow') return 'Power Query evaluation succeeded · 0 quality-rule errors';
  if (type === 'dbt') { const command = String(node.config.command ?? 'dbt build'); return `${command} completed · ${command === 'dbt compile' ? 'SQL compiled' : command === 'dbt test' ? 'tests evaluated' : command === 'dbt run' ? 'models materialized' : 'models materialized · tests evaluated'}`; }
  if (type === 'storedProcedure') {
    const base = c.id === 'turbine-realtime' ? '1 maintenance alert inserted' : c.id === 'erp-incremental' ? 'SCD2 merge completed · 1 version closed · 1 inserted' : 'Stored procedure completed';
    const count = procedureParameterCount(node);
    return `${base} · ${count} parameter${count === 1 ? '' : 's'} bound`;
  }
  if (type === 'lookup') return node.config.firstRowOnly ? '1 row returned · output.firstRow available for dynamic content' : '2 control rows returned · output.value available for dynamic content';
  if (type === 'script') return 'SQL script completed · 3 rows affected · logs captured';
  if (type === 'invokePipeline') return `${node.config.waitOnCompletion === false ? 'Child pipeline started asynchronously' : 'Child pipeline completed'} · parameter mapping accepted`;
  if (type === 'foreach') {
    const innerCount = nestedActivityCount(node.config.innerActivities);
    const evaluated = evaluateExpression(String(node.config.items ?? ''), { parameters, variables, nodes });
    const iterations = Array.isArray(evaluated) ? evaluated.length : 2;
    return `${iterations} iterations completed · ${innerCount} inner activit${innerCount === 1 ? 'y' : 'ies'} per iteration · ${node.config.sequential ? 'sequential' : `parallel batch ${node.config.batchCount ?? 20}`}`;
  }
  if (type === 'if') {
    const result = evaluateExpression(String(node.config.expression ?? ''), { parameters, variables, nodes });
    const branch = result === false ? 'False' : 'True';
    const childCount = nestedActivityCount(branch === 'True' ? node.config.trueActivities : node.config.falseActivities);
    return `Expression evaluated ${branch} · ${childCount} nested activit${childCount === 1 ? 'y' : 'ies'} selected`;
  }
  if (type === 'setVariable') return `Pipeline variable ${node.config.variableName || '(unselected)'} updated`;
  if (type === 'appendVariable') return `Value appended to array variable ${node.config.variableName || '(unselected)'}`;
  if (type === 'until') {
    const innerCount = nestedActivityCount(node.config.innerActivities);
    const result = evaluateExpression(String(node.config.expression ?? ''), { parameters, variables, nodes });
    return `Until condition ${result === true ? 'satisfied' : 'evaluated in mock loop'} · ${innerCount} child activit${innerCount === 1 ? 'y' : 'ies'} · 1 simulated iteration`;
  }
  if (type === 'eventstream') return '3 events accepted · 0 dropped · avg latency 184 ms';
  if (type === 'web') return `HTTP ${String(node.config.method ?? 'GET')} · 200 OK`;
  if (type === 'delete') return 'Delete completed · 2 objects removed';
  if (type === 'wait') return `Wait completed after ${Number(node.config.seconds ?? 5)} seconds (simulated)`;
  return 'Activity completed successfully';
}

function inputFor(node: PipelineNode): string {
  const policyKeys = new Set(['description', 'timeout', 'retry', 'retryIntervalSeconds', 'retryIntervalType', 'maxRetryIntervalSeconds', 'retryConditionField', 'retryConditionOperator', 'retryConditionValue', 'secureInput', 'secureOutput', 'simulateFailure', 'simulateFailureType', 'simulateErrorCode', 'simulateErrorMessage']);
  const config = Object.fromEntries(Object.entries(node.config).filter(([key]) => !policyKeys.has(key)));
  return JSON.stringify(config, null, 2);
}

function metricsFor(node: PipelineNode, c: CaseStudy, durationMs: number): Record<string, string | number> {
  if (node.type === 'copy') {
    const rows = c.id === 'retail-medallion' ? 4 : c.id === 'turbine-realtime' ? 3 : 5;
    const readBytes = c.id === 'retail-medallion' ? 18637 : rows * 6144;
    const writtenBytes = Math.round(readBytes * 0.92);
    return {
      rowsRead: rows,
      rowsWritten: rows,
      dataReadBytes: readBytes,
      dataWrittenBytes: writtenBytes,
      filesRead: 1,
      filesWritten: 1,
      throughputMBps: Number(((readBytes / 1024 / 1024) / Math.max(durationMs / 1000, 0.1)).toFixed(2)),
      queueMs: 120,
      transferMs: Math.max(durationMs - 120, 0),
      parallelCopies: Number(node.config.parallelCopies ?? 4),
      mappedColumns: parseCopyMapping(node.config.mapping).rows.length,
      autoMap: String(parseCopyMapping(node.config.mapping).autoMap),
    };
  }
  if (node.type === 'copyJob') return { rowsRead: 3, rowsWritten: 3, watermarkApplied: 'true', durationMs };
  if (node.type === 'lookup') return { rowsReturned: node.config.firstRowOnly ? 1 : 2, firstRowOnly: String(Boolean(node.config.firstRowOnly)), payloadBytes: 384 };
  if (node.type === 'storedProcedure') return { parametersBound: procedureParameterCount(node), rowsAffected: c.id === 'erp-incremental' ? 2 : 4, durationMs };
  if (node.type === 'dbt') return { command: String(node.config.command ?? 'dbt build'), target: String(node.config.target ?? 'dev'), select: String(node.config.select ?? ''), exclude: String(node.config.exclude ?? ''), threads: Number(node.config.threads ?? 4), fullRefresh: String(Boolean(node.config.fullRefresh)), failFast: String(Boolean(node.config.failFast)), models: 2, durationMs };
  if (node.type === 'script') return { statements: String(node.config.script ?? '').split(';').filter((part) => part.trim()).length, rowsAffected: 3, durationMs };
  if (node.type === 'invokePipeline') return { childRunId: `child-${node.id.slice(0, 8)}`, waitOnCompletion: String(node.config.waitOnCompletion !== false), durationMs };
  if (node.type === 'notebook') return { notebookRuntimeMs: durationMs, outputTables: 1, warnings: 0 };
  if (node.type === 'eventstream') return { eventsIn: 3, eventsOut: 3, droppedEvents: 0, averageLatencyMs: 184 };
  return { durationMs };
}

function retryConditionMatches(node: PipelineNode): boolean {
  const field = String(node.config.retryConditionField ?? 'Any failure');
  if (field === 'Any failure') return true;
  const expected = String(node.config.retryConditionValue ?? '').toLowerCase();
  if (!expected) return false;
  const operator = String(node.config.retryConditionOperator ?? 'Contains');
  const actual = field === 'Error code'
    ? String(node.config.simulateErrorCode ?? '429')
    : field === 'Failure type'
      ? String(node.config.simulateFailureType ?? 'System error')
      : String(node.config.simulateErrorMessage ?? 'Transient service throttling');
  const left = actual.toLowerCase();
  if (operator === 'Equals') return left === expected;
  if (operator === 'Starts with') return left.startsWith(expected);
  return left.includes(expected);
}

function retryWaitSeconds(node: PipelineNode, retryCount: number): number {
  if (retryCount <= 0) return 0;
  const base = Math.max(Number(node.config.retryIntervalSeconds ?? 30), 0);
  if (String(node.config.retryIntervalType ?? 'Fixed') !== 'Increasing Delay') return base * retryCount;
  const max = Math.max(Number(node.config.maxRetryIntervalSeconds ?? 3600), base);
  let total = 0;
  for (let attempt = 1; attempt <= retryCount; attempt += 1) total += Math.min(base * (2 ** Math.max(attempt - 1, 0)), max);
  return total;
}

function effectiveAttempts(node: PipelineNode, status: RunStatus): number {
  if (status !== 'Failed') return 1;
  const retry = Math.max(Number(node.config.retry ?? 0), 0);
  return retryConditionMatches(node) ? retry + 1 : 1;
}

function baseDurationFor(node: PipelineNode, index: number, status: RunStatus): number {
  if (status === 'Skipped') return 0;
  const retryCount = status === 'Failed' && retryConditionMatches(node) ? Number(node.config.retry ?? 0) : 0;
  const typeExtra = node.type === 'notebook' ? 2100 : node.type === 'copy' ? 900 : node.type === 'dataflow' ? 1200 : 0;
  return 420 + (index % 4) * 210 + typeExtra + Math.max(retryCount, 0) * 280;
}

function startOffsetsFor(nodes: PipelineNode[], edges: PipelineEdge[], durationById: Map<string, number>): Map<string, number> {
  const offsets = new Map<string, number>();
  const remaining = new Set(nodes.map((node) => node.id));
  while (remaining.size) {
    let progressed = false;
    for (const node of nodes) {
      if (!remaining.has(node.id)) continue;
      const incoming = edges.filter((edge) => edge.to === node.id && durationById.has(edge.from));
      if (incoming.some((edge) => remaining.has(edge.from))) continue;
      const start = incoming.length
        ? Math.max(...incoming.map((edge) => (offsets.get(edge.from) ?? 0) + (durationById.get(edge.from) ?? 0)))
        : 0;
      offsets.set(node.id, start);
      remaining.delete(node.id);
      progressed = true;
    }
    if (!progressed) {
      remaining.forEach((id) => offsets.set(id, 0));
      break;
    }
  }
  return offsets;
}

export function applyVariableActivities(nodes: PipelineNode[], statusByNode: Map<string, RunStatus>, parameters: PipelineParameter[], variables: PipelineVariable[]): PipelineVariable[] {
  let next = variables.map((variable) => ({ ...variable }));
  for (const node of nodes) {
    if (statusByNode.get(node.id) !== 'Succeeded') continue;
    if (node.type !== 'setVariable' && node.type !== 'appendVariable') continue;
    const variableName = String(node.config.variableName ?? '');
    const index = next.findIndex((variable) => variable.name === variableName);
    if (index < 0) continue;
    const evaluated = evaluateExpression(String(node.config.value ?? ''), { parameters, variables: next, nodes });
    if (node.type === 'setVariable') {
      next[index] = { ...next[index], currentValue: typeof evaluated === 'string' ? evaluated : JSON.stringify(evaluated) };
      continue;
    }
    let arrayValue: unknown[] = [];
    try {
      const parsed = JSON.parse(next[index].currentValue || next[index].defaultValue || '[]');
      if (Array.isArray(parsed)) arrayValue = parsed;
    } catch {
      arrayValue = [];
    }
    arrayValue.push(evaluated);
    next[index] = { ...next[index], currentValue: JSON.stringify(arrayValue) };
  }
  return next;
}

export function createRun(caseStudy: CaseStudy, experience: 'fabric' | 'azure', nodes: PipelineNode[], statusByNode?: Map<string, RunStatus>, parameters: PipelineParameter[] = [], variables: PipelineVariable[] = [], edges: PipelineEdge[] = [], trigger = 'Debug', runtimeErrors: Record<string, string> = {}): PipelineRun {
  const now = new Date();
  const durationById = new Map<string, number>();
  nodes.forEach((node, index) => durationById.set(node.id, baseDurationFor(node, index, statusByNode?.get(node.id) ?? 'Succeeded')));
  const startOffsets = startOffsetsFor(nodes, edges, durationById);
  const activities = nodes.map((n) => {
    const status = statusByNode?.get(n.id) ?? 'Succeeded';
    const retry = Math.max(Number(n.config.retry ?? 0), 0);
    const attempts = effectiveAttempts(n, status);
    const runtimeError = runtimeErrors[n.id];
    const output = status === 'Failed'
      ? runtimeError ? `Runtime failure in ${n.name}: ${runtimeError}` : `Simulated failure in ${n.name} after ${attempts} attempt${attempts === 1 ? '' : 's'}. Inspect activity diagnostics, correct the configuration, then retry.`
      : status === 'Skipped'
        ? 'Skipped because its dependency condition was not satisfied.'
        : outputFor(n, caseStudy, parameters, variables, nodes);
    const durationMs = durationById.get(n.id) ?? 0;
    return {
      nodeId: n.id,
      name: n.name,
      type: n.type,
      status,
      durationMs,
      startOffsetMs: startOffsets.get(n.id) ?? 0,
      attempts,
      input: inputFor(n),
      output,
      error: status === 'Failed' ? (runtimeError ? `LearningDataRuntimeError: ${runtimeError}` : `${String(n.config.simulateFailureType ?? 'System error')} ${String(n.config.simulateErrorCode ?? '429')}: ${String(n.config.simulateErrorMessage ?? `${n.name} failed after retry policy was exhausted.`)}`) : undefined,
      metrics: status === 'Skipped' ? {} : { ...metricsFor(n, caseStudy, durationMs), ...(status === 'Failed' ? { retry_policy: retry > 0 ? String(n.config.retryIntervalType ?? 'Fixed') : 'Disabled', retry_condition_match: String(retryConditionMatches(n)), retry_wait_seconds: retryWaitSeconds(n, Math.max(attempts - 1, 0)), failure_type: String(n.config.simulateFailureType ?? 'System error'), error_code: String(n.config.simulateErrorCode ?? '429') } : {}) },
      secureInput: Boolean(n.config.secureInput),
      secureOutput: Boolean(n.config.secureOutput),
      dependencies: edges.filter((edge) => edge.to === n.id).map((edge) => ({ nodeId: edge.from, condition: edge.condition })),
      rerunDisposition: 'Executed' as const,
    };
  });
  const status: RunStatus = activities.some((activity) => activity.status === 'Failed') ? 'Failed' : 'Succeeded';
  const durationMs = activities.reduce((max, activity) => Math.max(max, activity.startOffsetMs + activity.durationMs), 0);
  return {
    id: `run-${Date.now()}`,
    caseStudyId: caseStudy.id,
    experience,
    startedAt: now.toISOString(),
    durationMs,
    status,
    trigger,
    parameterValues: Object.fromEntries(parameters.map((parameter) => [parameter.name, parameter.defaultValue])),
    variableValues: Object.fromEntries(variables.map((variable) => [variable.name, variable.currentValue])),
    activities,
  };
}

export function applyStepSolution(step: TutorialStep, nodes: PipelineNode[], edges: PipelineEdge[]): { nodes: PipelineNode[]; edges: PipelineEdge[] } {
  let nextNodes = [...nodes];
  let nextEdges = [...edges];

  if (step.apply.addNode) {
    const exists = nextNodes.some((n) => n.type === step.apply.addNode?.type && n.name === step.apply.addNode?.name);
    if (!exists) {
      const partial = step.apply.addNode;
      const node: PipelineNode = {
        id: `${partial.type}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        type: partial.type,
        name: partial.name,
        x: partial.x ?? 70 + nextNodes.length * 230,
        y: partial.y ?? 150,
        status: 'Not run',
        config: { ...defaultConfig(partial.type), ...(partial.config ?? {}) },
      };
      nextNodes.push(node);
    }
  }

  if (step.apply.updateNodeType && step.apply.updateConfig) {
    nextNodes = nextNodes.map((n) => n.type === step.apply.updateNodeType ? { ...n, config: { ...n.config, ...step.apply.updateConfig } } : n);
  }

  if (step.apply.connectTypes) {
    const a = nextNodes.find((n) => n.type === step.apply.connectTypes?.[0]);
    const b = nextNodes.find((n) => n.type === step.apply.connectTypes?.[1]);
    if (a && b && !nextEdges.some((e) => e.from === a.id && e.to === b.id)) {
      nextEdges.push({ id: `edge-${a.id}-${b.id}`, from: a.id, to: b.id, condition: 'Succeeded' });
    }
  }

  return { nodes: nextNodes, edges: nextEdges };
}
