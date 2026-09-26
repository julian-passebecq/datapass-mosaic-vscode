import { Badge, Button, Text } from "@fluentui/react-components";
import { useState, type ReactNode } from "react";
import type { VsCodeApi } from "./WorkbenchApp";
import {
  missionStatus,
  nextBatch,
  ticketBlocks,
  type MissionProgressView,
  type MissionView,
  type TicketBlock,
  type TicketSpan
} from "../platform/missions";

export interface MissionsPanelState {
  missions: readonly MissionView[];
  progress: Readonly<Record<string, MissionProgressView>>;
}

const LEVEL: Record<string, string> = { intro: "Intro", intermediate: "Intermediate", advanced: "Advanced" };

/**
 * Missions: ticket-style tasks, less guided than Practice. Generic over the lab: the dbt Lab and the Terminal Lab
 * show it with their own missions and wording (the Infra Lab will too).
 */
export function MissionsPanel({
  state,
  vscode,
  canRun,
  blockedReason,
  openLabel = "Open the project",
  folderNote,
  send: sendAction,
  extra
}: {
  state: MissionsPanelState;
  vscode: VsCodeApi;
  canRun: boolean;
  blockedReason?: string;
  openLabel?: string;
  /** What to say about the mission's folder once it is started. */
  folderNote: (mission: MissionView, progress: MissionProgressView) => ReactNode;
  /** A lab with its own mission messages (the Lakehouse Lab) posts the actions itself. */
  send?: (action: string, missionId: string) => void;
  /** What the lab shows under the actions of a started mission (the Lakehouse Lab's Run and its output). */
  extra?: (mission: MissionView, progress: MissionProgressView) => ReactNode;
}) {
  const [selected, setSelected] = useState<string | undefined>(state.missions[0]?.id);
  const mission = state.missions.find(item => item.id === selected) ?? state.missions[0];
  if (!mission) return <p className="factory-note">No mission is shipped for this lab yet.</p>;
  const progress = state.progress[mission.id];
  const check = progress?.lastCheck;
  const next = nextBatch(mission, progress);
  const send = (type: string) => sendAction ? sendAction(type, mission.id) : vscode.postMessage({ type, missionId: mission.id } as never);

  return (
    <div className="missions">
      <nav className="missions-list" aria-label="Missions">
        {state.missions.map(item => {
          const status = missionStatus(state.progress[item.id]);
          return (
            <button key={item.id} type="button" className={`mission-card${item.id === mission.id ? " is-selected" : ""}`}
              onClick={() => setSelected(item.id)}>
              <span className="mission-card-title">{item.title}</span>
              <span className="mission-card-meta">
                {LEVEL[item.level] ?? item.level}{item.estimate ? ` · ${item.estimate}` : ""}
                {" · "}
                <span className={`mission-status-${status}`}>{status === "passed" ? "passed" : status === "in-progress" ? "in progress" : "new"}</span>
              </span>
            </button>
          );
        })}
      </nav>

      <article className="mission-detail">
        <header className="mission-ticket-head">
          <div className="eyebrow">Ticket · from {mission.ticket.from}</div>
          <Text size={500} weight="semibold">{mission.ticket.subject}</Text>
          <div className="button-row">
            {mission.skills.map(skill => <Badge key={skill} appearance="outline" size="small">{skill}</Badge>)}
          </div>
        </header>
        <TicketBody blocks={ticketBlocks(mission.ticket.body)} />

        <div className="button-row mission-actions">
          {!progress?.started ? (
            <Button appearance="primary" disabled={!canRun} onClick={() => send("startMission")}>Start mission</Button>
          ) : (
            <>
              <Button appearance="secondary" onClick={() => send("openMission")}>{openLabel}</Button>
              {next && <Button appearance="secondary" disabled={!canRun} onClick={() => send("loadMissionBatch")}>Load next batch: {next.label}</Button>}
              <Button appearance="primary" disabled={!canRun} onClick={() => send("checkMission")}>Check my work</Button>
              <Button appearance="subtle" disabled={!canRun} onClick={() => send("restartMission")}>Start over</Button>
            </>
          )}
        </div>
        {!canRun && blockedReason && <p className="factory-note">{blockedReason}</p>}
        {progress?.started && <p className="factory-note">{folderNote(mission, progress)}</p>}
        {progress?.started && extra?.(mission, progress)}

        <section className="mission-criteria">
          <Text weight="semibold">Acceptance criteria</Text>
          {check && (
            <p className={check.status === "passed" ? "mission-passed" : "factory-note"}>
              {check.status === "passed" ? "Mission passed. " : "Not there yet. "}
              Checked {new Date(check.checkedAt).toLocaleString()}.
            </p>
          )}
          {check?.requires.map(message => <p key={message} className="factory-warning">{message}</p>)}
          <ul>
            {mission.acceptance.map(item => {
              const result = check?.criteria.find(criterion => criterion.id === item.id);
              return (
                <li key={item.id} className={result ? (result.passed ? "criterion-pass" : "criterion-fail") : "criterion-open"}>
                  <span aria-hidden="true">{result ? (result.passed ? "✓" : "✗") : "○"}</span> {item.text}
                  {result && !result.passed && result.details.map((detail, index) => <small key={index}>{detail}</small>)}
                </li>
              );
            })}
          </ul>
          {check?.truth && <p className="factory-note">{check.truth}</p>}
        </section>

        <section className="mission-hints">
          <Text weight="semibold">Hints</Text>
          {mission.hints.slice(0, progress?.hintsShown ?? 0).map((hint, index) => (
            <p key={index} className="mission-hint"><TicketSpans spans={ticketBlocks(hint).flatMap(b => b.kind === "p" ? b.spans : [])} /></p>
          ))}
          {(progress?.hintsShown ?? 0) < mission.hints.length ? (
            <Button size="small" appearance="secondary" disabled={!progress?.started} onClick={() => send("revealMissionHint")}>
              Show a hint ({mission.hints.length - (progress?.hintsShown ?? 0)} left)
            </Button>
          ) : mission.hints.length > 0 && <p className="factory-note">No more hints.</p>}
        </section>
      </article>
    </div>
  );
}

function TicketBody({ blocks }: { blocks: TicketBlock[] }) {
  return (
    <div className="mission-ticket-body">
      {blocks.map((block, index) => {
        if (block.kind === "code") return <pre key={index} className="factory-json">{block.text}</pre>;
        if (block.kind === "p") return <p key={index}><TicketSpans spans={block.spans} /></p>;
        const items = block.items.map((spans, item) => <li key={item}><TicketSpans spans={spans} /></li>);
        return block.kind === "ul" ? <ul key={index}>{items}</ul> : <ol key={index}>{items}</ol>;
      })}
    </div>
  );
}

function TicketSpans({ spans }: { spans: TicketSpan[] }) {
  return (
    <>
      {spans.map((span, index) =>
        span.kind === "code" ? <code key={index}>{span.text}</code>
          : span.kind === "strong" ? <strong key={index}>{span.text}</strong>
            : <span key={index}>{span.text}</span>)}
    </>
  );
}
