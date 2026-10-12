// The real src/build/buildCommands.ts host against a small `vscode` stub over real temporary files: New Blank
// Workspace opens Mosaic without waiting for its notification (a non-modal notification's promise stays pending until
// the learner dismisses it; found by scripts/ui-suite/v1_acceptance.mjs).
import test, { after } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import fs from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import * as esbuild from 'esbuild';

const root = fileURLToPath(new URL('../..', import.meta.url));
const temp = await mkdtemp(path.join(tmpdir(), 'dpw-build-host-'));
after(() => rm(temp, { recursive: true, force: true }));

// Each test resets `globalThis.__vscodeStub` before calling the command.
const stub = `
const uri = p => ({ scheme: 'file', fsPath: p, path: p.split('\\\\').join('/'), toString: () => 'file://' + p });
const s = () => globalThis.__vscodeStub;
export const Uri = { file: uri, joinPath: (base, ...parts) => uri(require('node:path').join(base.fsPath, ...parts)) };
export const FileType = { File: 1, Directory: 2 };
export const workspace = {
  get workspaceFolders() { return [{ uri: uri(s().root), name: 'ws' }]; },
  get isTrusted() { return true; },
  fs: {
    stat: async u => require('node:fs/promises').stat(u.fsPath),
    readFile: async u => new Uint8Array(await require('node:fs/promises').readFile(u.fsPath)),
    writeFile: async (u, b) => { await require('node:fs/promises').mkdir(require('node:path').dirname(u.fsPath), { recursive: true }); await require('node:fs/promises').writeFile(u.fsPath, b); },
    createDirectory: async u => { await require('node:fs/promises').mkdir(u.fsPath, { recursive: true }); },
    readDirectory: async u => (await require('node:fs/promises').readdir(u.fsPath, { withFileTypes: true })).map(e => [e.name, e.isDirectory() ? 2 : 1])
  }
};
export const window = {
  showInformationMessage: (...args) => s().info(...args),
  showWarningMessage: (...args) => s().warn(...args),
  showErrorMessage: async () => undefined,
  showTextDocument: async () => undefined
};
export const commands = {
  registerCommand: (id, fn) => { s().registered[id] = fn; return { dispose() {} }; },
  executeCommand: async (id, ...args) => { s().executed.push(id); }
};
`;
const stubFile = path.join(temp, 'vscode-stub.mjs');
await writeFile(stubFile, stub);
const outfile = path.join(temp, 'buildCommands.mjs');
await esbuild.build({
  entryPoints: [path.join(root, 'src/build/buildCommands.ts')], bundle: true, platform: 'node', format: 'esm', target: 'node20',
  outfile, logLevel: 'silent',
  banner: { js: "import { createRequire as __cr } from 'node:module'; const require = __cr(import.meta.url);" },
  plugins: [{ name: 'vscode-stub', setup(build) { build.onResolve({ filter: /^vscode$/ }, () => ({ path: stubFile })); } }]
});
const { registerBuildCommands } = await import(pathToFileURL(outfile).href);

async function newWorkspace() {
  const folder = await mkdtemp(path.join(temp, 'ws-'));
  const state = { root: folder, registered: {}, executed: [], warnings: [], infos: [],
    // A notification nobody clicks: its promise never settles.
    info: (...args) => { state.infos.push(args[0]); return new Promise(() => undefined); },
    warn: async (...args) => { state.warnings.push(args[0]); return undefined; } };
  globalThis.__vscodeStub = state;
  const runtime = { snapshot: () => ({ status: 'stopped' }) };
  const trust = { resolve: async () => ({ effective: false, reason: 'off' }) };
  registerBuildCommands({ extension: { packageJSON: { version: '0.0.0' } } }, runtime, trust);
  void state.registered['datapass.build.newWorkspace']();
  for (let i = 0; i < 100 && !state.executed.includes('datapass.openMosaic'); i++) await new Promise(r => setTimeout(r, 20));
  return state;
}

test('New Blank Workspace opens Mosaic while its notification is still open', async () => {
  const state = await newWorkspace();
  assert.ok(state.infos.some(text => /Blank Datapass workspace ready/.test(text)), 'the notification is shown');
  assert.ok(state.executed.includes('datapass.openMosaic'), 'Mosaic opens without waiting for the notification');
  const manifest = JSON.parse(await readFile(path.join(state.root, '.datapass', 'project.json'), 'utf8'));
  assert.equal(manifest.catalog?.seed, 'none');
  assert.notEqual(manifest.runtime?.trustedLocalPython, true);
  assert.deepEqual((await readdir(state.root)).sort(), ['.datapass', 'datasets', 'notebooks', 'notes']);
  await fs.access(path.join(state.root, '.datapass', 'project.json'));
});
