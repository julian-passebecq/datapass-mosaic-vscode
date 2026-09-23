import { useRef, useState } from 'react';
import { Badge, Button, Text } from '@fluentui/react-components';
import { DataUsage20Regular, TableSimple20Regular } from '@fluentui/react-icons';
import { ConceptScene } from '@conceptmotion/react';
import {
  FigureFrame,
  InspectorPanel,
  PageHeader,
  TimelineControls,
  Workbench,
  useLocale,
} from '@datapass/ui';
import { SvgExportButton } from '../components/SvgExportButton';
import { tableLessonFrames, tableSceneSpec } from '../data/semanticFixtures';
import { figureLabels, timelineLabels } from '../lib/localizedChrome';
import { useTimeline } from '../lib/useTimeline';

export function WorkbenchPage() {
  const { locale } = useLocale();
  const timeline = useTimeline(tableLessonFrames.length, 'table-filter-sort');
  const current = tableLessonFrames[timeline.currentStep];
  const [selectedId, setSelectedId] = useState<string>();
  const visualRef = useRef<HTMLDivElement>(null);
  const rows = current.state.rowOrder
    .map((rowId) => current.state.rows.find((row) => row.id === rowId))
    .filter((row): row is NonNullable<typeof row> => Boolean(row));

  const navigation = (
    <div className="lesson-rail">
      <span className="surface-card__eyebrow">SEMANTIC STEPS</span>
      {tableLessonFrames.map((frame, index) => (
        <Button
          key={frame.id}
          appearance={timeline.currentStep === index ? 'subtle' : 'transparent'}
          className={timeline.currentStep === index ? 'lesson-rail__item is-active' : 'lesson-rail__item'}
          onClick={() => timeline.controls.onSeek(index)}
          aria-current={timeline.currentStep === index ? 'step' : undefined}
        >
          <span>{index + 1}</span>
          <span><b>{frame.operation}</b><small>{frame.caption}</small></span>
        </Button>
      ))}
    </div>
  );

  const fallback = (
    <table className="fallback-table">
      <caption className="visually-hidden">Current order rows after {current.operation}</caption>
      <thead><tr>{current.state.columns.map((column) => <th key={column.id}>{String(column.label ?? column.id)}</th>)}</tr></thead>
      <tbody>{rows.map((row) => <tr key={row.id} data-row-id={row.id}>{current.state.columns.map((column) => <td key={column.id}>{String(row.values[column.id] ?? 'NULL')}</td>)}</tr>)}</tbody>
    </table>
  );

  const inspector = (
    <InspectorPanel
      title={locale === 'no' ? 'Semantisk tilstand' : 'Semantic state'}
      description={locale === 'no' ? 'Beregnet i ren TypeScript før rendering.' : 'Compiled in pure TypeScript before rendering.'}
    >
      <dl className="inspector-list">
        <div><dt>Snapshot</dt><dd>{current.state.snapshot.id}</dd></div>
        <div><dt>{locale === 'no' ? 'Synlige rader' : 'Visible rows'}</dt><dd>{current.state.visibleRowIds.length}</dd></div>
        <div><dt>{locale === 'no' ? 'Filtrert ut' : 'Filtered out'}</dt><dd>{current.state.filteredOutRowIds.length}</dd></div>
        <div><dt>{locale === 'no' ? 'Flyttinger' : 'Moves'}</dt><dd>{current.transition.movingIds.length}</dd></div>
        <div><dt>{locale === 'no' ? 'Utganger' : 'Exits'}</dt><dd>{current.transition.exitingIds.length}</dd></div>
        <div><dt>{locale === 'no' ? 'Valgt objekt' : 'Selected entity'}</dt><dd>{selectedId ?? (locale === 'no' ? 'Ingen' : 'None')}</dd></div>
      </dl>
      <div className="semantic-id-note">
        <DataUsage20Regular aria-hidden />
        <Text size={200}>Row IDs survive position changes; slot coordinates do not define identity.</Text>
      </div>
    </InspectorPanel>
  );

  const figure = (
    <div ref={visualRef}>
      <FigureFrame
        {...figureLabels(locale)}
        title={locale === 'no' ? 'De samme radene beveger seg' : 'The same rows move'}
        subtitle={locale === 'no' ? 'Filtrer først, sorter deretter etter beløp.' : 'Filter first, then sort by amount.'}
        takeaway={current.caption}
        metadata={(
          <div className="metadata-row">
            <Badge appearance="tint" color="informative">{current.operation}</Badge>
            <Badge appearance="outline">{current.state.snapshot.entities.length} semantic entities</Badge>
          </div>
        )}
        toolbar={<TimelineControls {...timeline.controls} labels={timelineLabels(locale)} />}
        exportAction={<SvgExportButton hostRef={visualRef} filename={`table-${current.id}.svg`} label={locale === 'no' ? 'Eksporter SVG' : 'Export SVG'} />}
        source="Local deterministic fixture · @conceptmotion/core"
        note={locale === 'no' ? 'Bruk tabellalternativet for en bevegelsesfri representasjon.' : 'Use the table alternative for a non-motion representation.'}
        fallback={fallback}
        fallbackMode="details"
        minimumHeight="25rem"
      >
        <div className="visual-host" data-testid="table-scene">
          <ConceptScene
            spec={tableSceneSpec}
            frameIndex={timeline.currentStep}
            reducedMotion={timeline.reducedMotion}
            selectedId={selectedId}
            onSelect={setSelectedId}
            options={{
              transitionDurationMs: Math.round(520 / timeline.speed),
              locale,
            }}
            ariaLabel={`${current.operation}. ${current.caption}`}
            fallback={fallback}
          />
        </div>
      </FigureFrame>
    </div>
  );

  return (
    <Workbench
      data-testid="workbench-page"
      navigationLabel={locale === 'no' ? 'Leksjonstrinn' : 'Lesson steps'}
      canvasLabel={locale === 'no' ? 'Visualiseringsflate' : 'Visualization canvas'}
      inspectorLabel={locale === 'no' ? 'Detaljer' : 'Inspector'}
      header={(
        <PageHeader
          eyebrow="WORKBENCH · STABLE IDENTITY"
          title={locale === 'no' ? 'Tabelltransformasjon' : 'Table transformation'}
          description={locale === 'no'
            ? 'Semantisk tilstand, overgangsplan og SVG-rendering er separate, testbare lag.'
            : 'Semantic state, transition planning and SVG rendering are separate, testable layers.'}
          metadata={<Badge appearance="outline" icon={<TableSimple20Regular />}>filter → sort</Badge>}
        />
      )}
      navigation={navigation}
      canvas={figure}
      inspector={inspector}
      bottomPanel={(
        <div className="state-strip" aria-live="polite">
          <b>{current.operation}</b>
          <span>{current.caption}</span>
          {timeline.reducedMotion && <Badge appearance="tint">Reduced motion · step mode</Badge>}
        </div>
      )}
    />
  );
}
