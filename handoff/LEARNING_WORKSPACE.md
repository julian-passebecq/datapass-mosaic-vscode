# 2026-10-02 - Guided learning workspace handoff

User authorized a large Mosaic VS Code implementation pass. Repository comparison found GitHub and GitLab main at the identical `60192bd59c50e6a04b513c5e72d8042ca47917fa`; there were no newer feature branches or open PR/MRs. Work therefore continues on GitHub in `feat/guided-learning-workspace`, not the historical bootstrap branch. GitLab was not changed.

Read `docs/MOSAIC_LEARNING.md` for shipped surfaces, ownership, safety boundaries, test commands and intentional limits.

This tranche adds six curriculum paths / nineteen linked lessons, a collapsible learning rail, native tree, Read/Watch/Try/Exercise/Explain/Compare, course notes, native example files, direct delegation to Practice grading/hints, toy SQL/window/partition controls, existing SparkLab runtime evidence and pinned-run comparison. It does not merge the DataPass Hop or Studio shells.

Do not call the toy visual Spark telemetry, the authored storage view a real X-Ray, or a reading acknowledgment a solved challenge. Do not create another Python runtime or grader.

The existing four CI jobs are preserved; source Node checks and a real packaged Learning UI journey are appended to existing npm scripts. No workflow change, new npm dependency, deployment or release tag is part of this tranche. Version remains 0.2.0 on this development branch pending a separately qualified release.

Initial local evidence: 25 Node tests (16 contract/visual plus 9 actual-host-through-mocks) passed. Fifteen Chromium renderer interactions passed with a mocked VS Code bridge. These are not substitutes for the exact hosted four-job result and the packaged VS Code journey.

Next technical-lead priorities after this slice is green: tighten source/result provenance for arbitrary edits; persist explicit layout preferences without taking over the user's VS Code workbench; add a genuine runtime-fed graph renderer through existing graph surfaces; expose real Lakehouse inspection only when real file evidence is present; expand lesson authoring through small verified paths rather than another shell rewrite. Keep free-form Mosaic and Practice available independently.
