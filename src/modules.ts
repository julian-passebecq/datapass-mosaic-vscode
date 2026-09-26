import registry from "../content/modules.json";

export type ModuleId = "projects" | "mosaic" | "practice" | "fabric" | "bi" | "sparklab" | "dbt" | "terminal" | "infra" | "lakehouse" | "airflow" | "pipeline";
export type ExecutionMode = "real" | "simulated" | "hybrid";
/** "learn": guided labs and simulators; "work": projects and ticket-style missions (see content/modules.json). */
export type ModuleFamilyId = "learn" | "work";
/** What the Workbench shows: the Today home or one module. */
export type WorkbenchView = "home" | ModuleId;

export interface ModuleFamily {
  id: ModuleFamilyId;
  label: string;
  description: string;
}

export interface WorkbenchModule {
  id: ModuleId;
  family: ModuleFamilyId;
  label: string;
  description: string;
  command: string;
  execution: string;
  mode: ExecutionMode;
  /** A VS Code codicon name, for the Labs view. */
  icon: string;
  highlights: readonly string[];
}

/** The registry lives in content/modules.json; one entry there (plus its surface) registers a new lab. */
export const MODULE_FAMILIES: readonly ModuleFamily[] = registry.families as ModuleFamily[];
export const MODULES: readonly WorkbenchModule[] = registry.modules as WorkbenchModule[];

export function getModule(id: ModuleId): WorkbenchModule {
  const found = MODULES.find(module => module.id === id);
  if (!found) throw new Error(`Unknown Datapass module: ${id}`);
  return found;
}

export function familyModules(family: ModuleFamilyId): WorkbenchModule[] {
  return MODULES.filter(module => module.family === family);
}
