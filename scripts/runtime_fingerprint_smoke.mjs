// Stale managed runtime detection (src/platform/runtimeFingerprint.ts): the fingerprint of the bundled runtime/
// sources, the marker Setup writes in the managed venv, and the ready / stale / missing decision.
import assert from "node:assert/strict";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import * as esbuild from "esbuild";

const dir = await mkdtemp(path.join(tmpdir(), "datapass-runtime-fp-"));
const outfile = path.join(dir, "runtime-fingerprint.mjs");

function write(root, relative, text) {
  const file = path.join(root, ...relative.split("/"));
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, text);
}

try {
  await esbuild.build({
    entryPoints: ["src/platform/runtimeFingerprint.ts"],
    bundle: true,
    platform: "node",
    format: "esm",
    target: "node20",
    outfile,
    logLevel: "silent"
  });
  const mod = await import(pathToFileURL(outfile).href + `?v=${Date.now()}`);

  // --- Which files count --------------------------------------------------------------------------------------------
  const runtime = path.join(dir, "runtime");
  write(runtime, "pyproject.toml", "[project]\nname = \"datapass-runtime\"\nversion = \"0.1.0\"\n");
  write(runtime, "datapass_runtime/__init__.py", "");
  write(runtime, "datapass_runtime/main.py", "app = 1\n");
  write(runtime, "sparklab/profiles.json", "{}\n");
  write(runtime, "sparklab/build/keep.py", "# a package folder named build below the root is a source\n");
  assert.deepEqual(mod.runtimeSourceFiles(runtime), [
    "datapass_runtime/__init__.py", "datapass_runtime/main.py", "pyproject.toml", "sparklab/build/keep.py", "sparklab/profiles.json"
  ]);
  const base = mod.runtimeFingerprint(runtime);
  assert.match(base, /^sha256:[0-9a-f]{64}$/);
  assert.equal(mod.runtimeFingerprint(runtime), base, "deterministic");

  // What an install or an import leaves in the source folder does not change it (the VSIX does not ship it either).
  write(runtime, "datapass_runtime/__pycache__/main.cpython-312.pyc", "bytecode");
  write(runtime, "datapass_runtime/stray.pyc", "bytecode");
  write(runtime, "build/lib/datapass_runtime/main.py", "app = 1\n");
  write(runtime, "dist/datapass_runtime-0.1.0.tar.gz", "sdist");
  write(runtime, "datapass_runtime.egg-info/PKG-INFO", "Name: datapass-runtime\n");
  write(runtime, ".pytest_cache/v/cache/lastfailed", "{}");
  assert.equal(mod.runtimeFingerprint(runtime), base, "build output, bytecode and hidden folders are ignored");

  // A source change, a new module and a rename each change it.
  write(runtime, "datapass_runtime/main.py", "app = 2\n");
  const edited = mod.runtimeFingerprint(runtime);
  assert.notEqual(edited, base, "content change");
  write(runtime, "datapass_runtime/main.py", "app = 1\n");
  assert.equal(mod.runtimeFingerprint(runtime), base, "back to the same sources, back to the same fingerprint");
  write(runtime, "airflowlab/parser.py", "");
  const added = mod.runtimeFingerprint(runtime);
  assert.notEqual(added, base, "new file");
  const renamed = path.join(dir, "runtime-renamed");
  write(renamed, "pyproject.toml", readFileSync(path.join(runtime, "pyproject.toml"), "utf8"));
  write(renamed, "datapass_runtime/__init__.py", "");
  write(renamed, "datapass_runtime/app.py", "app = 1\n");
  write(renamed, "sparklab/profiles.json", "{}\n");
  write(renamed, "sparklab/build/keep.py", "# a package folder named build below the root is a source\n");
  assert.notEqual(mod.runtimeFingerprint(renamed), base, "same content under another name");
  const empty = path.join(dir, "empty");
  mkdirSync(empty);
  assert.throws(() => mod.runtimeFingerprint(empty), /No runtime sources/);

  // The repository's runtime/: every package's sources count, generated files do not.
  const real = mod.runtimeSourceFiles(path.resolve("runtime"));
  for (const expected of ["pyproject.toml", "datapass_runtime/main.py", "airflowlab/parser.py", "missionlab/terminal.py"]) {
    assert.ok(real.includes(expected), `${expected} is fingerprinted`);
  }
  assert.ok(!real.some(file => /__pycache__|\.pyc$|\.egg-info\/|^build\//.test(file)), "no generated file");

  // --- Marker ------------------------------------------------------------------------------------------------------
  const venv = path.join(dir, "runtime-venv");
  mkdirSync(venv);
  assert.equal(mod.readRuntimeMarker(venv), undefined, "absent");
  const marker = { schema: 1, fingerprint: base, extensionVersion: "0.1.0", installedAt: "2026-09-26T10:00:00.000Z" };
  mod.writeRuntimeMarker(venv, marker);
  assert.equal(path.basename(mod.runtimeMarkerPath(venv)), mod.RUNTIME_MARKER_FILE);
  assert.deepEqual(mod.readRuntimeMarker(venv), marker, "round trip");
  writeFileSync(mod.runtimeMarkerPath(venv), "{ not json");
  assert.equal(mod.readRuntimeMarker(venv), undefined, "unreadable counts as absent");
  writeFileSync(mod.runtimeMarkerPath(venv), JSON.stringify({ schema: 2, fingerprint: base }));
  assert.equal(mod.readRuntimeMarker(venv), undefined, "unknown schema counts as absent");
  mod.writeRuntimeMarker(venv, marker);
  mod.removeRuntimeMarker(venv);
  assert.equal(mod.readRuntimeMarker(venv), undefined, "removed before a reinstall");
  mod.removeRuntimeMarker(venv); // idempotent

  // --- Decision ----------------------------------------------------------------------------------------------------
  const check = mod.checkManagedRuntime;
  assert.deepEqual(check({ pythonExists: false, marker, fingerprint: base }), { status: "missing" });
  assert.equal(check({ pythonExists: true, marker, fingerprint: base, extensionVersion: "0.1.0" }).status, "ready");
  const unrecorded = check({ pythonExists: true, fingerprint: base, extensionVersion: "0.1.0" });
  assert.equal(unrecorded.status, "stale", "a venv set up before this change has no marker");
  assert.match(unrecorded.reason, /did not record its runtime.*Update it before starting/);
  const sameVersion = check({ pythonExists: true, marker, fingerprint: edited, extensionVersion: "0.1.0" });
  assert.equal(sameVersion.status, "stale");
  assert.match(sameVersion.reason, /Datapass 0\.1\.0 .*same version number, different runtime sources/);
  const older = check({ pythonExists: true, marker, fingerprint: edited, extensionVersion: "0.2.0" });
  assert.match(older.reason, /installed by Datapass 0\.1\.0 and does not match/);
  assert.doesNotMatch(older.reason, /same version number/);
  const anonymous = check({ pythonExists: true, marker: { ...marker, extensionVersion: undefined }, fingerprint: edited });
  assert.match(anonymous.reason, /another Datapass build/);

  assert.equal(mod.extensionVersion(path.resolve(".")), JSON.parse(readFileSync("package.json", "utf8")).version);
  assert.equal(mod.extensionVersion(empty), undefined);

  console.log("runtime fingerprint smoke passed");
} finally {
  await rm(dir, { recursive: true, force: true });
}
