import type { WebviewToHostMessage } from "../webview/contracts";
import { AirflowController } from "./airflow/controller";
import { BiController } from "./bi/controller";
import { DbtController } from "./dbt/controller";
import { FabricController } from "./fabric/controller";
import type { WorkbenchHost } from "./host";
import { InfraController } from "./infra/controller";
import { LakehouseController } from "./lakehouse/controller";
import { MissionsController } from "./missions/controller";
import { MosaicController } from "./mosaic/controller";
import { PipelineController } from "./pipeline/controller";
import { PracticeController } from "./practice/controller";
import { ProjectsController } from "./projects/controller";
import { SparkLabController } from "./sparklab/controller";
import { TerminalController } from "./terminal/controller";
import { WorkbenchController } from "./workbench/controller";

/**
 * One controller per lab (plus the Workbench shell and the shared missions). A lab that needs another lab's action
 * (the retail demo opens the pipeline, Airflow and dbt starters; a project step opens an exercise) gets it here.
 */
export function createLabControllers(host: WorkbenchHost) {
  const pipeline = new PipelineController(host);
  const airflow = new AirflowController(host);
  const dbt = new DbtController(host);
  const terminal = new TerminalController(host);
  const infra = new InfraController(host);
  const practice = new PracticeController(host);
  const fabric = new FabricController(host, {
    openPipelineSource: () => pipeline.openPipelineSource(),
    openAirflowSource: () => airflow.openAirflowSource(),
    createDbtSample: () => dbt.createDbtSample()
  });
  return {
    workbench: new WorkbenchController(host),
    projects: new ProjectsController(host, {
      openExercise: key => practice.openExercise(key),
      writeRetailDemoFiles: () => fabric.writeRetailDemoFiles()
    }),
    mosaic: new MosaicController(host),
    practice,
    fabric,
    bi: new BiController(host),
    sparklab: new SparkLabController(host),
    dbt,
    terminal,
    infra,
    lakehouse: new LakehouseController(host),
    airflow,
    pipeline,
    missions: new MissionsController(host, {
      dbt: dbt.missionHooks,
      terminal: terminal.missionHooks,
      infra: infra.missionHooks
    })
  };
}

export type LabControllers = ReturnType<typeof createLabControllers>;

/** Compile-time check: a webview message type that no controller handles fails the typecheck here. */
type HandledType = { [K in keyof LabControllers]: keyof LabControllers[K]["handlers"] }[keyof LabControllers];
type AssertNever<T extends never> = T;
export type UnhandledMessageTypes = AssertNever<Exclude<WebviewToHostMessage["type"], HandledType>>;
