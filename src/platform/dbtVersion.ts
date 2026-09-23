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
