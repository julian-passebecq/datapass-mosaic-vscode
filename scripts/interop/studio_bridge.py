"""Calls Mosaic Studio's own py/service/notebook_io.py (import_notebook / export_notebook) for studio_roundtrip.py.

Run with `python -I studio_bridge.py <folder holding a copy of notebook_io.py>`; reads one JSON request on stdin:
{"op": "import", "text": "<ipynb>"} or {"op": "export", "payload": {cells, outputs, executionCounts, results}}, and
prints {"ok": true, "result": ...} or {"ok": false, "error": "..."}. Studio's code runs nothing: it maps text.
"""
from __future__ import annotations

import json
import sys

sys.path.insert(0, sys.argv[1])
import notebook_io  # noqa: E402  (Studio's module, from the copy above)

request = json.loads(sys.stdin.read())
try:
    if request["op"] == "import":
        result = notebook_io.import_notebook(request["text"])
    elif request["op"] == "export":
        result = notebook_io.export_notebook(request["payload"])
    else:
        raise ValueError(f"unknown op {request['op']}")
    print(json.dumps({"ok": True, "result": result}))
except notebook_io.NotebookError as error:
    print(json.dumps({"ok": False, "error": str(error)}))
