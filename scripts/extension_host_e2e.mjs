// Launch a real VS Code Extension Development Host against a disposable
// workspace and run src/test/hostSuite.ts inside it.
//
//   npm run test:host
//
// Runtime steps run only when DATAPASS_E2E_PYTHON points to a Python that has
// ./runtime installed (e.g. `python -m pip install ./runtime`). On Linux CI run
// under xvfb-run. VSCODE_TEST_VERSION selects the VS Code build (default stable).
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { runTests } from "@vscode/test-electron";
import * as esbuild from "esbuild";

const root = process.cwd();
const suite = path.join(root, "dist-test", "hostSuite.js");

await esbuild.build({
  entryPoints: ["src/test/hostSuite.ts"],
  bundle: true,
  platform: "node",
  format: "cjs",
  target: "node20",
  outfile: suite,
  external: ["vscode"],
  sourcemap: true,
  logLevel: "silent"
});

const workspace = await mkdtemp(path.join(tmpdir(), "datapass-e2e-workspace-"));
const userData = await mkdtemp(path.join(tmpdir(), "datapass-e2e-user-"));

try {
  await runTests({
    version: process.env.VSCODE_TEST_VERSION || "stable",
    extensionDevelopmentPath: root,
    extensionTestsPath: suite,
    launchArgs: [
      workspace,
      "--disable-extensions",
      "--disable-workspace-trust",
      "--skip-welcome",
      "--skip-release-notes",
      `--user-data-dir=${userData}`
    ],
    extensionTestsEnv: {
      // Hostile on purpose: the runtime must still start with trusted Python off.
      DATAPASS_TRUSTED_PYTHON: "1",
      // Also hostile: the extension must replace an inherited runtime token with its own launch token.
      DATAPASS_RUNTIME_TOKEN: "inherited-token",
      DATAPASS_E2E_PYTHON: process.env.DATAPASS_E2E_PYTHON ?? "",
      // A Python with dbt-core + dbt-duckdb: enables the real dbt Core steps (terminal and catalog handoff).
      DATAPASS_DBT_PYTHON: process.env.DATAPASS_DBT_PYTHON ?? ""
    }
  });
  console.log("Extension host E2E passed.");
} catch (error) {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
} finally {
  await rm(workspace, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
  await rm(userData, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
}
