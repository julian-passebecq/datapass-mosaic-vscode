"""Projects content gate: schema, references, and a scripted reference walkthrough of every project.

1. Every content/projects/<id>/project.json validates (runtime/datapass_runtime/projects.py). Its steps use
   Workbench modules (src/modules.ts) and installed exercises, and every file a step opens is created by that
   step's own scaffolds (project files, the Cloud Lab and BI Lab samples, the Workbench starters).
2. In a fresh workspace, every automatic check of every project fails: no check passes vacuously.
3. The projects are then walked one after another in that same workspace, as a learner would. Each step first
   runs its open action's scaffolds, then the actions of content/projects/<id>/reference/walkthrough.json,
   through the runtime API with the payloads the extension sends (see src/factoryState.ts, src/biState.ts).
   After a project's walkthrough, every automatic check of that project passes.
"""
from __future__ import annotations

import ast
import copy
import json
import os
from pathlib import Path
import re
import shutil
import sys
from tempfile import TemporaryDirectory

os.environ.pop("DATAPASS_TRUSTED_PYTHON", None)

from fastapi.testclient import TestClient  # noqa: E402

from datapass_runtime import main  # noqa: E402
from datapass_runtime.projects import FILE_ROOTS, Project, load_projects, safe_path  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "content"
PROJECTS = CONTENT / "projects"


def ts_array(file: str, function: str) -> str:
    """The text a Workbench starter returns: a static `return [ ... ].join("\\n")` of string literals."""
    source = (ROOT / file).read_text(encoding="utf-8")
    start = source.index(f"export function {function}(")
    body = source[start:]
    match = re.search(r"return \[(.*?)\]\.join\(\"\\n\"\)", body, re.S)
    assert match, (file, function)
    return "\n".join(ast.literal_eval("[" + match.group(1) + "]"))


def workbench_modules() -> set[str]:
    return set(re.findall(r'id:"([a-z]+)"', (ROOT / "src" / "modules.ts").read_text(encoding="utf-8")))


def exercise_catalog() -> dict[str, dict]:
    """Exercises by extension key (pack/id/language), with the pack's reference solution."""
    found = {}
    for pack in sorted((CONTENT / "exercise-packs").iterdir()):
        exercises, grading = pack / "exercises.json", pack / "grading.server.json"
        if not exercises.is_file():
            continue
        manifest = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("enabled") is False:
            continue
        solutions = json.loads(grading.read_text(encoding="utf-8"))
        for item in json.loads(exercises.read_text(encoding="utf-8")):
            found[f"{manifest['id']}/{item['id']}/{item['language']}"] = {
                **item, "solution": solutions[item["id"]]["solution"]}
    return found


def scaffold_files(project: Project, name: str) -> dict[str, Path | str]:
    """Workspace path -> source file (or text) that a scaffold creates, never overwriting (like the extension)."""
    out: dict[str, Path | str] = {}
    if name == "project":
        base = PROJECTS / project.id / "files"
        for path in sorted(base.rglob("*")) if base.is_dir() else []:
            if path.is_file():
                out[path.relative_to(base).as_posix()] = path
    elif name in ("factory", "bi"):
        base = ROOT / "samples" / ("factory-lab" if name == "factory" else "bi-lab")
        for path in sorted(base.rglob("*")):
            if path.is_file():
                out[f"{name}/{path.relative_to(base).as_posix()}"] = path
    elif name == "retail_demo":
        out["datasets/retail_orders.csv"] = ts_array("src/scaffold/retailDemo.ts", "retailOrdersCsv")
    elif name == "airflow":
        out["airflow/dags/retail_daily.py"] = ts_array("src/scaffold/starters.ts", "airflowStarter")
    elif name == "pipeline":
        out["pipelines/main.pipeline.py"] = ts_array("src/scaffold/starters.ts", "pipelineStarter")
    elif name == "sparklab":
        out["notebooks/sparklab.py"] = "from pyspark.sql import functions as F\n"
    return out


