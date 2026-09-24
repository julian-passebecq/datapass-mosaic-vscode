import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";

const required = [
  "dist/extension.js",
  "dist/webview.js",
  "dist/webview.css",
  "media/datapass.svg",
  "content/modules.json",
  "content/cases/retail-medallion.json",
  "runtime/pyproject.toml",
  "runtime/datapass_runtime/main.py",
  "runtime/datapass_runtime/execution.py",
  "runtime/sparklab/profiles.json",
  "samples/dbt/retail-dbt/dbt_project.yml"
];

for (const path of required) {
  await access(path);
}

const ignore = await readFile(".vscodeignore", "utf8");
for (const forbidden of [
  "legacy-donors/**",
  "migration-sources/**",
  "workbench-core/**",
  "runtime/build/**",
  "runtime/**/*.egg-info/**",
  "**/*.map"
]) {
  assert.ok(ignore.includes(forbidden), `VSIX ignore is missing ${forbidden}`);
}

console.log("VSIX package boundary smoke passed.");
