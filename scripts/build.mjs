import * as esbuild from "esbuild";

const watch = process.argv.includes("--watch");

const extensionOptions = {
  entryPoints: ["src/extension.ts"],
  bundle: true,
  outfile: "dist/extension.js",
  platform: "node",
  format: "cjs",
  target: "node20",
  sourcemap: true,
  external: ["vscode"],
  logLevel: "info"
};

const webviewOptions = {
  entryPoints: { webview: "src/webview/main.tsx" },
  bundle: true,
  outdir: "dist",
  platform: "browser",
  format: "iife",
  target: ["chrome120"],
  sourcemap: true,
  logLevel: "info",
  define: {
    "process.env.NODE_ENV": JSON.stringify("production")
  }
};

if (watch) {
  const [extensionContext, webviewContext] = await Promise.all([
    esbuild.context(extensionOptions),
    esbuild.context(webviewOptions)
  ]);
  await Promise.all([extensionContext.watch(), webviewContext.watch()]);
  console.log("Datapass Workbench build watcher started.");
} else {
  await Promise.all([
    esbuild.build(extensionOptions),
    esbuild.build(webviewOptions)
  ]);
}
