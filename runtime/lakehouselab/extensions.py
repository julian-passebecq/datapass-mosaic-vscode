"""The DuckDB ducklake and delta extensions: installed once by "Setup runtime" (network), then only ever loaded.

DuckDB keeps extensions per user and DuckDB version (~/.duckdb/extensions/<version>/<platform>/), so one install serves
every later start, offline. Nothing else in the Lakehouse Lab downloads anything: the connection used for the
learner's SQL has extension auto-install and auto-load turned off.
"""
from __future__ import annotations

from functools import lru_cache


EXTENSIONS = ('ducklake', 'delta')


def _status(install: bool) -> dict:
    """`installed` / `version` describe ducklake; `delta` / `delta_version` the delta extension (Delta tables)."""
    try:
        import duckdb
    except ImportError as error:
        return {'installed': False, 'version': None, 'delta': False, 'error': f'DuckDB is not installed ({error}).'}
    db = duckdb.connect(config={'autoinstall_known_extensions': False, 'autoload_known_extensions': False})
    error = None
    try:
        if install:
            for name in EXTENSIONS:
                try:
                    db.execute(f'INSTALL {name}')
                except Exception as failure:  # offline, proxy, firewall: reported, never fatal
                    error = error or str(failure).splitlines()[0][:300]
        rows = {name: (bool(installed), version) for name, installed, version in db.execute(
            "SELECT extension_name, installed, extension_version FROM duckdb_extensions() "
            "WHERE extension_name IN ('ducklake', 'delta')").fetchall()}
        ducklake, delta = rows.get('ducklake', (False, None)), rows.get('delta', (False, None))
        return {'installed': ducklake[0], 'version': str(ducklake[1]) if ducklake[1] else None,
                'delta': delta[0], 'delta_version': str(delta[1]) if delta[1] else None,
                'duckdb': duckdb.__version__, 'error': error}
    finally:
        db.close()


@lru_cache(maxsize=1)
def _cached() -> dict:
    return _status(False)


def ducklake_status(refresh: bool = False) -> dict:
    """Whether the ducklake and delta extensions are installed for this DuckDB (read locally, no network)."""
    if refresh:
        _cached.cache_clear()
    status = _cached()
    return status if status['installed'] and status['delta'] else _status(False)


def setup_install() -> None:
    """Called by "Setup runtime": install the extensions when the network allows; say so either way, never fail."""
    status = _status(True)
    if status['installed'] and status['delta']:
        print(f'DuckLake and Delta extensions ready ({status["version"]}, {status["delta_version"]}).')
    else:
        print("DuckLake / Delta extensions not installed (no network?): the Lakehouse Lab's Parquet missions work; its "
              f'DuckLake and Delta missions need "Setup runtime" once online. {status.get("error") or ""}'.strip())


if __name__ == '__main__':
    setup_install()
