"""Grade every installed exercise through the real shared worker.

For each exercise:
- the private reference solution must PASS a full submission (visible, hidden
  and edge fixtures);
- the public starter must NOT pass (a starter that already passes teaches nothing);
- every listed mutant (a plausible wrong answer) must NOT pass, which proves the
  hidden/edge fixtures actually discriminate the mistake the lesson is about.

Python/Polars exercises run in a trusted worker here on purpose: this smoke
executes only repository-authored reference code.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.pop("DATAPASS_TRUSTED_PYTHON", None)

from datapass_runtime.exercises import definitions, solution
from datapass_runtime.kernels import KernelManager

# Each pack keeps its test-only quality data in content/exercise-packs/<pack>/quality.json
# (excluded from the VSIX), so adding a pack or a mutant touches only that pack's folder:
#   "mutants": {exercise_id: [code, ...]}  plausible wrong answers; each must run and fail.
#   "notes":   {exercise_id: text}         why a mutant is wrong, when it is not obvious.
#   "flags":
#     "runnable_starters": true            starters must run cleanly and fail only on their
#                                          results, so a learner never starts from a parse error;
#     "build_errors_are_answers": true     wrong answers may fail to build: a dbt model that does
#                                          not compile or reads a relation that was never built is
#                                          the outcome the lesson is about (dbt's own error);
#     "plan_only_starters": [id, ...]      SparkLab plan lessons: the starter returns the right rows
#                                          and must fail only on its simulated plan;
#     "starters_refused_by_design": [id]   the lesson is that the platform refuses the starter (a
#                                          Synapse table script run on Fabric Warehouse);
#     "skip": "reason"                     the pack is not graded here (guided Spark requires an
#                                          explicitly qualified remote connection).
PACKS_DIR = Path(__file__).resolve().parents[1] / "content" / "exercise-packs"
QUALITY_FILE = "quality.json"
QUALITY_KEYS = {"flags", "notes", "mutants"}
FLAG_KEYS = {"runnable_starters", "build_errors_are_answers", "plan_only_starters",
             "starters_refused_by_design", "skip"}


def load_quality() -> dict[str, dict]:
    """Quality data per pack id, read from every pack folder that has a quality.json."""
    quality: dict[str, dict] = {}
    for path in sorted(PACKS_DIR.glob(f"*/{QUALITY_FILE}")):
        pack = json.loads((path.parent / "manifest.json").read_text(encoding="utf-8"))["id"]
        data = json.loads(path.read_text(encoding="utf-8"))
        assert set(data) <= QUALITY_KEYS, f"{path}: unknown keys {sorted(set(data) - QUALITY_KEYS)}"
        flags = data.get("flags", {})
        assert set(flags) <= FLAG_KEYS, f"{path}: unknown flags {sorted(set(flags) - FLAG_KEYS)}"
        quality[pack] = {"flags": flags, "mutants": data.get("mutants", {})}
    return quality


def grade(manager, workspace: Path, spec: dict, code: str) -> dict:
    return manager.call("packs", workspace / ".datapass" / "data", {
        "op": "exercise",
        "exercise_id": spec["id"],
        "exercise_version": spec["version"],
        "language": spec["language"],
        "code": code,
        "mode": "submit",
        "notebook_id": "packs-smoke",
        "cell_id": "solution",
        "source_revision": 1,
        "profile": "generic_8x8",
        "aqe": True,
    }, cwd=workspace)


def fails_only_on_plan(result: dict) -> bool:
    rows = [check for check in result["checks"] if check.get("kind") != "plan"]
    plan = [check for check in result["checks"] if check.get("kind") == "plan"]
    return all(check["passed"] for check in rows) and bool(plan) and not all(check["passed"] for check in plan)


def summary(result: dict) -> str:
    return ", ".join(f"{c['id']}={c['status']}" for c in result.get("checks", [])) or str(result.get("status"))


def main() -> None:
    quality = load_quality()
    all_specs = definitions()
    pack_ids = {spec.get("pack", {}).get("id") for spec in all_specs}
    assert set(quality) <= pack_ids, f"quality.json for unknown packs: {sorted(set(quality) - pack_ids)}"
    for pack, data in quality.items():
        own = {spec["id"] for spec in all_specs if spec.get("pack", {}).get("id") == pack}
        listed = set(data["mutants"]) | set(data["flags"].get("plan_only_starters", [])) \
            | set(data["flags"].get("starters_refused_by_design", []))
        assert listed <= own, f"{pack}/quality.json references exercises outside the pack: {sorted(listed - own)}"

    def flags(spec: dict) -> dict:
        return quality.get(spec.get("pack", {}).get("id"), {}).get("flags", {})

    specs = [spec for spec in all_specs if not flags(spec).get("skip")]
    failures: list[str] = []
    counts = {"solutions": 0, "starters": 0, "mutants": 0}
    with TemporaryDirectory(prefix="datapass-packs-smoke-") as temp:
        workspace = Path(temp)
        manager = KernelManager(mode="duckdb", trusted=True, timeout=60.0, max_workers=1)
        try:
            for spec in specs:
                reference = solution(spec["id"])["source"]
                result = grade(manager, workspace, spec, reference)
                counts["solutions"] += 1
                if result["status"] != "passed":
                    failures.append(f"{spec['id']}: reference solution {result['status']} ({summary(result)})")
                starter = spec.get("starter_source", "")
                if starter.strip():
                    counts["starters"] += 1
                    graded = grade(manager, workspace, spec, starter)
                    refused = [check["execution_status"] != "success" for check in graded["checks"]]
                    if graded["status"] == "passed":
                        failures.append(f"{spec['id']}: starter already passes")
                    elif spec["id"] in flags(spec).get("starters_refused_by_design", []):
                        if not all(refused):
                            failures.append(f"{spec['id']}: starter should be refused ({summary(graded)})")
                    elif flags(spec).get("runnable_starters") and any(refused):
                        failures.append(f"{spec['id']}: starter does not execute ({summary(graded)})")
                    elif spec["id"] in flags(spec).get("plan_only_starters", []) and not fails_only_on_plan(graded):
                        failures.append(f"{spec['id']}: starter must pass its results and fail a plan check ({summary(graded)})")
                mutants = quality.get(spec.get("pack", {}).get("id"), {}).get("mutants", {})
                for index, mutant in enumerate(mutants.get(spec["id"], [])):
                    counts["mutants"] += 1
                    graded = grade(manager, workspace, spec, mutant)
                    if graded["status"] == "passed":
                        failures.append(f"{spec['id']}: mutant #{index} passed; fixtures do not discriminate it")
                    elif any(check["execution_status"] != "success" for check in graded["checks"]) \
                            and not flags(spec).get("build_errors_are_answers"):
                        # A mutant must be a runnable wrong answer, not a typo that errors.
                        failures.append(f"{spec['id']}: mutant #{index} does not execute ({summary(graded)})")
        finally:
            manager.close()
    if failures:
        raise SystemExit("Exercise pack smoke failed:\n  " + "\n  ".join(failures))
    print(f"Exercise pack smoke passed: {counts['solutions']} reference solutions, "
          f"{counts['starters']} starters rejected, {counts['mutants']} mutants rejected.")


if __name__ == "__main__":
    main()
