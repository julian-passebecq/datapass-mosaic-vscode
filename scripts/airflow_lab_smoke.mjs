import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import * as esbuild from "esbuild";

const dir = await mkdtemp(path.join(tmpdir(), "datapass-airflow-"));

try {
  const outfile = path.join(dir, "airflow-run.mjs");
  await esbuild.build({
    entryPoints: ["src/platform/airflowRun.ts"],
    bundle: true,
    platform: "node",
    format: "esm",
    target: "node20",
    outfile,
    logLevel: "silent"
  });
  const airflow = await import(pathToFileURL(outfile).href);

  // Scenario form -> runtime scenario: datetime-local inputs are UTC; behaviors map to try numbers.
  assert.equal(airflow.utcInput("2026-03-05T12:00"), "2026-03-05T12:00:00Z");
  assert.equal(airflow.utcInput("  "), undefined);
  const scenario = airflow.toRuntimeScenario({
    now: "2026-03-05T12:00",
    manualRunAt: "2026-03-05T09:15",
    tasks: {
      extract: { behavior: "fail_twice", durationSeconds: 30 },
      load: { behavior: "fail_always" },
      wait: { behavior: "success", sensorArrivalMinutes: 50 },
      never: { behavior: "success", sensorArrivalMinutes: null },
      pick: { behavior: "success", branch: ["b"] },
      plain: { behavior: "success" }
    }
  });
  assert.deepEqual(scenario, {
    now: "2026-03-05T12:00:00Z",
    manual_runs: ["2026-03-05T09:15:00Z"],
    tasks: {
      extract: { fail_attempts: [1, 2], duration_seconds: 30 },
      load: { fail_attempts: "all" },
      wait: { sensor_true_after_seconds: 3000 },
      never: { sensor_true_after_seconds: null },
      pick: { branch: ["b"] },
      plain: {}
    }
  });

  // Runtime view -> webview view keeps truth labels and camel-cases the payload.
  const view = airflow.toAirflowLabView({
    status: "simulated",
    truth: "Simulated Airflow 3 semantics; the DAG file is parsed, never executed.",
    now: "2026-03-05T12:00:00+00:00",
    dag: {
      dag_id: "retail_daily",
      schedule: { kind: "cron_trigger", label: "'@daily'", note: "CronTriggerTimetable" },
      start_date: "2026-03-01T00:00:00+00:00",
      catchup: false,
      tasks: [{ task_id: "wait", operator: "FileSensor", kind: "sensor", line: 9, trigger_rule: "all_success",
                retries: 0, retry_delay_s: 300, upstream: [], downstream: ["load"], templated_fields: ["filepath"],
                sensor: { poke_interval_s: 300, timeout_s: 3600, mode: "reschedule", soft_fail: true } }],
      edges: [{ upstream: "wait", downstream: "load" }]
    },
    total_runs: 1,
    runs: [{
      run_id: "scheduled__2026-03-05T00:00:00+00:00", run_type: "scheduled",
      logical_date: "2026-03-05T00:00:00+00:00", run_after: "2026-03-05T00:00:00+00:00",
      data_interval_start: "2026-03-05T00:00:00+00:00", data_interval_end: "2026-03-05T00:00:00+00:00",
      state: "success", duration_s: 60,
      instances: [{ task_id: "wait", state: "success", try_number: 1, start_s: 0, end_s: 0 },
                  { task_id: "load", state: "skipped", try_number: 0, start_s: null, end_s: 0 }],
      events: [{ t: 0, task_id: "wait", state: "running", try_number: 1, message: "sensor started" }],
      rendered: [{ task_id: "wait", field: "filepath", value: "/in/2026-03-05.csv" }],
      render_error: null
    }]
  }, "airflow/dags/retail_daily.py", { tasks: {} });
  assert.equal(view.status, "simulated");
  assert.match(view.truth, /never executed/);
  assert.equal(view.dag.dagId, "retail_daily");
  assert.deepEqual(view.dag.tasks[0].sensor, { pokeIntervalS: 300, timeoutS: 3600, mode: "reschedule", softFail: true });
  assert.equal(view.runs[0].instances[1].startS, undefined, "null start stays undefined, never 0");
  assert.equal(view.runs[0].events[0].state, "running");
  assert.equal(view.runs[0].renderError, undefined);

  const invalid = airflow.toAirflowLabView({ status: "invalid", error: { message: "line 2: Unsupported import", line: 2 } },
    "broken.py", { tasks: {} });
  assert.equal(invalid.status, "invalid");
  assert.deepEqual(invalid.error, { message: "line 2: Unsupported import", line: 2 });
  assert.equal(invalid.dag, undefined);
  assert.deepEqual(invalid.runs, []);

  console.log("Airflow Lab view contract smoke passed.");
} finally {
  await rm(dir, { recursive: true, force: true });
}
