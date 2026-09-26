import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import * as esbuild from "esbuild";

const dir = await mkdtemp(path.join(tmpdir(), "datapass-infra-lab-"));

try {
  const load = async name => {
    const outfile = path.join(dir, `${name}.mjs`);
    await esbuild.build({ entryPoints: [`src/platform/${name}.ts`], bundle: true, platform: "node", format: "esm", target: "node20", outfile, logLevel: "silent" });
    return import(pathToFileURL(outfile).href);
  };
  const shell = await load("infraShell");
  const m = await load("missions");

  // The simulated terminal's line editor: echo, Backspace, Enter (CR, LF or CRLF, pasted lines), Ctrl+C, history.
  const editor = new shell.LineEditor();
  let r = editor.feed("terraform plan");
  assert.equal(r.echo, "terraform plan");
  assert.deepEqual(r.submitted, []);
  r = editor.feed("\x7f\x7f\x7f\x7fplan\r");
  assert.deepEqual(r.submitted, ["terraform plan"]);
  assert.equal(editor.current, "");
  r = editor.feed("docker ps\r\nkubectl get pods\n");
  assert.deepEqual(r.submitted, ["docker ps", "kubectl get pods"]);
  r = editor.feed("\x1b[A");
  assert.equal(editor.current, "kubectl get pods");
  r = editor.feed("\x1b[A\x1b[A");
  assert.equal(editor.current, "terraform plan");
  r = editor.feed("\x1b[B");
  assert.equal(editor.current, "docker ps");
  r = editor.feed("\x03");
  assert.ok(r.interrupted && editor.current === "");
  r = editor.feed("az vm list\x1b[D\x1b[C\x1b[H\t\r");
  assert.deepEqual(r.submitted, ["az vm list"], "cursor keys and Tab are ignored, not typed");
  r = editor.feed("x".repeat(3000));
  assert.equal(editor.current.length, 2000);
  editor.feed("\x15");
  assert.equal(editor.current, "");
  assert.equal(shell.toTerminal("a\nb\r\nc"), "a\r\nb\r\nc");
  assert.ok(shell.isClear("clear") && shell.isClear(" cls ") && !shell.isClear("clear x"));
  assert.ok(shell.isExit("exit") && !shell.isExit("exit 1"));
  assert.match(shell.INFRA_BANNER, /simulated/);
  assert.match(shell.INFRA_BANNER, /nothing is provisioned, built or deployed/);

  // Every Infra Lab mission reads back; its ticket lives outside the mission folder; the ticket says it is simulated.
  const packDir = "content/missions/infra-v1";
  const pack = JSON.parse(await readFile(`${packDir}/pack.json`, "utf8"));
  assert.equal(pack.lab, "infra");
  assert.equal(pack.missions.length, 6);
  for (const id of pack.missions) {
    const mission = m.toMissionView(JSON.parse(await readFile(`${packDir}/${id}/mission.json`, "utf8")), pack.id);
    assert.ok(mission && mission.id === id && mission.lab === "infra" && mission.batches.length === 0, id);
    assert.equal(m.ticketPath(mission), `.datapass/missions/tickets/${id}.md`);
    const ticket = m.ticketMarkdown(mission);
    assert.match(ticket, /simulated terminal/);
    assert.match(ticket, /nothing is provisioned, built or\s+deployed/);
    const entries = await readdir(`${packDir}/${id}`);
    assert.ok(entries.includes("mutants"), id);
  }

  // The module is registered with its command; references and mutants never reach the VSIX.
  const pkg = JSON.parse(await readFile("package.json", "utf8"));
  assert.ok(pkg.contributes.commands.some(c => c.command === "datapass.openInfraLab"));
  const vscodeignore = await readFile(".vscodeignore", "utf8");
  assert.match(vscodeignore, /^content\/missions\/\*\/\*\/solution\/\*\*$/m);
  assert.match(vscodeignore, /^content\/missions\/\*\/\*\/mutants\/\*\*$/m);
  const modules = await readFile("src/modules.ts", "utf8");
  assert.match(modules, /id:"infra"[\s\S]*?mode:"simulated"/);

  console.log("Infra Lab smoke passed.");
} finally {
  await rm(dir, { recursive: true, force: true });
}
