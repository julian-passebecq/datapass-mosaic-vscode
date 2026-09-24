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
  assert.match(verify[1], /pandas/);

  const describe = mod.describeSetupOutputLine;
  assert.equal(describe("Collecting polars>=1.0"), "Resolving polars");
  assert.equal(
    describe("  Downloading polars-1.12.0-cp39-abi3-win_amd64.whl (35.2 MB)"),
    "Downloading polars (35.2 MB)"
  );
  assert.equal(
    describe("Downloading https://files.pythonhosted.org/packages/ab/cd/duckdb-1.1.3-cp312-cp312-win_amd64.whl (11.0 MB)"),
    "Downloading duckdb (11.0 MB)"
  );
  assert.equal(describe("Building wheel for datapass-runtime (pyproject.toml) ... done"), "Building datapass-runtime");
  assert.match(describe("Installing collected packages: numpy, polars, duckdb"), /^Installing packages/);
  assert.equal(describe("Successfully installed duckdb-1.1.3 polars-1.12.0"), "Packages installed");
  assert.equal(describe("  Requirement already satisfied: fastapi in ./venv"), undefined);
  assert.equal(describe("   ━━━━━━━━━━━━━━━━━━ 35.2/35.2 MB 8.1 MB/s eta 0:00:00"), undefined);

  console.log("Managed runtime environment smoke passed.");
} finally {
  await rm(dir, { recursive: true, force: true });
}
