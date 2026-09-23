import type { PracticeItem } from '@datapass/content';
import type { ProgressStateV2 } from '@datapass/progress';
import {
  CatalogShell,
  EntityCard,
  EntityTable,
  SearchFilterBar,
  ViewToggle,
  filterAndSortCatalogItems,
  setCatalogFacetValues,
  setCatalogQuery,
  setCatalogView,
  useCatalogUrlState,
} from '@datapass/ui';
import { Badge, Button, Field, Select } from '@fluentui/react-components';
import { CorpusMetrics } from '../components/CorpusMetrics';
import { practiceCatalog, practiceItems } from '../data/practice';
import { hasPracticeVisual } from '../data/visuals';
import { statusFor } from '../utils/progress';

const config = {
  allowedFacets: ['track', 'difficulty', 'language', 'status', 'visual'],
  defaultView: 'table' as const,
};
const statusLabels: Record<string, string> = {
  'not-started': 'Not started',
  'in-progress': 'In progress',
  completed: 'Completed',
  mastered: 'Mastered',
  review: 'Review later',
  flagged: 'Flagged',
};

export function PracticeCatalogPage({ progress, onSelect }: { progress: ProgressStateV2; onSelect: (id: string) => void }) {
  const [state, setState] = useCatalogUrlState({ config });
  const filtered = filterAndSortCatalogItems(practiceItems, state, {
    searchText: item => [item.title, item.summary, item.domain, item.concept, ...item.tags],
    facetValues: (item, facet) => {
      if (facet === 'track') return [item.trackId];
      if (facet === 'difficulty') return [item.difficulty];
      if (facet === 'language') return item.variants.flatMap(v => [v.language, v.label]);
      if (facet === 'status') return [statusFor(progress, item.id)];
      if (facet === 'visual') return [hasPracticeVisual(item.id) ? 'mapped' : 'text'];
      return [];
    },
  });

  const visualCount = practiceItems.filter(item => hasPracticeVisual(item.id)).length;
  const facet = (key: string, label: string, options: { value: string; label: string }[]) => (
    <Field className="lab-filter" label={label}>
      <Select
        aria-label={label}
        value={state.filters[key]?.[0] ?? ''}
        onChange={event => setState(current => setCatalogFacetValues(current, key, event.target.value ? [event.target.value] : []))}
      >
        <option value="">All</option>
        {options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
      </Select>
    </Field>
  );

  return (
    <>
      <CorpusMetrics items={practiceItems} tracks={practiceCatalog.tracks} visualCount={visualCount} />
      <CatalogShell
        header={
          <SearchFilterBar
            label="Search practice"
            placeholder="Search title, pattern, SQL clause, engine, or topic"
            query={state.query}
            onQueryChange={value => setState(current => setCatalogQuery(current, value))}
            filters={
              <>
                {facet('track', 'Track', practiceCatalog.tracks.map(track => ({ value: track.id, label: track.name })))}
                {facet('difficulty', 'Difficulty', ['Easy', 'Medium', 'Hard'].map(value => ({ value, label: value })))}
                {facet('language', 'Language / engine', [...new Set(practiceItems.flatMap(i => i.variants.map(v => v.label)))].sort().map(value => ({ value, label: value })))}
                {facet('status', 'Progress', ['not-started', 'in-progress', 'mastered', 'review', 'flagged'].map(value => ({ value, label: statusLabels[value] })))}
                {facet('visual', 'Visual', [{ value: 'mapped', label: 'Visualize available' }, { value: 'text', label: 'No mapped Figure' }])}
              </>
            }
            actions={<ViewToggle value={state.view} onChange={value => setState(current => setCatalogView(current, value))} />}
          />
        }
        results={
          <>
            <div className="lab-catalog-summary">
              <p role="status"><strong>{filtered.length}</strong> of {practiceItems.length} practice items</p>
              <div className="lab-actions">
                <Button onClick={() => setState(current => setCatalogFacetValues(current, 'status', ['review']))}>Review queue</Button>
                <Button onClick={() => setState(current => ({ ...current, query: '', filters: {} }))}>Clear filters</Button>
              </div>
            </div>
            {filtered.length === 0 ? <div className="lab-empty"><h2>No matching exercises</h2><p>Clear one or more filters, or try a broader pattern name.</p></div>
              : state.view === 'cards' ? (
                <div className="lab-grid">
                  {filtered.map(item => (
                    <EntityCard
                      key={item.id}
                      entityId={item.id}
                      title={item.title}
                      eyebrow={item.domain}
                      description={item.summary}
                      metadata={<><Badge appearance="outline">{item.difficulty}</Badge><Badge appearance="outline">{item.variants.length} variant{item.variants.length === 1 ? '' : 's'}</Badge>{hasPracticeVisual(item.id) && <Badge appearance="tint">Visualize</Badge>}</>}
                      onSelect={onSelect}
                    />
                  ))}
                </div>
              ) : (
                <EntityTable<PracticeItem>
                  items={filtered}
                  getRowId={item => item.id}
                  onRowSelect={item => onSelect(item.id)}
                  columns={[
                    { id: 'title', header: 'Practice item', renderCell: item => <><strong>{item.title}</strong><small>{item.domain}</small>{hasPracticeVisual(item.id) && <span className="lab-visual-indicator">Visualize available</span>}</> },
                    { id: 'difficulty', header: 'Difficulty', renderCell: item => item.difficulty },
                    { id: 'engines', header: 'Language / engine', renderCell: item => item.variants.map(v => v.label).join(' · ') },
                    { id: 'status', header: 'Progress', renderCell: item => statusLabels[statusFor(progress, item.id)] ?? 'Not started' },
                  ]}
                />
              )}
          </>
        }
      />
    </>
  );
}
