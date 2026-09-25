"""Bounded text-only CSV interchange into the shared catalog, never a file-path API."""
import csv
import hashlib
import io
import re

IDENT=re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,63}$')
def parse_csv(text: str):
    if not isinstance(text,str) or not text or len(text.encode('utf-8'))>1_000_000 or '\x00' in text:
        raise ValueError('CSV must be UTF-8 text up to 1 MB, without NUL bytes.')
    try:
        reader=csv.reader(io.StringIO(text.lstrip('\ufeff'),newline=''),strict=True)
        columns=next(reader)
        if not 1<=len(columns)<=40 or len(set(c.lower() for c in columns))!=len(columns) or any(not IDENT.fullmatch(c) for c in columns):
            raise ValueError('CSV needs 1-40 unique, case-insensitive simple headers: letters, digits, underscores; start with a letter.')
        rows=[]
        for row in reader:
            if len(row)!=len(columns):raise ValueError('Every CSV row must have the same field count as the header.')
            if any(len(v)>10000 for v in row):raise ValueError('CSV field exceeds 10,000 characters.')
            rows.append(row)
            if len(rows)>5000:raise ValueError('CSV import limit is 5,000 rows. Filter or split the data explicitly.')
        return columns,rows,hashlib.sha256(text.encode()).hexdigest()
    except (csv.Error,StopIteration) as e:
        raise ValueError('Malformed CSV.') from e


def import_csv(catalog,asset,text):
    from .catalog import asset_name
    asset=asset_name(asset)
    if not asset.startswith('bronze.'):raise ValueError('Local CSV imports create a new bronze table only. Source fixtures cannot be replaced.')
    columns,rows,digest=parse_csv(text)
    if catalog.exists(asset):raise ValueError('This table already exists. Choose a new name; imports never overwrite data.')
    catalog.db.execute('BEGIN TRANSACTION')
    try:
        schema=', '.join('"'+c+'" VARCHAR' for c in columns)
        catalog.db.execute(f'CREATE TABLE {asset} ({schema})')
        if rows:catalog.db.executemany(f'INSERT INTO {asset} VALUES ({",".join("?" for _ in columns)})',rows)
        catalog.db.execute('COMMIT')
    except BaseException:
        catalog.db.execute('ROLLBACK');raise
    catalog._touch(asset,[],'csv:'+digest)
    result=catalog.query('SELECT * FROM '+asset)
    return {'asset':asset,'sha256':digest,'rows_imported':len(rows),'schema':[{'name':c,'type':'VARCHAR'} for c in columns],
            'result':result,'truth':'real local import; all fields remain text, empty fields remain empty strings',
            'engine':catalog.kind,'catalog':catalog.listing()}


# ---- Mosaic data tools: profile, query plan, typed file import (DuckDB only) ----------------------------

FILE_IMPORT_MAX_BYTES = 10_000_000
FILE_IMPORT_MAX_ROWS = 100_000
FILE_IMPORT_MAX_COLUMNS = 100


def _duckdb_only(catalog, what):
    if catalog.kind == 'sqlite':
        raise ValueError(f'{what} needs DuckDB; this catalog runs on the SQLite compatibility engine.')


def profile_table(catalog, asset):
    """DuckDB SUMMARIZE of one catalog table: per column min, max, approximate distinct count, quantiles, NULL share."""
    import time
    from .catalog import asset_name
    asset = asset_name(asset)
    _duckdb_only(catalog, 'A table profile')
    if not catalog.exists(asset):
        raise ValueError(f'{asset} is not in the catalog.')
    started = time.perf_counter()
    result = catalog._result(catalog.db.execute(f'SUMMARIZE {asset}'))
    return {'asset': asset, 'result': result, 'elapsed_ms': round((time.perf_counter() - started) * 1000, 3),
            'engine': catalog.kind,
            'truth': 'real DuckDB SUMMARIZE on the local catalog; approx_unique and the quantiles are estimates'}


def explain_query(catalog, query, dialect=None):
    """EXPLAIN ANALYZE of one read-only query: DuckDB runs it once and reports each operator's rows and time.
    With a dialect, the query is first translated to DuckDB (runtime/sqldialects) and the plan is the translation's."""
    import time
    from .catalog import validate_sql
    _duckdb_only(catalog, 'EXPLAIN ANALYZE')
    translated = None
    if dialect:
        from .sql_dialects import dialect_view, translate_for_catalog
        translated = dialect_view(translate_for_catalog(catalog, query, dialect, 'query'))
        query = translated['sql']
    try:
        statement = validate_sql(query, read_only=True)[0].strip().rstrip(';')
    except ValueError as error:
        raise ValueError(f'EXPLAIN ANALYZE needs one SELECT or WITH query: {error} '
                         'Select the query in the editor to explain only it.') from error
    started = time.perf_counter()
    catalog.guard = True
    try:
        # A trailing line comment would swallow anything after it: the query goes last, on its own lines.
        rows = catalog.db.execute('EXPLAIN ANALYZE\n' + statement + '\n').fetchall()
    finally:
        catalog.guard = False
    result = {'plan': '\n'.join(str(row[-1]) for row in rows), 'query': statement,
              'elapsed_ms': round((time.perf_counter() - started) * 1000, 3), 'engine': catalog.kind,
              'truth': 'real DuckDB EXPLAIN ANALYZE: the query ran once on the local catalog to time each operator'}
    if translated is not None:
        result['dialect'] = translated
        result['truth'] += f"; {translated['label']}: the plan is the translated query's"
    return result


