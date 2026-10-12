# Mosaic Learning workspace

Implementation pass: 2026-10-02, learning engine and core content 2026-10-12. This is an additive teaching layer in Datapass Workbench, not Mosaic Studio, a Jupyter kernel or DataPass Hop.

## Open and use

Run **Datapass: Open Learning** from the command palette. The Labs title has the same book action; **Datapass: Resume Learning** returns to the saved topic.

Nine paths contain 35 lessons: SQL and data semantics (7), Python (5), Spark (3), warehouse and dbt (5), lakehouse storage (3), APIs and orchestration (4), Polars (3), data engineering foundations (2), Git and the shell (3). A lesson links an already-installed Practice exercise, and may also link concept checks, extra practice, Terminal, dbt or Lakehouse missions, a cheatsheet and a flashcard deck. Search looks at lesson concepts and titles, cheatsheet titles and flashcard fronts.

- **Read** combines a course card, pitfalls, prediction questions, native source example and teaching visual.
- **Watch** provides explicit previous/next/play/pause explanation steps. Join, window and partition controls are interactive, but illustrative; they do not execute the learner's code.
- **Try** opens a real `notebooks/learning/<lesson>/example.sql` or `.py`, preserving edits. Run uses its current editor buffer through the existing local runtime. Run selection requires a selection in that same example. SQL EXPLAIN ANALYZE executes the read-only query through the existing endpoint. A lesson whose source language is `none` (Git and the shell) lists commands to try in the lab instead.
- **Exercise** opens the existing Practice solution and delegates Run visible/Submit/hints to the existing controller. Full Practice feedback and reference-unlock behavior remain available.
- **Explain** juxtaposes the authored explanation and the recorded runtime result. Spark plan, stage and exchange evidence stays explicitly simulated; local result rows are separate.
- **Compare** shows a pinned immutable baseline and the latest recorded run for the same lesson/language/scope. It is not a benchmark or a guarantee that catalog inputs stayed identical.
- **Check your understanding** opens the linked concept checks (Practice language `quiz`, "concept check, no execution") in Practice. **More practice** opens extra exercises. **Missions** opens the mission's lab; it never starts or creates a mission by itself.
- **Cheatsheets** (`content/reference/learning-*.md`, 7 files: SQL, Python, Polars, Git and shell, dimensional modeling, dbt and loading patterns, lakehouse storage) open as a VS Code Markdown preview.
- **Flashcards** (`content/learning/flashcards/*.json`, 7 decks, 220 cards): **Datapass: Review Learning Flashcards** (or Review flashcards in the view) shows due cards first, then up to ten new ones; Show answer, then **Knew it** or **Missed it**. Intervals reuse Practice Review's Leitner schedule from `src/platform/practiceReview.ts` (1, 3, 7, 14, 30, 60 days), but the ratings are labelled "self-rated", kept in Learning's workspace state and never mixed with Practice Review or `.datapass/progress.json`.
- **Resume** (map and rail) shows the last lesson and view, the number of due flashcards and the next unverified check or exercise; it persists across restarts.

Balanced, Focus and Compact change presentation. The course rail hides with one click and becomes a compact top strip on a narrow view. A native Learning Path tree is also contributed, with a "Flashcards (self-rated)" entry and each lesson's levels in its description. The user may move that tree to the Secondary Side Bar through VS Code's **Move View** action; the extension does not rely on unsupported sidebar placement or exact-width APIs.

## Truth and persistence

Four progress levels are shown separately in the rail, the lesson and the native tree, never merged into one score:

| Level | Label | Evidence |
| --- | --- | --- |
| read | Read (self-reported) | Mark as read, for the current lesson version |
| checks | Checks k/n passed (concept check, no execution) | the last Practice Submit of each linked `quiz` item on its current version, passed or failed |
| executed | Ran locally, not graded | a Learning Run of the lesson example returned without error for the current lesson version; `{at, sourceHash, language}` is stored in workspace state |
| verified | Practice passed | a passed Submit in `.datapass/progress.json` for the current version of the lesson's exercise (for a lesson without one, of a linked practice item) |

A concept check never verifies a lesson, even when an older lesson links it as its exercise, and Run visible never counts. No mastery score is invented. Missing grading evidence is never a pass.

Topic, mode, layout, reading acknowledgements, local run records, flashcard ratings and saved notes live in VS Code workspace storage. JSON export contains these notes/self-reports, not fabricated grading. Practice keeps its existing `.datapass/progress.json` ownership. Current/pinned results and the last twenty Learning run metadata entries are session-local. Use Save notes explicitly. No telemetry or AI request is sent.

The toy joins show duplicate-key multiplicity, NULL non-matches, ON versus WHERE, semi and anti joins and input/output row linkage. The window visual compares explicit ROWS ordering against RANGE peers. The partition buckets conserve rows and cannot make coalesce increase the partition count; their bucket rule is not Spark's hash. Authored DAGs and storage/API timelines are teaching structures, not live task or file inspectors.

