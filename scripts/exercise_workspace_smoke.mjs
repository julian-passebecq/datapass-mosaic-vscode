import assert from "node:assert/strict";
import { access, mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import * as esbuild from "esbuild";

// Exercise folders: readable tab labels, Pylance stubs and per-exercise __builtins__.pyi (V1-3, V1-4).
const dir = await mkdtemp(path.join(tmpdir(), "datapass-exercise-workspace-"));
const outfile = path.join(dir, "exercise-workspace.mjs");

try {
  await esbuild.build({
    entryPoints: ["src/platform/exerciseWorkspace.ts"],
    bundle: true,
    platform: "node",
    format: "esm",
    target: "node20",
    outfile,
    logLevel: "silent"
  });
  const mod = await import(pathToFileURL(outfile).href + `?v=${Date.now()}`);

  // Tab labels: ${dirname} is the language folder, ${dirname(1)} the exercise folder.
  const patterns = mod.exerciseLabelPatterns(["exercises"]);
  assert.deepEqual(patterns, {
    "**/exercises/*/*/solution.*": "${dirname(1)} · ${dirname}",
    "**/exercises/*/*/README.md": "${dirname(1)} · brief"
  });
  assert.ok(Object.keys(mod.exerciseLabelPatterns(["learn", "practice"]))[0].startsWith("**/learn/practice/*/*/"));
  assert.deepEqual(mod.mergeMissing(undefined, patterns), patterns);
  assert.equal(mod.mergeMissing(patterns, patterns), undefined, "nothing to write twice");
  const learner = { "**/exercises/*/*/solution.*": "${filename}", "**/*.test.ts": "test ${filename}" };
  const merged = mod.mergeMissing(learner, patterns);
  assert.equal(merged["**/exercises/*/*/solution.*"], "${filename}", "a learner's template wins");
  assert.equal(merged["**/*.test.ts"], "test ${filename}");
  assert.equal(merged["**/exercises/*/*/README.md"], "${dirname(1)} · brief");

  assert.deepEqual(mod.exerciseFileExcludes(["exercises"]), { "**/exercises/*/*/__builtins__.pyi": true });
  assert.deepEqual(mod.mergeMissing({ "**/.git": true }, mod.exerciseFileExcludes(["exercises"])),
    { "**/.git": true, "**/exercises/*/*/__builtins__.pyi": true });

  // python.analysis.extraPaths keeps the learner's paths and adds the stubs folder once.
  assert.deepEqual(mod.mergeExtraPaths(undefined), [".datapass/pylance-stubs"]);
  assert.deepEqual(mod.mergeExtraPaths(["src"]), ["src", ".datapass/pylance-stubs"]);
  assert.equal(mod.mergeExtraPaths(["./.datapass/pylance-stubs/"]), undefined);
  assert.equal(mod.mergeExtraPaths([".datapass\\pylance-stubs"]), undefined);

  // __builtins__.pyi: exactly what the runtime injects per language.
  const kernel = mod.exerciseBuiltinsStub("python", ["raw_values", "class", "bad-name"]);
  for (const line of ["def query(sql: str) -> Rows: ...", "def display(", "def publish(", "input_rows: Rows", "tables: dict[str, Rows]", "raw_values: Rows"]) {
    assert.ok(kernel.includes(line), `python builtins declare ${line}`);
  }
  assert.ok(!kernel.includes("class: Rows") && !kernel.includes("bad-name"), "keywords and invalid names are skipped");
  assert.ok(mod.exerciseBuiltinsStub("polars", []).includes("def display("));
  assert.match(mod.exerciseBuiltinsStub("sparklab", ["orders"]), /^spark: Any$/m);
  assert.ok(!mod.exerciseBuiltinsStub("sparklab", ["orders"]).includes("orders"), "SparkLab reads tables through spark.table");
  assert.match(mod.exerciseBuiltinsStub("databricks-notebook", []), /^dbutils: Any$/m);
  assert.match(mod.exerciseBuiltinsStub("factory-notebook", []), /^notebookutils: Any$/m);
  const design = mod.exerciseBuiltinsStub("python", ["orders"], "datapass-dag-design-v1");
  assert.match(design, /^def pipeline\(/m, "Pipeline Lab design exercises declare the compiler's calls");
  assert.ok(!design.includes("def query("), "and not the Python kernel's names");
  assert.equal(mod.exerciseBuiltinsStub("airflow", []), undefined);
  assert.equal(mod.exerciseBuiltinsStub("sql", []), undefined);
  assert.equal(mod.isPythonExerciseLanguage("airflow"), true);
  assert.equal(mod.isPythonExerciseLanguage("sqlpool"), false);

  // Every import of a simulated package in every shipped starter resolves to a generated stub, with its names.
  const STUB_ROOT = "content/pylance-stubs";
  const SIMULATED = new Set(["pyspark", "airflow", "pendulum", "mlflow", "notebookutils", "mssparkutils"]);
  const stubFile = async module => {
    const parts = module.split(".");
    for (const candidate of [path.join(STUB_ROOT, ...parts) + ".py", path.join(STUB_ROOT, ...parts, "__init__.py")]) {
      try {
        await access(candidate);
        return candidate;
      } catch {
        // try the next layout
      }
    }
    return undefined;
  };
  const declares = (stub, name) =>
    stub.includes("def __getattr__(") ||
    new RegExp(`^(def ${name}\\(|${name}: |from \\. import ${name} as ${name}$)`, "m").test(stub);

  const starters = [];
  const packsRoot = "content/exercise-packs";
  for (const pack of await readdir(packsRoot)) {
    for (const file of ["exercises.json", "scenarios.json"]) {
      let items;
      try {
        items = JSON.parse(await readFile(path.join(packsRoot, pack, file), "utf8"));
      } catch {
        continue;
      }
      for (const item of items) {
        if (typeof item?.starter_source === "string" && mod.isPythonExerciseLanguage(item.language)) {
          starters.push({ where: `${pack}/${item.id}`, source: item.starter_source });
        }
        for (const [language, variant] of Object.entries(item?.variants ?? {})) {
          if (typeof variant?.starter_source === "string" && mod.isPythonExerciseLanguage(language)) {
            starters.push({ where: `${pack}/${item.common?.id}/${language}`, source: variant.starter_source });
          }
        }
      }
    }
  }
  assert.ok(starters.length > 50, `found ${starters.length} Python starters`);

  let checked = 0;
  for (const { where, source } of starters) {
    for (const match of source.matchAll(/^\s*(?:from\s+([\w.]+)\s+import\s+([^\n#]+)|import\s+([\w.]+))/gm)) {
      const module = match[1] ?? match[3];
      if (!SIMULATED.has(module.split(".")[0])) continue;
      const file = await stubFile(module);
      assert.ok(file, `${where}: no Pylance stub for ${module}`);
      const names = (match[2] ?? "").replace(/[()]/g, "").split(",").map(part => part.trim().split(/\s+as\s+/)[0]).filter(Boolean);
      const stub = await readFile(file, "utf8");
      for (const name of names) {
        const submodule = await stubFile(`${module}.${name}`);
        assert.ok(submodule || declares(stub, name), `${where}: ${module} stub does not declare ${name}`);
      }
      checked += 1;
    }
  }
  assert.ok(checked > 30, `checked ${checked} simulated imports`);

  console.log(`Exercise workspace smoke passed (${starters.length} Python starters, ${checked} simulated imports).`);
} finally {
  await rm(dir, { recursive: true, force: true });
}
