"""API Lab smoke: every reference passes its hidden checker; the untouched mission, the starter ingest.py played
with the reference steps, and every mutant (a naive answer that ignores pagination, retries, the rate limit, the
watermark or the schema change) fail. Then the security rules of the simulated API server:

- a request without the mission key gets 401, a foreign Host header gets 400, the right key and Host get 200;
- the runtime's launch token never reaches the server's environment, its config, its request log, its answers, the
  run history, or the learner's code (a probe ingest.py looks for it in os.environ);
- with trusted Python off, a run is refused and nothing runs.

Everything goes through the real runtime API (TestClient) and a real server process on a loopback port; the
learner's code runs for real in the kernel worker. Mission ids as arguments play only those.
"""
from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory

os.environ["DATAPASS_TRUSTED_PYTHON"] = "1"
os.environ.setdefault("DATAPASS_STORAGE", "duckdb")

from fastapi.testclient import TestClient  # noqa: E402

from apilab.model import load_missions, pack_dir  # noqa: E402
from apilab.service import server_env  # noqa: E402
from datapass_runtime import main as runtime_main  # noqa: E402
from runtime_test_auth import client_kwargs  # noqa: E402

PROBE = """import os
token_seen = any(os.environ.get(name) for name in os.environ if 'TOKEN' in name.upper())
print('TOKEN_ENV', os.environ.get('DATAPASS_RUNTIME_TOKEN'), token_seen)
"""


def start(client: TestClient, mission_id: str) -> dict:
    response = client.post("/api/local/apilab/start", json={"mission_id": mission_id})
    assert response.status_code == 200, response.text
    return response.json()


def play(client: TestClient, workspace: Path, mission, source: Path | None, verbose: bool = False) -> dict:
    """Start the mission, put `source` in as ingest.py (None: keep the starter), play the reference steps, check."""
    start(client, mission.id)
    target = workspace / mission.folder / "ingest.py"
    if source is not None:
        shutil.copyfile(source, target)
    for step in mission.reference:
        if step.batch:
            response = client.post("/api/local/apilab/advance", json={"mission_id": mission.id, "batch_id": step.batch})
            assert response.status_code == 200, response.text
            continue
        response = client.post("/api/local/apilab/run", json={"mission_id": mission.id})
        assert response.status_code == 200, response.text
        run = response.json()
        if verbose:
            print(f"    run {run['run']} day {run['day']}: {run['status']} {run['requests']} requests {run['statuses']}")
            if run.get("error"):
                print("      " + run["error"].strip().splitlines()[-1])
    response = client.post("/api/local/apilab/check", json={"mission_id": mission.id})
    assert response.status_code == 200, response.text
    return response.json()


def failed_checks(result: dict) -> list[str]:
    out = [f"requires: {r}" for r in result["requires"]]
    for criterion in result["criteria"]:
        for check in criterion["checks"]:
            if not check["passed"]:
                out.append(f"{criterion['id']}: {check['detail']}")
    return out


