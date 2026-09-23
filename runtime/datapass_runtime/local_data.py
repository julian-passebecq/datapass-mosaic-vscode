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