SparkLab still compiles its supported PySpark subset to local computation, with modeled distribution. Python and Polars still require trusted-local-Python opt-in. There is no new cloud connector, Spark scheduler, Python sandbox or implicit package installation.

## Source ownership

| Area | Location |
| --- | --- |
| Inert catalog / course content | `content/learning/catalog.json` (path index), `content/learning/paths/*.json` |
| Flashcard decks | `content/learning/flashcards/*.json` (`datapass.flashcards` version 1) |
| Cheatsheets | `content/reference/learning-*.md` |
| Shared validator, state and deterministic teaching models | `media/learning/model.mjs`, declaration companion `model.d.mts` |
| Browser composition and themed styles | `media/learning/view.mjs`, `view.css` |
| VS Code host, persistence, native files and controller delegation | `src/learning/learningWorkspace.ts` |
| Existing execution adapters | `src/labs/mosaic/client.ts`, `src/labs/sparklab/client.ts` |
| Registration | `src/extension.ts`, `package.json` |

The two execution adapters now return their own request result instead of forcing a consumer to read mutable global last-run state. Existing callers can continue to ignore the returned value.

The browser sends only catalog IDs and a bounded set of actions. It never sends source code, arbitrary file paths or command IDs; deck, card and cheatsheet ids are checked against the loaded files, and lesson links are addressed by index. Nonce CSP/local resource roots, text-only rendering, bounded inputs, workspace trust, refusal of symbolic-link lesson directories, exclusive file creation and source-hash freshness are enforced. This is defense in depth for a local trusted workspace, not adversarial process isolation.

## Authoring

`datapass.learning` version 1 contains `paths` and `lessons`. A lesson declares its id/version/title/summary/minutes, concepts, prerequisites, course blocks, source example, existing exercise ID/language, lab ID, visual kind/steps and related lesson IDs. Blocks are text, callout or check. Visuals are join, window, partitions, dag, grain, storage or timeline. Source-language `none` routes to the existing lab/exercise without inventing a scratch runner.

Optional fields: `checks` (at most 8 `{id, language}` Practice items, usually `quiz`), `practice` (at most 6 extra exercises, never `quiz`), `missions` (at most 6 `{pack, id}`, checked against `content/missions/*/pack.json`), `cheatsheet` (an id resolved only inside `content/reference/`) and `deck` (a flashcard deck id). Lessons without them stay valid. The exercise is optional only for a lesson that has checks, practice or missions (the Git and shell lessons link missions only). A deck is `{format: "datapass.flashcards", version: 1, id, title, path, cards}`, its id matches its file name, and it holds at most 80 plain-text cards `{id, front, back, lesson?, tags}` for an existing path and lessons; any deck in that format is loaded.

Validation refuses unknown fields, invalid sizes, unknown references, cycles, duplicate IDs, unsafe IDs and invalid source ranges. The host also verifies every exercise, check and practice target against the installed public catalog, and every mission, cheatsheet and deck against the shipped files; a catalog with a broken link is refused. Authored line highlights stop working when the corresponding source is edited, rather than pointing at stale lines.

## Tests

`npm test` retains the existing gates and adds `node --test scripts/learning_smoke.mjs scripts/learning_host_smoke.mjs` and `node --test scripts/suite/` (catalog files, flashcard decks).

The first script checks every exercise, check and practice target against the actual shipped packs, the shipped missions, cheatsheets and decks, contract rejection of the new fields, the four progress levels, next-unverified, restored run and flashcard state, bounded webview messages, search, SQL toy fixtures, partition conservation and renderer safety. The second executes the actual TypeScript host through a mocked VS Code/runtime adapter with real temporary files. It covers no implicit execution, file preservation, unsaved buffers, Restricted Mode, symlinks, controller delegation, cross-topic result isolation, immutable comparisons, local run records, concept checks that never verify, mission and cheatsheet links, flashcard rating and persistence apart from Practice, resume, refused bad references and tree level labels. A mocked adapter is not a real VS Code integration run.

`npm run test:ui` retains the old packaged Workbench journey, then runs `scripts/learning_vscode_smoke.mjs`. The new journey installs the VSIX in a fresh profile, opens Learning, switches views, reviews one flashcard, checks native files, starts the existing runtime explicitly, submits a real Practice answer, runs SQL and SparkLab, checks narrow layout and restarts VS Code to verify retained topic/notes. Its report and screenshots are written to `test-results/vscode-ui/learning`, already included in the existing CI artifact. A failed or incomplete journey exits nonzero.

Hosted CI and packaged VS Code results must be read from the exact PR commit/run, not inferred from local checks.

## Deliberately not delivered in this slice

No universal drag/drop block editor, arbitrary notebook-cell dependency inference, live per-row lineage for arbitrary code, animated real executor network, real Parquet X-Ray, Iceberg connector, external OpenTelemetry exporter or imported full Hop. Existing labs, Practice/Review/Interview and free-form Mosaic remain unchanged entry points. These lessons provide a coherent route into them rather than replacing them. Flashcard ratings are self-reports and are not exported to Practice.
