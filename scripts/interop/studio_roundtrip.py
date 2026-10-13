"""Round trip between this extension's .ipynb reader/writer (src/platform/studioNotebook.ts) and Mosaic Studio's own
py/service/notebook_io.py, from a local Studio checkout. Local only: CI has no Studio checkout and skips.

    DATAPASS_MOSAICSTUDIO=<path to a Mosaic Studio checkout> python scripts/interop/studio_roundtrip.py [--write-fixtures]

(a) Studio's notebook_io.py is copied to a temporary folder and run with `python -I` in a venv under %TEMP% holding
    the nbformat pinned by Studio's py/service/requirements-jupyter.txt (pip is the only network use).
(b) Every .ipynb this extension exports (a sample folder of .md/.sql/.py files, and each committed fixture imported
    then exported back from its record) goes into Studio's import_notebook: ids, kinds, titles, sources, charts,
    output tables and dependsOn must survive, with no dependency or cell in Studio's loss report.
(c) Studio's sample notebooks (py/notebooks, qa) and a payload covering every cell kind are exported by Studio's own
    export_notebook; this extension's importer must read each one losslessly (same cells as Studio's own import).
--write-fixtures writes the (c) exports to content/interop/examples/studio/ and records the Studio commit in its README.
Nothing is executed on either side: both sides map text.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CLI = REPO / "scripts" / "interop" / "studio_notebook_cli.mjs"
BRIDGE = REPO / "scripts" / "interop" / "studio_bridge.py"
FIXTURES = REPO / "content" / "interop" / "examples" / "studio"

# Every Studio cell kind, synthetic; exported by Studio's own export_notebook into studio-all-kinds.ipynb.
ALL_KINDS = {
    "cells": [
        {"id": "intro", "kind": "note", "title": "Sensor demo", "text": "# Sensor demo (synthetic)\nEvery row is generated; nothing here is real data.", "dependsOn": []},
        {"id": "make-readings", "kind": "jupyter", "title": "Make readings", "code": "readings = [{\"sensor\": s, \"step\": i, \"value\": (i * 7 + s) % 11} for s in range(3) for i in range(8)]\nprint(len(readings), \"synthetic rows\")\n", "outputTable": "readings", "dependsOn": []},
        {"id": "daily", "kind": "sql", "title": "Average by sensor", "sql": "SELECT sensor, avg(value)::DOUBLE AS mean_value\nFROM readings\nGROUP BY sensor\nORDER BY sensor", "chart": {"kind": "bar", "x": "sensor", "y": "mean_value"}, "dependsOn": ["make-readings"]},
        {"id": "ramp-model", "kind": "python", "title": "Synthetic ramp model", "model": "synthetic_ramp", "inputs": {"slope": 0.5, "steps": 12}, "outputTable": "ramp", "dependsOn": []},
        {"id": "joined", "kind": "sql", "title": "Sensors next to the ramp", "sql": "SELECT d.sensor, d.mean_value, r.*\nFROM daily AS d\nCROSS JOIN (SELECT count(*) AS ramp_rows FROM ramp) AS r", "dependsOn": ["daily", "ramp-model"]},
        {"id": "raw-notes", "kind": "inert", "title": "Raw notes", "original": json.dumps({"cell_type": "raw", "id": "raw-notes", "metadata": {}, "source": "Raw text, kept verbatim and never run."}), "reason": "raw cell", "dependsOn": []},
    ],
    "outputs": {}, "executionCounts": {}, "results": {},
}

failures: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + label + (f" ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(label)


def studio_python(studio: Path) -> Path:
    pins = (studio / "py" / "service" / "requirements-jupyter.txt").read_text(encoding="utf-8")
    match = re.search(r"^nbformat==([0-9][0-9A-Za-z.]*)\s*$", pins, re.M)
    if not match:
        raise SystemExit("Studio's requirements-jupyter.txt pins no nbformat version")
    venv = Path(tempfile.gettempdir()) / f"datapass-studio-nbformat-{match.group(1)}"
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.exists():
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
        subprocess.run([str(python), "-m", "pip", "install", "-q", "--disable-pip-version-check", f"nbformat=={match.group(1)}"], check=True)
    return python


class Studio:
    def __init__(self, checkout: Path) -> None:
        self.copy = Path(tempfile.mkdtemp(prefix="datapass-studio-io-"))
        shutil.copy2(checkout / "py" / "service" / "notebook_io.py", self.copy / "notebook_io.py")
        self.python = studio_python(checkout)

    def call(self, request: dict) -> dict:
        out = subprocess.run([str(self.python), "-I", str(BRIDGE), str(self.copy)], input=json.dumps(request), capture_output=True,
                             text=True, encoding="utf-8", cwd=self.copy)
        if out.returncode != 0:
            raise RuntimeError(out.stderr[-2000:])
        return json.loads(out.stdout)

    def import_notebook(self, text: str) -> dict:
        answer = self.call({"op": "import", "text": text})
        if not answer["ok"]:
            raise RuntimeError("Studio import refused: " + answer["error"])
        return answer["result"]

    def export_notebook(self, payload: dict) -> str:
        answer = self.call({"op": "export", "payload": payload})
        if not answer["ok"]:
            raise RuntimeError("Studio export refused: " + answer["error"])
        return answer["result"]

    def close(self) -> None:
        shutil.rmtree(self.copy, ignore_errors=True)


def ours(op: str, target: Path) -> dict:
    out = subprocess.run(["node", str(CLI), op, str(target)], capture_output=True, text=True, encoding="utf-8", cwd=REPO)
    if out.returncode != 0:
        raise RuntimeError(out.stderr[-2000:])
    return json.loads(out.stdout)


def _original(text: str) -> dict:
    cell = json.loads(text)
    if isinstance(cell.get("source"), list):  # nbformat: a list of lines and the joined text are the same source
        cell["source"] = "".join(cell["source"])
    return {k: v for k, v in cell.items() if k not in ("outputs", "execution_count", "id")}


def studio_view(cell: dict) -> dict:
    """A cell of Studio's import, as comparable facts."""
    kind = cell["kind"]
    content: object = {"note": cell.get("text"), "sql": cell.get("sql"), "jupyter": cell.get("code")}.get(kind)
    if kind == "python":
        content = {"model": cell["model"], "inputs": cell["inputs"], **({"outputTable": cell["outputTable"]} if "outputTable" in cell else {})}
    if kind == "inert":
        content = _original(cell["original"])
    view = {"id": cell["id"], "kind": kind, "title": cell["title"], "content": content, "dependsOn": cell["dependsOn"]}
    if kind == "sql" and "chart" in cell:
        view["chart"] = cell["chart"]
    if kind == "jupyter" and "outputTable" in cell:
        view["outputTable"] = cell["outputTable"]
    return view


