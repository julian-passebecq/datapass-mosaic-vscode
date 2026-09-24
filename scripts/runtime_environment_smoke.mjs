import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import * as esbuild from "esbuild";

const dir = await mkdtemp(path.join(tmpdir(), "datapass-runtime-env-"));
const outfile = path.join(dir, "runtime-environment.mjs");

try {
  await esbuild.build({
    entryPoints: ["src/platform/runtimeEnvironment.ts"],
    bundle: true,
    platform: "node",
    format: "esm",
    target: "node20",
    outfile,
    logLevel: "silent"
  });

  const mod = await import(pathToFileURL(outfile).href + `?v=${Date.now()}`);
  const linux = mod.managedVenvPython("/tmp/datapass-env", "linux").replaceAll("\\", "/");
  const windows = mod.managedVenvPython("C:/datapass-env", "win32").replaceAll("\\", "/");

  assert.ok(linux.endsWith("/bin/python"));
  assert.ok(windows.endsWith("/Scripts/python.exe"));

  const install = mod.runtimeInstallArgs("/extension/runtime");
  assert.deepEqual(install.slice(0, 3), ["-m", "pip", "install"]);
  assert.equal(install.at(-1), "/extension/runtime");

  const verify = mod.runtimeVerifyArgs();
  assert.equal(verify[0], "-c");
  assert.match(verify[1], /datapass_runtime/);
  assert.match(verify[1], /duckdb/);
  assert.match(verify[1], /polars/);

  console.log("Managed runtime environment smoke passed.");
} finally {
  await rm(dir, { recursive: true, force: true });
}
