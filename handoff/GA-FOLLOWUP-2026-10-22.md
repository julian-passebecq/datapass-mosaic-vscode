# Mosaic VS Code candidate follow-up — 2026-10-22

**RELEASE_PASS=false.** This resumes the [earlier candidate pass](GA-PASS-2026-10-22.md).
The previous candidate and its receipts are preserved. No main merge, Marketplace publication or live-provider
execution is authorized by this report. F08 real Docker remains excluded from V1; Infra remains simulated.

## Exact successor delivery

- Packaged source: `7647a6486db87246710c2e8f3cfa2fbd0668eb2d`; [draft PR 82](https://github.com/julian-passebecq/datapass-mosaic-vscode/pull/82).
- [Private successor candidate and evidence](https://github.com/julian-passebecq/datapass-codex-test/releases/tag/untagged-dfc5bedaa27c32a6efa1), tag `mosaic-vscode-0.4.1-candidate-7647a64`.
- VSIX SHA256: `46486d8403b2d8486f6965c83b10b615d140d1711df48dd0a77ab1de4e47677f`.
- Size: 2,122,120 bytes; 622 archive entries. Both installed V1 and module profiles match all 620 payload files,
  permitting only VS Code's `package.json.__metadata` addition.
- Eleven members differ from the preceding c3d73af package: extension bundle, changelog and nine content files.
  The entire Python runtime payload is byte-identical. Previous runtime/exercise receipts are preserved with
  their original source identity; the changed extension and content have fresh affected checks below.
- Release assets include `source-manifest.json`, `FOLLOWUP-SHA256SUMS`,
  `mosaic-vscode-0.4.1-7647a64-evidence.zip`, final `result.json` and authenticated download verification receipts.
  `followup-remote-verification.json` covers primary assets; `followup-delivery-verification.json` covers final
  metadata assets. The ZIP contains a pre-upload snapshot and its per-file digest manifest.

## What changed

- Runtime startup stays `starting` until initial catalog/kernel initialization completes. A stopped launch cannot
  publish stale readiness or overwrite a successor. The existing catalog deadline is unchanged.
- Native SQL receives the same 30-second response allowance as translated SQL, covering the existing 20-second
  worker limit, up to four seconds of worker termination waits and response overhead. Transport timeout does not
  cancel execution: the message explicitly says the query may have completed and does not retry it.
- The installed module harness now waits for the new document after Reload Window. The old selector existed
  before navigation, allowing the next command to reach the closing document. A focused before/after probe
  reproduced that boundary race; the 102-check journey then passed on unchanged c3d73af candidate bytes.
- The dbt oracle requires each invocation's own artifact and rejects unexpected process exits, runtime errors
  and accidental empty comparisons. Comparisons preserve NULL/type distinctions, relation kind and duplicate
  rows. Explicit snapshot clock-field exclusions remain; this is bounded fixture parity, not all-dbt parity.
- Selected learning text now qualifies SLO outage budgets, structured fields, summary quantiles, Bash `-e`
  exceptions and Git merges. The Bash example validates all inputs before moving any. Graded answers stay
  unchanged; see [the fact-check scope and sources](FACT-CHECK-2026-10-22.md).

## Validation

| Check | Result |
| --- | --- |
| Full source suite | PASS: contract smokes, 40 learning tests, 67 suite tests |
| SQL/startup regressions | PASS 5/5; old code reproduced four failures; one actual 11-second HTTP response and single-request assertion |
| Oracle evidence regressions | PASS 9/9 |
| Seven real dbt missions | PASS: 7 references; 7 untouched starters and 13 mutants rejected, 357.3 seconds |
| Strict dbt oracle | PASS: 4 cases, 12 comparisons; dbt Core and emulator node statuses, relation kinds, columns and typed rows compared |
| Installed module UI | PASS 102/102 on preserved c3d73af package using the corrected reload harness |
| Successor installed V1 | PASS 10/10 on exact 7647a64 VSIX, 135.4 seconds; first SQL and restart/history now pass |
| Successor installed module UI | PASS 102/102 on the same exact VSIX, 251.5 seconds; reload, layouts, all module navigation and runtime upgrade pass |
| Installed file identity | PASS 620/620 in each of the two isolated profiles |
| Corrected quiz packs | PASS 89 references; 89 starters and 175 mutants rejected; all 40 learning tests pass after final wording edits |
| Bash lesson | PASS nonempty input; empty/missing input rejected before any file moves |

The earlier V1 failure was an actual 10-second HTTP timeout: its retained journal shows the SQL completed one
second after the client recorded the error. Catalog initialization concurrent with early execution was a source
race; its exact contribution to that observed delay is an inference. No Playwright wait or server execution limit
was increased. The full source check includes the new regressions; heavy suites ran serially in this lane.
Runtime tools were Python 3.12.10, DuckDB 1.5.6, dbt Core 1.12.6, dbt-duckdb 1.11.0 and dbt Charts 0.8.0.
The oracle completed in 78.1 seconds. Installed UI used VS Code 1.142.0 with disposable profiles.

## Problems and questions

- The previous first-SQL and module reload failures are closed by fresh installed successor checks; earlier failed
  logs and the before/after boundary probe remain in the evidence archive.
- Physical native dialogs, pointer drag and save-conflict interaction remain NOT_QUALIFIED. Automated simple
  dialogs and commands do not establish those physical interactions.
- Full curriculum/vendor/version audit remains PARTIAL. Polars 2.0.0 was exercised earlier; the declared older
  supported floor has not been independently qualified in this pass.
- Oracle CI passed the earlier exact c3d73af source. That receipt is historical for this changed product source;
  a successor CI run requires coordinator routing. Hosted CI is exhausted; commits use `[skip ci]`.
- Questions: none. No additional live-provider, SQL endpoint, native desktop or release grant is assumed.
