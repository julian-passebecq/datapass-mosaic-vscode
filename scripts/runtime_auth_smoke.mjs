// The extension side of the runtime token (D-2): every client helper sends this launch's token, and the child
// environment carries a fresh token and port that an inherited shell variable can never replace.
import assert from "node:assert/strict";
import http from "node:http";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import * as esbuild from "esbuild";

const dir = await mkdtemp(path.join(tmpdir(), "datapass-runtime-auth-"));

async function load(entry, name) {
  const outfile = path.join(dir, `${name}.mjs`);
  await esbuild.build({ entryPoints: [entry], bundle: true, platform: "node", format: "esm", target: "node20", outfile, logLevel: "silent" });
  return import(pathToFileURL(outfile).href + `?v=${Date.now()}`);
}

let server;
try {
  const client = await load("src/platform/runtimeClient.ts", "runtime-client");
  const endpoint = await load("src/platform/runtimeEndpoint.ts", "runtime-endpoint");
  const trust = await load("src/platform/pythonTrust.ts", "python-trust");
  const security = await load("src/webview/security.ts", "webview-security");

  // D-9: webview nonces come from crypto, and images load only from the extension or data: URLs.
  const nonces = new Set(Array.from({ length: 200 }, () => security.makeNonce()));
  assert.equal(nonces.size, 200);
  assert.ok([...nonces].every(nonce => /^[A-Za-z0-9]{32}$/.test(nonce)));
  assert.equal(security.makeNonce(7).length, 7);
  const csp = security.contentSecurityPolicy({ cspSource: "vscode-resource:" }, "abc");
  assert.match(csp, /img-src vscode-resource: data:;/);
  assert.doesNotMatch(csp, /https:|http:/);
  assert.match(csp, /default-src 'none';/);
  assert.match(csp, /script-src 'nonce-abc';/);

  // Tokens: 32 random bytes as hex, a new one per launch.
  const token = client.newRuntimeToken();
  assert.match(token, /^[0-9a-f]{64}$/);
  assert.notEqual(client.newRuntimeToken(), token);
  assert.equal(client.RUNTIME_TOKEN_HEADER, "x-datapass-token");

  // The child environment carries this launch's token and port; inherited values are dropped whatever their case.
  const env = trust.runtimeProcessEnv(
    { PATH: "/bin", DATAPASS_RUNTIME_TOKEN: "stale", datapass_runtime_port: "1" },
    { contentRoot: "/c", storage: "duckdb", trustedPython: false, runtimeToken: token, runtimePort: 4321 }
  );
  assert.equal(env.DATAPASS_RUNTIME_TOKEN, token);
  assert.equal(env.DATAPASS_RUNTIME_PORT, "4321");
  assert.ok(!("datapass_runtime_port" in env));

  // A fake runtime that answers only with the right token, like the real middleware.
  const seen = [];
  server = http.createServer((request, response) => {
    seen.push({ url: request.url, method: request.method, token: request.headers["x-datapass-token"] });
    if (request.headers["x-datapass-token"] !== token) {
      response.writeHead(401, { "content-type": "application/json" });
      response.end(JSON.stringify({ detail: "Missing or invalid Datapass runtime token." }));
      return;
    }
    request.resume();
    request.on("end", () => {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify(request.url === "/api/health" ? { status: "ok", runtime: "local", version: "0.1.0" } : { ok: true }));
    });
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const base = `http://127.0.0.1:${server.address().port}`;

  assert.deepEqual(await client.requestJson(`${base}/api/local/query`, "POST", { sql: "select 1" }, 2000, token), { ok: true });
  assert.deepEqual(await client.requestGetJson(`${base}/api/local/catalog`, 2000, token), { ok: true });
  assert.equal((await endpoint.probeDatapassHealth(`${base}/api/health`, token)).status, "ok");
  assert.equal((await endpoint.waitForDatapassHealth(`${base}/api/health`, 2000, () => undefined, token)).runtime, "local");
  assert.ok(seen.every(entry => entry.token === token), "every helper sends the token");

  // Without the token the runtime refuses and the helpers surface the HTTP status.
  await assert.rejects(client.requestJson(`${base}/api/local/query`, "POST", {}, 2000), /HTTP 401/);
  await assert.rejects(client.requestGetJson(`${base}/api/local/catalog`, 2000, "wrong"), /HTTP 401/);
  await assert.rejects(endpoint.probeDatapassHealth(`${base}/api/health`), /HTTP 401/);
  assert.equal(seen.at(-3).token, undefined, "no header without a token");

  console.log("runtime auth smoke passed");
} finally {
  server?.close();
  await rm(dir, { recursive: true, force: true });
}
