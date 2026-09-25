/**
 * dbt Lab: the managed dbt tools environment and the real commands typed in the terminal.
 * Pure helpers (no vscode import) so scripts/dbt_lab_smoke.mjs can test them in Node.
 */

/** dbt Core, its DuckDB adapter and dbt Charts; installed only after an explicit Install dbt tools. */
export const DBT_TOOL_REQUIREMENTS = ["dbt-core>=1.10,<1.13", "dbt-duckdb>=1.9,<1.12"] as const;
export const DBT_TOOL_PACKAGES = ["dbt-core", "dbt-duckdb", "duckdb"] as const;

/** Python versions dbt Core supports. */
export const DBT_PYTHON_MIN: readonly [number, number] = [3, 10];
export const DBT_PYTHON_MAX: readonly [number, number] = [3, 13];

export const DBT_COMMANDS = ["build", "run", "test", "seed", "snapshot", "compile", "deps", "docs generate", "debug", "parse"] as const;
export type DbtCommand = typeof DBT_COMMANDS[number];

const SELECTABLE = new Set<DbtCommand>(["build", "run", "test", "seed", "snapshot", "compile", "docs generate"]);
const FULL_REFRESH = new Set<DbtCommand>(["build", "run", "seed"]);
const SELECTOR = /^[A-Za-z0-9_.*+:/@,-]{1,120}$/;

export interface DbtCommandInput {
  command: DbtCommand;
  select?: string;
  exclude?: string;
  fullRefresh?: boolean;
}

export function supportsSelection(command: DbtCommand): boolean {
  return SELECTABLE.has(command);
}

export function supportsFullRefresh(command: DbtCommand): boolean {
  return FULL_REFRESH.has(command);
}

/** Split a selection box ("tag:daily fct_sales+") into dbt selectors; refuse anything that is not one. */
export function parseSelectors(text: string | undefined): string[] {
  const parts = (text ?? "").trim().split(/\s+/).filter(Boolean);
  if (parts.length > 10) throw new Error("Use at most 10 selectors.");
  for (const part of parts) {
    if (!SELECTOR.test(part) || part.startsWith("-")) throw new Error(`${JSON.stringify(part)} is not a dbt selector.`);
  }
  return parts;
}

/**
 * Quote an argument for bash, zsh, PowerShell and cmd alike: plain words stay bare, anything else goes in double
 * quotes (selectors cannot contain quotes, `$` or backticks, so double quotes are inert in every shell).
 */
export function shellArg(value: string): string {
  return /^[A-Za-z0-9_./:=-]+$/.test(value) ? value : `"${value}"`;
}

/** The real dbt command line, as a learner would type it in the project folder. */
export function buildDbtCommand(input: DbtCommandInput): string {
  if (!DBT_COMMANDS.includes(input.command)) throw new Error(`Unknown dbt command ${input.command}.`);
  const parts = ["dbt", ...input.command.split(" ")];
  if (supportsSelection(input.command)) {
    const select = parseSelectors(input.select);
    const exclude = parseSelectors(input.exclude);
    if (select.length) parts.push("--select", ...select.map(shellArg));
    if (exclude.length) parts.push("--exclude", ...exclude.map(shellArg));
  }
  if (input.fullRefresh && supportsFullRefresh(input.command)) parts.push("--full-refresh");
  return parts.join(" ");
}

/** A command line that borrows the catalog file: dbt and dct open the DuckDB file; anything else does not. */
export function isCatalogCommand(commandLine: string): boolean {
  const words = commandLine.trim().replace(/^&\s*/, "").split(/\s+/);
  const tool = /^(dbt|dct)(\.exe)?$/i.exec((words[0] ?? "").replace(/^.*[\\/]/, ""))?.[1]?.toLowerCase();
  if (!tool) return false;
  const verb = (words[1] ?? "").toLowerCase();
  // Commands that never open the database. Releasing for anything else is harmless: it only takes a moment.
  const offline = tool === "dbt"
    ? ["", "--version", "-v", "--help", "-h", "deps", "clean", "init"]
    : ["", "--version", "--help", "-h", "validate", "docs", "examples", "search", "skills", "migrate", "init", "impact"];
  if (tool === "dbt" && verb === "docs") return (words[2] ?? "").toLowerCase() === "generate";
  return !offline.includes(verb);
}

