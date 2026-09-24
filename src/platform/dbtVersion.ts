export interface ParsedDbtVersion {
  coreVersion?: string;
  duckdbAdapterVersion?: string;
}

export function parseDbtVersionOutput(output: string): ParsedDbtVersion {
  const normalized = output.replaceAll("\r\n", "\n");
  const coreSection = /(?:^|\n)Core:\s*\n([\s\S]*?)(?=\n\S|$)/i.exec(normalized)?.[1] ?? normalized;
  const coreVersion =
    /installed:\s*v?([^\s]+)/i.exec(coreSection)?.[1] ??
    /dbt(?:\s+Core)?\s+v?([0-9]+\.[0-9]+(?:\.[0-9]+)?[^\s]*)/i.exec(normalized)?.[1];
  const duckdbAdapterVersion =
    /(?:^|\n)\s*-\s*duckdb:\s*v?([^\s]+)/im.exec(normalized)?.[1] ??
    /duckdb\s+(?:adapter\s+)?v?([0-9]+\.[0-9]+(?:\.[0-9]+)?[^\s]*)/i.exec(normalized)?.[1];

  return {
    coreVersion: clean(coreVersion),
    duckdbAdapterVersion: clean(duckdbAdapterVersion)
  };
}

function clean(value: string | undefined): string | undefined {
  if (!value) return undefined;
  const trimmed = value.trim().replace(/[;,]$/, "");
  return trimmed || undefined;
}

/**
 * One readable line from a failed `dbt --version` probe. A broken dbt install
 * prints a full Python traceback; its last line carries the actual cause.
 */
export function summarizeProbeError(error: string | undefined): string | undefined {
  if (!error) return undefined;
  const lines = error.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  const last = lines.at(-1) ?? error.trim();
  const summary = lines.length > 1 && /^Command failed/i.test(lines[0]) ? `${lines[0]}: ${last}` : last;
  return summary.length > 240 ? summary.slice(0, 237) + "..." : summary;
}
