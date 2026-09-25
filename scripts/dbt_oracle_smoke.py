"""Compare the Datapass dbt emulation (runtime/dbtlab) with real dbt Core + dbt-duckdb on the same projects.

Each case is a small dbt project run in steps (source tables set up with SQL, then a dbt command). After every
step the script compares, for real dbt and for the emulation: the status of every node, and the columns, types
and rows of every table and view in the catalog layers. Snapshot timestamps of the check strategy (and hard
deletes) come from the clock, so those columns can be ignored per case.

Needs a Python with dbt-core and dbt-duckdb (DATAPASS_DBT_PYTHON, or `dbt` on PATH). Without it, the script says
so and exits 0: CI does not install dbt Core; run it locally when changing runtime/dbtlab.

    DATAPASS_DBT_PYTHON=/path/to/venv/python PYTHONPATH=runtime python scripts/dbt_oracle_smoke.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))

from datapass_runtime.catalog import Catalog  # noqa: E402
from dbtlab.engine import Runner  # noqa: E402
from dbtlab.project import LAYERS, load_project  # noqa: E402

CATALOG_SEED = {'source.orders', 'source.dim_customer_segment', 'source.turbine_readings'}
SCHEMA_MACRO = '''{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}{{ target.schema }}{%- else -%}{{ custom_schema_name | trim }}{%- endif -%}
{%- endmacro %}
'''


def profile_name(files: dict[str, str]) -> str:
    import yaml
    return str(yaml.safe_load(files['dbt_project.yml']).get('profile') or 'datapass')


def dbt_command() -> list[str] | None:
    python = os.environ.get('DATAPASS_DBT_PYTHON')
    if python:
        folder = Path(python).parent
        for name in ('dbt.exe', 'dbt'):
            if (folder / name).exists():
                return [str(folder / name)]
    found = shutil.which('dbt')
    return [found] if found else None


def project(name: str, files: dict[str, str]) -> dict[str, str]:
    base = {'dbt_project.yml': f"name: {name}\nversion: '1.0.0'\nconfig-version: 2\nprofile: datapass\n",
            'macros/generate_schema_name.sql': SCHEMA_MACRO}
    base.update(files)
    return base


CASES: list[dict[str, Any]] = [
    {
        'name': 'materializations',
        'files': project('materializations', {
            'models/sources.yml': 'version: 2\nsources:\n  - name: shop\n    schema: source\n    tables:\n      - name: orders\n',
            'models/staging/stg_orders.sql': "{{ config(materialized='view') }}\nselect order_id, status, amount from {{ source('shop', 'orders') }}",
            'models/staging/eph_paid.sql': "{{ config(materialized='ephemeral') }}\nselect * from {{ ref('stg_orders') }} where status = 'paid'",
            'models/marts/fct_paid.sql': "{{ config(materialized='table', schema='gold') }}\nwith p as (select * from {{ ref('eph_paid') }}) select order_id, amount from p",
            'models/marts/inc_append.sql': ("{{ config(materialized='incremental', schema='gold') }}\n"
                                            "select order_id, amount from {{ ref('stg_orders') }}\n"
                                            "{% if is_incremental() %} where order_id > (select max(order_id) from {{ this }}) {% endif %}"),
            'models/marts/inc_key.sql': ("{{ config(materialized='incremental', unique_key='order_id', schema='gold') }}\n"
                                         "select order_id, status, amount from {{ ref('stg_orders') }}"),
            'models/marts/inc_merge.sql': ("{{ config(materialized='incremental', unique_key='order_id', incremental_strategy='merge', schema='gold') }}\n"
                                           "select order_id, status from {{ ref('stg_orders') }}"),
        }),
        'steps': [
            {'setup': "CREATE OR REPLACE TABLE source.orders AS SELECT * FROM (VALUES (1, 'paid', 10.0), (2, 'open', 5.0)) t(order_id, status, amount)",
             'command': 'build'},
            {'setup': "CREATE OR REPLACE TABLE source.orders AS SELECT * FROM (VALUES (1, 'paid', 10.0), (2, 'paid', 6.0), (3, 'open', 7.0)) t(order_id, status, amount)",
             'command': 'build'},
            {'command': 'run', 'select': ['inc_append'], 'full_refresh': True},
        ],
    },
    {
        'name': 'snapshots',
        'files': project('snapshots', {
            'models/sources.yml': 'version: 2\nsources:\n  - name: crm\n    schema: source\n    tables:\n      - name: customers\n',
            'snapshots/customers_ts.sql': ("{% snapshot customers_ts %}\n{{ config(target_schema='gold', unique_key='customer_id', "
                                           "strategy='timestamp', updated_at='updated_at') }}\nselect * from {{ source('crm', 'customers') }}\n{% endsnapshot %}\n"),
            'snapshots/customers_current.sql': ("{% snapshot customers_current %}\n{{ config(target_schema='gold', unique_key='customer_id', "
                                                "strategy='timestamp', updated_at='updated_at', hard_deletes='invalidate', "
                                                "dbt_valid_to_current=\"cast('9999-12-31' as timestamp)\") }}\n"
                                                "select * from {{ source('crm', 'customers') }}\n{% endsnapshot %}\n"),
            'snapshots/customers_check.sql': ("{% snapshot customers_check %}\n{{ config(target_schema='gold', unique_key='customer_id', "
                                              "strategy='check', check_cols=['segment']) }}\nselect customer_id, segment from {{ source('crm', 'customers') }}\n{% endsnapshot %}\n"),
        }),
        'ignore': {'gold.customers_check': ['dbt_scd_id', 'dbt_updated_at', 'dbt_valid_from', 'dbt_valid_to'],
                   'gold.customers_current': ['dbt_valid_to']},
        'steps': [
            {'setup': ("CREATE OR REPLACE TABLE source.customers AS SELECT * FROM (VALUES (1, 'Consumer', TIMESTAMP '2026-01-01'), "
                       "(2, 'Corporate', TIMESTAMP '2026-01-01'), (3, NULL, TIMESTAMP '2026-01-01')) t(customer_id, segment, updated_at)"),
             'command': 'snapshot'},
            {'setup': ("CREATE OR REPLACE TABLE source.customers AS SELECT * FROM (VALUES (1, 'Corporate', TIMESTAMP '2026-02-01'), "
                       "(2, 'Corporate', TIMESTAMP '2026-01-01'), (4, 'Consumer', TIMESTAMP '2026-02-01')) t(customer_id, segment, updated_at)"),
             'command': 'snapshot'},
            {'command': 'snapshot'},
        ],
    },
    {
        'name': 'tests_and_build',
        'files': project('tests_and_build', {
            'dbt_project.yml': ("name: tests_and_build\nversion: '1.0.0'\nconfig-version: 2\nprofile: datapass\n"
                                "vars:\n  min_amount: 0\nmodels:\n  tests_and_build:\n    +materialized: table\n    marts:\n      +schema: gold\n"),
            'seeds/raw_segments.csv': 'segment_id,segment_name,active,since\n1,Consumer,true,2026-01-01\n2,Corporate,false,2026-01-02\n3,Public Sector,true,\n',
            'models/staging/stg_customers.sql': "select * from {{ ref('raw_customers') }}",
            'models/marts/dim_customers.sql': ("select c.customer_id, c.segment_id, s.segment_name from {{ ref('stg_customers') }} c "
                                               "left join {{ ref('raw_segments') }} s using (segment_id) where c.amount > {{ var('min_amount') }}"),
            'models/marts/after.sql': "select count(*) as n from {{ ref('dim_customers') }}",
            'seeds/raw_customers.csv': 'customer_id,segment_id,amount\n1,1,10.5\n2,2,20\n2,3,5\n4,9,1\n',
            'models/schema.yml': ("version: 2\nmodels:\n  - name: stg_customers\n    columns:\n      - name: customer_id\n"
                                  "        data_tests: [not_null]\n      - name: segment_id\n        data_tests:\n"
                                  "          - relationships:\n              arguments:\n                to: ref('raw_segments')\n"
                                  "                field: segment_id\n              config:\n                severity: warn\n"
                                  "  - name: dim_customers\n    columns:\n      - name: customer_id\n        data_tests: [unique]\n"
                                  "      - name: segment_name\n        data_tests:\n          - accepted_values:\n"
                                  "              arguments:\n                values: ['Consumer', 'Corporate', 'Public Sector']\n"),
            'tests/assert_amount_positive.sql': "select * from {{ ref('stg_customers') }} where amount <= 0",
        }),
        'steps': [
            {'command': 'build'},
            {'command': 'build', 'select': ['+dim_customers'], 'vars': {'min_amount': 6}},
            {'command': 'test', 'select': ['tag:nothing']},
        ],
    },
]


def sample_case() -> dict[str, Any]:
    """The BI Lab's dbt sample on the BI Lab's sources: a full build, a corrected order line and a price change
    (the incremental fact and the snapshot), then a full refresh."""
    folder = ROOT / 'samples' / 'bi-lab' / 'dbt'
    files = {p.relative_to(folder).as_posix(): p.read_text(encoding='utf-8') for p in folder.rglob('*') if p.is_file()}
    sources = (ROOT / 'samples' / 'bi-lab' / 'warehouse' / '00_sources.sql').read_text(encoding='utf-8')
    change = ("UPDATE source.shop_order_lines SET discount_amount = 60 WHERE order_id = 'SO1011'; "
              "UPDATE source.erp_products SET list_price = 219 WHERE product_id = 'P01'")
    return {'name': 'bi-lab-sample', 'files': files,
            'ignore': {'silver.snap_erp_products': ['dbt_scd_id', 'dbt_updated_at', 'dbt_valid_from', 'dbt_valid_to']},
            'steps': [{'setup': sources, 'command': 'build'}, {'setup': change, 'command': 'build'},
                      {'command': 'build', 'full_refresh': True}]}


CASES.append(sample_case())


def run_dbt(dbt: list[str], folder: Path, step: dict) -> dict[str, str]:
    args = [*dbt, step['command'], '--profiles-dir', str(folder), '--project-dir', str(folder)]
    if step.get('select'):
        args += ['--select', *step['select']]
    if step.get('full_refresh'):
        args.append('--full-refresh')
    if step.get('vars'):
        args += ['--vars', json.dumps(step['vars'])]
    completed = subprocess.run(args, capture_output=True, text=True, cwd=folder, timeout=600)
    results = folder / 'target' / 'run_results.json'
    if not results.exists():
        raise RuntimeError(f'dbt produced no run_results.json:\n{completed.stdout[-3000:]}\n{completed.stderr[-2000:]}')
    data = json.loads(results.read_text(encoding='utf-8'))
    # unique_id is <type>.<project>.<name>, plus .<hash> for generic tests.
    for r in data['results']:
        if r['status'] == 'error':
            print(f"    dbt Core error in {r['unique_id']}: {(r.get('message') or '')[:1500]}")
    return {r['unique_id'].split('.')[2]: r['status'] for r in data['results']}


def run_emulation(catalog: Catalog, files: dict[str, str], step: dict) -> dict[str, str]:
    project = load_project(files, 'silver', step.get('vars'))
    outcome = Runner(catalog, project, '2026-03-01 00:00:00').run(
        step['command'], step.get('select'), step.get('exclude'), bool(step.get('full_refresh')))
    return {r['name']: r['status'] for r in outcome['results']}


def tables(connection) -> dict[str, dict]:
    found = {}
    rows = connection.execute("SELECT table_schema, table_name FROM information_schema.tables "
                              "WHERE table_schema IN ({}) ORDER BY 1, 2".format(', '.join(f"'{layer}'" for layer in LAYERS))).fetchall()
    for schema, table in rows:
        if table.endswith('__dbt_tmp'):
            continue
        columns = connection.execute('SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = ? '
                                     'AND table_name = ? ORDER BY ordinal_position', [schema, table]).fetchall()
        data = connection.execute(f'SELECT * FROM "{schema}"."{table}"').fetchall()
        found[f'{schema}.{table}'] = {'columns': columns, 'rows': data}
    return found


def comparable(table: dict, ignore: list[str]) -> tuple:
    keep = [i for i, (name, _) in enumerate(table['columns']) if name not in ignore]
    columns = [table['columns'][i] for i in keep]
    rows = sorted((tuple(str(row[i]) for i in keep) for row in table['rows']))
    return columns, rows


def main() -> int:
    dbt = dbt_command()
    if not dbt:
        print('dbt oracle smoke skipped: dbt Core is not installed (set DATAPASS_DBT_PYTHON).')
        return 0
    problems = []
    for case in CASES:
        with tempfile.TemporaryDirectory(prefix='datapass-dbt-oracle-', ignore_cleanup_errors=True) as temp:
            real_dir, emu_dir = Path(temp) / 'real', Path(temp) / 'emu'
            real_dir.mkdir()
            for path, text in case['files'].items():
                target = real_dir / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding='utf-8')
            database = real_dir / 'oracle.duckdb'
            (real_dir / 'profiles.yml').write_text(
                f"{profile_name(case['files'])}:\n  target: dev\n  outputs:\n    dev:\n      type: duckdb\n"
                f"      path: '{database.as_posix()}'\n      schema: silver\n      threads: 1\n", encoding='utf-8')
            setup = duckdb.connect(str(database))
            for layer in LAYERS:
                setup.execute(f'CREATE SCHEMA IF NOT EXISTS {layer}')
            setup.close()
            catalog = Catalog(emu_dir, 'duckdb')
            try:
                for index, step in enumerate(case['steps'], start=1):
                    if step.get('setup'):
                        connection = duckdb.connect(str(database))
                        connection.execute(step['setup'])
                        connection.close()
                        catalog.db.execute(step['setup'])
                    real = run_dbt(dbt, real_dir, step)
                    emulated = run_emulation(catalog, case['files'], step)
                    label = f"{case['name']} step {index} ({step['command']})"
                    if real != emulated:
                        diff = {k: (real.get(k), emulated.get(k)) for k in sorted(set(real) | set(emulated))
                                if real.get(k) != emulated.get(k)}
                        problems.append(f'{label}: statuses differ (dbt Core, emulation): {diff}')
                    connection = duckdb.connect(str(database), read_only=True)
                    real_tables = tables(connection)
                    connection.close()
                    emu_tables = {k: v for k, v in tables(catalog.db).items()
                                  if k in real_tables or k not in CATALOG_SEED}  # the catalog's own demo tables
                    for name in sorted(set(real_tables) | set(emu_tables)):
                        if name not in real_tables or name not in emu_tables:
                            problems.append(f'{label}: {name} exists only in {"dbt Core" if name in real_tables else "the emulation"}')
                            continue
                        ignore = case.get('ignore', {}).get(name, [])
                        a, b = comparable(real_tables[name], ignore), comparable(emu_tables[name], ignore)
                        if a != b:
                            only_real, only_emu = sorted(set(a[1]) - set(b[1]))[:5], sorted(set(b[1]) - set(a[1]))[:5]
                            problems.append(f'{label}: {name} differs'
                                            + (f'\n    columns: {a[0]} vs {b[0]}' if a[0] != b[0] else '')
                                            + f'\n    rows {len(a[1])} vs {len(b[1])}; only in dbt Core: {only_real}'
                                            + f'\n    only in the emulation: {only_emu}')
                    print(f'{label}: {len(real)} nodes, {len(real_tables)} relations compared')
            finally:
                catalog.close()
    if problems:
        print('\nPROBLEMS:\n  ' + '\n  '.join(problems))
        return 1
    print('dbt oracle smoke passed: the emulation matches dbt Core on every case.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
