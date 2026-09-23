"""Atomic metadata replacement with bounded retries for Windows sharing locks."""
import os
from pathlib import Path
import time


def replace_file(source: Path, destination: Path):
    for attempt in range(6):
        try:
            source.replace(destination)
            return
        except PermissionError:
            if os.name != 'nt' or attempt == 5:
                raise
            time.sleep(0.02 * 2 ** attempt)
