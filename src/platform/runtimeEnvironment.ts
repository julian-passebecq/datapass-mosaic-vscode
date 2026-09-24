import * as path from "node:path";

export function managedVenvPython(
  venvRoot: string,
  platform: NodeJS.Platform = process.platform
): string {
  return platform === "win32"
    ? path.join(venvRoot, "Scripts", "python.exe")
    : path.join(venvRoot, "bin", "python");
}

export function runtimeInstallArgs(runtimeRoot: string): string[] {
  return [
    "-m",
    "pip",
    "install",
    "--disable-pip-version-check",
    "--upgrade",
    runtimeRoot
  ];
}

/**
 * Turn one line of pip/venv output into a short progress message, or undefined
 * for noise. pip prints nothing while it unpacks wheels, so the last message can
 * stay unchanged for minutes on a slow disk.
 */
export function describeSetupOutputLine(line: string): string | undefined {
  const text = line.trim();
  let match = /^Collecting\s+([A-Za-z0-9_.\-]+)/.exec(text);
  if (match) return `Resolving ${match[1]}`;
  match = /^Downloading\s+(?:\S*\/)?([A-Za-z0-9_.\-]+?)(?:-\d[^\s]*)?\.(?:whl|tar\.gz|zip)\s*(\([^)]*\))?/.exec(text);
  if (match) return `Downloading ${match[1]}${match[2] ? ` ${match[2]}` : ""}`;
  match = /^Building wheels? for\s+([A-Za-z0-9_.\-]+)/.exec(text);
  if (match) return `Building ${match[1]}`;
  if (text.startsWith("Installing collected packages:")) return "Installing packages (unpacking can take several minutes)";
  if (text.startsWith("Successfully installed")) return "Packages installed";
  return undefined;
}

export function runtimeVerifyArgs(): string[] {
  return [
    "-c",
    [
      "import fastapi, uvicorn, duckdb, polars, pandas",
      "import datapass_runtime",
      "print('Datapass runtime environment ready')"
    ].join("; ")
  ];
}
