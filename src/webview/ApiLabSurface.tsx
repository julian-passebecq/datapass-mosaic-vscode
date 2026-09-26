import { Badge, Button, Text } from "@fluentui/react-components";
import type { ApiLabApiView, ApiLabViewState, PythonTrustView, RuntimeViewState } from "./contracts";
import type { VsCodeApi } from "./WorkbenchApp";
import { MissionsPanel } from "./MissionsPanel";
import { TrustedPythonControl } from "./TrustedPythonControl";

const TRUTH = "Simulated API (Datapass), your ingestion code runs for real";

/**
 * API Lab: the learner's ingest.py (real Python, trusted Python only) ingests a simulated REST API into bronze. The
 * API runs on its own loopback port with a fictitious per-mission key; the hidden checker reads bronze and the API's
 * request log.
 */
export function ApiLabSurface({
  vscode,
  apilab,
  runtime,
  pythonTrust
}: {
  vscode: VsCodeApi;
  apilab: ApiLabViewState | undefined;
  runtime: RuntimeViewState;
  pythonTrust: PythonTrustView;
}) {
  if (!apilab) return <div className="empty-state">API Lab state is not available.</div>;
  const running = runtime.status === "running";
  const started = apilab.missions.missions.filter(mission => apilab.missions.progress[mission.id]?.started);

  return (
    <section className="terminal-surface infra-surface apilab-surface">
      <div className="dbt-toolbar terminal-toolbar">
        <div className="button-row">
          <Badge appearance="tint" color="warning">Simulated API</Badge>
          <Badge appearance="tint" color="success">Your code runs for real</Badge>
          {started.length > 1 && (
            <label className="infra-folder">
              <Text size={200}>API of</Text>{" "}
              <select value={apilab.active} aria-label="Mission whose API is shown"
                onChange={event => vscode.postMessage({ type: "selectApiMission", missionId: event.target.value })}>
                {started.map(mission => <option key={mission.id} value={mission.id}>{mission.id}</option>)}
              </select>
            </label>
          )}
        </div>
        <div className="button-row">
          <TrustedPythonControl vscode={vscode} trust={pythonTrust} />
          <Button size="small" appearance="secondary" onClick={() => vscode.postMessage({ type: "refreshApiLab" })}>Refresh</Button>
        </div>
      </div>

      <p className="factory-note terminal-truth">
        {TRUTH}. Each mission gets a small REST API served by Datapass on 127.0.0.1 (its own port, a fictitious key).
        Your <code>ingest.py</code> runs as real local Python with <code>API_BASE_URL</code>, <code>API_KEY</code> and{" "}
        <code>bronze</code> in scope; the checker reads the bronze tables and the API's request log.
      </p>

      {!pythonTrust.effective && (
        <div className="pipeline-notice" role="status">
          <strong>Trusted local Python is off.</strong> The API Lab runs your <code>ingest.py</code> as real local
          Python, so a run is refused until you enable it (only for code you trust).
        </div>
      )}
      {apilab.apiError && <p className="factory-error">{apilab.apiError}</p>}
      {apilab.active && apilab.api && (
        <ApiPanel vscode={vscode} missionId={apilab.active} api={apilab.api} canRun={running && pythonTrust.effective} />
      )}

      <MissionsPanel
        state={apilab.missions}
        vscode={vscode}
        canRun={running}
        blockedReason={running ? undefined : "Start the runtime: it serves the simulated API, runs your ingestion and the checker."}
        openLabel="Open ingest.py and ticket"
        folderNote={mission => <>
          Folder: <code>missions/{mission.id}</code>: edit <code>ingest.py</code> there (API.md documents the API), then
          Run it above. Start over keeps your <code>ingest.py</code>.
        </>}
      />
    </section>
  );
}

function ApiPanel({ vscode, missionId, api, canRun }: { vscode: VsCodeApi; missionId: string; api: ApiLabApiView; canRun: boolean }) {
  const last = api.runs?.[api.runs.length - 1];
  const requests = (api.requests ?? []).slice(-12).reverse();
  return (
    <div className="infra-world" aria-label="Simulated API">
      <article className="infra-card">
        <Text weight="semibold">{missionId} · simulated API</Text>
        <p className="factory-note">
          {api.running ? <>Serving on <code>{api.base_url}</code></> : "Stopped: it starts again with your next run."}
          {" · "}day {api.day ?? 1} · {api.run ?? 0} run(s) · {api.request_count ?? 0} request(s)
        </p>
        {api.key && (
          <p className="infra-output">
            <code>Authorization: Bearer {api.key}</code>{" "}
            <Button size="small" appearance="subtle" onClick={() => vscode.postMessage({ type: "copyApiKey", missionId })}>Copy key</Button>
          </p>
        )}
        <div className="button-row">
          <Button appearance="primary" disabled={!canRun} onClick={() => vscode.postMessage({ type: "runApiIngestion", missionId })}>
            Run ingest.py
          </Button>
        </div>
      </article>
      {last && (
        <article className="infra-card">
          <Text weight="semibold">Run {last.run} · day {last.day} · {last.status === "ok" ? "finished" : "failed"}</Text>
          <p className="factory-note">
            {last.requests} request(s), {last.records} record(s) · answers {last.statuses.join(", ") || "none"}
            {last.tables.map(table => <span key={table.name}> · <code>{table.name}</code> {table.rows} row(s)</span>)}
          </p>
          {last.error && <pre className="factory-json">{last.error.trim().split(/\r?\n/).slice(-8).join("\n")}</pre>}
          {last.stdout && <pre className="factory-json">{last.stdout.trim().split(/\r?\n/).slice(-12).join("\n")}</pre>}
        </article>
      )}
      {requests.length > 0 && (
        <article className="infra-card infra-journal">
          <Text weight="semibold">Request log (latest first)</Text>
          <ul>
            {requests.map(entry => (
              <li key={entry.n} className={entry.status >= 400 ? "infra-failed" : undefined}>
                <code>{entry.status}</code> run {entry.run} · {entry.method} {entry.path}
                {Object.keys(entry.query).length ? `?${new URLSearchParams(entry.query as Record<string, string>).toString()}` : ""}
                {entry.records != null ? ` · ${entry.records} record(s)` : ""}
                {entry.retry_after != null ? ` · Retry-After ${entry.retry_after}s` : ""}
                {entry.violation ? " · sent before Retry-After was over" : ""}
              </li>
            ))}
          </ul>
        </article>
      )}
    </div>
  );
}
