"""Lakehouse Lab smoke: every reference passes its hidden checker; the untouched starter and every mutant fail.

Each play builds the mission folder through the real runtime API (/api/local/lakehouse/start), copies the pack's
`solution/` file for one engine (or a mutant's file), runs it as the Run button does (/api/local/lakehouse/run: DuckDB
SQL in the bounded child process, Polars as trusted local Python), then asks /api/local/lakehouse/check. Everything
is real and local: DuckDB, Parquet files on disk, the ducklake extension (installed once by Setup runtime; this smoke
installs it when it can and skips the DuckLake missions, loudly, when it cannot; the same for the delta extension
and the Delta mission).

Also checks the sandbox's bounds (INSTALL, ATTACH, SET and a file outside the mission folder are refused), that Start
over keeps the previous folder in the attic, and that the storage view measures files. Mission ids as arguments play
only those.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory

os.environ["DATAPASS_TRUSTED_PYTHON"] = "1"  # the Polars references run as trusted local Python, as in the lab

from fastapi.testclient import TestClient  # noqa: E402

from datapass_runtime import main as runtime_main  # noqa: E402
from lakehouselab.extensions import ducklake_status, setup_install  # noqa: E402
from lakehouselab.model import load_missions  # noqa: E402
from runtime_test_auth import client_kwargs  # noqa: E402

REQUIRE_DUCKLAKE = os.getenv("DATAPASS_REQUIRE_DUCKLAKE") == "1"


def engine_of(file: Path, mission) -> str:
    return next(engine for engine, name in mission.files.items() if name == file.name)


def play(client: TestClient, workspace: Path, mission, file: Path | None) -> dict:
    response = client.post("/api/local/lakehouse/start", json={"mission_id": mission.id})
    assert response.status_code == 200, response.text
    if file is not None:
        engine = engine_of(file, mission)
        shutil.copyfile(file, workspace / mission.folder / file.name)
        ran = client.post("/api/local/lakehouse/run", json={"mission_id": mission.id, "engine": engine})
        assert ran.status_code == 200, ran.text
        body = ran.json()
        if body.get("error") or body.get("exit_code"):
            print(f"    run {file.name}: {body.get('error') or body.get('stderr', '')[-600:]}")
    checked = client.post("/api/local/lakehouse/check", json={"mission_id": mission.id})
    assert checked.status_code == 200, checked.text
    return checked.json()


def failures(result: dict) -> list[str]:
    return [f"{c['id']}: {check['detail']}" for c in result["criteria"] for check in c["checks"] if not check["passed"]]


def bounds(client: TestClient, workspace: Path, mission) -> list[str]:
    """The Run button refuses what would escape the mission folder or change DuckDB's setup."""
    problems = []
    folder = workspace / mission.folder
    outside = (workspace / "outside.csv").as_posix()
    (workspace / "outside.csv").write_text("a\n1\n", encoding="utf-8")
    name = mission.files["duckdb"]
    for sql in ("INSTALL httpfs;", "ATTACH 'x.duckdb';", "SET enable_external_access = true;",
                f"SELECT * FROM read_csv('{outside}');", "LOAD httpfs;"):
        (folder / name).write_text(sql, encoding="utf-8")
        body = client.post("/api/local/lakehouse/run", json={"mission_id": mission.id, "engine": "duckdb"}).json()
        if not body.get("error"):
            problems.append(f"not refused: {sql}")
    return problems


def main() -> int:
    only = set(sys.argv[1:])
    status = ducklake_status()
    if not (status["installed"] and status["delta"]):
        setup_install()
        status = ducklake_status(refresh=True)
    if not (status["installed"] and status["delta"]) and REQUIRE_DUCKLAKE:
        print("FAIL: the ducklake or delta extension is not installed and DATAPASS_REQUIRE_DUCKLAKE=1.")
        return 1
    failed: list[str] = []
    played = skipped = 0
    with TemporaryDirectory(prefix="dp-lh-") as temp:
        workspace = Path(temp)
        os.environ["DATAPASS_WORKSPACE_ROOT"] = str(workspace)
        client = TestClient(runtime_main.app, **client_kwargs())
        listed = client.post("/api/local/lakehouse/missions", json={}).json()["missions"]
        assert [m["id"] for m in listed] == [m.id for m, _ in load_missions()], "the API lists the pack's missions"
        assert all("checks" not in str(m["acceptance"]) for m in listed), "checks stay hidden"
        for mission, pack_dir in load_missions():
            if only and mission.id not in only:
                continue
            if (mission.ducklake and not status["installed"]) or (mission.delta and not status["delta"]):
                print(f"SKIP {mission.id}: the ducklake or delta extension is not installed (offline).")
                skipped += 1
                continue
            base = pack_dir / mission.id
            starter = play(client, workspace, mission, None)
            if starter["status"] == "passed":
                failed.append(f"{mission.id}: the untouched starter passes")
            for engine, name in mission.files.items():
                reference = base / "solution" / name
                if not reference.is_file():
                    failed.append(f"{mission.id}: no reference for {engine}")
                    continue
                result = play(client, workspace, mission, reference)
                played += 1
                if result["status"] != "passed":
                    failed.append(f"{mission.id} reference {engine}: {failures(result)}")
                else:
                    print(f"ok   {mission.id} reference ({engine})")
            for mutant in sorted((base / "mutants").iterdir()):
                files = [f for f in mutant.iterdir() if f.is_file()]
                assert len(files) == 1, f"{mutant}: one file per mutant"
                result = play(client, workspace, mission, files[0])
                played += 1
                if result["status"] == "passed":
                    failed.append(f"{mission.id} mutant {mutant.name} passes")
                else:
                    print(f"ok   {mission.id} mutant {mutant.name} rejected: {failures(result)[0][:110]}")
            if "duckdb" in mission.files and not failed:
                failed += [f"{mission.id} {p}" for p in bounds(client, workspace, mission)]
        first = next((m for m, _ in load_missions() if not only or m.id in only), None)
        if first and (not first.ducklake or status["installed"]):
            again = client.post("/api/local/lakehouse/start", json={"mission_id": first.id}).json()
            if not again.get("previous") or not (workspace / again["previous"]).is_dir():
                failed.append("Start over did not keep the previous folder in the attic")
            view = client.post("/api/local/lakehouse/storage", json={"mission_id": first.id}).json()
            if not view["folders"]:
                failed.append("the storage view measured no file")
    print(f"{played} plays, {skipped} DuckLake / Delta missions skipped.")
    for line in failed:
        print("FAIL", line)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