def raw_get(port: int, host: str, key: str | None) -> tuple[int, bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {"Host": host}
    if key is not None:
        headers["Authorization"] = f"Bearer {key}"
    connection.request("GET", "/v1/customers?page=1", headers=headers)
    response = connection.getresponse()
    body = response.read()
    connection.close()
    return response.status, body


def security(client: TestClient, workspace: Path, token: str, failures: list[str]) -> None:
    mission_id = "api-paged-customers"
    api = start(client, mission_id)["api"]
    port = int(api["base_url"].rsplit(":", 1)[1])
    key = api["key"]
    if key == token or token in key:
        failures.append("the mission key is the runtime token")
    if port == int(os.environ["DATAPASS_RUNTIME_PORT"]):
        failures.append("the simulated API shares the runtime's port")
    answers = []
    for host, given, expected in ((f"127.0.0.1:{port}", None, 401), (f"127.0.0.1:{port}", "sim_wrong_key", 401),
                                  (f"127.0.0.1:{port}", token, 401), (f"evil.example:{port}", key, 400),
                                  (f"localhost:{port + 1}", key, 400), (f"localhost:{port}", key, 200),
                                  (f"127.0.0.1:{port}", key, 200)):
        status, body = raw_get(port, host, given)
        answers.append(body)
        if status != expected:
            failures.append(f"Host {host} with {'no key' if given is None else 'a key'}: {status}, expected {expected}")
    print("  security: 401 without the key, 400 on a foreign Host, 200 with both")
    # The token is nowhere the server or the learner can see.
    env = server_env()
    if any(token in value for value in env.values()) or any("TOKEN" in name.upper() for name in env):
        failures.append("the runtime token reaches the simulated API's environment")
    target = workspace / "missions" / mission_id / "ingest.py"
    target.write_text(PROBE, encoding="utf-8")
    run = client.post("/api/local/apilab/run", json={"mission_id": mission_id}).json()
    if "TOKEN_ENV None False" not in run["stdout"]:
        failures.append(f"the learner's code sees a token variable: {run['stdout'][:200]}")
    home = workspace / ".datapass" / "apilab"
    for path in home.rglob("*"):
        if path.is_file() and token in path.read_text(encoding="utf-8", errors="replace"):
            failures.append(f"the runtime token is written in {path.relative_to(workspace)}")
    if any(token.encode() in body for body in answers):
        failures.append("the runtime token appears in a simulated API answer")
    state = client.post("/api/local/apilab/state", json={"mission_id": mission_id}).text
    if token in state:
        failures.append("the runtime token appears in the API Lab state")
    print("  security: the runtime token is in no environment, file, answer or state of the API Lab")
    # Trusted Python off: refused, nothing runs.
    manager = runtime_main.kernel_manager
    manager.restart(runtime_main.NATIVE_WORKSPACE_ID)
    manager.trusted = False
    try:
        before = len(client.post("/api/local/apilab/state", json={"mission_id": mission_id}).json()["runs"])
        response = client.post("/api/local/apilab/run", json={"mission_id": mission_id})
        if response.status_code != 400 or "trusted" not in response.text.lower():
            failures.append(f"a run with trusted Python off was not refused: {response.status_code} {response.text[:200]}")
        after = client.post("/api/local/apilab/state", json={"mission_id": mission_id}).json()["runs"]
        if len(after) != before:
            failures.append("a refused run was recorded as a run")
    finally:
        manager.restart(runtime_main.NATIVE_WORKSPACE_ID)
        manager.trusted = True
    print("  trusted Python off: the run is refused")
    client.post("/api/local/apilab/stop", json={})
    status = client.post("/api/local/apilab/state", json={"mission_id": mission_id}).json()
    if status["running"]:
        failures.append("the simulated API is still running after stop")


def main() -> int:
    wanted = set(sys.argv[1:])
    missions = [m for m in load_missions() if not wanted or m.id in wanted]
    assert missions, "no API Lab missions found"
    verbose = bool(os.getenv("DATAPASS_SMOKE_VERBOSE"))
    failures: list[str] = []
    counts = {"references": 0, "untouched": 0, "starter": 0, "mutants": 0}
    with TemporaryDirectory(prefix="dp-api-") as temp:
        workspace = Path(temp) / "ws"
        workspace.mkdir()
        os.environ["DATAPASS_WORKSPACE_ROOT"] = str(workspace)
        kwargs = client_kwargs()
        token = os.environ["DATAPASS_RUNTIME_TOKEN"]
        with TestClient(runtime_main.app, **kwargs) as client:
            for mission in missions:
                mission_dir = pack_dir() / mission.id
                print(mission.id)
                result = play(client, workspace, mission, mission_dir / "solution" / "ingest.py", verbose)
                if result["status"] != "passed":
                    failures.append(f"{mission.id}: the reference does not pass: {failed_checks(result)}")
                else:
                    counts["references"] += 1
                    print("  reference passes")
                assert "simulated api" in result["truth"].lower(), "the check result must say the API is simulated"
                # Untouched: started, never run.
                start(client, mission.id)
                result = client.post("/api/local/apilab/check", json={"mission_id": mission.id}).json()
                if result["status"] == "passed":
                    failures.append(f"{mission.id}: the untouched mission passes")
                else:
                    counts["untouched"] += 1
                # The starter ingest.py, played with the reference steps.
                shutil.rmtree(workspace / mission.folder, ignore_errors=True)
                result = play(client, workspace, mission, None, verbose)
                if result["status"] == "passed":
                    failures.append(f"{mission.id}: the starter ingest.py passes")
                else:
                    counts["starter"] += 1
                    print(f"  starter fails: {failed_checks(result)[0]}")
                for mutant in sorted(p for p in (mission_dir / "mutants").iterdir() if p.is_dir()):
                    result = play(client, workspace, mission, mutant / "ingest.py", verbose)
                    if result["status"] == "passed":
                        failures.append(f"{mission.id}: mutant {mutant.name} passes")
                    else:
                        counts["mutants"] += 1
                        print(f"  mutant {mutant.name} fails: {failed_checks(result)[0]}")
            if not wanted or "api-paged-customers" in wanted:
                security(client, workspace, token, failures)
    print(json.dumps(counts))
    if failures:
        print("FAILURES:")
        for failure in failures:
            print(" - " + failure)
        return 1
    print("API Lab smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
