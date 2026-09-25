"""Terminal Lab missions smoke: every reference solution passes its hidden checker; the untouched fixture and every
mutant (a plausible wrong answer) fail.

Each play builds the mission folder through the real runtime API (/api/local/missions/setup, which creates the
files and the Git history from the pack), runs one script in it with a real shell, as a learner would type the
commands, then asks /api/local/missions/check. Reference scripts are `solution/solve.sh` (bash) and
`solution/solve.ps1` (PowerShell); every PowerShell found is played (pwsh, and Windows PowerShell 5.1 on Windows,
which writes UTF-16 with `>`). Mutants are `mutants/<name>/solve.sh` or `solve.ps1`.

Needs git and bash (Git Bash on Windows; DATAPASS_BASH overrides). PowerShell steps are skipped with a note when no
PowerShell is installed, unless DATAPASS_REQUIRE_POWERSHELL=1 (CI). Mission ids as arguments play only those.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

os.environ.pop("DATAPASS_TRUSTED_PYTHON", None)

from fastapi.testclient import TestClient  # noqa: E402

from datapass_runtime import main as runtime_main  # noqa: E402
from datapass_runtime.content import CONTENT  # noqa: E402
from missionlab.model import load_missions  # noqa: E402
from runtime_test_auth import client_kwargs  # noqa: E402

PACK = "terminal-v1"


def find_bash() -> str | None:
    configured = os.getenv("DATAPASS_BASH", "").strip()
    if configured:
        return configured
    if sys.platform == "win32":
        # Git Bash, next to git.exe; never C:\Windows\System32\bash.exe (WSL).
        git = shutil.which("git")
        candidates = [Path(git).resolve().parent.parent / "bin" / "bash.exe"] if git else []
        candidates.append(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe")
        return next((str(c) for c in candidates if c.is_file()), None)
    return shutil.which("bash")


def find_powershells() -> list[str]:
    found = [shutil.which("pwsh")]
    if sys.platform == "win32":
        found.append(shutil.which("powershell"))
    return [f for f in found if f]


def shell_env(home: Path) -> dict[str, str]:
    """The learner's shell: their own Git identity (a temporary global config here), no system config (so Git for
    Windows' autocrlf=true does not make the smoke differ between machines)."""
    config = home / "gitconfig"
    config.write_text("[user]\n\tname = Alex Learner\n\temail = alex.learner@example.com\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"GIT_CONFIG_GLOBAL": str(config), "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
                "GIT_EDITOR": "true", "GIT_MERGE_AUTOEDIT": "no", "LC_ALL": "C.UTF-8" if sys.platform != "win32" else "C"})
    return env


def run_script(shell: str, script: Path, cwd: Path, env: dict) -> subprocess.CompletedProcess:
    if script.suffix == ".sh":
        command = [shell, "--noprofile", "--norc", str(script)]
    else:
        command = [shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)]
    return subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=180)


def play(mission, pack_dir: Path, shell: str | None, script: Path | None) -> tuple[dict, subprocess.CompletedProcess | None, Path]:
    """Build the fixture, run `script` in it (None: the untouched fixture), check. Returns the check and the run."""
    temp = TemporaryDirectory(prefix="dpt-")
    workspace = Path(temp.name)
    os.environ["DATAPASS_WORKSPACE_ROOT"] = str(workspace)
    with TestClient(runtime_main.app, **client_kwargs()) as client:
        built = client.post("/api/local/missions/setup", json={"mission_id": mission.id})
        assert built.status_code == 200, f"{mission.id}: setup failed: {built.text}"
        folder = workspace / mission.folder
        done = run_script(shell, script, folder, shell_env(workspace)) if script and shell else None
        checked = client.post("/api/local/missions/check", json={"mission_id": mission.id})
        assert checked.status_code == 200, checked.text
    play.temps.append(temp)
    return checked.json(), done, workspace


play.temps = []


def describe(result: dict, done: subprocess.CompletedProcess | None = None) -> str:
    lines = [f"  requires: {m}" for m in result["requires"]]
    for criterion in result["criteria"]:
        mark = "ok  " if criterion["passed"] else "FAIL"
        details = "; ".join(c["detail"] for c in criterion["checks"] if not c["passed"])
        lines.append(f"  {mark} {criterion['id']}: {details}")
    if done is not None:
        lines.append(f"  script exited {done.returncode}; stderr: {done.stderr[-1500:]}")
    return "\n".join(lines)


def failed(result: dict) -> str:
    return ", ".join(c["id"] for c in result["criteria"] if not c["passed"]) or "the requirements"


def git_heads(folder: Path) -> str:
    done = subprocess.run(["git", "for-each-ref", "--format=%(refname) %(objectname)"], cwd=folder,
                          capture_output=True, text=True)
    return done.stdout


