// A small node entry over src/platform/studioNotebook.ts for scripts/interop/studio_roundtrip.py. Prints one JSON
// document on stdout. Runs no cell: it reads and writes text only.
//
//   node scripts/interop/studio_notebook_cli.mjs import <file.ipynb>          -> {ok, notebook | errors}
//   node scripts/interop/studio_notebook_cli.mjs export-folder <folder>        -> {ok, text | errors}  (plain .sql/.py/.md files)
//   node scripts/interop/studio_notebook_cli.mjs export-record <file.ipynb>    -> {ok, text | errors}  (import, then export from the record)
import { mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import * as esbuild from "esbuild";

const root = fileURLToPath(new URL("../..", import.meta.url));
const dir = await mkdtemp(path.join(tmpdir(), "datapass-studio-cli-"));
try {
  const outfile = path.join(dir, "studio.mjs");
  await esbuild.build({ entryPoints: [path.join(root, "src/platform/studioNotebook.ts")], bundle: true, platform: "node", format: "esm", target: "node20", outfile, logLevel: "silent" });
  const s = await import(pathToFileURL(outfile).href);
  const [op, target] = process.argv.slice(2);
  let result;
  if (op === "import") {
    result = s.parseStudioNotebook(await readFile(target, "utf8"), path.basename(target));
  } else if (op === "export-folder") {
    const names = (await readdir(target, { withFileTypes: true })).filter(entry => entry.isFile()).map(entry => entry.name).sort();
    const items = [];
    for (const name of names) {
      const kind = s.studioKindOfFile(name);
      if (kind && name !== "README.md") items.push({ name, kind, content: await readFile(path.join(target, name), "utf8") });
    }
    result = s.buildStudioNotebook(s.studioCellsFromPlain(items), "2026-10-13T00:00:00Z");
  } else if (op === "export-record") {
    const parsed = s.parseStudioNotebook(await readFile(target, "utf8"), path.basename(target));
    if (!parsed.ok) result = parsed;
    else {
      const plan = s.planStudioImport(parsed.notebook, "notebooks", "2026-10-13T00:00:00Z", path.basename(target));
      const record = JSON.parse(JSON.stringify(plan.record.content));
      const sources = new Map(plan.files.map(file => [file.path, file.content]));
      result = s.buildStudioNotebook(s.studioCellsFromRecord(record, sources), "2026-10-13T00:00:00Z", record.metadata);
    }
  } else {
    throw new Error(`unknown operation ${op}`);
  }
  process.stdout.write(JSON.stringify(result));
} finally {
  await rm(dir, { recursive: true, force: true });
}
