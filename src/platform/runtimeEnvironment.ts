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

/** The runtime's distribution name (runtime/pyproject.toml). */
const RUNTIME_DISTRIBUTION = "datapass-runtime";

/**
 * Where to look for uv, in order: PATH, then the folders its installers use
 * (the standalone installer and pipx put it in ~/.local/bin, cargo in ~/.cargo/bin).
 */
export function uvCandidates(home: string, platform: NodeJS.Platform = process.platform): string[] {
  const exe = platform === "win32" ? "uv.exe" : "uv";
  return ["uv", path.join(home, ".local", "bin", exe), path.join(home, ".cargo", "bin", exe)];
}

/**
 * Create the managed venv with uv from the same base interpreter `python -m venv` would use (an absolute path,
 * so uv never picks or downloads another Python). --seed installs pip, which keeps the pip fallback working.
 */
export function uvVenvArgs(basePython: string, venvRoot: string): string[] {
  return ["venv", "--seed", "--python", basePython, venvRoot];
}

/** Prints the absolute path of the interpreter a command such as `python` runs. */
export function pythonExecutableArgs(): string[] {
  return ["-c", "import sys; print(sys.executable)"];
}

/**
 * The same install as runtimeInstallArgs, done by uv into the managed venv. The runtime keeps its
 * version number between extension releases, so its own package is always rebuilt (--refresh-package)
 * and reinstalled (--reinstall-package); dependencies come from uv's cache when they can.
 */
export function uvInstallArgs(managedPython: string, runtimeRoot: string): string[] {
  return [
    "pip",
    "install",
    "--python",
    managedPython,
    "--upgrade",
    "--refresh-package",
    RUNTIME_DISTRIBUTION,
    "--reinstall-package",
    RUNTIME_DISTRIBUTION,
    runtimeRoot
  ];
}

/**
 * Turn one line of pip/uv/venv output into a short progress message, or undefined
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
  // uv
  match = /^Resolved\s+(\d+)\s+packages?/.exec(text);
  if (match) return `Resolved ${match[1]} packages`;
  match = /^Downloading\s+([A-Za-z0-9_.\-]+)\s+\(([^)]+)\)$/.exec(text);
  if (match) return `Downloading ${match[1]} (${match[2]})`;
  match = /^Building\s+([A-Za-z0-9_.\-]+)\s+@/.exec(text);
  if (match) return `Building ${match[1]}`;
  match = /^Prepared\s+(\d+)\s+packages?/.exec(text);
  if (match) return `Prepared ${match[1]} packages`;
  if (/^Installed\s+\d+\s+packages?/.test(text)) return "Packages installed";
  return undefined;
}

export function runtimeVerifyArgs(): string[] {
  return [
    "-c",
    [
      "import fastapi, uvicorn, duckdb, polars, pandas",
      "import datapass_runtime",
      // The Lakehouse Lab's DuckLake missions: install DuckDB's ducklake extension now, while Setup may use the
      // network; offline it says so and Setup still succeeds (the lab only ever LOADs it afterwards).
      "from lakehouselab.extensions import setup_install",
      "setup_install()",
      "print('Datapass runtime environment ready')"
    ].join("; ")
  ];
}
