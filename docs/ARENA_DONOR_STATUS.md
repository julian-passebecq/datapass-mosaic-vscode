# Arena donor status

Bounded comparison on 2026-10-04: Mosaic baseline
`60192bd59c50e6a04b513c5e72d8042ca47917fa` against
`julian-passebecq/leetcodedataeng` v2.12.2,
`a3bff6aeeb89af5e379b4d8c168b3b1f581fe026`. The donor README and source
inventory were read at that exact revision, alongside `HARVEST_AUDIT.md`,
the shipped packs, Practice surfaces and arena contract gates.

| Capability | Status | Mosaic decision/evidence |
| --- | --- | --- |
| DE curriculum, SQL challenges, Python drills and engine comparisons | PROMOTED | Versioned `sql-lab-v1`, `python-lab-v1`, `engine-lab-v1`, `de-patterns-v1` and specialist packs; selective harvest, not item-for-item equivalence. |
| One problem with several implementations | REPRESENTED | `practiceProblems.ts` groups semantic IDs; 315 cards / 639 variants at this baseline. |
| Run, Submit, visible feedback, hints and reference explanations | REPRESENTED | Native solution files and shared local grading; references unlock on success or after three unsuccessful gradings, per the existing rule. Hidden fixture rows remain private. |
| Filters, per-language progress and interview preparation | REPRESENTED | Browse filters, persisted variant records, Leitner Review and timed Interview with no hints/references. |
| Concept references and production troubleshooting | PROMOTED | 24 non-executable concept checks, reference sheets and eight real pytest exercises; specialist labs supply additional applied practice. |
| Visual architecture and plans | REPRESENTED | Existing graph/lineage/lab surfaces and SparkLab teaching plans; no claim of parity with donor animations. |
| 19 interactive animation families, visual Big-O and algorithm walkthroughs | USEFUL-LATER | Potential future teaching material; no animation framework migration in 0.3.0. |
| Donor breadth, optional tracks and remaining unharvested exercises | USEFUL-LATER | Promote only with a supported local truth model and reference/starter/mutant grading. Different content counts do not block this release. |
| React application shell, Monaco wrapper and duplicate navigation | DO-NOT-PORT | VS Code owns the editor and navigation integration. |
| Separate progress storage/runtime or standalone web Arena | DO-NOT-PORT | Mosaic owns one Practice surface, one progress file and one local runtime. |

The current gate grades 638 local variants: 638 references pass, 638 starters
fail and 643 mutants fail. The remaining catalog variant is guided Spark,
which requires a qualified remote connection and is explicitly skipped by
the local grading gate. There are 21 pack manifests. Donor figures (323 items,
180 SQL variants, 81 multi-engine implementations) use different units and
are not Mosaic acceptance totals.

Mosaic Arena already provides a coherent native-file practice journey. This
release preserves its engine truth labels and content boundaries. No donor
shell, bulk content migration or new product is introduced.
