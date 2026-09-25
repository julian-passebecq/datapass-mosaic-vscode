"""Missions pack smoke: every mission's reference solution passes its hidden checker, and the untouched project fails.

Each mission is played in a fresh workspace through the real runtime API, as the dbt Lab plays it: the fixture
batches are loaded with /api/local/missions/setup, real dbt Core and dct commands run in the mission folder while the
catalog is lent (/api/local/catalog/release, then /reattach), and /api/local/missions/check judges the result.

Needs DATAPASS_DBT_PYTHON: a Python whose environment has dbt-core, dbt-duckdb and dbt-charts (CI installs them).
Without it, only the pack contract and the fixtures are checked.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

os.environ.pop("DATAPASS_TRUSTED_PYTHON", None)

from fastapi.testclient import TestClient  # noqa: E402

from datapass_runtime import main as runtime_main  # noqa: E402
from datapass_runtime.content import CONTENT  # noqa: E402
from missionlab.model import load_missions  # noqa: E402

DBT_PYTHON = os.getenv("DATAPASS_DBT_PYTHON", "").strip()
EXE = ".exe" if sys.platform == "win32" else ""


def copy_tree(source: Path, target: Path) -> None:
    for path in source.rglob("*"):
        if path.is_file():
            destination = target / path.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)


def write_profiles(workspace: Path) -> Path:
    """What the dbt Lab generates (src/platform/dbtTools.ts profilesYaml): the workspace catalog, schema dbt_dev."""
    database = (workspace / ".datapass" / "data" / "workspace.duckdb").as_posix()
    folder = workspace / ".datapass" / "dbt"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "profiles.yml").write_text(
        f"datapass_missions:\n  target: dev\n  outputs:\n    dev:\n      type: duckdb\n      path: '{database}'\n"
        "      schema: dbt_dev\n      threads: 4\n", encoding="utf-8")
    return folder


def run_tool(client: TestClient, command: list[str], cwd: Path, env: dict, lend: bool) -> subprocess.CompletedProcess:
    if lend:
        assert client.post("/api/local/catalog/release", json={"holder": " ".join([Path(command[0]).stem, *command[1:3]])}).status_code == 200
    try:
        return subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=600)
    finally:
        if lend:
            reattached = client.post("/api/local/catalog/reattach")
            assert reattached.status_code == 200, reattached.text


def play(mission, pack_dir: Path, variant: str) -> dict:
    """Play the reference steps on the starter project ('starter'), with the reference overlay ('reference'), or
    with the reference overlay then a mutant overlay ('mutants/<name>': a plausible wrong answer)."""
    with TemporaryDirectory(prefix=f"datapass-mission-{mission.id}-") as temp:
        workspace = Path(temp)
        folder = workspace / mission.folder
        copy_tree(pack_dir / "base", folder)
        copy_tree(pack_dir / mission.id / "project", folder)
        if variant != "starter":
            copy_tree(pack_dir / mission.id / "solution", folder)
        if variant.startswith("mutants/"):
            copy_tree(pack_dir / mission.id / variant, folder)
        profiles = write_profiles(workspace)
        bin_dir = Path(DBT_PYTHON).parent
        env = {**os.environ, "DBT_PROFILES_DIR": str(profiles), "DBT_SEND_ANONYMOUS_USAGE_STATS": "false",
               "DO_NOT_TRACK": "1", "PYTHONIOENCODING": "utf-8", "DCT_NO_WORKSPACE_GUARD": "1",
               "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", "")}
        dct_results: dict[str, dict] = {}
        os.environ["DATAPASS_WORKSPACE_ROOT"] = str(workspace)
        runtime_main.kernel_manager.restart(runtime_main.NATIVE_WORKSPACE_ID)
        try:
            with TestClient(runtime_main.app) as client:
                for step in mission.reference:
                    if step.batch:
                        response = client.post("/api/local/missions/setup", json={"mission_id": mission.id, "batch_id": step.batch})
                        assert response.status_code == 200, response.text
                    elif step.dbt:
                        done = run_tool(client, [str(bin_dir / f"dbt{EXE}"), *shlex.split(step.dbt)], folder, env, True)
                        if variant == "reference":
                            assert done.returncode == step.exit_code, f"{mission.id}: dbt {step.dbt} exited {done.returncode}:\n{done.stdout[-3000:]}"
                    elif step.dct:
                        (folder / "renders").mkdir(exist_ok=True)
                        done = run_tool(client, [str(bin_dir / f"dct{EXE}"), *shlex.split(step.dct)], folder, env, True)
                        if variant == "reference":
                            assert done.returncode == step.exit_code, f"{mission.id}: dct {step.dct} exited {done.returncode}:\n{done.stdout[-2000:]}{done.stderr[-2000:]}"
                    elif step.dct_validate:
                        done = run_tool(client, [str(bin_dir / f"dct{EXE}"), "--no-workspace-guard", "validate", "--json",
                                                 step.dct_validate], folder, env, False)
                        try:
                            parsed = json.loads(done.stdout)
                            entry = parsed[0] if isinstance(parsed, list) else parsed
                            dct_results[step.dct_validate] = {"success": bool(entry.get("success")), "errors": entry.get("errors") or []}
                        except (json.JSONDecodeError, AttributeError, IndexError):
                            dct_results[step.dct_validate] = {"success": False, "errors": [{"message": done.stdout[-300:] or done.stderr[-300:]}]}
                response = client.post("/api/local/missions/check", json={"mission_id": mission.id, "dct": dct_results})
                assert response.status_code == 200, response.text
                return response.json()
        finally:
            runtime_main.kernel_manager.restart(runtime_main.NATIVE_WORKSPACE_ID)


def describe(result: dict) -> str:
    lines = [f"  requires: {m}" for m in result["requires"]]
    for criterion in result["criteria"]:
        mark = "ok  " if criterion["passed"] else "FAIL"
        details = "; ".join(c["detail"] for c in criterion["checks"] if not c["passed"])
        lines.append(f"  {mark} {criterion['id']}: {details}")
    return "\n".join(lines)


def main() -> None:
    # The dbt Lab's pack; the Terminal Lab's missions have their own smoke (scripts/terminal_missions_smoke.py).
    missions = [(mission, pack_dir) for mission, pack_dir in load_missions() if mission.lab == "dbt"]
    ids = [mission.id for mission, _ in missions]
    assert len(ids) == len(set(ids)) >= 5, ids
    pack = json.loads((CONTENT / "missions" / "dbt-v1" / "pack.json").read_text(encoding="utf-8"))
    assert pack["missions"] == ids, (pack["missions"], ids)
    for mission, pack_dir in missions:
        assert (pack_dir / mission.id / "project").is_dir(), mission.id
        assert mission.reference, f"{mission.id} has no reference steps"
        assert (pack_dir / mission.id / "solution").is_dir(), f"{mission.id} has no reference solution"
    if not DBT_PYTHON:
        print(f"Missions pack contract checked ({len(missions)} missions). Reference runs skipped: set DATAPASS_DBT_PYTHON.")
        return
    mutants = 0
    for mission, pack_dir in missions:
        reference = play(mission, pack_dir, "reference")
        assert reference["status"] == "passed", f"{mission.id}: the reference solution does not pass:\n{describe(reference)}"
        starter = play(mission, pack_dir, "starter")
        assert starter["status"] == "not-yet", f"{mission.id}: the untouched project passes:\n{describe(starter)}"
        failed = [c["id"] for c in starter["criteria"] if not c["passed"]]
        print(f"  {mission.id}: reference passes {len(reference['criteria'])} criteria; untouched project fails {', '.join(failed) or 'the requirements'}")
        mutants_dir = pack_dir / mission.id / "mutants"
        for mutant in sorted(p.name for p in mutants_dir.iterdir()) if mutants_dir.is_dir() else []:
            result = play(mission, pack_dir, f"mutants/{mutant}")
            assert result["status"] == "not-yet", f"{mission.id}: mutant {mutant} passes:\n{describe(result)}"
            failed = [c["id"] for c in result["criteria"] if not c["passed"]]
            print(f"    mutant {mutant}: fails {', '.join(failed) or 'the requirements'}")
            mutants += 1
    print(f"Missions smoke passed: {len(missions)} reference solutions pass; {len(missions)} untouched projects and "
          f"{mutants} mutants fail.")


if __name__ == "__main__":
    main()
