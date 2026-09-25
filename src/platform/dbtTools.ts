/**
 * dbt Lab: the managed dbt tools environment and the real commands typed in the terminal.
 * Pure helpers (no vscode import) so scripts/dbt_lab_smoke.mjs can test them in Node.
 */

/** dbt Core, its DuckDB adapter and dbt Charts (dct, pre-1.0: pinned to a minor); installed only on request. */
export const DBT_TOOL_REQUIREMENTS = ["dbt-core>=1.10,<1.13", "dbt-duckdb>=1.9,<1.12", "dbt-charts>=0.8,<0.9"] as const;
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

// ---- dbt Charts (dct) -------------------------------------------------------------------------------------------

export const DCT_FORMATS = ["png", "html", "json", "svg"] as const;
export type DctFormat = typeof DCT_FORMATS[number];

export type DctCommandInput =
  | { action: "validate"; board?: string }
  | { action: "render"; board: string; format: DctFormat }
  | { action: "serve"; port: number };

/** A board file relative to the project: `charts/sales.yml`. */
export function isBoardPath(value: string): boolean {
  return /^[A-Za-z0-9_][A-Za-z0-9_./-]{0,200}\.ya?ml$/.test(value) && !value.split("/").some(part => part === ".." || part === ".");
}

/** Where `dct render` writes a board by default (`renders/<stem>.<ext>`), used for JSON too so the lab can read it. */
export function renderPath(board: string, format: DctFormat): string {
  const stem = board.split("/").at(-1)!.replace(/\.ya?ml$/, "");
  return `renders/${stem}.${format}`;
}

/** The real dct command line, as a learner would type it in the project folder. */
export function buildDctCommand(input: DctCommandInput): string {
  if (input.action === "serve") {
    if (!Number.isInteger(input.port) || input.port < 1024 || input.port > 65535) throw new Error("Pick a port between 1024 and 65535.");
    // Loopback only: the preview server is never reachable from another machine.
    return `dct serve --host 127.0.0.1 --port ${input.port}`;
  }
  if (input.board !== undefined && !isBoardPath(input.board)) throw new Error(`${JSON.stringify(input.board)} is not a board file.`);
  if (input.action === "validate") return input.board ? `dct validate ${input.board}` : "dct validate";
  if (!DCT_FORMATS.includes(input.format)) throw new Error(`Unknown dct format ${input.format}.`);
  const parts = ["dct", "render", input.board, "--format", input.format];
  // JSON goes to stdout by default; write it next to the other renders so the lab can show the data.
  if (input.format === "json") parts.push("--output", renderPath(input.board, "json"));
  return parts.join(" ");
}

export interface DctIssueView {
  code: string;
  message: string;
  line?: number;
}

export interface DctValidationView {
  board: string;
  success: boolean;
  errors: DctIssueView[];
  warnings: DctIssueView[];
  checkedAt: string;
}

/** `dct validate --json` output (one object, or a list for several boards) for one board. */
export function toDctValidation(raw: unknown, board: string, checkedAt: string): DctValidationView {
  const list = Array.isArray(raw) ? raw : [raw];
  const entry = list.map(record).find(item => item && (item.path === board || list.length === 1)) ?? {};
  const issues = (value: unknown): DctIssueView[] => (Array.isArray(value) ? value : []).flatMap(item => {
    const issue = record(item);
    if (!issue) return [];
    const range = record(issue.range);
    return [{
      code: typeof issue.code === "string" ? issue.code : "",
      message: typeof issue.message === "string" ? issue.message : String(item),
      line: typeof range?.start_line === "number" ? range.start_line : undefined
    }];
  });
  const errors = issues(entry.errors);
  return { board, success: entry.success === true && errors.length === 0, errors, warnings: issues(entry.warnings), checkedAt };
}

export interface DctChartView {
  id: string;
  title: string;
  type: string;
  x?: string;
  y?: string;
  columns: string[];
  rows: Array<Record<string, string | number | boolean | null>>;
  totalRows: number;
}

export interface DctRenderView {
  title?: string;
  charts: DctChartView[];
  warnings: string[];
}

/** `dct render --format json`: the resolved board, with each chart's data. */
export function toDctRender(raw: unknown, maxRows = 50): DctRenderView {
  const board = record(raw);
  if (!board || !Array.isArray(board.items)) throw new Error("Not a dct JSON render.");
  const charts: DctChartView[] = [];
  const walk = (items: unknown[]) => {
    for (const value of items) {
      const item = record(value);
      if (!item) continue;
      if (Array.isArray(item.items)) walk(item.items);
      const chart = record(item.chart);
      if (item.type !== "chart" || !chart) continue;
      const data = (Array.isArray(item.data) ? item.data : []).map(row => record(row) ?? {});
      const columns = [...new Set(data.flatMap(row => Object.keys(row)))];
      charts.push({
        id: typeof chart.id === "string" ? chart.id : `chart ${charts.length + 1}`,
        title: typeof chart.title === "string" ? chart.title : "",
        type: typeof chart.chart_type === "string" ? chart.chart_type : "chart",
        x: typeof chart.x === "string" ? chart.x : undefined,
        y: typeof chart.y === "string" ? chart.y : undefined,
        columns,
        rows: data.slice(0, maxRows).map(row => Object.fromEntries(columns.map(column => [column, scalar(row[column])]))),
        totalRows: data.length
      });
    }
  };
  walk(board.items);
  const warnings = (Array.isArray(board.warnings) ? board.warnings : [])
    .flatMap(item => { const w = record(item); return w && typeof w.code === "string" ? [w.code] : []; });
  return { title: typeof board.title === "string" ? board.title : undefined, charts, warnings };
}

function record(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
}

function scalar(value: unknown): string | number | boolean | null {
  return value === null || ["string", "number", "boolean"].includes(typeof value) ? value as string | number | boolean | null : JSON.stringify(value);
}
