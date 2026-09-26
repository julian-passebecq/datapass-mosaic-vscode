import { Badge, Button, Input, Select, Text } from "@fluentui/react-components";
import { useEffect, useMemo, useState } from "react";
import {
  EMPTY_FILTERS,
  STATUS_LABELS,
  filterOptions,
  restoreFilters,
  type PracticeFilters,
  type PracticeStatus
} from "../platform/practiceProgress";
import {
  dueProblems,
  filterProblems,
  groupProblems,
  languageLabel,
  pickVariant,
  problemCounts,
  problemKeyOf,
  restoreLanguages,
  upcomingReviews
} from "../platform/practiceProblems";
import { REVIEW_INTERVALS_DAYS, daysBetween, localDay } from "../platform/practiceReview";
import type { PracticeViewState, RuntimeViewState, WorkbenchFocus } from "./contracts";
import { PracticeProblemCard } from "./PracticeProblemCard";
import type { VsCodeApi } from "./WorkbenchApp";

export function PracticeSurface({
  vscode,
  practice,
  runtime,
  focus
}: {
  vscode: VsCodeApi;
  practice: PracticeViewState;
  runtime: RuntimeViewState;
  /** An exercise a project step opened: the list is filtered on it. */
  focus?: WorkbenchFocus;
}) {
  const { exercises, progress } = practice;
  const [filters, setFilters] = useState<PracticeFilters>(() => {
    const saved = restoreFilters(readState(vscode).practiceFilters);
    return focus?.query ? { ...EMPTY_FILTERS, query: focus.query } : saved;
  });
  // The language each card shows (by problem key), and the language last picked anywhere.
  const [languages, setLanguages] = useState<Record<string, string>>(() => restoreLanguages(readState(vscode).practiceLanguages));
  const [preferred, setPreferred] = useState<string | undefined>(() => {
    const value = readState(vscode).practiceLanguage;
    return typeof value === "string" ? value : undefined;
  });
  const [mode, setModeState] = useState<PracticeMode>(() => focus?.query ? "browse" : restoreMode(readState(vscode).practiceMode));
  const setMode = (next: PracticeMode) => {
    setModeState(next);
    vscode.setState({ ...readState(vscode), practiceMode: next });
  };
  // Problems shown in this review round: a problem stays on screen after its Submit, so its result stays visible.
  const [reviewRound, setReviewRound] = useState<string[]>([]);
  const [reviewLanguages, setReviewLanguages] = useState<Record<string, string>>({});
  const update = (next: PracticeFilters) => {
    setFilters(next);
    vscode.setState({ ...readState(vscode), practiceFilters: next });
  };
  const choose = (problemKey: string, language: string) => {
    const next = { ...languages, [problemKey]: language };
    setLanguages(next);
    setPreferred(language);
    vscode.setState({ ...readState(vscode), practiceLanguages: next, practiceLanguage: language });
  };
  useEffect(() => {
    // A project step asks for one exercise: show it whatever the other filters were, in its language.
    if (focus?.query) {
      update({ ...EMPTY_FILTERS, query: focus.query });
      setMode("browse");
    }
    if (focus?.exerciseKey) {
      const language = focus.exerciseKey.slice(focus.exerciseKey.lastIndexOf("/") + 1);
      setLanguages(current => ({ ...current, [problemKeyOf(focus.exerciseKey!)]: language }));
    }
  }, [focus?.seq]);
  const runtimeReady = runtime.status === "running";

  const problems = useMemo(() => groupProblems(exercises), [exercises]);
  const options = useMemo(() => filterOptions(exercises), [exercises]);
  const filtered = useMemo(() => filterProblems(problems, progress, filters), [problems, progress, filters]);
  const counts = useMemo(() => problemCounts(problems, progress), [problems, progress]);
  const filtering = Object.values(filters).some(Boolean);
  const today = localDay(new Date());
  const due = useMemo(() => dueProblems(problems, progress, today), [problems, progress, today]);
  const upcoming = useMemo(() => upcomingReviews(problems, progress, today), [problems, progress, today]);
  useEffect(() => {
    if (mode !== "review") {
      setReviewRound([]);
      return;
    }
    setReviewRound(current => {
      const added = due.map(item => item.problem.key).filter(key => !current.includes(key));
      return added.length ? [...current, ...added] : current;
    });
  }, [mode, due]);

  return (
    <section className="practice-surface">
      <div className="practice-toolbar">
        <div>
          <div className="eyebrow">Native-file practice · versioned grading</div>
          <Text size={500} weight="semibold">{problems.length} problems</Text>
          <span className="muted"> · {exercises.length} language variants</span>
          <div className="practice-progress" aria-label="Your progress">
            <span className="practice-progress-solved">{counts.solved} solved</span>
            <span>{counts.attempted} attempted</span>
            <span>{counts["not-started"]} not started</span>
            <small className="muted">
              {practice.canSaveProgress ? "Saved per language in .datapass/progress.json" : "Open a folder to keep your progress"}
            </small>
          </div>
        </div>
        <div className="practice-toolbar-actions">
          <Badge appearance="tint" color={runtimeReady ? "success" : "informative"}>
            {runtimeReady ? "grader ready" : "runtime stopped"}
          </Badge>
          <Input
            aria-label="Filter exercises"
            placeholder="Filter SQL, Spark, Airflow, dbt…"
            value={filters.query}
            onChange={(_, data) => update({ ...filters, query: data.value })}
          />
        </div>
      </div>

      <div className="practice-modes" role="tablist" aria-label="Practice mode">
        <button type="button" role="tab" aria-selected={mode === "browse"} className={mode === "browse" ? "selected" : ""}
          onClick={() => setMode("browse")}>
          All problems
        </button>
        <button type="button" role="tab" aria-selected={mode === "review"} className={mode === "review" ? "selected" : ""}
          onClick={() => setMode("review")}>
          Review{due.length ? ` · ${due.length} due` : ""}
        </button>
      </div>

      {mode === "review" ? (
        reviewList()
      ) : (
      <>
      <div className="practice-filters" role="group" aria-label="Exercise filters">
        <FilterSelect label="Difficulty" all="All difficulties" value={filters.difficulty} values={options.difficulties}
          onChange={difficulty => update({ ...filters, difficulty })} />
        <FilterSelect label="Topic" all="All topics" value={filters.topic} values={options.topics}
          onChange={topic => update({ ...filters, topic })} />
        <FilterSelect label="Language" all="All languages" value={filters.language} values={options.languages}
          labels={Object.fromEntries(options.languages.map(language => [language, languageLabel(language)]))}
          onChange={language => update({ ...filters, language })} />
        <FilterSelect label="Status" all="All statuses" value={filters.status}
          values={Object.keys(STATUS_LABELS)} labels={STATUS_LABELS}
          onChange={status => update({ ...filters, status: status as PracticeStatus | "" })} />
        <Button appearance="subtle" size="small" disabled={!filtering} onClick={() => update(EMPTY_FILTERS)}>
          Clear filters
        </Button>
        <span className="muted">{filtered.length} shown</span>
      </div>
      {practice.progressError && (
        <div className="pipeline-notice">
          {practice.progressError} Progress is shown as empty and is not saved until the file is fixed or deleted.
        </div>
      )}

      <div className="practice-list">
        {filtered.map(problem => {
          const variant = pickVariant(problem, {
            chosen: languages[problem.key],
            filter: filters.language || undefined,
            preferred
          });
          return (
            <PracticeProblemCard key={problem.key} vscode={vscode} problem={problem} variant={variant}
              progress={progress} runtime={runtime} solution={practice.solutions[variant.key]}
              onLanguage={language => choose(problem.key, language)} />
          );
        })}
        {filtered.length === 0 && (
          <div className="empty-state">No exercises match this filter.</div>
        )}
      </div>
      </>
      )}
    </section>
  );

  function reviewList() {
    const dueByKey = new Map(due.map(item => [item.problem.key, item]));
    const shown = reviewRound.flatMap(key => {
      const problem = problems.find(item => item.key === key);
      return problem ? [{ problem, due: dueByKey.get(key) }] : [];
    });
    return (
      <>
        <p className="practice-review-rule muted">
          Spaced review, per language: a passed Submit on a due problem moves that language up a box, due again after{" "}
          {REVIEW_INTERVALS_DAYS.join(", ")} days. A Submit that does not pass sends it back to the first box, due
          tomorrow. Problems you started but did not solve come back the next day.
        </p>
        <div className="practice-list">
          {shown.map(({ problem, due: item }) => {
            const variant = pickVariant(problem, { chosen: reviewLanguages[problem.key] ?? item?.language });
            return (
              <PracticeProblemCard key={problem.key} vscode={vscode} problem={problem} variant={variant}
                progress={progress} runtime={runtime} solution={practice.solutions[variant.key]}
                badge={item ? `Review due: ${[item.language, ...item.alsoDue].map(languageLabel).join(", ")}` : "Reviewed"}
                onLanguage={language => setReviewLanguages(current => ({ ...current, [problem.key]: language }))} />
            );
          })}
          {shown.length === 0 && (
            <div className="empty-state">
              {upcoming.scheduled === 0
                ? "Nothing to review yet: problems you open or submit are scheduled here."
                : `Nothing due today. ${upcoming.scheduled} language ${upcoming.scheduled === 1 ? "variant is" : "variants are"} scheduled${upcoming.next ? `; the next one is due ${daysBetween(today, upcoming.next) === 1 ? "tomorrow" : `in ${daysBetween(today, upcoming.next)} days`}` : ""}.`}
            </div>
          )}
        </div>
      </>
    );
  }
}

type PracticeMode = "browse" | "review";

function restoreMode(raw: unknown): PracticeMode {
  return raw === "review" ? raw : "browse";
}

function FilterSelect({
  label,
  all,
  value,
  values,
  labels,
  onChange
}: {
  label: string;
  all: string;
  value: string;
  values: readonly string[];
  labels?: Record<string, string>;
  onChange: (value: string) => void;
}) {
  return (
    <Select aria-label={label} size="small" value={value} onChange={(_, data) => onChange(data.value)}>
      <option value="">{all}</option>
      {values.map(item => <option key={item} value={item}>{labels?.[item] ?? item}</option>)}
    </Select>
  );
}

function readState(vscode: VsCodeApi): Record<string, unknown> {
  const value = vscode.getState();
  return value && typeof value === "object" ? value as Record<string, unknown> : {};
}
