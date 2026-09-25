"""Catalog handoff: lend `.datapass/data/workspace.duckdb` to an external process (dbt Core, dct) and take it back.

DuckDB lets one process write a database file, and a read-only opener is refused while a writer holds it. The
runtime's kernel worker keeps the workspace catalog open, so a real `dbt build` or `dct render` in a terminal would
fail with an IO error. Releasing stops the worker gracefully (the connection is closed, the file lock is freed) and
refuses every catalog request until the catalog is reattached; reattaching reopens it through the worker.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
import threading

# DuckDB's messages when another process holds the file: Windows sharing violation, POSIX lock conflict.
LOCK_ERROR = re.compile(r'being used by another process|Could not set lock|Conflicting lock', re.I)


class CatalogReleased(Exception):
    """A catalog request while the catalog is lent to an external process."""


class CatalogLocked(Exception):
    """The catalog file is held by another process the runtime did not lend it to."""


def is_lock_error(error: BaseException) -> bool:
    return bool(LOCK_ERROR.search(str(error)))


class CatalogLease:
    def __init__(self):
        self._lock = threading.Lock()
        self.holder: str | None = None
        self.since: str | None = None

    def view(self) -> dict:
        with self._lock:
            return {'attached': self.holder is None, 'holder': self.holder, 'since': self.since}

    def hold(self, holder: str) -> None:
        with self._lock:
            self.holder = holder
            self.since = datetime.now(timezone.utc).isoformat(timespec='seconds')

    def clear(self) -> str | None:
        with self._lock:
            previous, self.holder, self.since = self.holder, None, None
            return previous

    def check(self) -> None:
        with self._lock:
            if self.holder is not None:
                raise CatalogReleased(
                    f'The catalog is lent to "{self.holder}" (since {self.since} UTC). '
                    'Datapass reattaches it when that run ends; or use Reattach catalog.')
