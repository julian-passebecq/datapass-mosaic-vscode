import type { WorkflowSpec } from '@conceptmotion/core';
import type { FigureSpec, JsonValue } from '@datapass/content';

export type PatternId =
  | 'fan-out-fan-in'
  | 'conditional-branch'
  | 'retry-idempotency'
  | 'partition-backfill'
  | 'quality-gate'
  | 'asset-trigger'
  | 'checkpoint-watermark';

export interface PatternRecord {
  readonly id: PatternId;
  readonly eyebrow: string;
  readonly title: string;
  readonly summary: string;
  readonly invariant: string;
  readonly failureTrap: string;
  readonly workflow: WorkflowSpec;
  readonly figure: FigureSpec;
  readonly captions: readonly string[];
  readonly checklist: readonly string[];
}

function workflowFigure(
  workflow: WorkflowSpec,
  title: string,
  takeaway: string,
  fallbackText: string
): FigureSpec {
  return {
    id: `figure.${workflow.id}`,
    kind: 'workflow',
    rendererId: 'workflow.run',
    title,
    takeaway,
    spec: JSON.parse(JSON.stringify(workflow)) as JsonValue,
    fallbackText,
    profile: 'professional',
    status: 'Deterministic teaching fixture; no pipeline is executed.'
  };
}

const fanOutFanIn: WorkflowSpec = {
  kind: 'workflow',
  version: '4-consumer-1',
  id: 'pipeline.fan-out-fan-in',
  title: 'Fan out ingestion, then fan in at a quality gate',
  description: 'One release creates independent ingestion work; publication waits for every required branch.',
  preset: 'generic',
  layout: { direction: 'lr', density: 'comfortable' },
  nodes: [
    { id: 'release', label: 'Release window', taskType: 'trigger', metadata: { role: 'upstream', watch: 'One event releases the parallel branches.' } },
    { id: 'orders', label: 'Ingest orders', taskType: 'ingest', metadata: { role: 'parallel', watch: 'Independent branch.' } },
    { id: 'customers', label: 'Ingest customers', taskType: 'ingest', metadata: { role: 'parallel', watch: 'Independent branch.' } },
    { id: 'products', label: 'Ingest products', taskType: 'ingest', metadata: { role: 'parallel', watch: 'Independent branch.' } },
    { id: 'quality', label: 'Cross-source quality gate', taskType: 'quality', metadata: { role: 'fan-in', watch: 'Must wait for all required upstream tasks.' } },
    { id: 'publish', label: 'Publish trusted snapshot', taskType: 'publish', metadata: { role: 'downstream', watch: 'Only eligible after the gate succeeds.' } }
  ],
  edges: [
    { id: 'release-orders', from: 'release', to: 'orders', condition: 'success' },
    { id: 'release-customers', from: 'release', to: 'customers', condition: 'success' },
    { id: 'release-products', from: 'release', to: 'products', condition: 'success' },
    { id: 'orders-quality', from: 'orders', to: 'quality', condition: 'success' },
    { id: 'customers-quality', from: 'customers', to: 'quality', condition: 'success' },
    { id: 'products-quality', from: 'products', to: 'quality', condition: 'success' },
    { id: 'quality-publish', from: 'quality', to: 'publish', condition: 'success' }
  ],
  runs: [{
    id: 'happy-path',
    label: 'All branches complete',
    frames: [
      { id: 'release-running', states: { release: { status: 'running' } } },
      { id: 'parallel-running', states: { release: { status: 'success' }, orders: { status: 'running' }, customers: { status: 'running' }, products: { status: 'running' } } },
      { id: 'two-ready', states: { orders: { status: 'success' }, customers: { status: 'success' } } },
      { id: 'gate-running', states: { products: { status: 'success' }, quality: { status: 'running' } } },
      { id: 'publish-running', states: { quality: { status: 'success' }, publish: { status: 'running' } } },
      { id: 'complete', states: { publish: { status: 'success' } } }
    ]
  }]
};

