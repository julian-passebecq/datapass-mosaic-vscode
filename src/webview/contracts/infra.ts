import type { MissionListView } from "./missions";


/** The simulated world of an Infra Lab folder (runtime/infralab/shell.py state_view). */
export interface InfraWorldView {
  clock: string;
  simulated: string;
  terraform: { initialized: boolean; configured?: boolean; resources: readonly string[]; outputs: Readonly<Record<string, string | number | boolean>> };
  azure: {
    resources: readonly { name: string; type: string; group: string; managed_by?: string | null }[];
    alerts: readonly { name: string; severity: number; metric: string; enabled: boolean; actions: number }[];
  };
  docker: {
    images: readonly { tags: readonly string[]; size_mb: number; user?: string }[];
    containers: readonly { name: string; image: string; status: string; health?: string | null; ports: readonly (readonly number[])[] }[];
  };
  kube: {
    nodes: number;
    deployments: readonly {
      name: string; namespace: string; image: string; replicas: number; ready: number; strategy: string;
      last_rollout?: { revision: number; complete: boolean; min_available?: number | null; to_image?: string } | null;
    }[];
    services: readonly { name: string; namespace: string; endpoints: number }[];
  };
  journal: readonly { n?: number; line: string; exit_code: number; at?: string }[];
}

export interface InfraViewState {
  /** The folder whose simulated world is shown (relative to the workspace), and the started missions to pick from. */
  folder?: string;
  folders: readonly string[];
  world?: InfraWorldView;
  worldError?: string;
  missions: MissionListView;
}

export interface InfraViewSlice {
  infra?: InfraViewState;
}

export type InfraMessage =
  | { type: "openInfraTerminal"; missionId?: string }
  | { type: "selectInfraFolder"; folder: string }
  | { type: "refreshInfraLab" };
