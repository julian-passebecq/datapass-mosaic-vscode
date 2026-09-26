import type { LocalCellRunView } from "./mosaic";

export interface SparkLabStageView {
  stage_id: number;
  name: string;
  operator: string;
  duration_s: number;
  partitions: number;
  task_count: number;
  shuffle_read_gb: number;
  shuffle_write_gb: number;
  spill_gb: number;
  skewed_tasks: number;
  dependencies: readonly number[];
  notes: readonly string[];
}

export interface SparkLabPlanNodeView {
  id: number;
  operation: string;
  source?: string;
  parents: readonly number[];
  dependency: string;
  concept: string;
}

export interface SparkLabSimulationView {
  status: "modeled" | "unavailable";
  truth?: string;
  reason?: string;
  totalDurationS?: number;
  shuffleGb?: number;
  spillGb?: number;
  clusterUtilizationPct?: number;
  /** Modeled shuffle exchanges (Spark planning rules over assumed sizes), with the reason for each. */
  exchanges?: readonly string[];
  credits?: { total: number; unit: string; fictional: boolean };
  assumptionsKind?: string;
  calibration?: string;
  stages: readonly SparkLabStageView[];
  plan: readonly SparkLabPlanNodeView[];
  comparisons: readonly { profile_id: string; aqe: boolean; duration_s: number; credits: number }[];
}

export interface SparkLabRunView {
  status: "success" | "error";
  fileName: string;
  profileId: string;
  aqe: boolean;
  elapsed_ms: number;
  compiledSql?: string;
  result?: LocalCellRunView["result"];
  error?: { type: string; message: string };
  simulation?: SparkLabSimulationView;
}

export interface SparkLabProfileView {
  id: string;
  label: string;
}

export interface SparkLabRuntimeSlice {
  sparkRun?: SparkLabRunView;
}

export interface SparkLabViewSlice {
  sparkProfiles?: readonly SparkLabProfileView[];
}

export type SparkLabMessage = { type: "runActiveSparkLab"; profileId: string; aqe: boolean };
