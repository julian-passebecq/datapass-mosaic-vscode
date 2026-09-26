import { Badge, Button, Text } from "@fluentui/react-components";
import type { InfraViewState, InfraWorldView, RuntimeViewState } from "./contracts";
import type { VsCodeApi } from "./WorkbenchApp";
import { MissionsPanel } from "./MissionsPanel";

/**
 * Infra Lab: Terraform on a simulated Azure subscription, Docker and compose, VM monitoring and Kubernetes, all
 * simulated by the runtime (runtime/infralab). The learner types in a simulated VS Code terminal (no process runs);
 * this surface shows the simulated world of the selected mission folder and the missions.
 */
export function InfraSurface({
  vscode,
  infra,
  runtime
}: {
  vscode: VsCodeApi;
  infra: InfraViewState | undefined;
  runtime: RuntimeViewState;
}) {
  if (!infra) return <div className="empty-state">Infra Lab state is not available.</div>;
  const running = runtime.status === "running";

  return (
    <section className="terminal-surface infra-surface">
      <div className="dbt-toolbar terminal-toolbar">
        <div className="button-row">
          <Badge appearance="tint" color="warning">Simulated</Badge>
          {infra.folders.length > 0 && (
            <label className="infra-folder">
              <Text size={200}>World of</Text>
              <select value={infra.folder} aria-label="Mission folder"
                onChange={event => vscode.postMessage({ type: "selectInfraFolder", folder: event.target.value })}>
                {infra.folders.map(folder => <option key={folder} value={folder}>{folder}</option>)}
              </select>
            </label>
          )}
        </div>
        <div className="button-row">
          <Button size="small" appearance="secondary" disabled={!infra.folder || !running}
            onClick={() => vscode.postMessage({ type: "openInfraTerminal" })}>Open simulated terminal</Button>
          <Button size="small" appearance="secondary" onClick={() => vscode.postMessage({ type: "refreshInfraLab" })}>Refresh</Button>
        </div>
      </div>

      <p className="factory-note terminal-truth">
        Everything here is simulated: terraform, docker, kubectl and az answer from Datapass's simulators, and nothing is
        provisioned in Azure, built, pulled or deployed. The terminal the lab opens starts no program; your Terraform
        files, Dockerfiles and manifests are read, never executed.
      </p>

      {!running && (
        <div className="pipeline-notice" role="status">
          <strong>Start the runtime</strong>: it builds the mission folders, runs the simulators and the checker.
        </div>
      )}
      {infra.worldError && <p className="factory-error">{infra.worldError}</p>}
      {infra.world && <WorldView world={infra.world} />}

      <MissionsPanel
        state={infra.missions}
        vscode={vscode}
        canRun={running}
        blockedReason={running ? undefined : "Start the runtime: it builds the mission folder and its simulated world, and runs the checker."}
        openLabel="Open terminal and ticket"
        folderNote={mission => <>
          Folder: <code>missions/{mission.id}</code>, where the simulated terminal opens. The ticket is in{" "}
          <code>.datapass/missions/tickets/{mission.id}.md</code>. The simulated world lives in{" "}
          <code>missions/{mission.id}/.infralab/</code>.
        </>}
      />
    </section>
  );
}