const branch: WorkflowSpec = {
  kind: 'workflow', version: '4-consumer-1', id: 'pipeline.conditional-branch', title: 'Choose one refresh path', preset: 'generic',
  layout: { direction: 'lr', density: 'comfortable' },
  groups: [{ id: 'decision', label: 'Refresh decision', kind: 'condition', childNodeIds: ['check', 'incremental', 'full'] }],
  nodes: [
    { id: 'check', label: 'Check change volume', groupId: 'decision', taskType: 'condition', metadata: { role: 'branch', watch: 'The condition selects one path.' } },
    { id: 'incremental', label: 'Incremental refresh', groupId: 'decision', taskType: 'transform', metadata: { role: 'selected-path', watch: 'Runs for the selected branch.' } },
    { id: 'full', label: 'Full rebuild', groupId: 'decision', taskType: 'transform', metadata: { role: 'alternate-path', watch: 'Skipped is not failed.' } },
    { id: 'publish', label: 'Publish model', taskType: 'publish', metadata: { role: 'merge', watch: 'Join semantics must tolerate the skipped alternate branch.' } }
  ],
  edges: [
    { id: 'check-incremental', from: 'check', to: 'incremental', condition: 'true', label: 'small change set' },
    { id: 'check-full', from: 'check', to: 'full', condition: 'false', label: 'large change set' },
    { id: 'incremental-publish', from: 'incremental', to: 'publish', condition: 'completion' },
    { id: 'full-publish', from: 'full', to: 'publish', condition: 'completion' }
  ],
  runs: [{ id: 'incremental-selected', frames: [
    { id: 'check', states: { check: { status: 'running' } } },
    { id: 'branch', states: { check: { status: 'success' }, incremental: { status: 'running' }, full: { status: 'skipped', message: 'Condition not selected' } } },
    { id: 'publish', states: { incremental: { status: 'success' }, publish: { status: 'running' } } },
    { id: 'complete', states: { publish: { status: 'success' } } }
  ] }]
};

const retry: WorkflowSpec = {
  kind: 'workflow', version: '4-consumer-1', id: 'pipeline.retry-idempotency', title: 'Retry a keyed write without duplicating effects', preset: 'generic',
  layout: { direction: 'lr', density: 'comfortable' },
  parameters: { idempotencyKey: 'event_id', retryLimit: 3 },
  nodes: [
    { id: 'extract', label: 'Read event', taskType: 'source', metadata: { role: 'input', watch: 'The event keeps the same business identity across retries.' } },
    { id: 'upsert', label: 'Upsert by event ID', taskType: 'sink', metadata: { role: 'idempotent-effect', watch: 'Attempt identity changes; business key does not.' } },
    { id: 'publish', label: 'Publish success marker', taskType: 'publish', metadata: { role: 'downstream', watch: 'Do not publish before the durable effect is confirmed.' } }
  ],
  edges: [
    { id: 'extract-upsert', from: 'extract', to: 'upsert', condition: 'success' },
    { id: 'upsert-publish', from: 'upsert', to: 'publish', condition: 'success' }
  ],
  runs: [{ id: 'lost-response', frames: [
    { id: 'read', states: { extract: { status: 'running' } } },
    { id: 'write-1', states: { extract: { status: 'success' }, upsert: { status: 'running', attempt: 1 } } },
    { id: 'retry', states: { upsert: { status: 'retrying', attempt: 2, message: 'Response lost; retry same event key' } } },
    { id: 'write-2', states: { upsert: { status: 'running', attempt: 2 } } },
    { id: 'publish', states: { upsert: { status: 'success', attempt: 2 }, publish: { status: 'running' } } },
    { id: 'complete', states: { publish: { status: 'success' } } }
  ] }]
};

