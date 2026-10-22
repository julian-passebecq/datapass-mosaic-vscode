# Mosaic VS Code candidate follow-up — 2026-10-22

**RELEASE_PASS=false.** This resumes the [earlier candidate pass](GA-PASS-2026-10-22.md).
The previous candidate and its receipts are preserved. No main merge, Marketplace publication or live-provider
execution is authorized by this report. F08 real Docker remains excluded from V1; Infra remains simulated.

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

## Validation before packaging

| Check | Result |
| --- | --- |
| Full source suite | PASS: contract smokes, 40 learning tests, 67 suite tests |
| SQL/startup regressions | PASS 5/5; old code reproduced four failures; one actual 11-second HTTP response and single-request assertion |
| Oracle evidence regressions | PASS 9/9 |
| Seven real dbt missions | PASS: 7 references; 7 untouched starters and 13 mutants rejected, 357.3 seconds |
| Strict dbt oracle | PASS: 4 cases, 12 comparisons; dbt Core and emulator node statuses, relation kinds, columns and typed rows compared |
| Installed module UI | PASS 102/102 on preserved c3d73af package using the corrected reload harness |
| Bash lesson | PASS nonempty input; empty/missing input rejected before any file moves |

The earlier V1 failure was an actual 10-second HTTP timeout: its retained journal shows the SQL completed one
second after the client recorded the error. Catalog initialization concurrent with early execution was a source
race; its exact contribution to that observed delay is an inference. No Playwright wait or server execution limit
was increased. The full source check includes the new regressions; heavy suites ran serially in this lane.

## Problems and questions

- Successor package and affected installed V1 journey are pending at this source checkpoint.
- Physical native dialogs, pointer drag and save-conflict interaction remain NOT_QUALIFIED. Automated simple
  dialogs and commands do not establish those physical interactions.
- Full curriculum/vendor/version audit remains PARTIAL. Polars 2.0.0 was exercised earlier; the declared older
  supported floor has not been independently qualified in this pass.
- Oracle CI passed the earlier exact c3d73af source. That receipt is historical for this changed product source;
  a successor CI run requires coordinator routing. Hosted CI is exhausted; commits use `[skip ci]`.
- Questions: none. No additional live-provider, SQL endpoint, native desktop or release grant is assumed.