def our_view(cell: dict) -> dict:
    """A cell of this extension's import, as the same facts."""
    kind = cell["kind"]
    content: object = cell["content"]
    if kind == "python":
        content = json.loads(cell["content"])
    if kind == "inert":
        content = _original(cell["content"])
    view = {"id": cell["id"], "kind": kind, "title": cell["title"], "content": content, "dependsOn": cell["dependsOn"]}
    dp = (cell.get("metadata") or {}).get("datapass") or {}
    if kind == "sql" and isinstance(dp.get("chart"), dict):
        view["chart"] = dp["chart"]
    if kind == "jupyter" and isinstance(dp.get("outputTable"), str):
        view["outputTable"] = dp["outputTable"]
    return view


def same(a: list[dict], b: list[dict]) -> tuple[bool, str]:
    if a == b:
        return True, ""
    for x, y in zip(a, b):
        if x != y:
            return False, f"{json.dumps(x)[:300]} != {json.dumps(y)[:300]}"
    return False, f"{len(a)} cells != {len(b)} cells"


def bad_loss(loss: list[dict]) -> list[dict]:
    return [item for item in loss if item["item"] in ("dependency", "cell") and "kept inert" not in item.get("detail", "")]


def studio_sha(checkout: Path) -> str:
    out = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"], capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else os.environ.get("DATAPASS_MOSAICSTUDIO_SHA", "unknown (not a git checkout)")


