import * as vscode from "vscode";
import { WorkbenchModule } from "./modules";

export function openModulePanel(context: vscode.ExtensionContext, module: WorkbenchModule): void {
  const panel = vscode.window.createWebviewPanel(
    `datapass.${module.id}`,
    `Datapass — ${module.label}`,
    vscode.ViewColumn.One,
    { enableScripts:false, retainContextWhenHidden:true, localResourceRoots:[context.extensionUri] }
  );
  panel.webview.html = render(module);
}

function render(module: WorkbenchModule): string {
  const esc = (s:string) => s.replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;");
  return `<!doctype html><html><head><meta charset="utf-8"><style>
  body{padding:28px;color:var(--vscode-foreground);background:var(--vscode-editor-background);font:13px/1.5 var(--vscode-font-family)}
  main{max-width:900px;margin:auto}.eyebrow{color:var(--vscode-descriptionForeground);text-transform:uppercase;letter-spacing:.08em;font-size:11px}
  h1{font-size:30px;margin:8px 0}.lead{font-size:15px;color:var(--vscode-descriptionForeground)}
  .card{margin-top:24px;padding:16px;border:1px solid var(--vscode-panel-border);background:var(--vscode-sideBar-background);border-radius:8px}
  </style></head><body><main><div class="eyebrow">Datapass local lab</div><h1>${esc(module.label)}</h1>
  <p class="lead">${esc(module.description)}</p><div class="card"><b>Execution:</b> ${esc(module.execution)}<br><b>Cloud dependency:</b> none by default</div>
  <div class="card">Bootstrap shell. React/Fluent/React Flow module UI comes next; code and files stay native to VS Code.</div>
  </main></body></html>`;
}
