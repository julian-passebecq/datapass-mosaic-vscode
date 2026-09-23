import { ChallengeWorkbench, type usePracticeWorkspace } from '@datapass/learning';
import { useLocale } from '@datapass/ui';
import { Button } from '@fluentui/react-components';
import { useReducedMotion } from '@conceptmotion/react';
import { practiceItemById, practiceItems } from '../data/practice';
import { figureForPracticeId, visualById } from '../data/visuals';

export function ChallengePage({ id, workspace, onBack }: { id: string; workspace: ReturnType<typeof usePracticeWorkspace>; onBack: () => void }) {
  const { locale } = useLocale();
  const reducedMotion = useReducedMotion();
  const item = practiceItemById(id);
  const figure = figureForPracticeId(id);
  const visual = figure ? visualById(figure.id) : undefined;

  if (!item) return <section className="lab-not-found"><h1>Practice item not found</h1><p>The stable ID is not present in the pinned corpus.</p><Button onClick={onBack}>Back to practice</Button></section>;

  const index = practiceItems.findIndex(candidate => candidate.id === id);
  const navigate = (offset: number) => {
    const next = practiceItems[index + offset];
    if (next) window.location.hash = `challenge/${encodeURIComponent(next.id)}`;
  };

  return (
    <>
      <div className="lab-challenge-nav" aria-label="Practice navigation">
        <Button onClick={onBack}>Back to practice</Button>
        <span>{index + 1} / {practiceItems.length}</span>
        <div className="lab-actions">
          <Button disabled={index === 0} onClick={() => navigate(-1)}>Previous</Button>
          <Button disabled={index === practiceItems.length - 1} onClick={() => navigate(1)}>Next</Button>
        </div>
      </div>
      <ChallengeWorkbench
        key={id}
        challenge={item}
        figure={figure}
        figureCaptions={visual?.captions}
        locale={locale}
        reducedMotion={reducedMotion}
        progress={workspace.state.progress}
        onProgressChange={workspace.updateProgress}
        notes={workspace.state.notes[id]}
        onNotesChange={notes => workspace.setNote(id, notes)}
      />
    </>
  );
}
