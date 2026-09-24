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
