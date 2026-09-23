"""Official DuckDB/DuckLake local lakehouse profile.

DuckLake is the table/lakehouse layer. DuckDB is the authoritative local
compute/reference implementation. New Datapass DuckLake workspaces use a
SQLite metadata catalog and Parquet data files. Small-write data inlining is
disabled deliberately so the teaching workspace keeps visible Parquet files
and remains simple to inspect/interoperate with.

This module performs only server-owned initialization. Notebook SQL never
receives INSTALL/LOAD/ATTACH/CALL access.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path
from typing import Any


def _sql_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "''")


@dataclass(frozen=True)
class DuckLakeProfile:
    schema_version: int
    active: bool
    table_format: str
    compute_engine: str
    metadata_backend: str
    metadata_file: str
    data_format: str
    data_directory: str
    data_inlining_row_limit: int
    truth: str
    duckdb_version: str
    ducklake_extension_version: str | None
    sqlite_extension_version: str | None
    legacy_metadata: bool = False

    def contract(self) -> dict[str, Any]:
        return asdict(self)


def _extension_versions(db) -> dict[str, str | None]:
    rows = db.execute(
        """
        SELECT extension_name, extension_version
        FROM duckdb_extensions()
        WHERE extension_name IN ('ducklake', 'sqlite')
        """
    ).fetchall()
    return {str(name): (str(version) if version is not None else None) for name, version in rows}


def attach_ducklake(db, directory: Path) -> DuckLakeProfile:
    """Attach the workspace DuckLake through the official DuckDB extension.

    New workspaces use SQLite metadata. If the previous Datapass prototype's
    DuckDB-backed metadata file already exists, it is preserved in-place rather
    than silently orphaned; new workspaces never create that legacy format.
    """
    directory.mkdir(parents=True, exist_ok=True)
    data = directory / 'lake-files'
    data.mkdir(parents=True, exist_ok=True)

    legacy_metadata = directory / 'lake-catalog.ducklake'
    sqlite_metadata = directory / 'lake-metadata.sqlite'
    use_legacy = legacy_metadata.exists() and not sqlite_metadata.exists()
    metadata = legacy_metadata if use_legacy else sqlite_metadata
    metadata_backend = 'duckdb-legacy' if use_legacy else 'sqlite'

    install = os.environ.get('DATAPASS_INSTALL_DUCKLAKE') == '1'
    if install:
        db.execute('INSTALL ducklake')
        if not use_legacy:
            db.execute('INSTALL sqlite')

    try:
        db.execute('LOAD ducklake')
        if not use_legacy:
            db.execute('LOAD sqlite')
    except Exception as error:
        raise RuntimeError(
            'DuckLake mode requires the official DuckDB ducklake extension'
            + (' and sqlite extension' if not use_legacy else '')
            + '. Install them once with --install-ducklake (network required), '
              'or start with --storage duckdb for local DuckDB compatibility mode. '
              f'Original error: {error}'
        ) from error

    data_sql = _sql_path(data)
    metadata_sql = _sql_path(metadata)
    if use_legacy:
        attach = f"ATTACH 'ducklake:{metadata_sql}' AS lake (DATA_PATH '{data_sql}', DATA_INLINING_ROW_LIMIT 0)"
    else:
        attach = f"ATTACH 'ducklake:sqlite:{metadata_sql}' AS lake (DATA_PATH '{data_sql}', DATA_INLINING_ROW_LIMIT 0)"
    db.execute(attach)
    db.execute('USE lake')

    # DuckLake must keep access to its SQLite metadata and Parquet tree after
    # external access is disabled for learner-authored SQL.
    root = _sql_path(directory)
    db.execute(f"SET allowed_directories=['{root}']")

    versions = _extension_versions(db)
    duckdb_version = str(db.execute('SELECT version()').fetchone()[0])
    return DuckLakeProfile(
        schema_version=1,
        active=True,
        table_format='ducklake',
        compute_engine='duckdb',
        metadata_backend=metadata_backend,
        metadata_file=metadata.name,
        data_format='parquet',
        data_directory=data.name,
        data_inlining_row_limit=0,
        truth='real local DuckLake via the official DuckDB extension',
        duckdb_version=duckdb_version,
        ducklake_extension_version=versions.get('ducklake'),
        sqlite_extension_version=versions.get('sqlite'),
        legacy_metadata=use_legacy,
    )
