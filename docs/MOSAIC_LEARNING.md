# Mosaic Learning workspace

Implementation pass: 2026-10-02. This is an additive teaching layer in Datapass Workbench, not Mosaic Studio, a Jupyter kernel or DataPass Hop.

## Open and use

Run **Datapass: Open Learning** from the command palette. The Labs title has the same book action; **Datapass: Resume Learning** returns to the saved topic.

Six paths contain nineteen lessons: SQL semantics (4), Python (3), Spark (3), warehouse/dbt (3), storage (2), APIs/orchestration (4). Each links an already-installed Practice activity. Search looks at concepts as well as titles.

- **Read** combines a course card, pitfalls, prediction questions, native source example and teaching visual.
- **Watch** provides explicit previous/next/play/pause explanation steps. Join, window and partition controls are interactive, but illustrative; they do not execute the learner's code.
- **Try** opens a real `notebooks/learning/<lesson>/example.sql` or `.py`, preserving edits. Run uses its current editor buffer through the existing local runtime. Run selection requires a selection in that same example. SQL EXPLAIN ANALYZE executes the read-only query through the existing endpoint.
- **Exercise** opens the existing Practice solution and delegates Run visible/Submit/hints to the existing controller. Full Practice feedback and reference-unlock behavior remain available.
- **Explain** juxtaposes the authored explanation and the recorded runtime result. Spark plan, stage and exchange evidence stays explicitly simulated; local result rows are separate.
- **Compare** shows a pinned immutable baseline and the latest recorded run for the same lesson/language/scope. It is not a benchmark or a guarantee that catalog inputs stayed identical.

Balanced, Focus and Compact change presentation. The course rail hides with one click and becomes a compact top strip on a narrow view. A native Learning Path tree is also contributed. The user may move that tree to the Secondary Side Bar through VS Code's **Move View** action; the extension does not rely on unsupported sidebar placement or exact-width APIs.

## Truth and persistence

Reading acknowledgements are self-reports. A linked exercise is practiced only when existing Practice progress records a passed Submit for that exercise version. No mastery score is invented. Missing grading evidence is never a pass.

Topic, mode, layout, reading acknowledgements and saved notes live in VS Code workspace storage. JSON export contains these notes/self-reports, not fabricated grading. Practice keeps its existing `.datapass/progress.json` ownership. Current/pinned results and the last twenty Learning run metadata entries are session-local. Use Save notes explicitly. No telemetry or AI request is sent.

The toy joins show duplicate-key multiplicity, NULL non-matches, ON versus WHERE, semi and anti joins and input/output row linkage. The window visual compares explicit ROWS ordering against RANGE peers. The partition buckets conserve rows and cannot make coalesce increase the partition count; their bucket rule is not Spark's hash. Authored DAGs and storage/API timelines are teaching structures, not live task or file inspectors.

SparkLab still compiles its supported PySpark subset to local computation, with modeled distribution. Python and Polars still require trusted-local-Python opt-in. There is no new cloud connector, Spark scheduler, Python sandbox or implicit package installation.

## Source ownership

| Area | Location |
| --- | --- |
| Inert catalog / course content | `content/learning/catalog.json` |
| Shared validator, state and deterministic teaching models | `media/learning/model.mjs`, declaration companion `model.d.mts` |
| Browser composition and themed styles | `media/learning/view.mjs`, `view.css` |
| VS Code host, persistence, native files and controller delegation | `src/learning/learningWorkspace.ts` |
| Existing execution adapters | `src/labs/mosaic/client.ts`, `src/labs/sparklab/client.ts` |
| Registration | `src/extension.ts`, `package.json` |

The two execution adapters now return their own request result instead of forcing a consumer to read mutable global last-run state. Existing callers can continue to ignore the returned value.

The browser sends only catalog IDs and a bounded set of actions. It never sends source code, arbitrary file paths or command IDs. Nonce CSP/local resource roots, text-only rendering, bounded inputs, workspace trust, refusal of symbolic-link lesson directories, exclusive file creation and source-hash freshness are enforced. This is defense in depth for a local trusted workspace, not adversarial process isolation.

## Authoring

`datapass.learning` version 1 contains `paths` and `lessons`. A lesson declares its id/version/title/summary/minutes, concepts, prerequisites, course blocks, source example, existing exercise ID/language, lab ID, visual kind/steps and related lesson IDs. Blocks are text, callout or check. Visuals are join, window, partitions, dag, grain, storage or timeline. Source-language `none` routes to the existing lab/exercise without inventing a scratch runner.

Validation refuses unknown fields, invalid sizes, unknown references, cycles, duplicate IDs, unsafe IDs and invalid source ranges. The host also verifies every exercise target against the installed public catalog. Authored line highlights stop working when the corresponding source is edited, rather than pointing at stale lines.

## Tests

`npm test` retains the existing gates and adds `node --test scripts/learning_smoke.mjs scripts/learning_host_smoke.mjs`.

The first script checks the nineteen targets against actual shipped packs, contract rejection, progress semantics, SQL toy fixtures, partition conservation and renderer safety. The second executes the actual TypeScript host through a mocked VS Code/runtime adapter with real temporary files. It covers no implicit execution, file preservation, unsaved buffers, Restricted Mode, symlinks, controller delegation, cross-topic result isolation and immutable comparisons. A mocked adapter is not a real VS Code integration run.

`npm run test:ui` retains the old packaged Workbench journey, then runs `scripts/learning_vscode_smoke.mjs`. The new journey installs the VSIX in a fresh profile, opens Learning, switches views, checks native files, starts the existing runtime explicitly, submits a real Practice answer, runs SQL and SparkLab, checks narrow layout and restarts VS Code to verify retained topic/notes. Its report and screenshots are written to `test-results/vscode-ui/learning`, already included in the existing CI artifact. A failed or incomplete journey exits nonzero.

At the initial implementation snapshot, 25 Node checks and 15 Chromium renderer checks passed locally; the Chromium checks used inlined local modules and a mocked VS Code transport, not an Extension Host. Hosted CI and packaged VS Code results must be read from the exact PR commit/run, not inferred from these local checks.

## Deliberately not delivered in this slice

No universal drag/drop block editor, arbitrary notebook-cell dependency inference, live per-row lineage for arbitrary code, animated real executor network, real Parquet X-Ray, Iceberg connector, external OpenTelemetry exporter or imported full Hop. Existing labs, Practice/Review/Interview and free-form Mosaic remain unchanged entry points. These lessons provide a coherent route into them rather than replacing them.
