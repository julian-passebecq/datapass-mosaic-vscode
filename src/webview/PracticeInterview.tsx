import { Badge, Button, Input, Select, Text } from "@fluentui/react-components";
import { useEffect, useMemo, useState } from "react";
import {
  MAX_INTERVIEW_PROBLEMS,
  MIXED_LANGUAGES,
  PATTERN_FAMILIES,
  clock,
  defaultLimitMinutes,
  drawInterview,
  familyLabel,
  interviewLanguages,
  secondsBetween,
  seededRandom,
  startInterview,
  summarizeInterview,
  trackInterview,
  type InterviewOptions,
  type InterviewRecord,
  type InterviewSession
} from "../platform/practiceInterview";
import { LANGUAGE_ORDER, languageLabel, type PracticeProblem } from "../platform/practiceProblems";
import type { PracticeViewState, RuntimeViewState } from "./contracts";
import { PracticeProblemCard } from "./PracticeProblemCard";
import type { VsCodeApi } from "./WorkbenchApp";

const DEFAULT_OPTIONS: InterviewOptions = { format: "mixed", language: "sql", count: 3, difficulty: "", family: "" };

/** Practice › Interview: set up a series, work it against the clock without hints, then read its summary. */
export function PracticeInterview({ vscode, practice, runtime, problems }: {
  vscode: VsCodeApi;
  practice: PracticeViewState;
  runtime: RuntimeViewState;
  problems: readonly PracticeProblem[];
}) {
  const saved = readState(vscode);
  const [options, setOptionsState] = useState<InterviewOptions>(() => restoreOptions(saved.practiceInterviewOptions));
  const [limit, setLimit] = useState<number>(() => defaultLimitMinutes(restoreOptions(saved.practiceInterviewOptions).count));
  const [session, setSessionState] = useState<InterviewSession | undefined>(() => restoreSession(saved.practiceInterview));
  const [shortDraw, setShortDraw] = useState<number>();
  const setOptions = (next: InterviewOptions) => {
    if (next.count !== options.count) setLimit(defaultLimitMinutes(next.count));
    setOptionsState(next);
    vscode.setState({ ...readState(vscode), practiceInterviewOptions: next });
  };
  const setSession = (next: InterviewSession | undefined) => {
    setSessionState(next);
    vscode.setState({ ...readState(vscode), practiceInterview: next });
  };

  // Every grading shows up in the variant's progress record: follow the series through it.
  useEffect(() => {
    if (!session) return;
    const next = trackInterview(session, practice.progress.exercises);
    if (next !== session) setSession(next);
  }, [practice.progress, session]);

  const languages = useMemo(() => interviewLanguages(problems)
    .sort((a, b) => rank(a) - rank(b) || a.localeCompare(b)), [problems]);
  const difficulties = useMemo(() => [...new Set(problems.map(p => p.difficulty))]
    .sort((a, b) => ["easy", "medium", "hard"].indexOf(a) - ["easy", "medium", "hard"].indexOf(b)), [problems]);

  const start = () => {
    const drawn = drawInterview(problems, options, seededRandom(Date.now()));
    if (!drawn.length) {
      setShortDraw(0);
      return;
    }
    setShortDraw(drawn.length < options.count ? drawn.length : undefined);
    setSession(startInterview(drawn, options, limit, practice.progress.exercises, new Date().toISOString()));
  };

  if (session && !session.finishedAt) {
    return <RunningInterview vscode={vscode} practice={practice} runtime={runtime} problems={problems} session={session}
      shortDraw={shortDraw}
      onFinish={() => {
        const finishedAt = new Date().toISOString();
        const tracked = trackInterview(session, practice.progress.exercises);
        vscode.postMessage({ type: "saveInterview", interview: summarizeInterview(tracked, finishedAt) });
        setSession({ ...tracked, finishedAt });
      }}
      onAbandon={() => setSession(undefined)} />;
  }

  return (
    <div className="interview">
      {session?.finishedAt && (
        <InterviewSummary record={summarizeInterview(session, session.finishedAt)} problems={problems}
          onClose={() => setSession(undefined)} />
      )}
      {!session && (
        <div className="interview-setup">
          <Text size={400} weight="semibold">Interview mode</Text>
          <p className="muted">
            A random series against the clock, without hints or reference solutions. Submits count as usual: they
            solve the language variant and move its spaced review. When the time is up the clock keeps running as
            overtime.
          </p>
          <div className="interview-format" role="radiogroup" aria-label="Interview format">
            <label>
              <input type="radio" name="interview-format" checked={options.format === "mixed"}
                onChange={() => setOptions({ ...options, format: "mixed" })} />
              <span>
                <strong>Mixed interview</strong>
                <small className="muted">
                  {MIXED_LANGUAGES.map(languageLabel).join(", ")} in turn, each problem on a different classic pattern
                  (joins, aggregation, window functions, deduplication, time series…).
                </small>
              </span>
            </label>
            <label>
              <input type="radio" name="interview-format" checked={options.format === "fixed"}
                onChange={() => setOptions({ ...options, format: "fixed" })} />
              <span>
                <strong>One language</strong>
                <small className="muted">Every problem in the language you pick, on varied patterns or on one you choose.</small>
              </span>
            </label>
          </div>
          <div className="interview-options">
            {options.format === "fixed" && (
              <Select aria-label="Interview language" size="small" value={options.language}
                onChange={(_, data) => setOptions({ ...options, language: data.value })}>
                {languages.map(language => <option key={language} value={language}>{languageLabel(language)}</option>)}
              </Select>
            )}
            <Select aria-label="Number of problems" size="small" value={String(options.count)}
              onChange={(_, data) => setOptions({ ...options, count: Number(data.value) })}>
              {Array.from({ length: MAX_INTERVIEW_PROBLEMS }, (_, i) => i + 1).map(n => (
                <option key={n} value={n}>{n} {n === 1 ? "problem" : "problems"}</option>
              ))}
            </Select>
            <Select aria-label="Interview difficulty" size="small" value={options.difficulty}
              onChange={(_, data) => setOptions({ ...options, difficulty: data.value })}>
              <option value="">Any difficulty</option>
              {difficulties.map(d => <option key={d} value={d}>{d}</option>)}
            </Select>
            {options.format === "fixed" && (
              <Select aria-label="Interview pattern" size="small" value={options.family}
                onChange={(_, data) => setOptions({ ...options, family: data.value })}>
                <option value="">Varied patterns</option>
                {PATTERN_FAMILIES.map(family => <option key={family.id} value={family.id}>{family.label}</option>)}
              </Select>
            )}
            <label className="interview-limit">
              <Input aria-label="Time limit in minutes" size="small" type="number" min={1} max={240} value={String(limit)}
                onChange={(_, data) => setLimit(Math.max(1, Math.min(240, Number(data.value) || 1)))} />
              <span className="muted">minutes</span>
            </label>
            <Button appearance="primary" size="small" disabled={!practice.canSaveProgress} onClick={start}>
              Start interview
            </Button>
          </div>
          {!practice.canSaveProgress && (
            <div className="pipeline-notice">Open a folder first: the interview follows your Submits through .datapass/progress.json.</div>
          )}
          {practice.canSaveProgress && runtime.status !== "running" && (
            <small className="muted">The runtime is stopped: start it before you submit, or the clock runs while you wait.</small>
          )}
          {shortDraw === 0 && <div className="pipeline-notice">No problem matches these settings. Widen the difficulty or the pattern.</div>}
        </div>
      )}
      <InterviewHistory interviews={practice.progress.interviews ?? []} />
    </div>
  );
}