def main() -> int:
    location = os.environ.get("DATAPASS_MOSAICSTUDIO")
    if not location:
        print("SKIP studio_roundtrip: DATAPASS_MOSAICSTUDIO is not set (it names a local Mosaic Studio checkout; CI has none).")
        return 0
    checkout = Path(location).resolve()
    if not (checkout / "py" / "service" / "notebook_io.py").is_file():
        print(f"FAIL {checkout} has no py/service/notebook_io.py")
        return 1
    write = "--write-fixtures" in sys.argv[1:]
    sha = studio_sha(checkout)
    print(f"Mosaic Studio checkout {checkout} at {sha}")
    studio = Studio(checkout)
    work = Path(tempfile.mkdtemp(prefix="datapass-studio-roundtrip-"))
    try:
        # (c) Studio's own exports of its sample notebooks and of every cell kind; our importer reads them losslessly.
        samples = sorted((checkout / "py" / "notebooks").glob("*.ipynb")) + sorted((checkout / "qa").rglob("*.ipynb"))
        exports: dict[str, str] = {}
        for sample in samples:
            imported = studio.import_notebook(sample.read_text(encoding="utf-8"))
            exports[f"studio-{re.sub(r'[^a-z0-9-]+', '-', sample.stem.lower())}.ipynb"] = studio.export_notebook(
                {"cells": imported["cells"], "outputs": {}, "executionCounts": {}, "results": imported["results"]})
        exports["studio-all-kinds.ipynb"] = studio.export_notebook(ALL_KINDS)
        if write:
            FIXTURES.mkdir(parents=True, exist_ok=True)
            for name, text in exports.items():
                (FIXTURES / name).write_text(text, encoding="utf-8", newline="\n")
            readme = (FIXTURES / "README.md")
            body = readme.read_text(encoding="utf-8") if readme.exists() else ""
            body = re.sub(r"(?m)^Studio commit: .*$", f"Studio commit: {sha}", body) if "Studio commit:" in body else body + f"\nStudio commit: {sha}\n"
            readme.write_text(body, encoding="utf-8", newline="\n")
            print(f"wrote {len(exports)} fixtures to {FIXTURES}")
        for name, text in exports.items():
            path = work / name
            path.write_text(text, encoding="utf-8", newline="\n")
            mine = ours("import", path)
            check(mine["ok"], f"(c) our importer reads Studio's export {name}", "; ".join(mine.get("errors", [])))
            if mine["ok"]:
                ok, detail = same([our_view(c) for c in mine["notebook"]["cells"]], [studio_view(c) for c in studio.import_notebook(text)["cells"]])
                check(ok, f"(c) {name}: same cells, kinds, sources, titles, charts, output tables and dependsOn as Studio's import", detail)
        check(len(samples) >= 1, "(c) Studio has sample notebooks", str(checkout))

        # (b) our exports into Studio's import_notebook.
        folder = work / "sample-folder"
        folder.mkdir()
        (folder / "01-intro.md").write_text("# Orders sample\nSynthetic rows, made up for this check.\n", encoding="utf-8", newline="\n")
        (folder / "02-orders.sql").write_text("SELECT 1 AS order_id, 'north' AS region, 12.5 AS amount\n", encoding="utf-8", newline="\n")
        (folder / "03-clean.py").write_text("rows = [{'order_id': 1, 'amount': 12.5}]\nprint(len(rows), 'rows')\n", encoding="utf-8", newline="\n")
        built = ours("export-folder", folder)
        check(built["ok"], "(b) our exporter writes the sample folder", "; ".join(built.get("errors", [])))
        if built["ok"]:
            back = studio.import_notebook(built["text"])
            expected = [("note", (folder / "01-intro.md").read_text(encoding="utf-8")), ("sql", (folder / "02-orders.sql").read_text(encoding="utf-8")),
                        ("jupyter", (folder / "03-clean.py").read_text(encoding="utf-8"))]
            got = [(c["kind"], c.get("text") or c.get("sql") or c.get("code")) for c in back["cells"]]
            check(got == expected, "(b) sample folder: Studio imports note, sql and jupyter with the files' exact text", f"{got}")
            check(not bad_loss(back["loss"]), "(b) sample folder: nothing in Studio's loss report", json.dumps(back["loss"])[:300])
        fixtures = sorted(FIXTURES.glob("*.ipynb"))
        check(len(fixtures) >= 3, "(b) committed fixtures present", str(FIXTURES))
        for fixture in fixtures:
            mine = ours("import", fixture)
            again = ours("export-record", fixture)
            check(mine["ok"] and again["ok"], f"(b) {fixture.name}: our import then export from the record", "; ".join(mine.get("errors", []) + again.get("errors", [])))
            if not (mine["ok"] and again["ok"]):
                continue
            back = studio.import_notebook(again["text"])
            ok, detail = same([studio_view(c) for c in back["cells"]], [our_view(c) for c in mine["notebook"]["cells"]])
            check(ok, f"(b) {fixture.name}: Studio's import of our export has the same cells and dependsOn", detail)
            check(not bad_loss(back["loss"]), f"(b) {fixture.name}: no dependency or cell lost in Studio's report", json.dumps(back["loss"])[:300])
            ok, detail = same([studio_view(c) for c in studio.import_notebook(fixture.read_text(encoding="utf-8"))["cells"]], [our_view(c) for c in mine["notebook"]["cells"]])
            check(ok, f"(b) {fixture.name}: our import equals Studio's import of the committed file", detail)
            drift = {k: v for k, v in exports.items() if k == fixture.name}
            if drift:
                strip = lambda text: re.sub(r'"exportedAt": "[^"]*"', "", text)  # noqa: E731
                same_text = strip(drift[fixture.name]) == strip(fixture.read_text(encoding="utf-8"))
                print(("PASS " if same_text else "INFO ") + f"{fixture.name} {'matches' if same_text else 'differs from'} Studio's export at {sha[:12]} (exportedAt aside)")
    finally:
        studio.close()
        shutil.rmtree(work, ignore_errors=True)
    print(f"\n{'FAILED' if failures else 'OK'}: Studio round trip at {sha}" + (f", {len(failures)} failure(s)" if failures else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
