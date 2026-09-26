/**
 * The contract between the extension host and the Workbench webview, one file per lab. Each lab file declares its
 * views, the slice of the runtime state and of the Workbench state it adds, and the messages its surface sends; this
 * file composes them. A new lab adds one file and one line to each composition below.
 */
import type { WorkbenchModule, WorkbenchView } from "../../modules";
import type { AirflowMessage, AirflowRuntimeSlice, AirflowViewSlice } from "./airflow";
import type { BiMessage, BiRuntimeSlice, BiViewSlice } from "./bi";
import type { DbtMessage, DbtViewSlice } from "./dbt";
import type { FabricMessage, FabricRuntimeSlice, FabricViewSlice } from "./fabric";
import type { InfraMessage, InfraViewSlice } from "./infra";
import type { MissionMessage } from "./missions";
import type { MosaicMessage, MosaicRuntimeSlice, MosaicViewSlice } from "./mosaic";
import type { PipelineMessage, PipelineRuntimeSlice, PipelineViewSlice } from "./pipeline";
import type { PracticeMessage, PracticeRuntimeSlice, PracticeViewSlice } from "./practice";
import type { ProjectsMessage, ProjectsViewSlice } from "./projects";
import type { SparkLabMessage, SparkLabRuntimeSlice, SparkLabViewSlice } from "./sparklab";
import type { TerminalMessage, TerminalViewSlice } from "./terminal";
import type { HomeViewSlice, PythonTrustView, WorkbenchFocus, WorkbenchMessage, WorkbenchRuntimeSlice, WorkspaceViewState } from "./workbench";

export * from "./airflow";
export * from "./bi";
export * from "./dbt";
export * from "./fabric";
export * from "./graph";
export * from "./infra";
export * from "./missions";
export * from "./mosaic";
export * from "./pipeline";
export * from "./practice";
export * from "./projects";
export * from "./sparklab";
export * from "./terminal";
export * from "./workbench";

export interface RuntimeViewState
  extends WorkbenchRuntimeSlice,
    MosaicRuntimeSlice,
    SparkLabRuntimeSlice,
    PracticeRuntimeSlice,
    PipelineRuntimeSlice,
    AirflowRuntimeSlice,
    FabricRuntimeSlice,
    BiRuntimeSlice {}

export interface WorkbenchViewState
  extends MosaicViewSlice,
    SparkLabViewSlice,
    PracticeViewSlice,
    PipelineViewSlice,
    AirflowViewSlice,
    FabricViewSlice,
    BiViewSlice,
    DbtViewSlice,
    TerminalViewSlice,
    InfraViewSlice,
    ProjectsViewSlice,
    HomeViewSlice {
  /** "home" (the Today page) or the module shown. */
  selectedModule: WorkbenchView;
  modules: readonly WorkbenchModule[];
  workspace: WorkspaceViewState;
  runtime: RuntimeViewState;
  pythonTrust: PythonTrustView;
  /** A lab tab or Practice filter to show, set when a project step opens a lab; seq changes on each request. */
  focus?: WorkbenchFocus;
}

export type HostToWebviewMessage = {
  type: "state";
  state: WorkbenchViewState;
};

export type WebviewToHostMessage =
  | WorkbenchMessage
  | MosaicMessage
  | SparkLabMessage
  | PracticeMessage
  | PipelineMessage
  | AirflowMessage
  | FabricMessage
  | BiMessage
  | DbtMessage
  | TerminalMessage
  | InfraMessage
  | MissionMessage
  | ProjectsMessage;
