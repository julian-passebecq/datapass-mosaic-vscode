import * as vscode from "vscode";
import {
  SQL_DIALECTS, SqlDialectId, dialectFromName, dialectHeaderEdit, dialectInfo, readDialectHeader, statusText
} from "./platform/sqlDialect";

export const PICK_SQL_DIALECT = "datapass.sql.pickDialect";

/**
 * "SQL: DuckDB ▾" on .sql editors, like a notebook's kernel picker: the file's first line `-- dialect: <name>` says
 * which dialect Run and Explain active SQL translate to DuckDB. Choosing one writes, replaces or removes that line.
 */
export function registerSqlDialectStatus(): vscode.Disposable[] {
  const item = vscode.window.createStatusBarItem("datapass.sqlDialect", vscode.StatusBarAlignment.Right, 101);
  item.name = "Datapass SQL dialect";

  const update = () => {
    const document = vscode.window.activeTextEditor?.document;
    if (!document || !isSqlDocument(document)) {
      item.hide();
      return;
    }
    if (/[\\/]solution\.sql$/i.test(document.fileName)) {
      // A Practice solution: the exercise's language decides, not a header.
      item.text = "SQL: exercise";
      item.tooltip = "Practice sets this solution's dialect (DuckDB SQL or the exercise's translated dialect); Submit grades it.";
      item.command = undefined;
      item.show();
      return;
    }
    const header = readDialectHeader(document.getText());
    const info = dialectInfo(header.dialect);
    item.text = header.unknown ? `SQL: ${header.unknown}? ▾` : statusText(header.dialect);
    const tooltip = new vscode.MarkdownString(undefined, true);
    tooltip.appendMarkdown(header.unknown
      ? `**Unknown SQL dialect \`${header.unknown}\`**: Run active SQL refuses this file. Click to choose a dialect.`
      : header.dialect === "duckdb"
        ? "**DuckDB SQL**: Run and Explain active SQL run this file as written on the local catalog. Click to write it in another dialect."
        : `**${info.label}.** Run and Explain active SQL translate this file to DuckDB for a documented subset and run the translation on the local catalog; Mosaic shows the translated SQL. Click to change.`);
    item.tooltip = tooltip;
    item.command = PICK_SQL_DIALECT;
    item.show();
  };

  const pick = vscode.commands.registerCommand(PICK_SQL_DIALECT, async (requested?: string) => {
    const editor = vscode.window.activeTextEditor;
    if (!editor || !isSqlDocument(editor.document)) {
      void vscode.window.showWarningMessage("Open a .sql file to choose its SQL dialect.");
      return;
    }
    let chosen: SqlDialectId | undefined = typeof requested === "string" ? dialectFromName(requested) : undefined;
    if (typeof requested === "string" && !chosen) {
      void vscode.window.showErrorMessage(`Unknown SQL dialect '${requested}'.`);
      return;
    }
    if (!chosen) {
      const current = readDialectHeader(editor.document.getText()).dialect;
      const choice = await vscode.window.showQuickPick(
        SQL_DIALECTS.map(info => ({
          id: info.id,
          label: `${info.id === current ? "$(check) " : ""}${info.title}`,
          description: info.family,
          detail: info.label
        })),
        { title: "SQL dialect of this file", placeHolder: "Run and Explain active SQL translate the file to DuckDB" }
      );
      chosen = choice?.id;
    }
    if (!chosen) return;
    await setSqlDialect(editor.document, chosen);
    update();
  });

  update();
  return [
    item,
    pick,
    vscode.window.onDidChangeActiveTextEditor(update),
    vscode.workspace.onDidChangeTextDocument(event => {
      if (event.document === vscode.window.activeTextEditor?.document) update();
    })
  ];
}

/** Writes the dialect header of a .sql document (not saved: the next Run saves it). */
export async function setSqlDialect(document: vscode.TextDocument, dialect: SqlDialectId): Promise<boolean> {
  const change = dialectHeaderEdit(document.getText(), dialect);
  if (!change) return true;
  const edit = new vscode.WorkspaceEdit();
  if (change.line === undefined) {
    edit.insert(document.uri, new vscode.Position(0, 0), `${change.text}\n`);
  } else if (change.text === undefined) {
    edit.delete(document.uri, document.lineAt(change.line).rangeIncludingLineBreak);
  } else {
    edit.replace(document.uri, document.lineAt(change.line).range, change.text);
  }
  return vscode.workspace.applyEdit(edit);
}

/** SQL files the learner edits: not read-only views such as the translated SQL tab (datapass-plan:). */
function isSqlDocument(document: vscode.TextDocument): boolean {
  if (document.uri.scheme !== "file" && document.uri.scheme !== "untitled") return false;
  return document.languageId === "sql" || document.fileName.toLowerCase().endsWith(".sql");
}
