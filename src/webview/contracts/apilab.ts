import type { MissionListView } from "./missions";

/** One request the simulated API logged (runtime/apilab/server.py); header values are never logged. */
export interface ApiLabRequestView {
  n: number;
  at: string;
  run: number;
  day: number;
  method: string;
  path: string;
  query: Readonly<Record<string, string>>;
  status: number;
  records?: number | null;
  retry_after?: number | null;
  violation?: string | null;
}

/** One run of the learner's ingest.py. */
export interface ApiLabRunView {
  run: number;
  day: number;
  at: string;
  status: "ok" | "error";
  error?: string | null;
  stdout: string;
  tables: readonly { name: string; rows: number; written: number }[];
  requests: number;
  records: number;
  statuses: readonly number[];
}

/** The simulated API of a mission (runtime/apilab/service.py status). */
export interface ApiLabApiView {
  truth: string;
  mission_id: string | null;
  running: boolean;
  base_url?: string | null;
  /** The mission's fictitious API key (never the runtime's token). */
  key?: string;
  day?: number;
  batch?: string | null;
  run?: number;
  runs?: readonly ApiLabRunView[];
  requests?: readonly ApiLabRequestView[];
  request_count?: number;
}

export interface ApiLabViewState {
  missions: MissionListView;
  /** The mission whose API is shown: the last one started or run. */
  active?: string;
  api?: ApiLabApiView;
  apiError?: string;
}

export interface ApiLabViewSlice {
  apilab?: ApiLabViewState;
}

export type ApiLabMessage =
  | { type: "runApiIngestion"; missionId: string }
  | { type: "selectApiMission"; missionId: string }
  | { type: "copyApiKey"; missionId: string }
  | { type: "refreshApiLab" };
