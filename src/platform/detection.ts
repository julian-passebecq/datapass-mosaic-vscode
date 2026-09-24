import { execFile } from "node:child_process";
import type { ToolProbe } from "./types";

export interface CliSpec {
  id: string;
  label: string;
  command: string;
  args?: string[];
}

export interface ProbeResult {
  ok: boolean;
  output?: string;
  error?: string;
}

export type ProbeRunner = (command: string, args: string[], timeoutMs: number) => Promise<ProbeResult>;

export const defaultProbeRunner: ProbeRunner = async (command, args, timeoutMs) =>
  new Promise(resolve => {
    execFile(command, args, { timeout: timeoutMs, windowsHide: true }, (error, stdout, stderr) => {
      if (error) {
        resolve({ ok: false, error: String(error.message || error) });
        return;
      }
      const output = String(stdout || stderr || "").trim();
      resolve({ ok: true, output });
    });
  });

export async function detectCli(
  spec: CliSpec,
  runner: ProbeRunner = defaultProbeRunner,
  timeoutMs = 1800
): Promise<ToolProbe> {
  const result = await runner(spec.command, spec.args ?? ["--version"], timeoutMs);
  return {
    id: spec.id,
    label: spec.label,
    available: result.ok,
    version: result.ok ? firstLine(result.output) : undefined,
    detail: result.ok ? undefined : result.error
  };
}

export async function detectManyCli(specs: CliSpec[], runner: ProbeRunner = defaultProbeRunner): Promise<ToolProbe[]> {
  return Promise.all(specs.map(spec => detectCli(spec, runner)));
}

function firstLine(value?: string): string | undefined {
  if (!value) return undefined;
  const line = value.split(/\r?\n/, 1)[0]?.trim();
  return line || undefined;
}
