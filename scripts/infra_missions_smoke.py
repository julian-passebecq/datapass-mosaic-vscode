"""Infra Lab missions smoke: every reference passes its hidden checker; the untouched fixture, the starter project
played with the reference commands, and every mutant (a plausible wrong answer) fail.

Each play builds the mission folder through the real runtime API (/api/local/missions/setup: files, simulated world,
fixture commands), copies the pack's `solution/` overlay (and a mutant's overlay on top of it), types the reference
lines in the simulated shell (/api/local/infra/command), as a learner would, then asks /api/local/missions/check.
A mutant with a `commands.txt` plays those lines instead of the reference ones. Everything is simulated: no real
terraform, docker, kubectl or az is needed or run.

Also checks that two builds of a fixture give the same simulated world (deterministic ids, clock and metrics) and that
Start over moves the previous folder to the attic. Mission ids as arguments play only those.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory

os.environ.pop("DATAPASS_TRUSTED_PYTHON", None)

from fastapi.testclient import TestClient  # noqa: E402

from datapass_runtime import main as runtime_main  # noqa: E402
from datapass_runtime.content import CONTENT  # noqa: E402
from infralab.shell import strip_ansi  # noqa: E402
from missionlab.model import load_missions  # noqa: E402
from runtime_test_auth import client_kwargs  # noqa: E402

PACK = "infra-v1"


def overlay(source: Path, target: Path) -> None:
    if not source.is_dir():
        return
    for path in sorted(source.rglob("*")):
        if path.is_file() and path.name != "commands.txt":
            destination = target / path.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)


def play(client: TestClient, workspace: Path, mission, pack_dir: Path, overlays: list[Path], lines: list[str],
         expect_codes: dict[int, int] | None = None, verbose: bool = False) -> dict:
    response = client.post("/api/local/missions/setup", json={"mission_id": mission.id})
    assert response.status_code == 200, response.text
    folder = workspace / mission.folder
    for layer in overlays:
        overlay(layer, folder)
    for index, line in enumerate(lines):
        result = client.post("/api/local/infra/command", json={"folder": mission.folder, "line": line})
        assert result.status_code == 200, result.text
        body = result.json()
        expected = (expect_codes or {}).get(index)
        if verbose or (expected is not None and body["exit_code"] != expected):
            print(f"    $ {line}  -> {body['exit_code']}")
            print("      " + strip_ansi(body["output"]).strip().replace("\n", "\n      ")[-3000:])
        if expected is not None:
            assert body["exit_code"] == expected, f"{mission.id}: `{line}` exited {body['exit_code']}, expected {expected}"
    check = client.post("/api/local/missions/check", json={"mission_id": mission.id})
    assert check.status_code == 200, check.text
    return check.json()


def failed_checks(result: dict) -> list[str]:
    out = [f"requires: {r}" for r in result["requires"]]
    for criterion in result["criteria"]:
        for check in criterion["checks"]:
            if not check["passed"]:
                out.append(f"{criterion['id']}: {check['detail']}")
    return out


def main() -> int:
    wanted = set(sys.argv[1:])
    missions = [(m, p) for m, p in load_missions(CONTENT / "missions") if m.lab == "infra" and (not wanted or m.id in wanted)]
    assert missions, "no infra missions found"
    failures: list[str] = []
    counts = {"references": 0, "untouched": 0, "starter": 0, "mutants": 0}
    with TemporaryDirectory(prefix="dp-infra-") as temp:
        workspace = Path(temp) / "ws"
        workspace.mkdir()
        os.environ["DATAPASS_WORKSPACE_ROOT"] = str(workspace)
        with TestClient(runtime_main.app, **client_kwargs()) as client:
            for mission, pack_dir in missions:
                mission_dir = pack_dir / mission.id
                reference = [step.infra for step in mission.reference]
                codes = {i: step.exit_code for i, step in enumerate(mission.reference)}
                print(f"{mission.id}")
                # Determinism: two builds of the fixture give the same world.
                client.post("/api/local/missions/setup", json={"mission_id": mission.id})
                first = (workspace / mission.folder / ".infralab" / "world.json").read_text(encoding="utf-8")
                response = client.post("/api/local/missions/setup", json={"mission_id": mission.id})
                assert response.json().get("previous"), "Start over must move the previous folder to the attic"
                second = (workspace / mission.folder / ".infralab" / "world.json").read_text(encoding="utf-8")
                if first != second:
                    failures.append(f"{mission.id}: the fixture world differs between two builds")
                # Reference.
                result = play(client, workspace, mission, pack_dir, [mission_dir / "solution"], reference, codes,
                              verbose=bool(os.getenv("DATAPASS_SMOKE_VERBOSE")))
                if result["status"] != "passed":
                    failures.append(f"{mission.id}: the reference does not pass: {failed_checks(result)}")
                else:
                    counts["references"] += 1
                    print("  reference passes")
                assert "simulat" in result["truth"].lower(), "the check result must say it was simulated"
                # Untouched fixture.
                result = play(client, workspace, mission, pack_dir, [], [])
                if result["status"] == "passed":
                    failures.append(f"{mission.id}: the untouched fixture passes")
                else:
                    counts["untouched"] += 1
                # The starter project played with the reference commands (when the answer includes files: a mission
                # answered by commands alone has no solution/ folder).
                if (mission_dir / "solution").is_dir():
                    result = play(client, workspace, mission, pack_dir, [], reference)
                    if result["status"] == "passed":
                        failures.append(f"{mission.id}: the starter project passes with the reference commands")
                    else:
                        counts["starter"] += 1
                # Mutants.
                mutants = sorted(p for p in (mission_dir / "mutants").iterdir() if p.is_dir()) if (mission_dir / "mutants").is_dir() else []
                for mutant in mutants:
                    commands = mutant / "commands.txt"
                    lines = [l for l in commands.read_text(encoding="utf-8").splitlines() if l.strip()] if commands.is_file() else reference
                    result = play(client, workspace, mission, pack_dir, [mission_dir / "solution", mutant], lines)
                    if result["status"] == "passed":
                        failures.append(f"{mission.id}: mutant {mutant.name} passes")
                    else:
                        counts["mutants"] += 1
                        print(f"  mutant {mutant.name} fails: {failed_checks(result)[0]}")
    print(json.dumps(counts))
    if failures:
        print("FAILURES:")
        for failure in failures:
            print(" - " + failure)
        return 1
    print("infra missions smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