# Together, the projects must use every lab and these lab tabs.
REQUIRED_MODULES = {"mosaic", "practice", "fabric", "bi", "sparklab", "airflow", "pipeline"}
REQUIRED_TABS = {("fabric", "pipelines"), ("bi", "warehouse"), ("bi", "dbt")}
MIN_PROJECTS = 1


def validate_content(projects: list[Project], exercises: dict[str, dict]) -> None:
    modules = workbench_modules()
    assert modules >= REQUIRED_MODULES, modules
    assert len(projects) >= MIN_PROJECTS, [p.id for p in projects]
    used_modules: set[str] = set()
    for project in projects:
        assert 8 <= len(project.steps) <= 12, (project.id, len(project.steps))
        files = PROJECTS / project.id / "files"
        for path in (p for p in files.rglob("*") if p.is_file()) if files.is_dir() else []:
            relative = path.relative_to(files).as_posix()
            assert safe_path(relative), (project.id, relative, FILE_ROOTS)
            if relative.startswith("projects/"):
                assert relative.startswith(f"projects/{project.id}/"), (project.id, relative)
        walkthrough = json.loads((PROJECTS / project.id / "reference" / "walkthrough.json").read_text(encoding="utf-8"))
        assert set(walkthrough["steps"]) == {s.id for s in project.steps}, (project.id, "walkthrough steps")
        assert set(walkthrough.get("starters", {})) <= {s.id for s in project.steps if s.checks}, (project.id, "starters")
        for step in project.steps:
            assert step.module in modules, (project.id, step.id, step.module)
            used_modules.add(step.module)
            if step.open.exercise:
                assert step.open.exercise in exercises, (project.id, step.id, step.open.exercise)
            for check in step.checks:
                if check.kind == "exercise":
                    assert check.exercise in exercises, (project.id, step.id, check.exercise)
                    assert check.exercise == step.open.exercise, (project.id, step.id, "opens another exercise")
            if step.open.file:
                created = {path for name in step.open.scaffold for path in scaffold_files(project, name)}
                assert step.open.file in created, (project.id, step.id, step.open.file, "not created by", step.open.scaffold)
            if step.checks:
                assert walkthrough["steps"][step.id], (project.id, step.id, "an automatic step needs walkthrough actions")
    assert used_modules >= REQUIRED_MODULES, used_modules
    tabs = {(s.module, s.open.tab) for p in projects for s in p.steps if s.open.tab}
    assert tabs >= REQUIRED_TABS, REQUIRED_TABS - tabs


# ---- Payloads, built from the workspace like the extension builds them ------------------------------------


def factory_files(ws: Path, flavor: str) -> dict:
    files = {"pipelines": {}, "datasets": {}, "procedures": {}, "notebooks": {}}
    root = ws / "factory"
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        parts = path.relative_to(root).parts
        text = path.read_text(encoding="utf-8")
        if parts[0] == "fabric" and len(parts) == 3 and parts[1].endswith(".DataPipeline") and parts[2] == "pipeline-content.json":
            if flavor == "fabric":
                files["pipelines"][parts[1].removesuffix(".DataPipeline")] = json.loads(text)
        elif parts[0] == "fabric" and len(parts) == 3 and parts[1].endswith(".Notebook") and parts[2] == "notebook-content.py":
            files["notebooks"]["fabric:" + parts[1].removesuffix(".Notebook")] = text
        elif parts[0] in ("adf", "synapse") and len(parts) == 3 and parts[1] in ("pipeline", "dataset") and parts[2].endswith(".json"):
            if parts[0] == flavor:
                files["pipelines" if parts[1] == "pipeline" else "datasets"][parts[2][:-5]] = json.loads(text)
        elif parts[0] == "synapse" and len(parts) == 3 and parts[1] == "notebook" and parts[2].endswith(".py"):
            files["notebooks"]["synapse:" + parts[2][:-3]] = text
        elif parts[0] == "databricks" and parts[-1].endswith(".py"):
            files["notebooks"]["databricks:/" + "/".join(parts[1:])[:-3]] = text
        elif parts[:2] == ("sql", "procedures") and len(parts) == 3 and parts[2].endswith(".sql"):
            files["procedures"][parts[2][:-4]] = text
    return files


