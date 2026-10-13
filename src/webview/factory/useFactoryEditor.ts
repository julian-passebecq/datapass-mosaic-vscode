import { useEffect, useState } from "react";
import type { FactoryDesignView } from "../contracts";
import {
  pushHistory,
  redo as redoHistory,
  startHistory,
  undo as undoHistory,
  type EditResult,
  type EditorHistory
} from "../../platform/factoryDocument";

interface Session {
  history: EditorHistory;
  /** The disk text the edits started from, and its hash (sent as baseHash on save). */
  baseText: string;
  baseHash: string;
  reloadSeq: number;
  /** The file changed on disk while there were unsaved edits. */
  diskChanged: boolean;
}

export interface FactoryEditor {
  /** The text being edited (equal to the file when nothing changed). */
  text: string;
  dirty: boolean;
  diskChanged: boolean;
  canUndo: boolean;
  canRedo: boolean;
  baseHash: string;
  /** Apply an edit; returns its error, if any (nothing changes then). */
  apply(result: EditResult): string | undefined;
  undo(): void;
  redo(): void;
  /** Drop the edits and show the file as it is on disk. */
  reload(): void;
}

function fresh(design: FactoryDesignView): Session {
  const text = design.text ?? "";
  return { history: startHistory(text), baseText: text, baseHash: design.hash ?? "", reloadSeq: design.reloadSeq ?? 0, diskChanged: false };
}

/**
 * Unsaved edits per pipeline file, kept while the learner switches pipelines. When the file on disk changes: an
 * untouched session follows it, a saved session (the disk now holds the edited text) takes the new base, and a session
 * with other edits keeps them and says the file changed (saving then asks Reload or Overwrite).
 */
export function useFactoryEditor(design: FactoryDesignView | undefined): FactoryEditor | undefined {
  const [sessions, setSessions] = useState<Record<string, Session>>({});
  const path = design?.path;

  useEffect(() => {
    if (!design || design.text === undefined) return;
    setSessions(current => {
      const session = current[design.path];
      if (!session || (design.reloadSeq ?? 0) !== session.reloadSeq) return { ...current, [design.path]: fresh(design) };
      if (design.hash === session.baseHash) return current;
      const text = design.text!;
      if (session.history.present === text) {
        return { ...current, [design.path]: { ...session, baseText: text, baseHash: design.hash ?? "", diskChanged: false } };
      }
      if (session.history.present === session.baseText) return { ...current, [design.path]: fresh(design) };
      return session.diskChanged ? current : { ...current, [design.path]: { ...session, diskChanged: true } };
    });
  }, [design?.path, design?.hash, design?.reloadSeq]);

  if (!design || !path || design.text === undefined) return undefined;
  const session = sessions[path] ?? fresh(design);
  const update = (change: (session: Session) => Session) =>
    setSessions(current => ({ ...current, [path]: change(current[path] ?? fresh(design)) }));

  return {
    text: session.history.present,
    dirty: session.history.present !== session.baseText,
    diskChanged: session.diskChanged,
    canUndo: session.history.past.length > 0,
    canRedo: session.history.future.length > 0,
    baseHash: session.baseHash,
    apply(result) {
      if (result.error !== undefined) return result.error;
      update(current => ({ ...current, history: pushHistory(current.history, result.text) }));
      return undefined;
    },
    undo: () => update(current => ({ ...current, history: undoHistory(current.history) })),
    redo: () => update(current => ({ ...current, history: redoHistory(current.history) })),
    reload: () => update(() => fresh(design))
  };
}
