import { Badge, Button } from "@fluentui/react-components";
import { DEPENDENCY_CONDITIONS } from "../../platform/factoryDocument";

/** Save, undo/redo, the condition new connections get, and the file actions of the pipeline editor. */
export function EditorToolbar({
  dirty,
  diskChanged,
  canUndo,
  canRedo,
  errorCount,
  connectCondition,
  onConnectCondition,
  onSave,
  onUndo,
  onRedo,
  onRevert,
  onExport
}: {
  dirty: boolean;
  diskChanged: boolean;
  canUndo: boolean;
  canRedo: boolean;
  errorCount: number;
  connectCondition: string;
  onConnectCondition: (condition: string) => void;
  onSave: () => void;
  onUndo: () => void;
  onRedo: () => void;
  onRevert: () => void;
  onExport: () => void;
}) {
  return (
    <div className="factory-editor-toolbar" role="toolbar" aria-label="Pipeline editor">
      <Button size="small" appearance="primary" disabled={!dirty} onClick={onSave} title="Save (Ctrl+S)">Save</Button>
      <Button size="small" appearance="secondary" disabled={!canUndo} onClick={onUndo} title="Undo (Ctrl+Z)">Undo</Button>
      <Button size="small" appearance="secondary" disabled={!canRedo} onClick={onRedo} title="Redo (Ctrl+Y)">Redo</Button>
      <Button size="small" appearance="secondary" disabled={!dirty} onClick={onRevert}>Discard edits</Button>
      <Button size="small" appearance="secondary" onClick={onExport}>Export JSON…</Button>
      <label className="factory-editor-condition">
        New dependency on
        <select value={connectCondition} onChange={event => onConnectCondition(event.target.value)} aria-label="Condition of new dependencies">
          {DEPENDENCY_CONDITIONS.map(condition => <option key={condition} value={condition}>{condition}</option>)}
        </select>
      </label>
      {dirty && <Badge appearance="tint" color="warning">unsaved edits</Badge>}
      {diskChanged && <Badge appearance="tint" color="danger">file changed on disk</Badge>}
      {errorCount > 0 && <Badge appearance="tint" color="danger">{errorCount} issue{errorCount === 1 ? "" : "s"}</Badge>}
    </div>
  );
}