def databricks_payload(ws: Path) -> tuple[dict, dict]:
    files: dict = {"notebooks": {}, "sql": {}}
    jobs: dict = {}
    root = ws / "factory" / "databricks"
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        parts = path.relative_to(root).parts
        text = path.read_text(encoding="utf-8")
        if parts[-1].endswith(".py"):
            files["notebooks"]["databricks:/" + "/".join(parts)[:-3]] = text
        elif len(parts) == 2 and parts[0] == "jobs" and parts[1].endswith(".json"):
            jobs[parts[1][:-5]] = json.loads(text)
        elif parts == ("compute.json",):
            files["compute"] = json.loads(text)
        elif parts == ("unity_catalog.json",):
            files["unity_catalog"] = json.loads(text)
        elif parts == ("grants.sql",):
            files["grants"] = text
        elif parts[-1].endswith(".sql"):
            files["sql"]["databricks:/" + "/".join(parts)] = text
    return files, jobs


def bi_payload(ws: Path) -> tuple[list[dict], dict | None]:
    folder = ws / "bi" / "warehouse"
    scripts = [{"path": f"bi/warehouse/{p.name}", "text": p.read_text(encoding="utf-8")}
               for p in sorted(folder.glob("*.sql"), key=lambda p: p.name)]
    model = ws / "bi" / "model.json"
    return scripts, json.loads(model.read_text(encoding="utf-8")) if model.is_file() else None


def dbt_files(ws: Path) -> dict[str, str]:
    root = ws / "bi" / "dbt"
    out = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root).as_posix()
        if any(part in ("target", "logs", "dbt_packages") for part in path.relative_to(root).parts[:-1]):
            continue
        if (relative == "dbt_project.yml" or re.search(r"\.(sql|yml|yaml|csv)$", relative)) and \
                relative not in ("profiles.yml", "packages.yml"):
            out[relative] = path.read_text(encoding="utf-8")
    return out


def json_array(document: dict, dotted: str) -> list:
    node = document
    for key in dotted.split("."):
        node = node[key]
    assert isinstance(node, list), dotted
    return node


