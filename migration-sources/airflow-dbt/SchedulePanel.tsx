import type { AirflowDefinition } from '../types.js';
import { previewDataIntervals, scheduleDescription } from '../lib/scheduleSimulator.js';

export function SchedulePanel({definition}:{definition:AirflowDefinition}){
  const intervals=previewDataIntervals(definition,3);
  return <div className="schedule-panel">
    <section className="schedule-summary-card">
      <div className="eyebrow">DAG SCHEDULE</div><h3>{definition.schedule}</h3>
      <dl><dt>Meaning</dt><dd>{scheduleDescription(definition.schedule)}</dd><dt>start_date</dt><dd>{definition.startDate}</dd><dt>catchup</dt><dd>{String(definition.catchup)}</dd><dt>Simulator scope</dt><dd>Bounded cron/data-interval preview only. This UI does not implement Airflow's full timetable engine, time zones, DST, datasets, or custom timetables.</dd></dl>
    </section>
    <section className="schedule-learning-card">
      <h3>Scheduler mental model</h3>
      <div className="schedule-steps"><article><strong>1 · Data interval</strong><p>For a cron data-interval timetable, a scheduled run represents the interval between consecutive schedule boundaries. The run is eligible after the interval ends.</p></article><article><strong>2 · Catchup</strong><p>{definition.catchup?'Catchup is enabled: historical scheduled intervals after start_date can become candidates when the DAG is activated.':'Catchup is disabled: Airflow normally advances toward the latest eligible interval instead of automatically materializing every missed interval.'}</p></article><article><strong>3 · Backfill</strong><p>Backfill explicitly requests historical runs. It is different from retrying one failed task instance inside one DAG run.</p></article></div>
    </section>
    <section className="interval-preview-card"><div className="section-heading"><h3>Bounded data-interval preview</h3><span>UTC teaching preview anchored to 2026-09-17; supported cron subset only</span></div>{intervals.length?<div className="interval-row">{intervals.map((interval)=><div key={`${interval.start}-${interval.end}`}><span>data interval</span><strong>{interval.start}</strong><small>→ {interval.end}</small><small>scheduled after {interval.runAfter}</small><small>{definition.catchup?'catchup/backfill candidate if historical':'manual backfill candidate if historical'}</small></div>)}</div>:<div className="empty-state"><strong>Schedule preview intentionally unavailable</strong><span>The expression is outside this simulator's bounded cron subset. The real Airflow timetable engine supports more schedules than this teaching preview.</span></div>}</section>
  </div>;
}
