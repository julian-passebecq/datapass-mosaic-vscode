import * as vscode from "vscode";
import { resolvePythonTrust, type PythonTrustResolution } from "./platform/pythonTrust";
import {
  createDefaultProjectManifest,
  readProjectManifest,
  withTrustedLocalPython,
  writeProjectManifest
} from "./project/projectManifest";

/** Per-machine confirmation. workspaceState is already scoped to this workspace. */
export const ACKNOWLEDGED_KEY = "datapass.trustedLocalPython.acknowledged";

export class PythonTrustController {
  constructor(private readonly context: Pick<vscode.ExtensionContext, "workspaceState">) {}

  async resolve(): Promise<PythonTrustResolution> {
    const manifest = await readProjectManifest();
    return resolvePythonTrust({
      manifestOptIn: manifest.manifest?.runtime?.trustedLocalPython === true,
      acknowledged: this.context.workspaceState.get<boolean>(ACKNOWLEDGED_KEY) === true,
      workspaceTrusted: vscode.workspace.isTrusted
    });
  }

  /** Returns true when the effective trust setting changed. */
  async enable(): Promise<boolean> {
    const folder = vscode.workspace.workspaceFolders?.[0];
    if (!folder) {
      void vscode.window.showWarningMessage("Open a workspace folder before enabling trusted local Python.");
      return false;
    }
    if (!vscode.workspace.isTrusted) {
      const manage = "Manage Workspace Trust";
      const choice = await vscode.window.showWarningMessage(
        "Trusted local Python requires VS Code Workspace Trust for this folder.",
        manage
      );
      if (choice === manage) await vscode.commands.executeCommand("workbench.trust.manage");
      return false;
    }

    const current = await readProjectManifest();
    if (current.exists && !current.manifest) {
      void vscode.window.showErrorMessage(
        `Fix .datapass/project.json before changing trusted Python: ${current.errors.join(" ")}`
      );
      return false;
    }

    const confirm = "Enable trusted local Python";
    const choice = await vscode.window.showWarningMessage(
      "Enable trusted local Python for this workspace?",
      {
        modal: true,
        detail: [
          "Datapass will run Python and Polars files from this workspace as real local code with your user permissions: file system, network and installed packages.",
          "The runtime worker is a separate process for lifecycle management only. It is NOT a security sandbox.",
          "Only enable this for code you wrote or have reviewed. SQL and bounded SparkLab do not need it.",
          "",
          "This sets runtime.trustedLocalPython in .datapass/project.json and records your confirmation on this machine."
        ].join("\n")
      },
      confirm
    );
    if (choice !== confirm) return false;

    const before = await this.resolve();
    const manifest = current.manifest ?? createDefaultProjectManifest(folder.name);
    if (manifest.runtime?.trustedLocalPython !== true) {
      await writeProjectManifest(withTrustedLocalPython(manifest, true));
    }
    await this.context.workspaceState.update(ACKNOWLEDGED_KEY, true);
    return !before.effective;
  }

  /** Returns true when the effective trust setting changed. */
  async disable(): Promise<boolean> {
    const before = await this.resolve();
    await this.context.workspaceState.update(ACKNOWLEDGED_KEY, undefined);
    const current = await readProjectManifest();
    if (current.manifest && current.manifest.runtime?.trustedLocalPython !== false) {
      await writeProjectManifest(withTrustedLocalPython(current.manifest, false));
    }
    return before.effective;
  }
}