function WorldView({ world }: { world: InfraWorldView }) {
  const tf = world.terraform;
  const azure = world.azure;
  const docker = world.docker;
  const kube = world.kube;
  return (
    <div className="infra-world" aria-label="Simulated world">
      {(tf.configured || tf.initialized || tf.resources.length > 0) && <article className="infra-card">
        <h3>Terraform</h3>
        <p className="factory-note">{tf.initialized ? "Initialized" : "Not initialized: terraform init"} · {tf.resources.length} in terraform.tfstate</p>
        {tf.resources.length > 0 && <ul>{tf.resources.slice(0, 12).map(address => <li key={address}><code>{address}</code></li>)}</ul>}
        {Object.entries(tf.outputs).map(([name, value]) => <p key={name} className="infra-output"><code>{name}</code> = {String(value)}</p>)}
      </article>}
      <article className="infra-card">
        <h3>Azure (simulated)</h3>
        <p className="factory-note">{azure.resources.length} resource(s) · {azure.alerts.length} alert rule(s)</p>
        {azure.resources.length > 0 && (
          <ul>{azure.resources.slice(0, 12).map(resource => (
            <li key={`${resource.group}/${resource.type}/${resource.name}`}>
              <code>{resource.name}</code> <small>{resource.type.split("/").pop()}{resource.managed_by ? ` · ${resource.managed_by}` : ""}</small>
            </li>
          ))}</ul>
        )}
        {azure.alerts.map(alert => (
          <p key={alert.name} className="infra-output">
            <code>{alert.name}</code> <small>sev {alert.severity} · {alert.metric}{alert.actions ? "" : " · no action group"}{alert.enabled ? "" : " · disabled"}</small>
          </p>
        ))}
      </article>
      {(docker.images.length > 0 || docker.containers.length > 0 || (docker.volumes?.length ?? 0) > 0) && (
        <article className="infra-card">
          <h3>Docker (simulated)</h3>
          <ul>
            {docker.images.map(image => (
              <li key={image.tags.join(",") || String(image.size_mb)}>
                <code>{image.tags[0] ?? "<none>"}</code> <small>{Math.round(image.size_mb)} MB · user {image.user ?? "root"}</small>
              </li>
            ))}
            {docker.containers.map(container => (
              <li key={container.name}>
                <code>{container.name}</code>{" "}
                <small>{container.status}{container.health ? ` (${container.health})` : ""}{container.ports.length ? ` · ${container.ports.map(p => `${p[0]}→${p[1]}`).join(", ")}` : ""}</small>
              </li>
            ))}
            {(docker.volumes ?? []).map(volume => <li key={`vol/${volume}`}><code>volume/{volume}</code></li>)}
            {(docker.networks ?? []).map(network => (
              <li key={`net/${network.name}`}><code>network/{network.name}</code>{network.internal ? <small> · internal</small> : null}</li>
            ))}
          </ul>
        </article>
      )}
      {kube.nodes > 0 && (
        <article className="infra-card">
          <h3>Kubernetes (simulated)</h3>
          <p className="factory-note">{kube.nodes} node(s)</p>
          <ul>
            {kube.deployments.map(deployment => (
              <li key={`${deployment.namespace}/${deployment.name}`}>
                <code>{deployment.name}</code> <small>{deployment.ready}/{deployment.replicas} ready · {deployment.image.split("/").pop()} · {deployment.strategy}
                  {deployment.last_rollout && !deployment.last_rollout.complete ? " · rollout stuck" : ""}
                  {deployment.last_rollout?.min_available != null ? ` · last rollout: at least ${deployment.last_rollout.min_available} serving` : ""}</small>
              </li>
            ))}
            {kube.services.map(service => (
              <li key={`svc/${service.namespace}/${service.name}`}><code>svc/{service.name}</code> <small>{service.endpoints} endpoint(s){service.namespace !== "default" ? ` · ${service.namespace}` : ""}</small></li>
            ))}
            {(kube.ingresses ?? []).map(ingress => (
              <li key={`ing/${ingress.namespace}/${ingress.name}`}>
                <code>ingress/{ingress.name}</code> <small>{ingress.hosts.join(", ")} · {ingress.address || "no controller serves it"}</small>
              </li>
            ))}
            {(kube.hpas ?? []).map(hpa => (
              <li key={`hpa/${hpa.namespace}/${hpa.name}`}>
                <code>hpa/{hpa.name}</code> <small>{hpa.target} · {hpa.min}..{hpa.max} replicas, now {hpa.replicas} · cpu {hpa.current == null ? "unknown" : `${hpa.current}%`}/{hpa.goal ?? "?"}%</small>
              </li>
            ))}
          </ul>
        </article>
      )}
      {world.journal.length > 0 && (
        <article className="infra-card infra-journal">
          <h3>Recent commands</h3>
          <ol>{world.journal.slice(-8).map((entry, index) => (
            <li key={`${entry.n ?? index}`} className={entry.exit_code === 0 ? undefined : "infra-failed"}>
              <code title={entry.line}>{entry.line.length > 90 ? `${entry.line.slice(0, 87)}…` : entry.line}</code>{entry.exit_code === 0 ? "" : <small> · exit {entry.exit_code}</small>}
            </li>
          ))}</ol>
        </article>
      )}
      <p className="factory-note infra-clock">Simulated clock: {world.clock}</p>
    </div>
  );
}
