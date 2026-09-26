import { AirflowClient } from "./airflow/client";
import { BiClient } from "./bi/client";
import { FabricClient } from "./fabric/client";
import { InfraClient } from "./infra/client";
import { MissionsClient } from "./missions/client";
import { MosaicClient } from "./mosaic/client";
import { PipelineClient } from "./pipeline/client";
import { PracticeClient } from "./practice/client";
import { ProjectsClient } from "./projects/client";
import type { RuntimeConnection } from "./runtimeConnection";
import { SparkLabClient } from "./sparklab/client";

/**
 * One runtime client per lab, all on the RuntimeManager's connection (`runtimeManager.labs.<lab>`). The dbt Lab and
 * the Terminal Lab have none: their commands run in the learner's terminal, and their missions use `missions`.
 */
export function createLabClients(connection: RuntimeConnection) {
  return {
    mosaic: new MosaicClient(connection),
    sparklab: new SparkLabClient(connection),
    practice: new PracticeClient(connection),
    pipeline: new PipelineClient(connection),
    airflow: new AirflowClient(connection),
    fabric: new FabricClient(connection),
    bi: new BiClient(connection),
    infra: new InfraClient(connection),
    missions: new MissionsClient(connection),
    projects: new ProjectsClient(connection)
  };
}

export type LabClients = ReturnType<typeof createLabClients>;