export function parsePythonVersion(output: string): [number, number] | undefined {
  const match = /Python\s+(\d+)\.(\d+)/i.exec(output);
  return match ? [Number(match[1]), Number(match[2])] : undefined;
}

export function isSupportedDbtPython(version: readonly [number, number] | undefined): boolean {
  if (!version) return false;
  const value = version[0] * 100 + version[1];
  return value >= DBT_PYTHON_MIN[0] * 100 + DBT_PYTHON_MIN[1] && value <= DBT_PYTHON_MAX[0] * 100 + DBT_PYTHON_MAX[1];
}

/** Interpreters to try, newest supported first; a configured one comes before all of them. */
export function pythonCandidates(platform: string, configured?: string): Array<{ command: string; args: string[] }> {
  const configuredCandidate = configured?.trim() ? [{ command: configured.trim(), args: [] }] : [];
  const versions = ["3.13", "3.12", "3.11", "3.10"];
  const found = platform === "win32"
    ? [...versions.map(v => ({ command: "py", args: [`-${v}`] })), { command: "python", args: [] }, { command: "python3", args: [] }]
    : [...versions.map(v => ({ command: `python${v}`, args: [] })), { command: "python3", args: [] }, { command: "python", args: [] }];
  return [...configuredCandidate, ...found];
}

/** pip requirements, with DuckDB pinned to the runtime's version so both processes use one storage format. */
export function dbtToolRequirements(runtimeDuckdb?: string, extra: readonly string[] = []): string[] {
  const duckdb = runtimeDuckdb && /^\d+\.\d+\.\d+$/.test(runtimeDuckdb) ? `duckdb==${runtimeDuckdb}` : "duckdb>=1.4";
  return [...DBT_TOOL_REQUIREMENTS, ...extra, duckdb];
}

export function readProfileName(projectYaml: string): string | undefined {
  return /^profile:\s*['"]?([A-Za-z0-9_]+)['"]?\s*(?:#.*)?$/m.exec(projectYaml)?.[1];
}

export function readProjectName(projectYaml: string): string | undefined {
  return /^name:\s*['"]?([A-Za-z0-9_]+)['"]?\s*(?:#.*)?$/m.exec(projectYaml)?.[1];
}

export const DBT_DEV_SCHEMA = "dbt_dev";

/**
 * `.datapass/dbt/profiles.yml`: one DuckDB output per project profile, all on the workspace catalog file.
 * No secrets: a local file path only. Projects whose generate_schema_name uses custom schemas as is land in the
 * catalog layers; the others build into the `dbt_dev` development schema, as a developer's dbt target would.
 */
export function profilesYaml(profiles: readonly string[], databasePath: string): string {
  const path = databasePath.replaceAll("\\", "/").replaceAll("'", "''");
  const unique = [...new Set(profiles)].filter(name => /^[A-Za-z0-9_]+$/.test(name)).sort();
  const lines = [
    "# Generated by Datapass for the dbt Lab. Regenerated when a project is added; do not store secrets here.",
    "# Every profile targets the local workspace catalog (DuckDB), never a cloud warehouse.",
    ""
  ];
  for (const name of unique) {
    lines.push(
      `${name}:`,
      "  target: dev",
      "  outputs:",
      "    dev:",
      "      type: duckdb",
      `      path: '${path}'`,
      `      schema: ${DBT_DEV_SCHEMA}`,
      "      threads: 4",
      ""
    );
  }
  return lines.join("\n");
}

/**
 * Environment of the dbt Lab terminal: the managed tools first on PATH, the generated profiles directory, and no
 * telemetry (nothing leaves the machine). The PATH key keeps the casing the host uses ("Path" on Windows).
 */
export function dbtTerminalEnv(
  base: Readonly<Record<string, string | undefined>>,
  venvBin: string,
  venvRoot: string,
  profilesDir: string,
  delimiter: string
): Record<string, string> {
  const pathKey = Object.keys(base).find(key => key.toUpperCase() === "PATH") ?? "PATH";
  const current = base[pathKey] ?? "";
  return {
    [pathKey]: current ? `${venvBin}${delimiter}${current}` : venvBin,
    VIRTUAL_ENV: venvRoot,
    DBT_PROFILES_DIR: profilesDir,
    DBT_SEND_ANONYMOUS_USAGE_STATS: "false",
    DO_NOT_TRACK: "1"
  };
}
