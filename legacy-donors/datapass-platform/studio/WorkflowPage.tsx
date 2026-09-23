import { useEffect, useMemo, useRef, useState } from 'react';
import { JsonSpecEditor } from '@datapass/code';
import {
  Badge,
  Button,
  Dropdown,
  MessageBar,
  MessageBarBody,
  Option,
  Select,
  Slider,
  Tab,
  TabList,
  Text,
} from '@fluentui/react-components';
import {
  ArrowDownload20Regular,
  ArrowReset20Regular,
  CheckmarkCircle20Regular,
  Copy20Regular,
  ErrorCircle20Regular,
  FolderOpen20Regular,
  ZoomFit20Regular,
  ZoomIn20Regular,
  ZoomOut20Regular,
} from '@fluentui/react-icons';
import {
  compileWorkflowRun,
  parseJson,
  resolveLocalizedText,
  serializeDeterministic,
  validateWorkflowSpec,
  type CompiledWorkflowRunFrame,
  type ValidationIssue,
  type WorkflowPreset,
  type WorkflowSpec,
  type WorkflowStatus,
} from '@conceptmotion/core';
import { WorkflowScene } from '@conceptmotion/react';
import {
  FigureFrame,
  InspectorPanel,
  PageHeader,
  TimelineControls,
  WorkflowWorkbenchShell,
  useLocale,
} from '@datapass/ui';
import { SvgExportButton } from '../components/SvgExportButton';
import { workflowFixture, workflowPresets, workflowWithPreset } from '../data/diagramFixtures';
import { figureLabels, timelineLabels } from '../lib/localizedChrome';
import { useTimeline } from '../lib/useTimeline';

type WorkflowMode = 'topology' | 'run' | 'spec';

function resolveTaskId(selectedId: string | undefined, spec: WorkflowSpec): string | undefined {
  if (!selectedId) return undefined;
  if (spec.nodes.some((node) => node.id === selectedId)) return selectedId;
  return spec.nodes.find((node) => selectedId.endsWith(`:${node.id}`))?.id;
}

