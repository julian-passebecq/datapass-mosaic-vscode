import type { StatusLevel, ToolProbe } from "./types";

export function deriveStatus(tools: ToolProbe[], configured = false): StatusLevel {
  if (tools.length === 0) return configured ? "partial" : "unbound";
  const available = tools.filter(tool => tool.available).length;
  if (available === tools.length && configured) return "ready";
  if (available > 0) return "partial";
  return configured ? "partial" : "missing";
}

export function statusLabel(status: StatusLevel): string {
  switch (status) {
    case "ready": return "Ready";
    case "partial": return "Partial";
    case "missing": return "Missing";
    case "unbound": return "Unbound";
    case "error": return "Error";
  }
}