function RunningInterview({ vscode, practice, runtime, problems, session, shortDraw, onFinish, onAbandon }: {
  vscode: VsCodeApi;
  practice: PracticeViewState;
  runtime: RuntimeViewState;
  problems: readonly PracticeProblem[];
  session: InterviewSession;
  shortDraw?: number;
  onFinish: () => void;
  onAbandon: () => void;
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const elapsed = Math.max(0, Math.floor((now - Date.parse(session.startedAt)) / 1000));
  const remaining = session.limitMinutes * 60 - elapsed;
  const solved = session.items.filter(item => item.passedAt).length;
  return (
    <div className="interview">
      <div className={`interview-bar${remaining < 0 ? " overtime" : ""}`}>
        <div>
          <strong>Interview · {solved} of {session.items.length} solved</strong>
          <small className="muted">
            {session.format === "mixed" ? "Mixed" : languageLabel(session.language ?? "")} · {session.limitMinutes} min · no hints
          </small>
        </div>
        <div className="interview-clock" role="timer" aria-live="off" aria-label={remaining < 0 ? "Overtime" : "Time left"}>
          {remaining >= 0 ? `${clock(remaining)} left` : `Overtime +${clock(-remaining)}`}
        </div>
        <div className="button-row">
          <Button appearance="primary" size="small" onClick={onFinish}>Finish interview</Button>
          <Button appearance="subtle" size="small" onClick={onAbandon}>Abandon</Button>
        </div>
      </div>
      {shortDraw !== undefined && shortDraw > 0 && (
        <small className="muted">Only {shortDraw} problems matched these settings.</small>
      )}
      <div className="practice-list">
        {session.items.map((item, index) => {
          const problem = problems.find(p => p.key === item.problemKey);
          const variant = problem?.variants.find(v => v.key === item.exerciseKey);
          if (!problem || !variant) {
            return <div key={item.exerciseKey} className="empty-state">{item.exerciseKey} is no longer installed.</div>;
          }
          return (
            <PracticeProblemCard key={item.exerciseKey} vscode={vscode} problem={problem} variant={variant}
              progress={practice.progress} runtime={runtime} interview
              badge={`Problem ${index + 1} of ${session.items.length}${item.passedAt ? ` · solved at ${clock(secondsBetween(session.startedAt, item.passedAt))}` : ""}`}
              onLanguage={() => undefined} />
          );
        })}
      </div>
    </div>
  );
}

function InterviewSummary({ record, problems, onClose }: {
  record: InterviewRecord;
  problems: readonly PracticeProblem[];
  onClose: () => void;
}) {
  const solved = record.items.filter(item => item.solved).length;
  const limit = record.limitMinutes * 60;
  const overtime = record.elapsedSeconds - limit;
  const title = (key: string) => problems.find(p => key.startsWith(`${p.key}/`))?.title ?? key;
  return (
    <div className="interview-summary" aria-label="Interview summary">
      <div className="interview-summary-head">
        <Text size={500} weight="semibold">{solved} of {record.items.length} solved</Text>
        <span className="muted">
          {clock(record.elapsedSeconds)} for a {record.limitMinutes}-minute limit
          {overtime > 0 ? ` · ${clock(overtime)} overtime` : ""}
        </span>
        <Button appearance="primary" size="small" onClick={onClose}>New interview</Button>
      </div>
      <table className="interview-table">
        <thead>
          <tr><th>#</th><th>Problem</th><th>Language</th><th>Pattern</th><th>Result</th></tr>
        </thead>
        <tbody>
          {record.items.map((item, index) => (
            <tr key={item.key}>
              <td>{index + 1}</td>
              <td>{title(item.key)}</td>
              <td>{languageLabel(item.key.slice(item.key.lastIndexOf("/") + 1))}</td>
              <td>{familyLabel(item.family)}</td>
              <td>
                {item.solved
                  ? <Badge appearance="tint" color={item.solvedAfterSeconds! > limit ? "warning" : "success"}>
                      solved at {clock(item.solvedAfterSeconds ?? 0)}{item.solvedAfterSeconds! > limit ? " (overtime)" : ""}
                    </Badge>
                  : <Badge appearance="outline" color="danger">{item.submits ? `not solved · ${item.submits} ${item.submits === 1 ? "submit" : "submits"}` : "not submitted"}</Badge>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <small className="muted">
        A problem submitted without a pass is due for review tomorrow. Hints and reference solutions are back in All problems.
      </small>
    </div>
  );
}

function InterviewHistory({ interviews }: { interviews: readonly InterviewRecord[] }) {
  if (!interviews.length) return null;
  return (
    <div className="interview-history">
      <strong>Past interviews</strong>
      <ul>
        {[...interviews].reverse().slice(0, 5).map(item => (
          <li key={item.at}>
            <span>{new Date(item.at).toLocaleString()}</span>
            <span>{item.format === "mixed" ? "Mixed" : languageLabel(item.language ?? "")}</span>
            <span>{item.items.filter(i => i.solved).length} of {item.items.length} solved</span>
            <span className="muted">{clock(item.elapsedSeconds)} / {item.limitMinutes} min</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function rank(language: string): number {
  const index = LANGUAGE_ORDER.indexOf(language);
  return index < 0 ? LANGUAGE_ORDER.length : index;
}

function restoreOptions(raw: unknown): InterviewOptions {
  const value = raw && typeof raw === "object" ? raw as Record<string, unknown> : {};
  const text = (v: unknown, fallback: string) => typeof v === "string" && /^[A-Za-z0-9_-]{0,40}$/.test(v) ? v : fallback;
  const count = typeof value.count === "number" && Number.isInteger(value.count) ? value.count : DEFAULT_OPTIONS.count;
  return {
    format: value.format === "fixed" ? "fixed" : "mixed",
    language: text(value.language, DEFAULT_OPTIONS.language!) || DEFAULT_OPTIONS.language,
    count: Math.max(1, Math.min(MAX_INTERVIEW_PROBLEMS, count)),
    difficulty: text(value.difficulty, ""),
    family: text(value.family, "")
  };
}

/** The series in progress, kept in the webview state so it survives the Workbench being hidden. */
function restoreSession(raw: unknown): InterviewSession | undefined {
  const value = raw && typeof raw === "object" ? raw as InterviewSession : undefined;
  if (!value || typeof value.startedAt !== "string" || !Array.isArray(value.items) || typeof value.limitMinutes !== "number") return undefined;
  return value;
}

function readState(vscode: VsCodeApi): Record<string, unknown> {
  const value = vscode.getState();
  return value && typeof value === "object" ? value as Record<string, unknown> : {};
}
