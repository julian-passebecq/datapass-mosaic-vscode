import { Badge, Button, Text } from "@fluentui/react-components";
import type { RuntimeViewState, TerminalViewState } from "./contracts";
import type { VsCodeApi } from "./WorkbenchApp";
import { MissionsPanel } from "./MissionsPanel";

/**
 * Terminal Lab: real bash, PowerShell and Git. Datapass opens a VS Code terminal in the mission folder with the shell
 * the learner chose and types nothing in it; the hidden checker reads the resulting folder and repository.
 */
export function TerminalSurface({
  vscode,
  terminal,
  runtime
}: {
  vscode: VsCodeApi;
  terminal: TerminalViewState | undefined;
  runtime: RuntimeViewState;
}) {
  if (!terminal) return <div className="empty-state">Terminal Lab state is not available.</div>;
  const running = runtime.status === "running";
  const git = terminal.git;
  const identity = git.userName && git.userEmail ? `${git.userName} <${git.userEmail}>` : undefined;

  return (
    <section className="terminal-surface">
      <div className="dbt-toolbar terminal-toolbar">
        <div className="button-row" role="radiogroup" aria-label="Shell">
          <Text weight="semibold">Shell</Text>
          {terminal.shells.map(shell => (
            <Button key={shell.id} size="small" role="radio" aria-checked={terminal.shell === shell.id}
              appearance={terminal.shell === shell.id ? "primary" : "secondary"} disabled={!shell.path}
              title={shell.path ?? shell.note}
              onClick={() => vscode.postMessage({ type: "selectTerminalShell", shell: shell.id })}>
              {shell.label}{shell.path ? ` · ${shell.note}` : " · not found"}
            </Button>
          ))}
        </div>
        <div className="button-row">
          <Badge appearance="tint" color={git.version ? "success" : "danger"}>{git.version ? `Git ${git.version}` : "Git not found"}</Badge>
          <Button size="small" appearance="secondary" disabled={!terminal.shell}
            onClick={() => vscode.postMessage({ type: "openLabTerminal" })}>Open a terminal</Button>
          <Button size="small" appearance="secondary" onClick={() => vscode.postMessage({ type: "refreshTerminalLab" })}>Refresh</Button>
        </div>
      </div>

      <p className="factory-note terminal-truth">
        Your commands stay yours: Datapass opens a real terminal in the mission folder and types nothing in it. When you
        ask, a hidden checker reads the folder and its Git repository; scripts are read as text, never run.
      </p>

      {!terminal.shell && (
        <div className="pipeline-notice" role="status">
          <strong>No shell found.</strong> Install Git for Windows (it brings Git Bash and Git) or PowerShell 7, then
          Refresh. On Windows, <code>datapass.terminalLab.bashPath</code> can point at a bash.exe elsewhere.
        </div>
      )}
      {git.version && !identity && (
        <div className="pipeline-notice" role="status">
          <strong>Git does not know who you are yet</strong>, so <code>git commit</code> will refuse to run. Tell it
          once, in any terminal: <code>git config --global user.name "Your Name"</code> and{" "}
          <code>git config --global user.email "you@example.com"</code>.
        </div>
      )}
      {!git.version && (
        <div className="pipeline-notice" role="status">
          <strong>Git was not found on PATH.</strong> The Git missions need it: install Git (on Windows, Git for Windows),
          then Refresh.
        </div>
      )}

      <MissionsPanel
        state={terminal.missions}
        vscode={vscode}
        canRun={running}
        blockedReason={running ? undefined : "Start the runtime: it builds the mission folder from the ticket and runs the checker."}
        openLabel="Open terminal and ticket"
        folderNote={mission => <>
          Folder: <code>missions/{mission.id}</code>, where the terminal opens. The ticket is in{" "}
          <code>.datapass/missions/tickets/{mission.id}.md</code>. {identity ? <>Git records your commits as {identity}.</> : null}
        </>}
      />
    </section>
  );
}