const backfill: WorkflowSpec = {
  kind: 'workflow', version: '4-consumer-1', id: 'pipeline.partition-backfill', title: 'Backfill three bounded partitions', preset: 'generic',
  layout: { direction: 'lr', density: 'comfortable' },
  parameters: { startDate: '2026-09-01', endDate: '2026-09-03', writeMode: 'replace-partition' },
  groups: [{ id: 'partitions', label: 'Bounded date partitions', kind: 'foreach', childNodeIds: ['p-0901', 'p-0902', 'p-0903'] }],
  nodes: [
    { id: 'plan', label: 'Resolve partition range', taskType: 'plan', metadata: { role: 'scope', watch: 'Bound the historical scope explicitly.' } },
    { id: 'p-0901', label: '2026-09-01', groupId: 'partitions', taskType: 'partition', metadata: { role: 'partition', partition: '2026-09-01' } },
    { id: 'p-0902', label: '2026-09-02', groupId: 'partitions', taskType: 'partition', metadata: { role: 'partition', partition: '2026-09-02' } },
    { id: 'p-0903', label: '2026-09-03', groupId: 'partitions', taskType: 'partition', metadata: { role: 'partition', partition: '2026-09-03' } },
    { id: 'reconcile', label: 'Reconcile partition counts', taskType: 'quality', metadata: { role: 'fan-in', watch: 'Verify all requested dates before publication.' } },
    { id: 'publish', label: 'Expose rebuilt range', taskType: 'publish', metadata: { role: 'downstream', watch: 'Current partitions outside the range are untouched.' } }
  ],
  edges: [
    { id: 'plan-p1', from: 'plan', to: 'p-0901', condition: 'success' },
    { id: 'plan-p2', from: 'plan', to: 'p-0902', condition: 'success' },
    { id: 'plan-p3', from: 'plan', to: 'p-0903', condition: 'success' },
    { id: 'p1-reconcile', from: 'p-0901', to: 'reconcile', condition: 'success' },
    { id: 'p2-reconcile', from: 'p-0902', to: 'reconcile', condition: 'success' },
    { id: 'p3-reconcile', from: 'p-0903', to: 'reconcile', condition: 'success' },
    { id: 'reconcile-publish', from: 'reconcile', to: 'publish', condition: 'success' }
  ],
  runs: [{ id: 'three-days', frames: [
    { id: 'plan', states: { plan: { status: 'running' } } },
    { id: 'partitions', states: { plan: { status: 'success' }, 'p-0901': { status: 'running' }, 'p-0902': { status: 'running' }, 'p-0903': { status: 'running' } } },
    { id: 'two-complete', states: { 'p-0901': { status: 'success' }, 'p-0902': { status: 'success' } } },
    { id: 'reconcile', states: { 'p-0903': { status: 'success' }, reconcile: { status: 'running' } } },
    { id: 'publish', states: { reconcile: { status: 'success' }, publish: { status: 'running' } } },
    { id: 'complete', states: { publish: { status: 'success' } } }
  ] }]
};

const qualityGate: WorkflowSpec = {
  kind: 'workflow', version: '4-consumer-1', id: 'pipeline.quality-gate', title: 'A failed quality gate blocks publication', preset: 'generic',
  layout: { direction: 'lr', density: 'comfortable' },
  nodes: [
    { id: 'build', label: 'Build candidate', taskType: 'transform', metadata: { role: 'candidate', watch: 'Candidate data is not yet trusted.' } },
    { id: 'quality', label: 'Validate contract', taskType: 'quality', metadata: { role: 'gate', watch: 'Freshness, row count and key checks decide readiness.' } },
    { id: 'publish', label: 'Publish', taskType: 'publish', metadata: { role: 'protected', watch: 'A blocked publish is a successful guardrail.' } },
    { id: 'alert', label: 'Raise incident', taskType: 'observe', metadata: { role: 'failure-path', watch: 'Failure path should be visible and actionable.' } }
  ],
  edges: [
    { id: 'build-quality', from: 'build', to: 'quality', condition: 'success' },
    { id: 'quality-publish', from: 'quality', to: 'publish', condition: 'success' },
    { id: 'quality-alert', from: 'quality', to: 'alert', condition: 'failure' }
  ],
  runs: [{ id: 'quality-fails', frames: [
    { id: 'build', states: { build: { status: 'running' } } },
    { id: 'quality', states: { build: { status: 'success' }, quality: { status: 'running' } } },
    { id: 'blocked', states: { quality: { status: 'failed', message: 'Duplicate business keys > 0' }, publish: { status: 'upstream_failed' }, alert: { status: 'running' } } },
    { id: 'incident', states: { alert: { status: 'success' } } }
  ] }]
};

