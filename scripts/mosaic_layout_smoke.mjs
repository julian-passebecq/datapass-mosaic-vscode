import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import * as esbuild from "esbuild";

const dir = await mkdtemp(path.join(tmpdir(), "datapass-mosaic-layout-"));
const outfile = path.join(dir, "mosaic-layout.mjs");

try {
  await esbuild.build({
    entryPoints: ["src/platform/mosaicLayout.ts"],
    bundle: true,
    platform: "node",
    format: "esm",
    target: "node20",
    outfile,
    logLevel: "silent"
  });
  const mod = await import(pathToFileURL(outfile).href + `?v=${Date.now()}`);

  // Round trip keeps geometry only.
  const layout = [
    { i: "python", x: 0, y: 0, w: 12, h: 10, minW: 2, moved: false, static: false },
    { i: "sql", x: 0, y: 10, w: 6, h: 8 },
    { i: "data", x: 6, y: 10, w: 6, h: 8 },
    { i: "notes", x: 0, y: 18, w: 12, h: 5 }
  ];
  const clean = mod.sanitizeMosaicLayout(layout);
  assert.deepEqual(clean[0], { i: "python", x: 0, y: 0, w: 12, h: 10 });
  const text = mod.serializeMosaicLayout(clean);
  assert.equal(JSON.parse(text).schemaVersion, 1);
  assert.deepEqual(mod.parseMosaicLayoutDocument(text), clean);

  // Unknown/duplicate blocks and out-of-range geometry are dropped, not trusted.
  const hostile = mod.sanitizeMosaicLayout([
    { i: "sql", x: 0, y: 0, w: 6, h: 9 },
    { i: "sql", x: 6, y: 0, w: 6, h: 9 },
    { i: "__proto__", x: 0, y: 0, w: 6, h: 9 },
    { i: "python", x: 0, y: 0, w: 99, h: 9 },
    { i: "data", x: "0", y: 0, w: 6, h: 9 },
    { i: "notes", x: 11, y: 0, w: 4, h: 5 }
  ]);
  assert.deepEqual(hostile.map(item => item.i), ["sql", "notes"]);
  assert.equal(hostile[1].x, 8, "x is clamped so the block stays inside 12 columns");
  assert.equal(mod.sanitizeMosaicLayout("nope"), undefined);
  assert.equal(mod.sanitizeMosaicLayout([{ i: "unknown", x: 0, y: 0, w: 1, h: 1 }]), undefined);

  // Partial documents are completed from defaults below the stored blocks.
  const partial = mod.parseMosaicLayoutDocument(JSON.stringify({
    schemaVersion: 1,
    layout: [{ i: "notes", x: 0, y: 0, w: 12, h: 4 }]
  }));
  assert.deepEqual(partial.map(item => item.i).sort(), ["data", "notes", "python", "sql"]);
  assert.ok(partial.filter(item => item.i !== "notes").every(item => item.y >= 4));

  // Unknown schema versions and corrupt JSON fall back to "no project layout".
  assert.equal(mod.parseMosaicLayoutDocument(JSON.stringify({ schemaVersion: 2, layout: clean })), undefined);
  assert.equal(mod.parseMosaicLayoutDocument("{not json"), undefined);

  assert.equal(mod.MOSAIC_DEFAULT_LAYOUT.length, mod.MOSAIC_BLOCKS.length);

  console.log("Mosaic layout contract smoke passed.");
} finally {
  await rm(dir, { recursive: true, force: true });
}
