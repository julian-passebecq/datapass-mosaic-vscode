"""Validate/expand a shared semantic lesson into the existing runtime wire contract."""
from copy import deepcopy
import re

LANGUAGES={'sql','python','polars','dbt','sparklab','snowflake','tsql','bigquery','dbt-sql'}
# Runtime adapter and truth of each variant language (default: shared-<language>-v1, real).
RUNTIMES={'dbt':('dbt-drill-sql-v1','semantic-emulation'),'sparklab':('shared-sparklab-v1','semantic-emulation'),
          'snowflake':('snowflake-dialect-duckdb-v1','semantic-emulation'),
          'tsql':('tsql-dialect-duckdb-v1','semantic-emulation'),
          'bigquery':('bigquery-dialect-duckdb-v1','semantic-emulation'),
          'dbt-sql':('datapass-dbt-emulation-v1','semantic-emulation')}
DBT_SOURCE='zilla'
MODEL=re.compile('[a-z][a-z0-9_]{0,62}')


def dbt_project(source,tables):
    """The small dbt project a dbt-sql variant's model joins: the scenario tables are sources in the source layer."""
    listing=''.join(f'      - name: {name}\n' for name in tables)
    return {'dbt_project.yml':f"name: {source}\nversion: '1.0.0'\nconfig-version: 2\nprofile: datapass\n\n"
                              f"models:\n  {source}:\n    +materialized: table\n",
            'models/_sources.yml':f'version: 2\nsources:\n  - name: {source}\n    schema: source\n    tables:\n{listing}'}


def dbt_fixture(fixture,context,model,source=DBT_SOURCE):
    """The shared fixture as a dbt emulation scenario: seed the tables as sources, build the model, grade its table."""
    if fixture.get('input_rows') or not fixture.get('tables'):
        raise ValueError('A dbt-sql semantic variant needs named fixture tables.')
    columns={c['name']:c['columns'] for c in context}
    tables=[{'name':'source.'+name,'columns':list(columns[name]),'types':dict(columns[name]),
             'rows':[{c:row[c] for c in columns[name]} for row in rows]} for name,rows in fixture['tables'].items()]
    scenario={'files':dbt_project(source,list(fixture['tables'])),'file':f'models/{model}.sql','tables':tables,
              'runs':[{'command':'run','select':[model]}],'outcome':'table','table':'silver.'+model}
    return {'id':fixture['id'],'visibility':fixture['visibility'],'input_rows':[],'expected':deepcopy(fixture['expected']),
            'scenario':scenario}

def expand_scenarios(scenarios, grading):
    if not isinstance(scenarios,list) or not 1<=len(scenarios)<=100:
        raise ValueError('A semantic pack needs 1-100 scenarios.')
    definitions=[];private={};seen=set()
    for scenario in scenarios:
        common=deepcopy(scenario['common']);variants=scenario['variants'];semantic=deepcopy(scenario['semantic'])
        sid=semantic['id'];version=semantic['version']
        if sid in seen or not re.fullmatch('[A-Za-z0-9_-]{1,70}',sid) or not re.fullmatch('[A-Za-z0-9_-]{1,15}',version):
            raise ValueError('Duplicate/invalid semantic exercise identity.')
        seen.add(sid)
        if set(variants)-LANGUAGES or not variants:
            raise ValueError('Unqualified semantic language adapter.')
        expected=grading[sid]
        if set(expected['solutions'])!=set(variants):
            raise ValueError('Every variant needs exactly one private reference solution.')
        if common.get('fixtures')!=[{'id':sid+'-fixtures','version':scenario['fixture_version']}]:
            raise ValueError('All variants bind the same exact scenario fixture version.')
        forbidden={'id','version','language','semantic','starter_source','runtime','truth','pack'}
        if forbidden & common.keys():raise ValueError('Common fields cannot override identity/runtime.')
        semantic['variants']={language:sid+'-'+language for language in variants}
        for language,variant in variants.items():
            allowed={'starter_source','supported_operations'}|({'model'} if language=='dbt-sql' else set())
            if not {'starter_source','supported_operations'}<=set(variant)<=allowed:
                raise ValueError('Variant can only specify source and supported operations (and a dbt-sql model name).')
            ident=semantic['variants'][language]
            runtime,truth=RUNTIMES.get(language,('shared-'+language+'-v1','real'))
            definitions.append({**common,'id':ident,'version':version,'language':language,
                                'runtime':runtime,'truth':truth,
                                'semantic':{**semantic,'supported_operations':variant['supported_operations']},
                                'starter_source':variant['starter_source']})
            fixtures=deepcopy(expected['fixtures'])
            if language=='dbt-sql':
                # A model is a table: it has no row order to grade.
                if (common.get('validation') or {}).get('ordered'):
                    raise ValueError('An ordered result cannot be a dbt-sql model: '+sid)
                model=variant.get('model') or sid.replace('-','_')
                if not MODEL.fullmatch(model):raise ValueError('Invalid dbt-sql model name: '+model)
                fixtures=[dbt_fixture(f,common.get('data_context',[]),model) for f in fixtures]
            private[ident]={'solution':expected['solutions'][language],'fixtures':fixtures}
    if set(grading)!=seen:raise ValueError('Unmatched private semantic scenario.')
    return definitions,private