const assetTrigger: WorkflowSpec = {
  kind: 'workflow', version: '4-consumer-1', id: 'pipeline.asset-trigger', title: 'Downstream work starts from an asset event', preset: 'generic',
  schedule: { kind: 'event', label: 'Trusted orders asset updated' },
  layout: { direction: 'lr', density: 'comfortable' },
  nodes: [
    { id: 'detect', label: 'Detect asset update', taskType: 'event', metadata: { role: 'trigger', watch: 'Freshness is driven by an event, not a fixed clock.' } },
    { id: 'model', label: 'Build daily sales model', taskType: 'model', metadata: { role: 'consumer', watch: 'The task depends on declared upstream data readiness.' } },
    { id: 'refresh', label: 'Refresh BI semantic model', taskType: 'serve', metadata: { role: 'serve', watch: 'Serving refresh follows the model, not the source event directly.' } }
  ],
  edges: [
    { id: 'detect-model', from: 'detect', to: 'model', condition: 'success', dataFlowKind: 'control' },
    { id: 'model-refresh', from: 'model', to: 'refresh', condition: 'success', dataFlowKind: 'control' }
  ],
  runs: [{ id: 'asset-update', frames: [
    { id: 'event', states: { detect: { status: 'running' } } },
    { id: 'model', states: { detect: { status: 'success' }, model: { status: 'running' } } },
    { id: 'refresh', states: { model: { status: 'success' }, refresh: { status: 'running' } } },
    { id: 'complete', states: { refresh: { status: 'success' } } }
  ] }]
};

const checkpointWatermark: WorkflowSpec = {
  kind: 'workflow', version: '4-consumer-1', id: 'pipeline.checkpoint-watermark', title: 'Checkpoint progress while a watermark bounds late data', preset: 'generic',
  layout: { direction: 'lr', density: 'comfortable' },
  nodes: [
    { id: 'events', label: 'Read event stream', taskType: 'stream', metadata: { role: 'source', watch: 'Offsets define replay position.' } },
    { id: 'checkpoint', label: 'Persist checkpoint', taskType: 'state', metadata: { role: 'recovery', watch: 'Recovery resumes from durable progress.' } },
    { id: 'window', label: 'Aggregate event-time window', taskType: 'window', metadata: { role: 'event-time', watch: 'Watermark is a lateness policy, not wall-clock ordering.' } },
    { id: 'sink', label: 'Upsert window result', taskType: 'sink', metadata: { role: 'idempotent-sink', watch: 'Replay-safe writes avoid duplicate effects.' } }
  ],
  edges: [
    { id: 'events-checkpoint', from: 'events', to: 'checkpoint', condition: 'success', dataFlowKind: 'data' },
    { id: 'checkpoint-window', from: 'checkpoint', to: 'window', condition: 'success', dataFlowKind: 'data' },
    { id: 'window-sink', from: 'window', to: 'sink', condition: 'success', dataFlowKind: 'data' }
  ],
  runs: [{ id: 'micro-batch', frames: [
    { id: 'read', states: { events: { status: 'running' } } },
    { id: 'checkpoint', states: { events: { status: 'success' }, checkpoint: { status: 'running' } } },
    { id: 'window', states: { checkpoint: { status: 'success' }, window: { status: 'running' } } },
    { id: 'sink', states: { window: { status: 'success' }, sink: { status: 'running' } } },
    { id: 'complete', states: { sink: { status: 'success' } } }
  ] }]
};

