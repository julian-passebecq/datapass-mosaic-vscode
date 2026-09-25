import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import * as esbuild from "esbuild";

const dir = await mkdtemp(path.join(tmpdir(), "datapass-trust-"));

async function load(entry, name) {
  const outfile = path.join(dir, `${name}.mjs`);
  await esbuild.build({
    entryPoints: [entry],
    bundle: true,
    platform: "node",
    format: "esm",
    target: "node20",
    outfile,
    logLevel: "silent"
  });
  return import(pathToFileURL(outfile).href + `?v=${Date.now()}`);
}

try {
  const trust = await load("src/platform/pythonTrust.ts", "python-trust");
  const manifest = await load("src/project/projectManifestModel.ts", "manifest");
  const spark = await load("src/platform/sparkLabRun.ts", "spark-run");

  // Trust requires manifest opt-in AND local confirmation AND Workspace Trust.
  const all = { manifestOptIn: true, acknowledged: true, workspaceTrusted: true };
  assert.equal(trust.resolvePythonTrust(all).effective, true);
  assert.equal(trust.resolvePythonTrust(all).state, "enabled");
  assert.match(trust.resolvePythonTrust(all).reason, /not a sandbox/);
  for (const [key, state] of [
    ["manifestOptIn", "disabled"],
    ["workspaceTrusted", "blocked-untrusted-workspace"],
    ["acknowledged", "requested"]
  ]) {
    const resolved = trust.resolvePythonTrust({ ...all, [key]: false });
    assert.equal(resolved.effective, false, `${key}=false must disable trusted Python`);
    assert.equal(resolved.state, state);
  }
  assert.equal(
    trust.resolvePythonTrust({ manifestOptIn: false, acknowledged: false, workspaceTrusted: true }).state,
    "disabled"
  );
  // A cloned repository that sets the manifest flag is not enough on its own.
  assert.equal(
    trust.resolvePythonTrust({ manifestOptIn: true, acknowledged: false, workspaceTrusted: true }).effective,
    false
  );

  // An inherited shell variable can never silently enable Python.
  const inherited = { PATH: "/bin", DATAPASS_TRUSTED_PYTHON: "1", datapass_trusted_python: "1", EMPTY: undefined };
  const off = trust.runtimeProcessEnv(inherited, {
    contentRoot: "/ext/content",
    storage: "duckdb",
    trustedPython: false,
    workspaceRoot: "/ws"
  });
  assert.equal(off.DATAPASS_TRUSTED_PYTHON, undefined);
  assert.equal(off.datapass_trusted_python, undefined);
  assert.equal(off.PATH, "/bin");
  assert.equal(off.DATAPASS_STORAGE, "duckdb");
  assert.equal(off.DATAPASS_WORKSPACE_ROOT, "/ws");
  assert.equal(off.DATAPASS_CONTENT_ROOT, "/ext/content");
  assert.ok(!("EMPTY" in off));
  const on = trust.runtimeProcessEnv({ PATH: "/bin" }, {
    contentRoot: "/ext/content",
    storage: "ducklake",
    trustedPython: true
  });
  assert.equal(on.DATAPASS_TRUSTED_PYTHON, "1");
  assert.equal(on.DATAPASS_WORKSPACE_ROOT, undefined);

  // Manifest contract: default false, strict boolean, update preserves other fields.
  const created = manifest.createDefaultProjectManifest("My Project");
  assert.equal(created.runtime.trustedLocalPython, false);
  assert.deepEqual(manifest.validateProjectManifest(created), []);
  const enabled = manifest.withTrustedLocalPython(created, true);
  assert.equal(enabled.runtime.trustedLocalPython, true);
  assert.equal(enabled.runtime.pythonCommand, "python");
  assert.equal(enabled.project.id, "my-project");
  assert.equal(created.runtime.trustedLocalPython, false, "withTrustedLocalPython must not mutate");
  const invalid = { ...created, runtime: { ...created.runtime, trustedLocalPython: "yes" } };
  assert.ok(manifest.validateProjectManifest(invalid).some(issue => issue.includes("trustedLocalPython")));
  const badStorage = { ...created, runtime: { storage: "postgres" } };
  assert.ok(manifest.validateProjectManifest(badStorage).some(issue => issue.includes("runtime.storage")));
  // Older manifests without the key stay valid and resolve to disabled.
  const legacy = { schemaVersion: 1, project: { id: "x", title: "x" }, runtime: { storage: "duckdb" } };
  assert.deepEqual(manifest.validateProjectManifest(legacy), []);

  // SparkLab view mapping keeps truth labels and drops per-task payloads.
  const view = spark.toSparkLabRunView({
    status: "success",
    elapsed_ms: 12.5,
    compiled_sql: "SELECT 1",
    result: { columns: ["a"], rows: [{ a: 1 }], truncated: false },
    catalog: [{ name: "big" }],
    simulation: {
      status: "modeled",
      truth: "Local semantic result + simulated distributed execution",
      metrics: {
        total_duration_s: 1.34,
        shuffle_gb: 0,
        spill_gb: 0,
        stages: [{ stage_id: 0, name: "scan", operator: "scan", tasks: [{ task_id: 0 }], notes: ["n"], dependencies: [] }],
        plan_facts: { exchanges: 1, exchange_details: [{ reason: "aggregate", partitioning: "hash", keys: ["customer_id"] }] }
      },
      logical_plan: [{ id: 0, operation: "scan", source: "source.orders", parents: [], dependency: "narrow", concept: "c" }],
      datapass_credits: { total: 0.01, unit: "Datapass Credits", fictional: true },
      assumptions: { kind: "catalog row counts", calibration: "No real Spark benchmark calibration" },
      comparisons: [{ profile_id: "generic_8x8", aqe: true, duration_s: 1.34, credits: 0.01 }]
    }
  }, { fileName: "notebooks/sparklab.py", profileId: "generic_8x8", aqe: true });
  assert.equal(view.status, "success");
  assert.equal(view.simulation.status, "modeled");
  assert.match(view.simulation.truth, /simulated/);
  assert.equal(view.simulation.credits.fictional, true);
  assert.equal(view.simulation.stages.length, 1);
  assert.ok(!("tasks" in view.simulation.stages[0]), "per-task arrays must not reach the webview");
  assert.deepEqual(view.simulation.exchanges, ["hash(customer_id) for aggregate"]);
  assert.ok(!("catalog" in view));
  const rejected = spark.toSparkLabRunView({
    status: "error",
    elapsed_ms: 1,
    error: { type: "SparkLabSyntaxError", message: "Only PySpark SQL imports are allowed" },
    simulation: null
  }, { fileName: "x.py", profileId: "generic_8x8", aqe: false });
  assert.equal(rejected.status, "error");
  assert.equal(rejected.error.type, "SparkLabSyntaxError");
  assert.equal(rejected.simulation, undefined);

  console.log("Trusted Python and SparkLab contract smoke passed.");
} finally {
  await rm(dir, { recursive: true, force: true });
}