class Walker:
    def __init__(self, client: TestClient, ws: Path, exercises: dict[str, dict]):
        self.client, self.ws, self.exercises = client, ws, exercises

    def post(self, url: str, body: dict) -> dict:
        response = self.client.post(url, json=body)
        assert response.status_code == 200, (url, response.status_code, response.text[:800])
        return response.json()

    def scaffold(self, project: Project, name: str) -> None:
        for relative, source in scaffold_files(project, name).items():
            target = self.ws / relative
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(source, Path):
                shutil.copyfile(source, target)
            else:
                target.write_text(source if source.endswith("\n") else source + "\n", encoding="utf-8")

    def text(self, relative: str) -> str:
        return (self.ws / relative).read_text(encoding="utf-8")

    def run(self, project: Project, action: dict) -> None:
        do = action["do"]
        reference = PROJECTS / project.id
        if do == "write":
            (self.ws / action["file"]).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(reference / action["from"], self.ws / action["file"])
        elif do == "append":
            with (self.ws / action["file"]).open("a", encoding="utf-8") as handle:
                handle.write("\n" + (reference / action["from"]).read_text(encoding="utf-8"))
        elif do == "replace":
            text = self.text(action["file"])
            assert text.count(action["old"]) == 1, (action["file"], action["old"])
            (self.ws / action["file"]).write_text(text.replace(action["old"], action["new"]), encoding="utf-8")
        elif do in ("json_insert", "json_set"):
            path = self.ws / action["file"]
            document = json.loads(path.read_text(encoding="utf-8"))
            items = json_array(document, action["array"])
            # The item is the one whose keys match `after` (insert after it) or `where` (set one of its keys).
            match = action["after"] if do == "json_insert" else action["where"]
            index = next(i for i, item in enumerate(items) if all(item.get(k) == v for k, v in match.items()))
            if do == "json_insert":
                items.insert(index + 1, json.loads((reference / action["from"]).read_text(encoding="utf-8")))
            else:
                items[index][action["key"]] = copy.deepcopy(action["value"])
            path.write_text(json.dumps(document, indent=2), encoding="utf-8")
        elif do == "import_csv":
            self.post("/api/local/import-csv", {"asset": action["asset"], "text": self.text(action["file"])})
        elif do in ("sql", "sparklab", "python", "polars"):
            if do in ("python", "polars") and not main.kernel_manager.trusted:
                # The learner enables trusted local Python explicitly; the runtime restarts with it.
                main.kernel_manager.trusted = True
                main.kernel_manager.restart(main.NATIVE_WORKSPACE_ID)
            run = self.post("/api/local/execute", {"language": do, "code": self.text(action["file"]),
                                                   "notebook_id": "vscode-" + do, "cell_id": "active-" + do})
            assert run["status"] == "success", (action, run.get("error"))
        elif do == "exercise":
            item = self.exercises[action["exercise"]]
            graded = self.post("/api/local/exercise", {
                "exercise_id": item["id"], "exercise_version": item["version"], "language": item["language"],
                "code": item["solution"], "mode": "submit", "notebook_id": f"exercise-{item['id']}", "cell_id": "solution",
                "source_revision": 0})
            assert graded["status"] == "passed", (action, [c for c in graded["checks"] if not c["passed"]][:2])
        elif do == "factory":
            files = factory_files(self.ws, action["flavor"])
            view = self.post("/api/local/factory/simulate", {
                "flavor": action["flavor"], "name": action["pipeline"], "document": files["pipelines"][action["pipeline"]],
                "files": files, "scenario": action.get("scenario", {}), "data_plane": action.get("data_plane", "local")})
            assert view["status"] == "simulated", (action, view.get("issues"))
        elif do == "sqlpool":
            view = self.post("/api/local/sqlpool/run", {"flavor": action["flavor"], "script": self.text(action["file"]),
                                                        "scale": action.get("scale", 1), "source": action["file"]})
            assert view["status"] == "ok", (action, [s for s in view["statements"] if s["status"] == "error"])
        elif do == "databricks":
            files, jobs = databricks_payload(self.ws)
            self.post("/api/local/databricks/run", {"name": action["job"], "document": jobs[action["job"]], "files": files,
                                                    "scenario": action.get("scenario", {}), "data_plane": "local"})
        elif do == "bi":
            scripts, model = bi_payload(self.ws)
            view = self.post("/api/local/bi/lab", {"scripts": scripts, "model": model, "run": action["mode"] == "build"})
            assert view["status"] == "ok", (action, view.get("stopped"))
        elif do == "dbt":
            self.post("/api/local/bi/dbt", {"files": dbt_files(self.ws), "command": action["command"],
                                            "select": action.get("select", [])})
        elif do == "airflow":
            view = self.post("/api/local/airflow/simulate", {"source": self.text(action["file"]),
                                                             "scenario": action.get("scenario", {})})
            assert view["status"] == "simulated", (action, view.get("error"))
        elif do == "pipeline_lab":
            self.post("/api/pipeline/run", {"source": self.text("pipelines/main.pipeline.py")})
        elif do == "retail_demo":
            self.post("/api/demo/retail/run", {"dataset_path": "datasets/retail_orders.csv"})
        else:
            raise AssertionError(f"unknown walkthrough action {do}")


def verify(client: TestClient, project_id: str) -> dict:
    response = client.post("/api/local/projects/check", json={"project_id": project_id})
    assert response.status_code == 200, response.text
    return response.json()


