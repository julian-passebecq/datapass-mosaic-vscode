"""Start the single-user local service and print a token-bearing launch URL."""
from __future__ import annotations
import argparse
import os
import secrets
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description='Datapass Studio local root')
    parser.add_argument('--storage',choices=['auto','duckdb','ducklake','sqlite'],default='ducklake',help='DuckLake is canonical; duckdb/sqlite are explicit compatibility modes. No silent fallback.')
    parser.add_argument('--install-ducklake',action='store_true',help='Allow one-time download/install of the official ducklake + sqlite DuckDB extensions. Requires --storage ducklake and network access.')
    parser.add_argument('--trusted-local-python',action='store_true',help='Enable arbitrary trusted Python in a local worker. NOT a secure sandbox.')
    parser.add_argument('--trusted-local-dbt',action='store_true',help='Enable reviewed local dbt Core projects. Macros/hooks run as your OS user; NOT sandboxed.')
    parser.add_argument('--data-dir',default=str(Path(__file__).parent/'.local'/'workspaces'))
    parser.add_argument('--port', type=int, default=int(os.environ.get('DATAPASS_PORT', '8000')))
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    os.environ['DATAPASS_PORT'] = str(args.port)
    if args.install_ducklake and args.storage != 'ducklake':
        parser.error('--install-ducklake requires --storage ducklake')
    token = secrets.token_urlsafe(32)
    os.environ['DATAPASS_TOKEN']=token
    os.environ['DATAPASS_STORAGE']=args.storage
    os.environ['DATAPASS_DATA_DIR']=args.data_dir
    os.environ['DATAPASS_TRUSTED_DBT']='1' if args.trusted_local_dbt else '0'
    os.environ['DATAPASS_TRUSTED_PYTHON']='1' if args.trusted_local_python else '0'
    os.environ['DATAPASS_INSTALL_DUCKLAKE']='1' if args.install_ducklake else '0'
    print('\nDatapass Studio - LOCAL, SINGLE USER',flush=True)
    print(f'Open: http://127.0.0.1:{args.port}/#token={token}',flush=True)
    print(f'React dev: http://127.0.0.1:5173/#token={token}',flush=True)
    print(f'Storage: {args.storage}',flush=True)
    if args.storage == 'ducklake':
        print('DuckLake profile: DuckDB compute + SQLite metadata + Parquet data + inlining disabled.',flush=True)
        if not args.install_ducklake:
            print('DuckLake extensions must already be installed; add --install-ducklake once if needed.',flush=True)
    print(f'If React is not built, port {args.port} serves the explicitly labeled diagnostic client.',flush=True)
    if args.trusted_local_dbt:
        print('WARNING: dbt macros/hooks are trusted local code, not sandboxed.',flush=True)
    if args.trusted_local_python:
        print('WARNING: trusted Python can access this computer as your OS user. Process separation is not sandboxing.',flush=True)
    import uvicorn
    uvicorn.run('apps.api.datapass.api:app',host='127.0.0.1',port=args.port,workers=1)


if __name__=='__main__':
    main()