def import_file(catalog, asset, file_format, data):
    """A NEW bronze table from Parquet or JSON CONTENT (base64). Types come from the file (Parquet) or from
    DuckDB's read_json_auto inference (JSON). Never a path from the client, never an overwrite."""
    import base64
    import binascii
    import uuid
    from .catalog import asset_name
    asset = asset_name(asset)
    if not asset.startswith('bronze.'):
        raise ValueError('Local file imports create a new bronze table only.')
    if file_format not in ('parquet', 'json'):
        raise ValueError('Import Parquet or JSON files here; CSV has its own text import.')
    _duckdb_only(catalog, f'{file_format.capitalize()} import')
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError('The file content is not valid base64.') from error
    if not raw or len(raw) > FILE_IMPORT_MAX_BYTES:
        raise ValueError(f'Import files must be 1 byte to {FILE_IMPORT_MAX_BYTES // 1_000_000} MB.')
    if file_format == 'parquet' and not (raw[:4] == b'PAR1' and raw[-4:] == b'PAR1'):
        raise ValueError('This is not a Parquet file (the PAR1 markers are missing).')
    if file_format == 'json':
        try:
            raw.decode('utf-8')
        except UnicodeDecodeError as error:
            raise ValueError('JSON files must be UTF-8 text.') from error
    if catalog.exists(asset):
        raise ValueError('This table already exists. Choose a new name; imports never overwrite data.')
    digest = hashlib.sha256(raw).hexdigest()
    catalog.import_directory.mkdir(parents=True, exist_ok=True)
    temp = catalog.import_directory / f'{uuid.uuid4().hex}.{file_format}'
    temp.write_bytes(raw)
    # The runtime wrote this file itself: its path is quoted here, never taken from the request.
    literal = "'" + temp.resolve().as_posix().replace("'", "''") + "'"
    reader = f'read_parquet({literal})' if file_format == 'parquet' else f'read_json_auto({literal})'
    try:
        import duckdb
        try:
            described = catalog.db.execute(f'DESCRIBE SELECT * FROM {reader}').fetchall()
            columns = [(str(row[0]), str(row[1])) for row in described]
            if not 1 <= len(columns) <= FILE_IMPORT_MAX_COLUMNS:
                raise ValueError(f'Import files need 1 to {FILE_IMPORT_MAX_COLUMNS} columns.')
            names = [name for name, _ in columns]
            bad = [name for name in names if not IDENT.fullmatch(name)]
            if bad or len({n.lower() for n in names}) != len(names):
                raise ValueError('Column names must be unique simple identifiers (letters, digits, underscores; start '
                                 f'with a letter). Rename in the source file: {", ".join(bad[:5]) or "duplicate names"}.')
            count = catalog.db.execute(f'SELECT COUNT(*) FROM {reader}').fetchone()[0]
            if count > FILE_IMPORT_MAX_ROWS:
                raise ValueError(f'The file import limit is {FILE_IMPORT_MAX_ROWS:,} rows; this file has {count:,}.')
            catalog.db.execute('BEGIN TRANSACTION')
            try:
                catalog.db.execute(f'CREATE TABLE {asset} AS SELECT * FROM {reader}')
                catalog.db.execute('COMMIT')
            except BaseException:
                catalog.db.execute('ROLLBACK')
                raise
        except duckdb.Error as error:
            first = str(error).strip().splitlines()[0] if str(error).strip() else type(error).__name__
            raise ValueError(f'DuckDB could not read this {file_format} file: {first}') from error
    finally:
        try:
            temp.unlink()
        except OSError:
            pass
    catalog._touch(asset, [], f'{file_format}:{digest}')
    truth = ('real local import; column types come from the Parquet file' if file_format == 'parquet'
             else 'real local import; column types inferred by DuckDB read_json_auto')
    return {'asset': asset, 'format': file_format, 'sha256': digest, 'rows_imported': count,
            'schema': [{'name': n, 'type': t} for n, t in columns], 'result': catalog.query('SELECT * FROM ' + asset),
            'truth': truth, 'engine': catalog.kind, 'catalog': catalog.listing()}
