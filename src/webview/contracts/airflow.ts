/** Airflow Lab project files: DAGs are Python files under <assets.airflow>/dags. */
export interface AirflowViewState {
  dagsFolder: string;
  starterPath: string;
  starterExists: boolean;
  /** Pre-simulator JSON spec (airflow/main.dag.json), no longer simulated. */
  legacySpecPath?: string;
}

export type AirflowTaskBehavior = "success" | "fail_once" | "fail_twice" | "fail_always";

/** What the learner chooses in the Airflow Lab scenario form. Times are UTC, "YYYY-MM-DDTHH:MM". */
export interface AirflowTaskScenarioInput {
  behavior: AirflowTaskBehavior;
  durationSeconds?: number;
  /** Sensors: minutes after the sensor starts when its file/condition appears; null = never. */
  sensorArrivalMinutes?: number | null;
  /** Branch tasks: the task ids it chooses. Omitted: its literal return value, if any. */
  branch?: string[];
}

export interface AirflowScenarioInput {
  now?: string;
  unpausedAt?: string;
  manualRunAt?: string;
  tasks: Record<string, AirflowTaskScenarioInput>;
}

export interface AirflowLabTaskView {
  taskId: string;
  operator: string;
  kind: string;
  line: number;
  triggerRule: string;
  retries: number;
  retryDelayS: number;
  upstream: string[];
  downstream: string[];
  templatedFields: string[];
  staticBranch?: string[];
  sensor?: { pokeIntervalS: number; timeoutS: number; mode: string; softFail: boolean };
}

export interface AirflowLabInstanceView {
  taskId: string;
  state: string;
  tryNumber: number;
  startS?: number;
  endS?: number;
}

export interface AirflowLabEventView {
  t: number;
  taskId: string;
  state: string;
  tryNumber: number;
  message: string;
}

export interface AirflowLabRunView {
  runId: string;
  runType: string;
  logicalDate: string;
  runAfter: string;
  dataIntervalStart: string;
  dataIntervalEnd: string;
  state: string;
  durationS: number;
  instances: AirflowLabInstanceView[];
  events: AirflowLabEventView[];
  rendered: { taskId: string; field: string; value: string }[];
  renderError?: string;
}

/** Runtime simulation of one DAG file: parsed, never executed. */
export interface AirflowLabView {
  fileName: string;
  status: "simulated" | "invalid" | "simulation_error";
  truth: string;
  error?: { message: string; line?: number };
  now?: string;
  unpausedAt?: string;
  dag?: {
    dagId: string;
    schedule: { kind: string; label: string; note: string };
    startDate?: string;
    endDate?: string;
    catchup: boolean;
    tasks: AirflowLabTaskView[];
    edges: { upstream: string; downstream: string }[];
  };
  totalRuns: number;
  runs: AirflowLabRunView[];
  scenario: AirflowScenarioInput;
}

export interface AirflowRuntimeSlice {
  airflowRun?: AirflowLabView;
}

export interface AirflowViewSlice {
  airflow?: AirflowViewState;
}

export type AirflowMessage =
  | { type: "openAirflowSource" }
  | { type: "refreshAirflow" }
  | { type: "simulateAirflow"; scenario: AirflowScenarioInput }
  | { type: "revealAirflowLine"; line: number };
