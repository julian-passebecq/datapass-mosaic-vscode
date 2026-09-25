import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import * as esbuild from "esbuild";

const dir = await mkdtemp(path.join(tmpdir(), "datapass-terminal-lab-"));

try {
  const load = async name => {
    const outfile = path.join(dir, `${name}.mjs`);
    await esbuild.build({ entryPoints: [`src/platform/${name}.ts`], bundle: true, platform: "node", format: "esm", target: "node20", outfile, logLevel: "silent" });
    return import(pathToFileURL(outfile).href);
  };
  const shells = await load("terminalShells");
  const m = await load("missions");

  // bash on Windows is Git Bash, found next to git.exe or in the usual folders; never WSL's System32\bash.exe.
  const env = { ProgramFiles: "C:\\Program Files", LOCALAPPDATA: "C:\\Users\\a\\AppData\\Local", SystemRoot: "C:\\Windows" };
  const bash = shells.bashCandidates("win32", env, "C:\\Program Files\\Git\\cmd\\git.exe");
  assert.equal(bash[0], "C:\\Program Files\\Git\\bin\\bash.exe");
  assert.ok(bash.includes("C:\\Users\\a\\AppData\\Local\\Programs\\Git\\bin\\bash.exe"));
  assert.ok(!shells.bashCandidates("win32", env, "C:\\Windows\\System32\\git.exe", "C:\\Windows\\System32\\bash.exe").some(c => /system32\\bash\.exe$/i.test(c)));
  assert.equal(shells.bashCandidates("win32", env, undefined, "D:\\tools\\bash.exe")[0], "D:\\tools\\bash.exe");
  assert.equal(shells.bashCandidates("linux", {})[0], "/bin/bash");
  const ps = shells.powershellCandidates("win32", env, "C:\\Program Files\\PowerShell\\7\\pwsh.exe");
  assert.equal(ps[0], "C:\\Program Files\\PowerShell\\7\\pwsh.exe");
  assert.equal(ps.at(-1), "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe");
  assert.equal(shells.shellNote("powershell", ps.at(-1), "win32"), "Windows PowerShell 5.1");
  assert.equal(shells.shellNote("powershell", ps[0], "win32"), "PowerShell 7 (pwsh)");
  assert.match(shells.shellNote("bash", undefined, "win32"), /Git for Windows/);

  // The terminal: Git Bash as a login shell that stays in the mission folder; nothing else is passed to the shell.
  assert.deepEqual(shells.terminalLaunch("bash", "C:\\Git\\bin\\bash.exe", "win32"), { shellPath: "C:\\Git\\bin\\bash.exe", shellArgs: ["--login", "-i"], env: { CHERE_INVOKING: "1" } });
  assert.deepEqual(shells.terminalLaunch("powershell", "pwsh", "linux").shellArgs, ["-NoLogo"]);

  // The learner's choice wins when installed; otherwise the first shell found.
  const found = [{ id: "bash", path: undefined }, { id: "powershell", path: "pwsh" }];
  assert.equal(shells.preferredShell(found, "bash"), "powershell");
  assert.equal(shells.preferredShell([{ id: "bash", path: "b" }, { id: "powershell", path: "p" }], "powershell"), "powershell");
  assert.equal(shells.preferredShell([{ id: "bash" }, { id: "powershell" }], undefined), undefined);
  assert.equal(shells.toShellId("zsh"), undefined);

  // Every Terminal Lab mission reads back; no SQL batch; the ticket lives outside the mission folder.
  const packDir = "content/missions/terminal-v1";
  const pack = JSON.parse(await readFile(`${packDir}/pack.json`, "utf8"));
  assert.equal(pack.lab, "terminal");
  assert.equal(pack.missions.length, 8);
  const levels = new Set();
  for (const id of pack.missions) {
    const mission = m.toMissionView(JSON.parse(await readFile(`${packDir}/${id}/mission.json`, "utf8")), "terminal-v1");
    assert.ok(mission && mission.id === id && mission.lab === "terminal", id);
    assert.ok(mission.ticket.body.length > 200 && mission.acceptance.length >= 2 && mission.hints.length >= 3, id);
    assert.deepEqual(mission.batches, [], id);
    assert.equal(m.ticketPath(mission), `.datapass/missions/tickets/${id}.md`);
    const ticket = m.ticketMarkdown(mission);
    assert.match(ticket, /Datapass runs none\s+of your commands and never runs your scripts/);
    assert.doesNotMatch(ticket, /dbt Lab/);
    const entries = await readdir(`${packDir}/${id}`);
    assert.ok(entries.includes("solution") && entries.includes("mutants"), id);
    levels.add(mission.level);
  }
  assert.deepEqual([...levels].sort(), ["advanced", "intermediate", "intro"]);
  // The dbt Lab keeps its TICKET.md in the project.
  assert.equal(m.ticketPath({ id: "sales-board", lab: "dbt" }), "missions/sales-board/TICKET.md");

  // References and mutants never reach the VSIX.
  const vscodeignore = await readFile(".vscodeignore", "utf8");
  assert.match(vscodeignore, /^content\/missions\/\*\/\*\/solution\/\*\*$/m);
  assert.match(vscodeignore, /^content\/missions\/\*\/\*\/mutants\/\*\*$/m);

  // The module is registered with its command.
  const pkg = JSON.parse(await readFile("package.json", "utf8"));
  assert.ok(pkg.contributes.commands.some(c => c.command === "datapass.openTerminalLab"));
  assert.ok(pkg.contributes.configuration.properties["datapass.terminalLab.bashPath"]);

  console.log("Terminal Lab smoke passed.");
} finally {
  await rm(dir, { recursive: true, force: true });
}