def main_smoke() -> None:
    projects = load_projects()
    exercises = exercise_catalog()
    validate_content(projects, exercises)
    automatic = sum(1 for p in projects for s in p.steps for _ in s.checks)

    with TemporaryDirectory(prefix="datapass-projects-smoke-") as temp:
        ws = Path(temp)
        previous = os.environ.get("DATAPASS_WORKSPACE_ROOT")
        os.environ["DATAPASS_WORKSPACE_ROOT"] = temp
        try:
            with TestClient(main.app) as client:
                # The route: content ids only, unknown projects and steps refused.
                assert client.post("/api/local/projects/check", json={"project_id": "nope"}).status_code == 404
                assert client.post("/api/local/projects/check", json={"project_id": "../x"}).status_code == 422
                assert client.post("/api/local/projects/check", json={"project_id": projects[0].id, "sql": "x"}).status_code == 422
                unknown = client.post("/api/local/projects/check", json={"project_id": projects[0].id, "steps": ["nope"]})
                assert unknown.status_code == 400, unknown.text

                # A fresh workspace: every automatic check fails, manual steps stay manual.
                for project in projects:
                    for step in verify(client, project.id)["steps"]:
                        if not project.steps[[s.id for s in project.steps].index(step["id"])].checks:
                            assert step["status"] == "manual" and step["checks"] == [], step
                            continue
                        passed = [c for c in step["checks"] if c["status"] == "passed"]
                        assert not passed, (project.id, step["id"], passed)

                walker = Walker(client, ws, exercises)
                starters = 0
                for project in projects:
                    walkthrough = json.loads((PROJECTS / project.id / "reference" / "walkthrough.json").read_text(encoding="utf-8"))
                    for step in project.steps:
                        for name in step.open.scaffold:
                            walker.scaffold(project, name)
                        # The untouched starter files must not complete the step (a starter may also fail to run).
                        for action in walkthrough.get("starters", {}).get(step.id, []):
                            try:
                                walker.run(project, action)
                            except AssertionError:
                                pass
                        if walkthrough.get("starters", {}).get(step.id):
                            starters += 1
                            [checked] = client.post("/api/local/projects/check", json={
                                "project_id": project.id, "steps": [step.id]}).json()["steps"]
                            assert checked["status"] == "failed", (project.id, step.id, "the starter already passes")
                        for action in walkthrough["steps"][step.id]:
                            walker.run(project, action)
                    result = verify(client, project.id)
                    failed = [(s["id"], c["label"], c["message"]) for s in result["steps"] for c in s["checks"]
                              if c["status"] != "passed"]
                    assert not failed, (project.id, failed)
                    truths = {c["truth"] for s in result["steps"] for c in s["checks"]}
                    assert truths <= {"real", "simulated", "emulation", "hybrid", "static"}, truths
                    print(f"{project.id}: {len(project.steps)} steps, "
                          f"{sum(1 for s in project.steps if s.checks)} verified automatically "
                          f"({sum(len(s.checks) for s in project.steps)} checks; truths {sorted(truths)}).")

                # Later projects in the same workspace can change shared tables; progress keeps the first success.
                for project in projects:
                    stale = [f"{s['id']}: {c['label']}" for s in verify(client, project.id)["steps"] for c in s["checks"]
                             if c["status"] != "passed"]
                    if stale:
                        print(f"{project.id}: after every walkthrough, {len(stale)} check(s) no longer hold: {stale}")

                journal = json.loads((ws / ".datapass" / "data" / "run_journal.json").read_text(encoding="utf-8"))
                assert journal["schema_version"] == 1 and journal["subjects"], journal
        finally:
            if previous is None:
                os.environ.pop("DATAPASS_WORKSPACE_ROOT", None)
            else:
                os.environ["DATAPASS_WORKSPACE_ROOT"] = previous
            main.kernel_manager.close()
            main.kernel_manager.trusted = False

    print(f"Datapass projects smoke passed: {len(projects)} projects, {automatic} automatic checks, "
          f"{starters} starters left unverified.")


if __name__ == "__main__":
    sys.exit(main_smoke())
