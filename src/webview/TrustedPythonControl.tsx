import { Badge, Button } from "@fluentui/react-components";
import type { PythonTrustView } from "./contracts";
import type { VsCodeApi } from "./WorkbenchApp";

const LABELS: Record<PythonTrustView["state"], string> = {
  disabled: "trusted Python off",
  requested: "needs confirmation",
  "blocked-untrusted-workspace": "workspace not trusted",
  enabled: "trusted Python on"
};

export function TrustedPythonControl({
  vscode,
  trust
}: {
  vscode: VsCodeApi;
  trust: PythonTrustView;
}) {
  return (
    <div className="trust-control">
      <div className="trust-control-line">
        <Badge appearance="tint" color={trust.effective ? "warning" : "informative"}>
          {LABELS[trust.state]}
        </Badge>
        {trust.effective ? (
          <Button
            appearance="subtle"
            size="small"
            onClick={() => vscode.postMessage({ type: "setTrustedPython", enabled: false })}
          >
            Disable
          </Button>
        ) : (
          <Button
            appearance="secondary"
            size="small"
            onClick={() => vscode.postMessage({ type: "setTrustedPython", enabled: true })}
          >
            {trust.state === "requested" ? "Review and confirm…" : "Enable trusted local Python…"}
          </Button>
        )}
      </div>
      <small className="muted">{trust.reason}</small>
      {trust.restartRequired && (
        <small className="error-text">The running runtime uses a different setting. Restart the runtime to apply it.</small>
      )}
    </div>
  );
}
