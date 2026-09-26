import type {
  SparkLabEngine,
  SparkLabPlanNodeView,
  SparkLabRunView,
  SparkLabSimulationView,
  SparkLabStageView
} from "../webview/contracts";

type Raw = Record<string, unknown>;

/**
 * Reduce a runtime `/api/local/execute` SparkLab response to what the webview
 * shows. Per-task arrays and the catalog snapshot are dropped; truth labels are
 * kept verbatim so simulated evidence is never presented as measured.
 */
export function toSparkLabRunView(
  raw: unknown,
  context: { engine: SparkLabEngine; fileName: string; profileId: string; aqe: boolean }
): SparkLabRunView {
  const run = asRecord(raw);
  const error = asRecord(run.error);
  const plan = asRecord(run.polars_plan);
  return {
    status: run.status === "success" ? "success" : "error",
    engine: context.engine,
    fileName: context.fileName,
    profileId: context.profileId,
    aqe: context.aqe,
    elapsed_ms: num(run.elapsed_ms),
    compiledSql: typeof run.compiled_sql === "string" ? run.compiled_sql : undefined,
    result: run.result ? run.result as SparkLabRunView["result"] : undefined,
    error: run.status === "success"
      ? undefined
      : { type: str(error.type, "Error"), message: str(error.message, "SparkLab execution failed.") },
    simulation: run.simulation ? toSimulation(asRecord(run.simulation)) : undefined,
    stdout: typeof run.stdout === "string" && run.stdout ? run.stdout : undefined,
    polarsPlan: typeof plan.text === "string"
      ? { truth: str(plan.truth, "Polars optimized plan (real)"), text: plan.text }
      : undefined
  };
}

function toSimulation(sim: Raw): SparkLabSimulationView {
  if (sim.status !== "modeled") {
    return {
      status: "unavailable",
      reason: str(sim.reason, "Simulation unavailable."),
      stages: [],
      plan: [],
      comparisons: []
    };
  }
  const metrics = asRecord(sim.metrics);
  const credits = asRecord(sim.datapass_credits);
  const assumptions = asRecord(sim.assumptions);
  return {
    status: "modeled",
    truth: str(sim.truth, "Simulated distributed execution"),
    totalDurationS: num(metrics.total_duration_s),
    shuffleGb: num(metrics.shuffle_gb),
    spillGb: num(metrics.spill_gb),
    clusterUtilizationPct: num(metrics.cluster_utilization_pct),
    exchanges: list(asRecord(metrics.plan_facts).exchange_details).map(toExchange),
    credits: {
      total: num(credits.total),
      unit: str(credits.unit, "Datapass Credits"),
      fictional: credits.fictional !== false
    },
    assumptionsKind: typeof assumptions.kind === "string" ? assumptions.kind : undefined,
    calibration: typeof assumptions.calibration === "string" ? assumptions.calibration : undefined,
    stages: list(metrics.stages).map(toStage),
    plan: list(sim.logical_plan).map(toPlanNode),
    comparisons: list(sim.comparisons).map(item => {
      const row = asRecord(item);
      return {
        profile_id: str(row.profile_id, "unknown"),
        aqe: row.aqe === true,
        duration_s: num(row.duration_s),
        credits: num(row.credits)
      };
    })
  };
}

function toStage(item: unknown): SparkLabStageView {
  const stage = asRecord(item);
  return {
    stage_id: num(stage.stage_id),
    name: str(stage.name, "stage"),
    operator: str(stage.operator, "unknown"),
    duration_s: num(stage.duration_s),
    partitions: num(stage.partitions),
    task_count: num(stage.task_count),
    shuffle_read_gb: num(stage.shuffle_read_gb),
    shuffle_write_gb: num(stage.shuffle_write_gb),
    spill_gb: num(stage.spill_gb),
    skewed_tasks: num(stage.skewed_tasks),
    dependencies: list(stage.dependencies).map(num),
    notes: list(stage.notes).filter((note): note is string => typeof note === "string")
  };
}

function toExchange(item: unknown): string {
  const exchange = asRecord(item);
  const keys = list(exchange.keys).filter((key): key is string => typeof key === "string");
  return `${str(exchange.partitioning, "exchange")}${keys.length ? `(${keys.join(", ")})` : ""} for ${str(exchange.reason, "operator")}`;
}

function toPlanNode(item: unknown): SparkLabPlanNodeView {
  const node = asRecord(item);
  return {
    id: num(node.id),
    operation: str(node.operation, "unknown"),
    source: typeof node.source === "string" ? node.source : undefined,
    parents: list(node.parents).map(num),
    dependency: str(node.dependency, "unknown"),
    concept: str(node.concept, "")
  };
}

function asRecord(value: unknown): Raw {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Raw : {};
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function num(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function str(value: unknown, fallback: string): string {
  return typeof value === "string" && value ? value : fallback;
}