def main() -> None:
    only = set(sys.argv[1:])
    missions = [(m, p) for m, p in load_missions() if m.lab == "terminal"]
    ids = [m.id for m, _ in missions]
    pack = json.loads((CONTENT / "missions" / PACK / "pack.json").read_text(encoding="utf-8"))
    assert pack["missions"] == ids, (pack["missions"], ids)
    assert 6 <= len(ids) <= 10 or only, ids
    if only:
        missions = [(m, p) for m, p in missions if m.id in only]
    bash = find_bash()
    powershells = find_powershells()
    assert shutil.which("git"), "git is needed"
    assert bash, "bash is needed (Git Bash on Windows, or set DATAPASS_BASH)"
    if not powershells:
        assert os.getenv("DATAPASS_REQUIRE_POWERSHELL") != "1", "PowerShell is required here but was not found"
        print("  (no PowerShell found: the PowerShell references and mutants are skipped)")
    print(f"  bash: {bash}; PowerShell: {', '.join(powershells) or 'none'}")

    references = mutants = 0
    for mission, pack_dir in missions:
        mission_dir = pack_dir / mission.id
        assert mission.reference, f"{mission.id} has no reference solution"
        assert not (mission_dir / "solution" / "project").exists()
        # The fixture is reproducible: the same commits (hashes) every time it is built.
        if mission.fixture.git:
            first = play(mission, pack_dir, None, None)
            second = play(mission, pack_dir, None, None)
            assert git_heads(first[2] / mission.folder) == git_heads(second[2] / mission.folder), f"{mission.id}: fixture not reproducible"
        starter, _, _ = play(mission, pack_dir, None, None)
        assert starter["status"] == "not-yet", f"{mission.id}: the untouched fixture passes:\n{describe(starter)}"
        assert all(c["detail"] for criterion in starter["criteria"] for c in criterion["checks"])
        played = []
        for step in mission.reference:
            script = mission_dir / (step.bash or step.powershell)
            assert script.is_file(), f"{mission.id}: {script} is missing"
            for shell in ([bash] if step.bash else powershells):
                result, done, _ = play(mission, pack_dir, shell, script)
                assert done.returncode == 0, f"{mission.id}: {script.name} with {Path(shell).name} exited {done.returncode}:\n{done.stdout[-1500:]}{done.stderr[-1500:]}"
                assert result["status"] == "passed", f"{mission.id}: {script.name} with {Path(shell).name} does not pass:\n{describe(result, done)}"
                played.append(Path(shell).stem)
                references += 1
        print(f"  {mission.id}: reference passes {len(mission.acceptance)} criteria with {', '.join(played)}; untouched fixture fails {failed(starter)}")
        mutants_dir = mission_dir / "mutants"
        for mutant in sorted(p for p in mutants_dir.iterdir() if p.is_dir()) if mutants_dir.is_dir() else []:
            scripts = sorted(mutant.glob("solve.*"))
            assert len(scripts) == 1, f"{mission.id}: mutant {mutant.name} needs one solve.sh or solve.ps1"
            shell = bash if scripts[0].suffix == ".sh" else (powershells[0] if powershells else None)
            if shell is None:
                print(f"    mutant {mutant.name}: skipped (no PowerShell)")
                continue
            result, done, _ = play(mission, pack_dir, shell, scripts[0])
            assert result["status"] == "not-yet", f"{mission.id}: mutant {mutant.name} passes:\n{describe(result, done)}"
            print(f"    mutant {mutant.name}: fails {failed(result)}")
            if done.returncode != 0:
                # A mutant is a plausible answer that runs through; say so when its script itself stopped.
                print(f"      (its script exited {done.returncode}: {done.stderr.strip()[-400:]})")
            mutants += 1

    # Start over: the learner's folder is moved to the attic, never deleted, and the fixture is rebuilt.
    mission, pack_dir = missions[0]
    with TemporaryDirectory(prefix="dpt-") as temp:
        os.environ["DATAPASS_WORKSPACE_ROOT"] = temp
        with TestClient(runtime_main.app, **client_kwargs()) as client:
            assert client.post("/api/local/missions/setup", json={"mission_id": mission.id}).status_code == 200
            (Path(temp) / mission.folder / "mine.txt").write_text("my work\n", encoding="utf-8")
            again = client.post("/api/local/missions/setup", json={"mission_id": mission.id}).json()
            assert again["previous"] and (Path(temp) / again["previous"] / "mine.txt").is_file(), again
            assert not (Path(temp) / mission.folder / "mine.txt").exists()
    for temp in play.temps:
        temp.cleanup()
    print(f"Terminal missions smoke passed: {references} reference plays pass; {len(missions)} untouched fixtures and "
          f"{mutants} mutants fail.")


if __name__ == "__main__":
    main()
