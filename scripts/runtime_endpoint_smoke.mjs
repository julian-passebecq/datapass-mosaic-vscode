import assert from "node:assert/strict";
import http from "node:http";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import * as esbuild from "esbuild";

const dir = await mkdtemp(path.join(tmpdir(), "datapass-runtime-endpoint-"));
const outfile = path.join(dir, "runtime-endpoint.mjs");

try {
  await esbuild.build({
    entryPoints: ["src/platform/runtimeEndpoint.ts"],
    bundle: true,
    platform: "node",
    format: "esm",
    target: "node20",
    outfile,
    logLevel: "silent"
  });

  const mod = await import(pathToFileURL(outfile).href + `?v=${Date.now()}`);

  const port = await mod.findFreePort("127.0.0.1");
  assert.ok(Number.isInteger(port) && port > 0 && port < 65536);

  const goodServer = http.createServer((request, response) => {
    if (request.url === "/api/health") {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ status: "ok", runtime: "local", version: "0.1.0" }));
      return;
    }
    response.writeHead(404);
    response.end();
  });
  await new Promise(resolve => goodServer.listen(0, "127.0.0.1", resolve));
  const goodAddress = goodServer.address();
  assert.ok(goodAddress && typeof goodAddress !== "string");
  const health = await mod.probeDatapassHealth(
    `http://127.0.0.1:${goodAddress.port}/api/health`
  );
  assert.equal(health.runtime, "local");
  assert.equal(health.status, "ok");
  await new Promise((resolve, reject) => goodServer.close(error => error ? reject(error) : resolve()));

  const badServer = http.createServer((_request, response) => {
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify({ status: "ok", runtime: "something-else", version: "1.0.0" }));
  });
  await new Promise(resolve => badServer.listen(0, "127.0.0.1", resolve));
  const badAddress = badServer.address();
  assert.ok(badAddress && typeof badAddress !== "string");
  await assert.rejects(
    mod.probeDatapassHealth(`http://127.0.0.1:${badAddress.port}/api/health`),
    /not a Datapass local runtime/
  );
  await new Promise((resolve, reject) => badServer.close(error => error ? reject(error) : resolve()));

  console.log("Runtime endpoint smoke tests passed.");
} finally {
  await rm(dir, { recursive: true, force: true });
}
