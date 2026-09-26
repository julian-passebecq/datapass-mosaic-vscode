import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import * as esbuild from "esbuild";

// The Workbench's message table (src/labs/messageTable.ts) and the per-lab layout of src/labs.
const dir = await mkdtemp(path.join(tmpdir(), "datapass-message-table-"));

try {
  const outfile = path.join(dir, "messageTable.mjs");
  await esbuild.build({ entryPoints: ["src/labs/messageTable.ts"], bundle: true, platform: "node", format: "esm", target: "node20", outfile, logLevel: "silent" });
  const { buildMessageTable } = await import(pathToFileURL(outfile).href);

  // Each message type reaches the one controller that handles it; an unknown type has no route.
  const seen = [];
  const table = buildMessageTable([
    { handlers: { runAirflow: message => seen.push(["airflow", message.type]) } },
    { handlers: { runBi: message => seen.push(["bi", message.type]), refreshBi: () => seen.push(["bi", "refresh"]) } }
  ]);
  await table.get("runBi")({ type: "runBi" });
  await table.get("runAirflow")({ type: "runAirflow" });
  assert.deepEqual(seen, [["bi", "runBi"], ["airflow", "runAirflow"]]);
  assert.equal(table.size, 3);
  assert.equal(table.get("nope"), undefined);

  // Two controllers answering one message type is refused when the Workbench opens.
  assert.throws(
    () => buildMessageTable([{ handlers: { ready: () => undefined } }, { handlers: { ready: () => undefined } }]),
    /Two Workbench controllers handle the "ready" message/
  );

  // Labs stay independent: a lab's files import no other lab (the registry, src/labs/controllers.ts, wires the few
  // cross-lab actions), except the shared missions hooks type.
  const labs = (await readdir("src/labs", { withFileTypes: true })).filter(entry => entry.isDirectory()).map(entry => entry.name);
  assert.ok(labs.length >= 13, `expected one folder per lab in src/labs, found ${labs.join(", ")}`);
  for (const lab of labs) {
    for (const file of await readdir(path.join("src/labs", lab))) {
      const text = await readFile(path.join("src/labs", lab, file), "utf8");
      for (const [, target] of text.matchAll(/from "\.\.\/([a-z]+)\/[^"]+"/g)) {
        if (target === lab) continue;
        assert.ok(target === "missions" && /import type \{ MissionLabHooks \} from "\.\.\/missions\/controller"/.test(text),
          `src/labs/${lab}/${file} imports src/labs/${target}: wire cross-lab actions in src/labs/controllers.ts`);
      }
    }
  }

  // Each lab's messages live in its own contracts file, composed in contracts/index.ts.
  const contracts = await readdir("src/webview/contracts");
  for (const lab of labs) assert.ok(contracts.includes(`${lab}.ts`), `src/webview/contracts/${lab}.ts is missing`);

  console.log(`Message table smoke passed (${labs.length} lab folders).`);
} finally {
  await rm(dir, { recursive: true, force: true });
}
