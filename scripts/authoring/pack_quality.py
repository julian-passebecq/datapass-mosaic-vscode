"""Write a pack's test-only quality data: content/exercise-packs/<pack>/quality.json.

`scripts/exercise_packs_smoke.py` reads it (mutants that must run and fail, gate flags,
notes); the VSIX leaves it out. See docs/EXERCISE_AUTHORING.md "Quality gate".
"""
from __future__ import annotations

import json
from pathlib import Path


def write_mutants(pack: Path, mutants: dict[str, list[str]], *, replace_all: bool = False) -> None:
    """Store the generated mutants of these exercises in <pack>/quality.json.

    Flags and notes are kept. Mutants of other exercises are kept too, unless
    `replace_all` says the generator owns the whole mutant list of the pack.
    """
    path = pack / "quality.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    current = {} if replace_all else dict(data.get("mutants", {}))
    current.update({ident: list(items) for ident, items in mutants.items() if items})
    out = {key: data[key] for key in ("flags", "notes") if data.get(key)}
    out["mutants"] = current
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