export const patterns: readonly PatternRecord[] = [
  {
    id: 'fan-out-fan-in', eyebrow: 'DAG SHAPE', title: 'Fan-out / fan-in',
    summary: 'Parallelize independent work, then converge at an explicit dependency boundary.',
    invariant: 'The fan-in task is not ready until every required predecessor reaches an accepted terminal state.',
    failureTrap: 'Treating “one branch finished” as “the dataset is ready” creates partial snapshots.',
    workflow: fanOutFanIn,
    figure: workflowFigure(fanOutFanIn, 'Fan-out / fan-in', 'Parallelism changes elapsed time; it does not remove downstream completeness requirements.', 'Release window fans out to orders, customers and products. All three converge on a quality gate before publish.'),
    captions: ['Release the dependency window.', 'Three independent ingestions run in parallel.', 'Two branches are done; the gate still waits.', 'The final branch finishes and the fan-in gate runs.', 'Gate success releases publication.', 'The trusted snapshot is complete.'],
    checklist: ['Independent branches have explicit IDs.', 'Fan-in declares every required predecessor.', 'Partial success is observable.', 'Publication is downstream of validation.']
  },
  {
    id: 'conditional-branch', eyebrow: 'CONTROL FLOW', title: 'Branch + skipped path',
    summary: 'Select one mutually exclusive path without misclassifying the unselected path as a failure.',
    invariant: 'Skipped is a deliberate terminal state; downstream joins need trigger semantics that accept the intended branch outcome.',
    failureTrap: 'A downstream task that requires all branches to succeed can deadlock after a valid skip.',
    workflow: branch,
    figure: workflowFigure(branch, 'Conditional branch', 'Skipped and failed communicate different causes and require different downstream logic.', 'Change-volume check selects incremental refresh. Full rebuild is skipped. Publish continues after the selected branch.'),
    captions: ['Evaluate the branch condition.', 'Incremental refresh is selected; full rebuild is skipped.', 'The selected path succeeds and publication starts.', 'Publication completes.'],
    checklist: ['Branch predicate is observable.', 'Skipped state is expected.', 'Join trigger rule matches branch semantics.', 'Both paths write compatible outputs.']
  },
  {
    id: 'retry-idempotency', eyebrow: 'RELIABILITY', title: 'Retry + idempotency',
    summary: 'Retry transport or task failure without duplicating the business effect.',
    invariant: 'Repeated application of the same business event must converge to the same durable state.',
    failureTrap: 'Retries are a scheduler policy; idempotency is a data-effect property. One does not imply the other.',
    workflow: retry,
    figure: workflowFigure(retry, 'Retry a keyed write', 'Keep attempt identity separate from business identity.', 'Read one event, upsert by stable event ID, retry after a lost response, then publish only after durable success.'),
    captions: ['Read one event with a stable business key.', 'Attempt 1 starts the keyed write.', 'The response is lost; schedule a retry with the same business key.', 'Attempt 2 repeats the same intended effect.', 'Durable success releases publication.', 'All tasks are complete.'],
    checklist: ['Stable idempotency key.', 'Bounded retry policy.', 'Side effects happen after durable commit.', 'Metrics separate attempts from business events.']
  },
  {
    id: 'partition-backfill', eyebrow: 'HISTORICAL REPLAY', title: 'Bounded partition backfill',
    summary: 'Recompute a declared historical range without silently touching unrelated current partitions.',
    invariant: 'The backfill scope is explicit, replayable and reconciled before exposure.',
    failureTrap: 'A “rerun everything” backfill can mutate current data, explode cost and hide partition-specific failures.',
    workflow: backfill,
    figure: workflowFigure(backfill, 'Backfill three partitions', 'Partition-scoped replay makes historical repair bounded and auditable.', 'Plan three dates, process each partition, reconcile the requested range, then expose only after every requested partition succeeds.'),
    captions: ['Resolve the exact historical range.', 'Run the three requested partitions independently.', 'Two dates are done; one is still running.', 'All dates finish; reconcile counts and keys.', 'Publish the rebuilt range.', 'Backfill completes without touching outside partitions.'],
    checklist: ['Start/end partition are explicit.', 'Writes are partition-scoped or key-scoped.', 'Each partition can retry independently.', 'Reconciliation covers the requested range.']
  },
  {
    id: 'quality-gate', eyebrow: 'DATA CONTRACT', title: 'Quality gate blocks publish',
    summary: 'Make “not trusted yet” a visible state in the pipeline rather than an after-the-fact dashboard surprise.',
    invariant: 'Publication requires an explicit quality success condition.',
    failureTrap: 'Logging failed checks without blocking the publish task turns quality into decoration.',
    workflow: qualityGate,
    figure: workflowFigure(qualityGate, 'Quality gate', 'A blocked publish can be the correct pipeline outcome.', 'Build candidate data, validate its contract, fail the gate, block publish and raise an incident.'),
    captions: ['Build candidate data.', 'Run the declared data contract checks.', 'The gate fails; publication is blocked while the failure path runs.', 'The incident path completes; publish remains blocked.'],
    checklist: ['Checks map to an owned contract.', 'Failure blocks dependent publish.', 'Incident path carries evidence.', 'Override, if allowed, is explicit and audited.']
  },
  {
    id: 'asset-trigger', eyebrow: 'SCHEDULING', title: 'Asset / event-triggered downstream work',
    summary: 'Trigger consumers from declared data readiness instead of guessing a clock offset.',
    invariant: 'The trigger represents a meaningful upstream state transition, not merely elapsed time.',
    failureTrap: 'A 06:00 downstream schedule does not prove that the 05:30 upstream data is actually ready.',
    workflow: assetTrigger,
    figure: workflowFigure(assetTrigger, 'Asset-triggered delivery', 'Schedule from dependency readiness where the platform supports it.', 'Trusted asset update triggers model build, which then triggers BI semantic model refresh.'),
    captions: ['Observe the trusted asset update.', 'Build the downstream analytical model.', 'Refresh the serving semantic model.', 'Delivery is complete.'],
    checklist: ['Event has stable identity.', 'Missed events can be replayed.', 'Consumer can detect stale upstream state.', 'Clock scheduling remains a fallback, not fake lineage.']
  },
  {
    id: 'checkpoint-watermark', eyebrow: 'STREAMING', title: 'Checkpoint + late-data watermark',
    summary: 'Separate recovery progress from event-time completeness policy.',
    invariant: 'Checkpoint answers “where can I resume?”; watermark answers “how late can event-time data arrive before a window is considered complete?”',
    failureTrap: 'Treating checkpoint and watermark as the same control confuses fault recovery with business-time correctness.',
    workflow: checkpointWatermark,
    figure: workflowFigure(checkpointWatermark, 'Checkpoint and watermark', 'Recovery state and event-time policy solve different failure modes.', 'Read a stream, persist recovery progress, aggregate by event time under a lateness policy, and upsert the window result.'),
    captions: ['Read the next bounded chunk of events.', 'Persist recovery progress.', 'Evaluate event-time windows under the lateness policy.', 'Write the window result with replay-safe semantics.', 'The micro-batch is complete.'],
    checklist: ['Checkpoint storage is durable.', 'Watermark policy matches business lateness.', 'Sink tolerates replay.', 'Lag, late drops and checkpoint age are observable.']
  }
] as const;

export const patternById = (id: PatternId): PatternRecord => patterns.find(pattern => pattern.id === id)!;
