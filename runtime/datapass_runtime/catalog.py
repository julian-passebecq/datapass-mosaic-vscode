"""One catalog per workspace, owned by its kernel worker.

DuckDB is the local analytical engine. DuckLake is the canonical lakehouse
profile when explicitly selected: the official DuckDB extension owns the
format, SQLite owns new-workspace metadata and Parquet owns table data.
SQLite compatibility mode remains an explicit dependency fallback.

This is a LOCAL learning service, not an untrusted multi-tenant SQL service.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from decimal import Decimal
from pathlib import Path
import re
import sqlite3
from typing import Any
import uuid
from .atomic import replace_file
from .lakehouse import attach_ducklake

LAYERS = ('source', 'bronze', 'silver', 'gold', 'warehouse', 'features', 'metrics')
IDENT = re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,62}$')
ASSET = re.compile(r'^(source|bronze|silver|gold|warehouse|features|metrics)\.([A-Za-z][A-Za-z0-9_]{0,62})$')
MAX_ROWS = 200


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def asset_name(name: str) -> str:
    if not ASSET.fullmatch(name):
        raise ValueError('Use a registered layer and simple table name, for example gold.revenue.')
    return name


def json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Decimal):
        if not value.is_finite():
            return None
        number = float(value)
        # JSON consumers use IEEE-754 numbers. Preserve precision-sensitive
        # decimals as strings instead of silently rounding them for a chart.
        return number if math.isfinite(number) and Decimal(str(number)) == value else str(value)
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value)


def sql_tokens(sql: str) -> str:
    """Remove literals/comments before checking command tokens, not a SQL parser."""
    return re.sub(r"'(?:''|[^'])*'|--[^\n]*|/\*[\s\S]*?\*/", ' ', sql)


def statements(sql: str) -> list[str]:
    # sqlite's lexer recognizes quoted semicolons. It does not execute SQL.
    out, current = [], ''
    for char in sql:
        current += char
        if char == ';' and sqlite3.complete_statement(current):
            if sql_tokens(current).strip(' ;\r\n\t'):
                out.append(current.strip())
            current = ''
    if sql_tokens(current).strip(' ;\r\n\t'):  # \r: files with Windows line endings
        out.append(current.strip())
    if not out or len(out) > 20:
        raise ValueError('Submit between 1 and 20 SQL statements.')
    return out


def validate_sql(sql: str, *, read_only: bool = False) -> list[str]:
    if len(sql) > 40_000:
        raise ValueError('SQL exceeds the 40,000-character limit.')
    result = statements(sql)
    if read_only and len(result) != 1:
        raise ValueError('A materialized output must be one SELECT or WITH query.')
    for statement in result:
        clean = sql_tokens(statement).strip()
        first = re.match(r'[A-Za-z]+', clean)
        first = first.group().upper() if first else ''
        allowed = {'SELECT', 'WITH'} if read_only else {'SELECT', 'WITH', 'CREATE', 'INSERT', 'UPDATE', 'DELETE', 'DROP', 'MERGE'}
        if first not in allowed:
            raise ValueError(f'{first or "This statement"} is outside the local SQL teaching contract.')
        # External I/O is intentionally not exposed through arbitrary SQL.
        if re.search(r'\b(ATTACH|DETACH|INSTALL|LOAD|COPY|EXPORT|IMPORT|SECRET|PRAGMA|CALL|VACUUM|CHECKPOINT|TRUNCATE)\b', clean, re.I):
            raise ValueError('External I/O, extension loading and configuration commands are not allowed in cells.')
        if re.search(r'\b(read_[A-Za-z0-9_]*|sqlite_scan|postgres_scan|httpfs|load_extension|writefile|readfile)\s*\(', clean, re.I):
            raise ValueError('Use the workspace catalog, not filesystem or network table functions.')
        if re.search(r'\b(_datapass|sqlite_master|sqlite_schema)\b', clean, re.I):
            raise ValueError('Internal catalog metadata is not a learning asset.')
        if first == 'CREATE' and not re.match(r'CREATE\s+(OR\s+REPLACE\s+)?(TABLE|VIEW)\b', clean, re.I):
            raise ValueError('Only CREATE TABLE or CREATE VIEW is supported in SQL cells.')
    return result


def references(sql: str) -> list[str]:
    return sorted(set(m.group(1) for m in re.finditer(r'\b(?:FROM|JOIN)\s+((?:source|bronze|silver|gold|warehouse|features|metrics)\.[A-Za-z][A-Za-z0-9_]*)', sql_tokens(sql), re.I)))


class Catalog:
    def __init__(self, directory: Path, mode: str = 'auto'):
        self.directory = directory
        self.import_directory = directory / 'imports'
        directory.mkdir(parents=True, exist_ok=True)
        has_duckdb = importlib.util.find_spec('duckdb') is not None
        if mode not in {'auto', 'duckdb', 'ducklake', 'sqlite'}:
            raise ValueError('Unknown storage mode.')
        if mode in {'duckdb', 'ducklake'} and not has_duckdb:
            raise RuntimeError('DuckDB is not installed. Install requirements-engines.txt; no silent storage substitution was made.')
        self.kind = ('duckdb' if has_duckdb else 'sqlite') if mode == 'auto' else mode
        self.metadata_path = directory / 'asset-lineage.json'
        try:
            self.versions = json.loads(self.metadata_path.read_text())
        except FileNotFoundError:
            self.versions = {}
        self.guard = False
        self.lakehouse = None
        self._duckdb_capability = None
        if self.kind == 'sqlite':
            self.db = sqlite3.connect(directory / 'workspace.sqlite3')
            self.db.enable_load_extension(False)
            for layer in LAYERS:
                self.db.execute(f'ATTACH DATABASE ? AS {layer}', (str(directory / f'{layer}.sqlite3'),))
            self.db.set_authorizer(self._authorize)
        else:
            import duckdb
            self.db = duckdb.connect(str(directory / 'workspace.duckdb'))
            self.db.execute("SET threads=2")
            self.db.execute("SET memory_limit='512MB'")
            if self.kind == 'ducklake':
                self.lakehouse = attach_ducklake(self.db, directory)
            else:
                version = str(self.db.execute('SELECT version()').fetchone()[0])
                extension = self.db.execute(
                    "SELECT installed, extension_version FROM duckdb_extensions() WHERE extension_name='ducklake'"
                ).fetchone()
                self._duckdb_capability = {
                    'version': version,
                    'ducklake_extension_installed': bool(extension and extension[0]),
                    'ducklake_extension_version': str(extension[1]) if extension and extension[1] is not None else None,
                }
            for layer in LAYERS:
                self.db.execute(f'CREATE SCHEMA IF NOT EXISTS {layer}')
            if self.kind == 'duckdb':
                # Mosaic file imports (local_data.import_file) stage a copy of the learner's Parquet/JSON here for
                # one import. Only this runtime-owned folder stays readable; cell SQL still cannot call file
                # functions (validate_sql). DuckLake mode already allows its whole data folder (lakehouse.py).
                staging = (self.import_directory.resolve().as_posix() + '/').replace("'", "''")
                self.db.execute(f"SET allowed_directories=['{staging}']")
            # After controlled initialization, notebook SQL cannot read arbitrary files.
            self.db.execute('SET enable_external_access=false')
        self._seed()

    def _authorize(self, action, arg1, arg2, db_name, source):
        if not self.guard:
            return sqlite3.SQLITE_OK
        blocked = {sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH, sqlite3.SQLITE_PRAGMA}
        if action in blocked:
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION and str(arg2).lower() in {'load_extension', 'readfile', 'writefile'}:
            return sqlite3.SQLITE_DENY
        if action in {sqlite3.SQLITE_READ, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_INSERT, sqlite3.SQLITE_DELETE} and db_name not in LAYERS:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    def _save_versions(self):
        tmp = self.metadata_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.versions, indent=2))
        replace_file(tmp, self.metadata_path)

    def _touch(self, name: str, dependencies: list[str], producer: str):
        self.versions[name] = {
            'version': uuid.uuid4().hex,
            'producer': producer,
            'inputs': {key: self.versions.get(key, {}).get('version') for key in dependencies if key != name},
        }
        self._save_versions()

    def _seed(self):
        if self.exists('source.orders'):
            return
        self.db.execute('CREATE TABLE source.orders (order_id VARCHAR, customer_id VARCHAR, segment_id INTEGER, net_amount DOUBLE, loaded_at VARCHAR)')
        rows = [
            ('O-001','C001',1,100.0),('O-002','C001',1,50.0),('O-003','C002',2,200.0),
            ('O-004','C003',2,-10.0),('O-005','CORPORATE_ACCOUNT_01',3,1000.0),
            ('O-006','CORPORATE_ACCOUNT_01',3,1500.0),('O-007','CORPORATE_ACCOUNT_01',3,2000.0),
            ('O-008','C002',2,25.0),('O-009','C004',1,0.0),('O-010','C005',2,75.0),
            ('O-011','C005',2,25.0),('O-012','C006',4,10.0),
        ]
        self.db.executemany('INSERT INTO source.orders VALUES (?,?,?,?,?)', [(*r, f'2026-09-17T01:{i:02d}:00') for i, r in enumerate(rows)])
        self.db.execute('CREATE TABLE source.dim_customer_segment (segment_id INTEGER, segment_name VARCHAR)')
        self.db.executemany('INSERT INTO source.dim_customer_segment VALUES (?,?)', [(1,'Consumer'),(2,'Small Business'),(3,'Corporate'),(4,'Public Sector')])
        self.db.execute('CREATE TABLE source.turbine_readings (sample_id INTEGER, turbine_id VARCHAR, wind_speed DOUBLE, actual_power DOUBLE)')
        self.db.executemany('INSERT INTO source.turbine_readings VALUES (?,?,?,?)', [(i, 'T-01', float(i+3), float(2*(i+3)+4)) for i in range(1,19)])
        if self.kind == 'sqlite':
            self.db.commit()
        for asset in ('source.orders', 'source.dim_customer_segment', 'source.turbine_readings'):
            self._touch(asset, [], 'deterministic seed v1')

    def exists(self, name: str) -> bool:
        layer, table = asset_name(name).split('.')
        if self.kind == 'sqlite':
            return bool(self.db.execute(f"SELECT name FROM {layer}.sqlite_master WHERE type IN ('table','view') AND name=?", (table,)).fetchone())
        return bool(self.db.execute('SELECT table_name FROM information_schema.tables WHERE table_catalog=current_database() AND table_schema=? AND table_name=?', [layer, table]).fetchone())

    def fresh(self, name: str, seen: set[str] | None = None) -> bool:
        seen = set() if seen is None else set(seen)
        if name in seen or not self.exists(name) or name not in self.versions:
            return False
        seen.add(name)
        for dependency, version in self.versions[name]['inputs'].items():
            if self.versions.get(dependency, {}).get('version') != version or not self.fresh(dependency, seen):
                return False
        return True

    def _ducklake_metadata_connection(self):
        if self.kind != 'ducklake' or self.lakehouse is None or self.lakehouse.metadata_backend != 'sqlite':
            return None
        path = (self.directory / self.lakehouse.metadata_file).resolve()
        if not path.exists():
            return None
        return sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True)

    def _ducklake_partition_evidence(self, layer: str, table: str) -> dict | None:
        metadata = self._ducklake_metadata_connection()
        if metadata is None:
            return None
        try:
            table_row = metadata.execute(
                """
                SELECT t.table_id
                FROM ducklake_table t
                JOIN ducklake_schema s ON s.schema_id=t.schema_id
                WHERE s.schema_name=? AND t.table_name=?
                  AND s.end_snapshot IS NULL AND t.end_snapshot IS NULL
                ORDER BY t.begin_snapshot DESC
                LIMIT 1
                """,
                (layer, table),
            ).fetchone()
            if table_row is None:
                return None
            table_id = int(table_row[0])
            partition_row = metadata.execute(
                """
                SELECT partition_id
                FROM ducklake_partition_info
                WHERE table_id=? AND end_snapshot IS NULL
                ORDER BY begin_snapshot DESC
                LIMIT 1
                """,
                (table_id,),
            ).fetchone()
            if partition_row is None:
                return {
                    'partitioned': False,
                    'partition_id': None,
                    'columns': [],
                    'truth': 'measured DuckLake catalog metadata',
                }
            partition_id = int(partition_row[0])
            columns = metadata.execute(
                """
                SELECT pc.partition_key_index, c.column_name, c.column_type, pc.transform
                FROM ducklake_partition_column pc
                JOIN ducklake_column c
                  ON c.table_id=pc.table_id AND c.column_id=pc.column_id
                WHERE pc.table_id=? AND pc.partition_id=? AND c.end_snapshot IS NULL
                ORDER BY pc.partition_key_index
                """,
                (table_id, partition_id),
            ).fetchall()
            values = metadata.execute(
                """
                SELECT
                    fpv.partition_key_index,
                    fpv.partition_value,
                    COUNT(DISTINCT df.data_file_id) AS file_count,
                    COALESCE(SUM(df.file_size_bytes), 0) AS size_bytes,
                    COALESCE(SUM(df.record_count), 0) AS record_count
                FROM ducklake_data_file df
                JOIN ducklake_file_partition_value fpv
                  ON fpv.data_file_id=df.data_file_id AND fpv.table_id=df.table_id
                WHERE df.table_id=? AND df.end_snapshot IS NULL AND df.partition_id=?
                GROUP BY fpv.partition_key_index, fpv.partition_value
                ORDER BY fpv.partition_key_index, fpv.partition_value
                """,
                (table_id, partition_id),
            ).fetchall()
            by_index: dict[int, list[dict]] = {}
            for key_index, value, file_count, size_bytes, record_count in values:
                by_index.setdefault(int(key_index), []).append({
                    'value': str(value),
                    'file_count': int(file_count or 0),
                    'size_bytes': int(size_bytes or 0),
                    'record_count': int(record_count or 0),
                })
            return {
                'partitioned': True,
                'partition_id': partition_id,
                'columns': [
                    {
                        'key_index': int(key_index),
                        'column': str(column_name),
                        'column_type': str(column_type),
                        'transform': str(transform),
                        'values': by_index.get(int(key_index), []),
                    }
                    for key_index, column_name, column_type, transform in columns
                ],
                'truth': 'measured DuckLake catalog metadata',
            }
        finally:
            metadata.close()

    def partition_pruning_evidence(self, name: str, column: str, value: str) -> dict:
        """Exact candidate-file evidence for simple equality on identity partitions.

        Files written under older/different partition specs are retained as
        candidates rather than being incorrectly claimed as pruned.
        """
        layer, table = asset_name(name).split('.')
        if not IDENT.fullmatch(column):
            raise ValueError('Partition pruning column must be a simple identifier.')
        partitioning = self._ducklake_partition_evidence(layer, table)
        storage = self._ducklake_storage_evidence(layer, table)
        if not partitioning or not storage:
            return {'eligible': False, 'reason': 'DuckLake partition metadata is unavailable.'}
        key = next(
            (
                item for item in partitioning.get('columns', [])
                if item['column'] == column and item['transform'] == 'identity'
            ),
            None,
        )
        if key is None:
            return {
                'eligible': False,
                'reason': 'Only equality filters on current identity partition columns are modeled as exact pruning evidence.',
                'partitioning': partitioning,
            }
        metadata = self._ducklake_metadata_connection()
        if metadata is None:
            return {'eligible': False, 'reason': 'SQLite DuckLake metadata is unavailable.'}
        try:
            table_row = metadata.execute(
                """
                SELECT t.table_id
                FROM ducklake_table t
                JOIN ducklake_schema s ON s.schema_id=t.schema_id
                WHERE s.schema_name=? AND t.table_name=?
                  AND s.end_snapshot IS NULL AND t.end_snapshot IS NULL
                ORDER BY t.begin_snapshot DESC LIMIT 1
                """,
                (layer, table),
            ).fetchone()
            if table_row is None:
                return {'eligible': False, 'reason': 'DuckLake table metadata is unavailable.'}
            table_id = int(table_row[0])
            rows = metadata.execute(
                """
                SELECT
                    df.data_file_id,
                    df.partition_id,
                    df.file_size_bytes,
                    df.record_count,
                    MAX(CASE
                        WHEN fpv.partition_key_index=? AND fpv.partition_value=? THEN 1
                        ELSE 0
                    END) AS partition_match
                FROM ducklake_data_file df
                LEFT JOIN ducklake_file_partition_value fpv
                  ON fpv.data_file_id=df.data_file_id AND fpv.table_id=df.table_id
                WHERE df.table_id=? AND df.end_snapshot IS NULL
                GROUP BY df.data_file_id, df.partition_id, df.file_size_bytes, df.record_count
                """,
                (int(key['key_index']), str(value), table_id),
            ).fetchall()
        finally:
            metadata.close()
        partition_id = int(partitioning['partition_id'])
        candidates = [
            row for row in rows
            if row[1] != partition_id or int(row[4] or 0) == 1
        ]
        total_files = len(rows)
        candidate_files = len(candidates)
        total_bytes = sum(int(row[2] or 0) for row in rows)
        candidate_bytes = sum(int(row[2] or 0) for row in candidates)
        return {
            'eligible': True,
            'asset': name,
            'column': column,
            'operator': '=',
            'value': str(value),
            'partition_transform': 'identity',
            'total_files': total_files,
            'candidate_files': candidate_files,
            'pruned_files': total_files - candidate_files,
            'total_bytes': total_bytes,
            'candidate_bytes': candidate_bytes,
            'pruned_bytes': total_bytes - candidate_bytes,
            'candidate_records': sum(int(row[3] or 0) for row in candidates),
            'snapshot_id': storage.get('snapshot_id'),
            'truth': 'exact candidate-file set from DuckLake identity partition metadata; not runtime scan telemetry',
        }

    def lakehouse_overview(self) -> dict:
        """Return read-only DuckLake maintenance evidence for teaching.

        The small-file threshold is a Datapass heuristic, not a DuckLake rule.
        No maintenance function is executed here.
        """
        if self.kind != 'ducklake':
            return {
                'active': False,
                'truth': 'unavailable',
                'reason': 'DuckLake is not attached for this workspace.',
                'snapshots': [],
                'tables': [],
            }
        snapshot_rows = self.db.execute(
            """
            SELECT snapshot_id, CAST(snapshot_time AS VARCHAR), schema_version
            FROM ducklake_snapshots('lake')
            ORDER BY snapshot_id DESC
            LIMIT 20
            """
        ).fetchall()
        assets = self.listing()
        tables = []
        for asset in assets:
            storage = asset.get('storage')
            if not storage:
                continue
            file_count = int(storage.get('file_count') or 0)
            size_bytes = int(storage.get('size_bytes') or 0)
            average = round(size_bytes / file_count) if file_count else 0
            # DuckLake docs recommend Parquet files of at least a few MB.
            # Datapass uses 8 MiB only as an educational warning threshold.
            small_threshold = 8 * 1024 * 1024
            small_files = int(storage.get('small_file_count') or 0)
            tables.append({
                'name': asset['name'],
                'rows': asset['row_count'],
                'file_count': file_count,
                'size_bytes': size_bytes,
                'average_file_size_bytes': average,
                'small_file_threshold_bytes': small_threshold,
                'small_file_count': small_files,
                'delete_file_count': int(storage.get('delete_file_count') or 0),
                'snapshot_id': storage.get('snapshot_id'),
                'partitioning': storage.get('partitioning'),
                'compaction_advisory': (
                    'consider_merge_adjacent_files'
                    if file_count >= 4 and small_files / max(file_count, 1) >= 0.5
                    else 'none'
                ),
                'truth': 'measured DuckLake metadata + Datapass advisory heuristic',
            })
        return {
            'active': True,
            'truth': 'read-only measured DuckLake metadata; no maintenance executed',
            'maintenance_capability': 'ducklake_merge_adjacent_files',
            'small_file_threshold_truth': 'Datapass teaching heuristic: 8 MiB; DuckLake documentation recommends files of at least a few megabytes',
            'snapshots': [
                {
                    'snapshot_id': int(row[0]),
                    'snapshot_time': str(row[1]),
                    'schema_version': int(row[2]),
                }
                for row in snapshot_rows
            ],
            'tables': tables,
        }

    def _ducklake_storage_evidence(self, layer: str, table: str) -> dict | None:
        if self.kind != 'ducklake':
            return None
        # layer/table passed here already came through IDENT/registered LAYERS.
        try:
            row = self.db.execute(
                f"""
                WITH listed AS (
                    SELECT *
                    FROM ducklake_list_files('lake', '{table}', schema => '{layer}')
                ),
                data_files AS (
                    SELECT DISTINCT data_file, data_file_size_bytes
                    FROM listed
                    WHERE data_file IS NOT NULL
                ),
                delete_files AS (
                    SELECT DISTINCT delete_file
                    FROM listed
                    WHERE delete_file IS NOT NULL
                )
                SELECT
                    (SELECT COUNT(*) FROM data_files) AS file_count,
                    (SELECT COALESCE(SUM(data_file_size_bytes), 0) FROM data_files) AS size_bytes,
                    (SELECT COUNT(*) FROM delete_files) AS delete_file_count,
                    (SELECT COUNT(*) FROM data_files WHERE data_file_size_bytes < 8388608) AS small_file_count,
                    (SELECT COALESCE(MIN(data_file_size_bytes), 0) FROM data_files) AS min_file_size_bytes,
                    (SELECT COALESCE(MAX(data_file_size_bytes), 0) FROM data_files) AS max_file_size_bytes
                """
            ).fetchone()
        except Exception:
            # Views and other non-physical relations do not own DuckLake files.
            return None
        snapshot = self.db.execute(
            "SELECT MAX(snapshot_id) FROM ducklake_snapshots('lake')"
        ).fetchone()
        return {
            'format': 'parquet',
            'file_count': int(row[0] or 0),
            'size_bytes': int(row[1] or 0),
            'delete_file_count': int(row[2] or 0),
            'small_file_count': int(row[3] or 0),
            'min_file_size_bytes': int(row[4] or 0),
            'max_file_size_bytes': int(row[5] or 0),
            'snapshot_id': int(snapshot[0]) if snapshot and snapshot[0] is not None else None,
            'truth': 'measured_ducklake_metadata',
        }

    def listing(self):
        items = []
        for layer in LAYERS:
            if self.kind == 'sqlite':
                names = self.db.execute(f"SELECT name FROM {layer}.sqlite_master WHERE type IN ('table','view') ORDER BY name").fetchall()
            else:
                names = self.db.execute('SELECT table_name FROM information_schema.tables WHERE table_catalog=current_database() AND table_schema=? ORDER BY table_name', [layer]).fetchall()
            for (name,) in names:
                if not IDENT.fullmatch(name):
                    continue
                full = f'{layer}.{name}'
                count = self.db.execute(f'SELECT COUNT(*) FROM {full}').fetchone()[0]
                item = {'name': full, 'layer': layer, 'row_count': count, 'fresh': self.fresh(full), **self.versions.get(full, {})}
                storage = self._ducklake_storage_evidence(layer, name)
                if storage is not None:
                    partitioning = self._ducklake_partition_evidence(layer, name)
                    if partitioning is not None:
                        storage['partitioning'] = partitioning
                    item['storage'] = storage
                items.append(item)
        return items

    def schema(self) -> dict:
        """Every table and view with its columns, types and row count, for the Catalog tree view.

        Schemas outside the layers (dbt Core may build into `main` or `<target>_<custom>`) are listed too,
        flagged `layer: false`: the tree shows what is really in the file.
        """
        tables = []
        if self.kind == 'sqlite':
            for layer in LAYERS:
                for name, kind in self.db.execute(f"SELECT name, type FROM {layer}.sqlite_master WHERE type IN ('table','view') ORDER BY name").fetchall():
                    if not IDENT.fullmatch(name):
                        continue
                    columns = [{'name': c[1], 'type': c[2] or 'ANY'} for c in self.db.execute(f'PRAGMA {layer}.table_info({name})').fetchall()]
                    tables.append({'schema': layer, 'name': name, 'kind': 'view' if kind == 'view' else 'table', 'columns': columns})
        else:
            rows = self.db.execute(
                "SELECT table_schema, table_name, table_type FROM information_schema.tables "
                "WHERE table_catalog=current_database() AND table_schema NOT IN ('information_schema','pg_catalog') "
                "ORDER BY table_schema, table_name").fetchall()
            columns: dict[tuple[str, str], list[dict]] = {}
            for schema, table, column, data_type in self.db.execute(
                    "SELECT table_schema, table_name, column_name, data_type FROM information_schema.columns "
                    "WHERE table_catalog=current_database() ORDER BY table_schema, table_name, ordinal_position").fetchall():
                columns.setdefault((schema, table), []).append({'name': column, 'type': str(data_type)})
            for schema, table, table_type in rows:
                tables.append({'schema': schema, 'name': table, 'kind': 'view' if 'VIEW' in str(table_type).upper() else 'table',
                               'columns': columns.get((schema, table), [])})
        truncated = len(tables) > 500
        tables = tables[:500]
        for item in tables:
            item['layer'] = item['schema'] in LAYERS
            item['columns'] = item['columns'][:200]
            full = f'{quote_ident(item["schema"])}.{quote_ident(item["name"])}'
            try:
                item['row_count'] = int(self.db.execute(f'SELECT COUNT(*) FROM {full}').fetchone()[0])
            except Exception as error:  # a broken view still shows, with its error
                item['row_count'] = None
                item['error'] = str(error).splitlines()[0][:300]
            if item['layer']:
                item['fresh'] = self.fresh(f'{item["schema"]}.{item["name"]}') if IDENT.fullmatch(item['name']) else False
        return {'engine': self.kind, 'layers': list(LAYERS), 'tables': tables, 'truncated': truncated}

    def runtime_contract(self) -> dict:
        if self.kind == 'ducklake' and self.lakehouse is not None:
            return self.lakehouse.contract()
        if self.kind == 'duckdb':
            capability = self._duckdb_capability or {}
            return {
                'schema_version': 1,
                'active': False,
                'table_format': 'ducklake',
                'compute_engine': 'duckdb',
                'metadata_backend': None,
                'metadata_file': None,
                'data_format': 'parquet',
                'data_directory': None,
                'data_inlining_row_limit': 0,
                'truth': 'real local DuckDB compatibility mode; DuckLake is not attached',
                'duckdb_version': capability.get('version'),
                'ducklake_extension_installed': bool(capability.get('ducklake_extension_installed')),
                'ducklake_extension_version': capability.get('ducklake_extension_version'),
                'legacy_metadata': False,
            }
        return {
            'schema_version': 1,
            'active': False,
            'table_format': 'ducklake',
            'compute_engine': 'sqlite',
            'metadata_backend': None,
            'metadata_file': None,
            'data_format': None,
            'data_directory': None,
            'data_inlining_row_limit': 0,
            'truth': 'SQLite compatibility fallback; DuckLake and DuckDB are unavailable',
            'duckdb_version': None,
            'ducklake_extension_installed': False,
            'ducklake_extension_version': None,
            'legacy_metadata': False,
        }

    def _result(self, cursor) -> dict:
        if cursor.description is None:
            return {'columns': [], 'rows': [], 'total_rows': 0, 'truncated': False}
        columns = [x[0] for x in cursor.description]
        if len(columns) != len(set(columns)):
            raise ValueError('Duplicate result columns are ambiguous. Give joined columns unique aliases.')
        values = cursor.fetchmany(MAX_ROWS + 1)
        truncated = len(values) > MAX_ROWS
        return {'columns': columns, 'rows': [dict(zip(columns, map(json_value, row))) for row in values[:MAX_ROWS]], 'total_rows': None if truncated else len(values), 'truncated': truncated}

    def query(self, sql: str) -> dict:
        parts = validate_sql(sql, read_only=True)
        self.guard = True
        try:
            return self._result(self.db.execute(parts[0]))
        finally:
            self.guard = False

    def execute(self, sql: str, producer: str) -> dict:
        parts = validate_sql(sql)
        touched = []
        self.db.execute('BEGIN TRANSACTION')
        self.guard = True
        try:
            result = {}
            for statement in parts:
                result = self._result(self.db.execute(statement))
                for match in re.finditer(r'\b(?:TABLE(?:\s+IF\s+(?:NOT\s+)?EXISTS)?|VIEW(?:\s+IF\s+(?:NOT\s+)?EXISTS)?|INTO|UPDATE|DELETE\s+FROM)\s+((?:source|bronze|silver|gold|warehouse|features|metrics)\.[A-Za-z][A-Za-z0-9_]*)', sql_tokens(statement), re.I):
                    touched.append(match.group(1))
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise
        finally:
            self.guard = False
        for name in dict.fromkeys(touched):
            self._touch(name, references(sql), producer)
        return result

    def materialize(self, name: str, sql: str, producer: str) -> dict:
        name = asset_name(name)
        if name.startswith('source.'):
            raise ValueError('Source fixtures are immutable through Publish. Use a different layer.')
        statement = validate_sql(sql, read_only=True)[0].rstrip(';')
        if name in references(sql):
            raise ValueError('Publishing cannot replace the table it reads. Use a different output asset.')
        # Both engines preserve the old table when a replacement query fails.
        self.db.execute('BEGIN TRANSACTION')
        try:
            self.db.execute(f'DROP TABLE IF EXISTS {name}')
            self.guard = True
            self.db.execute(f'CREATE TABLE {name} AS {statement}')
            self.guard = False
            self.db.execute('COMMIT')
        except BaseException:
            self.guard = False
            self.db.execute('ROLLBACK')
            raise
        self._touch(name, references(sql), producer)
        return self.query(f'SELECT * FROM {name}')

    def publish_rows(self, name: str, rows: list[dict], producer: str, dependencies: list[str]) -> dict:
        name = asset_name(name)
        if name.startswith('source.'):
            raise ValueError('Publish cannot replace a source fixture.')
        if name in dependencies:
            raise ValueError('Publishing cannot replace the table it reads. Use a different output asset.')
        if not rows or len(rows) > 10_000:
            raise ValueError('Publishing Python results requires 1..10,000 rows.')
        cols = list(rows[0])
        if not cols or not all(IDENT.fullmatch(c) for c in cols):
            raise ValueError('Published columns must have simple unique identifiers.')
        if any(set(row) != set(cols) for row in rows):
            raise ValueError('Every published row must have the same columns.')
        types = []
        for col in cols:
            values = [r[col] for r in rows if r[col] is not None]
            if values and all(isinstance(v, (int, bool)) for v in values):
                types.append('BIGINT')
            elif values and all(isinstance(v, (int, float)) for v in values):
                types.append('DOUBLE')
            else:
                types.append('VARCHAR')
        self.db.execute('BEGIN TRANSACTION')
        try:
            self.db.execute(f'DROP TABLE IF EXISTS {name}')
            schema = ', '.join(f'"{col}" {typ}' for col, typ in zip(cols, types))
            self.db.execute(f'CREATE TABLE {name} ({schema})')
            normalized = [tuple(json_value(row[col]) for col in cols) for row in rows]
            self.db.executemany(f'INSERT INTO {name} VALUES ({",".join("?" for _ in cols)})', normalized)
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise
        self._touch(name, dependencies, producer)
        return self.query(f'SELECT * FROM {name}')

    def fingerprint(self, name: str) -> str:
        result = self.query(f'SELECT * FROM {asset_name(name)}')
        return hashlib.sha256(json.dumps(result['rows'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()

    def close(self):
        self.db.close()
