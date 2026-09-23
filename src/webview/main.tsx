import { createRoot } from "react-dom/client";
import { WorkbenchApp, type VsCodeApi } from "./WorkbenchApp";
import "./workbench.css";

declare function acquireVsCodeApi(): VsCodeApi;

const root = document.getElementById("root");
if (!root) throw new Error("Datapass webview root was not found.");

const vscode = acquireVsCodeApi();
createRoot(root).render(<WorkbenchApp vscode={vscode} />);