function saveText(filename: string, text: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function statusCounts(frame: CompiledWorkflowRunFrame | undefined) {
  const result: Partial<Record<WorkflowStatus, number>> = {};
  Object.values(frame?.states ?? {}).forEach(({ status }) => { result[status] = (result[status] ?? 0) + 1; });
  return result;
}

export function WorkflowPage() {
  const { locale } = useLocale();
  const [mode, setMode] = useState<WorkflowMode>('run');
  const [preset, setPreset] = useState<WorkflowPreset>('airflow');
  const [runId, setRunId] = useState('run-retry');
  const [focusedGroupId, setFocusedGroupId] = useState<string>();
  const [selectedId, setSelectedId] = useState<string>('transform');
  const [zoom, setZoom] = useState(1);
  const initialJson = useMemo(() => serializeDeterministic(workflowFixture), []);
  const [source, setSource] = useState(initialJson);
  const [editorIssues, setEditorIssues] = useState<ValidationIssue[]>([]);
  const [parsedSpec, setParsedSpec] = useState<WorkflowSpec>(workflowFixture);
  const visualRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      try {
        const candidate = parseJson<WorkflowSpec>(source);
        const result = validateWorkflowSpec(candidate);
        setEditorIssues([...result.issues]);
        if (result.valid) setParsedSpec(candidate);
      } catch (error) {
        setEditorIssues([{ code: 'json.syntax', path: '$', severity: 'error', message: error instanceof Error ? error.message : String(error) }]);
      }
    }, 220);
    return () => window.clearTimeout(timer);
  }, [source]);

  const activeBase = mode === 'spec' ? parsedSpec : workflowFixture;
  const activeSpec = useMemo(() => ({ ...activeBase, preset }), [activeBase, preset]);
  const focusGroup = activeSpec.groups?.[0];
  const activeFocusedGroup = activeSpec.groups?.find((group) => group.id === focusedGroupId);
  useEffect(() => {
    if (focusedGroupId && !activeFocusedGroup) setFocusedGroupId(undefined);
  }, [activeFocusedGroup, focusedGroupId]);
  const availableRunId = activeSpec.runs?.some((run) => run.id === runId) ? runId : activeSpec.runs?.[0]?.id;
  const frames = useMemo(
    () => availableRunId ? compileWorkflowRun(activeSpec, availableRunId) : [],
    [activeSpec, availableRunId],
  );
  const timeline = useTimeline(Math.max(1, frames.length), `${activeSpec.id}:${availableRunId ?? 'none'}:${mode}`);
  const currentFrame = mode === 'run' ? frames[timeline.currentStep] : undefined;
  const taskId = resolveTaskId(selectedId, activeSpec);
  const selectedTask = activeSpec.nodes.find((node) => node.id === taskId);
  const selectedState = taskId ? currentFrame?.states[taskId] : undefined;
  const counts = statusCounts(currentFrame);

  const modeTabs = (
    <TabList selectedValue={mode} onTabSelect={(_, data) => setMode(data.value as WorkflowMode)} aria-label="Workflow mode">
      <Tab id="workflow-tab-topology" aria-controls="workflow-mode-panel" value="topology">{locale === 'no' ? 'Topologi' : 'Topology'}</Tab>
      <Tab id="workflow-tab-run" aria-controls="workflow-mode-panel" value="run">{locale === 'no' ? 'Kjøringsforklaring' : 'Run explanation'}</Tab>
      <Tab id="workflow-tab-spec" aria-controls="workflow-mode-panel" value="spec">Spec playground</Tab>
    </TabList>
  );

  const toolbar = (
    <div className="workflow-toolbar">
      <Dropdown
        aria-label="Presentation preset"
        selectedOptions={[preset]}
        value={workflowPresets.find((item) => item.id === preset)?.label}
        onOptionSelect={(_, data) => setPreset((data.optionValue ?? 'airflow') as WorkflowPreset)}
      >
        {workflowPresets.map((item) => <Option key={item.id} value={item.id}>{item.label}</Option>)}
      </Dropdown>
      {mode === 'run' && (
        <Select aria-label="Synthetic workflow run" value={runId} onChange={(event) => setRunId(event.currentTarget.value)}>
          {(activeSpec.runs ?? []).map((run) => <option key={run.id} value={run.id}>{typeof run.label === 'string' ? run.label : run.label?.[locale] ?? run.id}</option>)}
        </Select>
      )}
      <div className="zoom-controls" role="group" aria-label="Canvas zoom controls">
        <Button icon={<ZoomOut20Regular />} aria-label="Zoom out" onClick={() => setZoom((value) => Math.max(.75, value - .1))} />
        <Slider min={.75} max={1.5} step={.05} value={zoom} aria-label="Canvas zoom" onChange={(_, data) => setZoom(data.value)} />
        <Button icon={<ZoomIn20Regular />} aria-label="Zoom in" onClick={() => setZoom((value) => Math.min(1.5, value + .1))} />
        <Button icon={<ZoomFit20Regular />} aria-label="Reset zoom to 100%" title="Reset zoom to 100%" onClick={() => setZoom(1)} />
      </div>
    </div>
  );

  const breadcrumb = (
    <div className="workflow-breadcrumb">
      <Button appearance="transparent" size="small" onClick={() => setFocusedGroupId(undefined)}>{resolveLocalizedText(activeSpec.title, locale)}</Button>
      {activeFocusedGroup && <><span aria-hidden>/</span><Text size={200} weight="semibold" aria-current="page">{resolveLocalizedText(activeFocusedGroup.label, locale)}</Text></>}
      <Button
        appearance={activeFocusedGroup ? 'subtle' : 'transparent'}
        size="small"
        icon={<FolderOpen20Regular />}
        disabled={!focusGroup}
        onClick={() => setFocusedGroupId((value) => value ? undefined : focusGroup?.id)}
      >
        {activeFocusedGroup ? 'Show full graph' : 'Focus task group'}
      </Button>
    </div>
  );

  const workflowFallback = (
    <div className="workflow-fallback">
      <p>{currentFrame ? `Synthetic run ${currentFrame.runId}, frame ${currentFrame.index + 1} of ${frames.length}.` : 'Topology-only view; no tasks are executed.'}</p>
      <ul>{activeSpec.nodes.map((node) => <li key={node.id}><b>{typeof node.label === 'string' ? node.label : node.label[locale] ?? node.label.en}</b>: {currentFrame?.states[node.id]?.status ?? 'topology'}</li>)}</ul>
    </div>
  );

  const graph = (
    <div ref={visualRef} className="workflow-visual-host">
      <FigureFrame
        {...figureLabels(locale)}
        title={`${workflowPresets.find((item) => item.id === preset)?.label} · ${mode === 'run' ? 'synthetic run' : 'topology'}`}
        subtitle="One WorkflowSpec; presentation changes, semantics do not."
        takeaway={currentFrame
          ? currentFrame.transition.items.length
            ? `${currentFrame.transition.items.length} semantic state changes in this frame.`
            : 'Declared start state.'
          : 'Topology mode does not imply execution.'}
        metadata={(
          <div className="metadata-row">
            <Badge appearance="outline">preset: {preset}</Badge>
            <Badge appearance="outline">{activeSpec.nodes.length} tasks</Badge>
            <Badge appearance="outline">{activeSpec.groups?.length ?? 0} group</Badge>
          </div>
        )}
        exportAction={<SvgExportButton hostRef={visualRef} filename={`workflow-${preset}-${mode}.svg`} />}
        fallback={workflowFallback}
        fallbackMode="details"
        source="Local WorkflowSpec fixture · no provider API"
        note="Edge line pattern, marker and label carry condition meaning in addition to color."
        minimumHeight="30rem"
      >
        <div className="workflow-zoom-viewport" data-testid="workflow-scene">
          <div className="workflow-zoom-layer" style={{ transform: `scale(${zoom})` }}>
            <WorkflowScene
              spec={activeSpec}
              frameIndex={timeline.currentStep}
              runId={availableRunId}
              mode={mode === 'run' ? 'run' : 'topology'}
              focusedGroupId={focusedGroupId}
              preset={preset}
              selectedId={selectedId}
              onSelect={setSelectedId}
              reducedMotion={timeline.reducedMotion}
              options={{ locale }}
              ariaLabel="Provider-independent workflow topology and synthetic run state"
              fallback={workflowFallback}
            />
          </div>
        </div>
      </FigureFrame>
    </div>
  );

  const specPlayground = (
    <div className="spec-playground" data-testid="spec-playground">
      <section className="spec-editor" aria-label="Workflow JSON editor">
        <div className="spec-toolbar">
          <div>
            <b>WorkflowSpec JSON</b>
            <span>{editorIssues.length ? `${editorIssues.length} validation issue${editorIssues.length === 1 ? '' : 's'}` : 'Valid · preview updated'}</span>
          </div>
          <div className="toolbar-row">
            <Button size="small" icon={<Copy20Regular />} onClick={() => void navigator.clipboard?.writeText(source)}>Copy</Button>
            <Button size="small" icon={<ArrowDownload20Regular />} onClick={() => saveText('sales-refresh.workflow.json', source, 'application/json')}>JSON</Button>
            <Button size="small" icon={<ArrowReset20Regular />} onClick={() => setSource(initialJson)}>Reset</Button>
          </div>
        </div>
        <div className="monaco-frame monaco-frame--compact">
          <JsonSpecEditor
            height="430px"
            value={source}
            onChange={(value) => setSource(value ?? '')}
            path="sales-refresh.workflow.json"
            ariaLabel="WorkflowSpec JSON editor"
            diagnostics={editorIssues.map((issue) => ({
              severity: issue.severity === 'warning' ? 'warning' : 'error',
              message: `${issue.path} — ${issue.message}`,
              source: issue.code,
            }))}
            options={{ fontSize: 12 }}
          />
        </div>
        <div className="validation-panel" role="status" aria-live="polite">
          {editorIssues.length === 0 ? (
            <MessageBar intent="success"><MessageBarBody><CheckmarkCircle20Regular /> Valid WorkflowSpec. Live preview updated.</MessageBarBody></MessageBar>
          ) : (
            <MessageBar intent="error"><MessageBarBody><ErrorCircle20Regular /> {editorIssues.slice(0, 4).map((issue) => <div key={`${issue.path}:${issue.code}`}><code>{issue.path}</code> — {issue.message}</div>)}</MessageBarBody></MessageBar>
          )}
        </div>
      </section>
      <section className="spec-preview" aria-label="Last valid WorkflowSpec preview">
        {graph}
      </section>
    </div>
  );

  const inspector = (
    <InspectorPanel title={selectedTask ? (typeof selectedTask.label === 'string' ? selectedTask.label : selectedTask.label[locale] ?? selectedTask.label.en) : 'Select a task'} description={selectedTask?.providerType ?? 'Task inspector'}>
      {selectedTask ? (
        <dl className="inspector-list">
          <div><dt>Stable ID</dt><dd>{selectedTask.id}</dd></div>
          <div><dt>Task type</dt><dd>{selectedTask.taskType ?? 'generic'}</dd></div>
          <div><dt>Run state</dt><dd><span className={`run-state run-state--${selectedState?.status ?? 'pending'}`}>{selectedState?.status ?? (mode === 'topology' ? 'topology only' : 'pending')}</span></dd></div>
          <div><dt>Attempt</dt><dd>{selectedState?.attempt ?? '—'}</dd></div>
          <div><dt>Group</dt><dd>{selectedTask.groupId ?? 'Root'}</dd></div>
          {Object.entries(selectedTask.metadata ?? {}).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{String(value)}</dd></div>)}
        </dl>
      ) : <Text>Select a task with pointer, Enter or Space.</Text>}
    </InspectorPanel>
  );

  const bottom = mode === 'run' ? (
    <div className="workflow-bottom">
      <TimelineControls {...timeline.controls} labels={timelineLabels(locale)} />
      <div className="run-state-legend" aria-label="Current workflow state summary" aria-live="polite">
        {Object.entries(counts).map(([status, count]) => <span key={status} className={`run-state run-state--${status}`}>{status.replace('_', ' ')} {count}</span>)}
      </div>
      <div className="edge-legend" aria-label="Dependency condition legend">
        <span data-condition="success">→ success</span>
        <span data-condition="failure">⇢ failure</span>
        <span data-condition="completion">⇒ completion</span>
        <span data-condition="skip">⋯ skip</span>
      </div>
    </div>
  ) : undefined;

  return (
    <WorkflowWorkbenchShell
      data-testid="workflow-page"
      canvasLabel={locale === 'no' ? 'Arbeidsflytflate' : 'Workflow canvas'}
      inspectorLabel={locale === 'no' ? 'Detaljer for valgt oppgave' : 'Selected task inspector'}
      breadcrumbLabel={locale === 'no' ? 'Fokusert oppgavegruppe' : 'Focused workflow group'}
      header={(
        <PageHeader
          eyebrow="ORCHESTRATION WORKBENCH · DECLARED RUNS ONLY"
          title={locale === 'no' ? 'Én motor, tre presentasjoner' : 'One engine, three presentations'}
          description={locale === 'no'
            ? 'Airflow, Fabric/ADF og Lakeflow deler validering, topologi og deterministiske kjøringstilstander.'
            : 'Airflow, Fabric/ADF and Lakeflow share validation, topology and deterministic run state.'}
          metadata={<Badge appearance="tint" color="informative">No execution</Badge>}
        />
      )}
      modeTabs={modeTabs}
      toolbar={toolbar}
      breadcrumb={breadcrumb}
      canvas={mode === 'spec' ? specPlayground : graph}
      canvasId="workflow-mode-panel"
      canvasLabelledBy={`workflow-tab-${mode}`}
      inspector={mode === 'spec' ? undefined : inspector}
      bottomPanel={bottom}
    />
  );
}
