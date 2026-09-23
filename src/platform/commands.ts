import * as path from "node:path";

export function quoteShellArg(value: string, platform: NodeJS.Platform = process.platform): string {
  if (/\r|\n|\0/.test(value)) throw new Error("Command argument contains unsupported control characters.");
  if (platform === "win32") return `"${value.replace(/"/g, '""')}"`;
  return `'${value.replace(/'/g, `'"'"'`)}'`;
}

export function buildDatabricksBundleCommand(
  operation: "validate" | "deploy" | "run",
  projectRoot: string,
  target?: string,
  platform: NodeJS.Platform = process.platform
): string {
  const prefix = `cd ${quoteShellArg(path.resolve(projectRoot), platform)}`;
  if (operation === "run") {
    if (!target?.trim()) throw new Error("A Databricks bundle run target is required.");
    return `${prefix} && databricks bundle run ${quoteShellArg(target.trim(), platform)}`;
  }
  return `${prefix} && databricks bundle ${operation}`;
}

export function buildGrafanaPreviewCommand(
  generatorCommand: string,
  watchPath?: string,
  platform: NodeJS.Platform = process.platform
): string {
  const generator = generatorCommand.trim();
  if (!generator) throw new Error("Configure datapass.grafana.generatorCommand first.");
  if (/\r|\n|\0/.test(generator)) throw new Error("Generator command contains unsupported control characters.");
  const watch = watchPath?.trim();
  return [
    "gcx dev serve",
    "--script",
    quoteShellArg(generator, platform),
    watch ? `--watch ${quoteShellArg(watch, platform)}` : ""
  ].filter(Boolean).join(" ");
}

export function buildIaCCommand(
  tool: "tofu" | "terraform",
  operation: "validate" | "plan",
  root: string,
  platform: NodeJS.Platform = process.platform
): string {
  return `cd ${quoteShellArg(path.resolve(root), platform)} && ${tool} ${operation}`;
}
export function quotePowerShellArg(value: string): string {
  if (/\r|\n|\0/.test(value)) throw new Error("PowerShell argument contains unsupported control characters.");
  return `'${value.replace(/'/g, "''")}'`;
}

export function buildFabricSecurityAuditCommand(scriptPath: string, url: string, user?: string): string {
  const cleanUrl = url.trim();
  if (!/^https:\/\//i.test(cleanUrl)) {
    throw new Error("Fabric Security Audit requires a full https:// Fabric or Power BI URL.");
  }
  const parts = [
    "&",
    quotePowerShellArg(scriptPath),
    "-Url",
    quotePowerShellArg(cleanUrl),
    "-NoPrompt"
  ];
  const cleanUser = user?.trim();
  if (cleanUser) parts.push("-User", quotePowerShellArg(cleanUser));
  return parts.join(" ");
}
