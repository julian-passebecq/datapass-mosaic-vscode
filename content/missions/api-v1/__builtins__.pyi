# Names the API Lab puts in scope when it runs a mission's ingest.py (runtime/apilab/runner.py), for Pylance only.
# Copied next to ingest.py when a mission starts; nothing here runs.
from typing import Any, Iterable, Mapping

API_BASE_URL: str
"""The simulated API's base URL on loopback, e.g. http://127.0.0.1:<port> (see API.md)."""
API_KEY: str
"""The mission's API key, sent as `Authorization: Bearer <API_KEY>`."""

class _Bronze:
    """`bronze.append / merge / overwrite / query / columns` over tables of the catalog's bronze layer."""
    def append(self, table: str, rows: Iterable[Mapping[str, Any]], evolve: bool = False) -> int:
        """Insert the rows as they are (duplicates stay duplicates)."""
        ...
    def overwrite(self, table: str, rows: Iterable[Mapping[str, Any]]) -> int:
        """Replace the whole table with these rows (its schema too)."""
        ...
    def merge(self, table: str, rows: Iterable[Mapping[str, Any]], key: str, evolve: bool = False) -> int:
        """Upsert on `key`: a row whose key is already in the table replaces it; within `rows`, the last one wins."""
        ...
    def query(self, sql: str) -> list[dict[str, Any]]:
        """A read-only query on the catalog (for example your watermark: SELECT max(updated_at) ...)."""
        ...
    def columns(self, table: str) -> list[str]:
        """The table's columns, or [] when it does not exist yet."""
        ...

bronze: _Bronze
