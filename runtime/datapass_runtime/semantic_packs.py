"""Validate/expand a shared semantic lesson into the existing runtime wire contract."""
from copy import deepcopy
import re

LANGUAGES={'sql','python','polars','dbt','sparklab'}

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
            if set(variant)!={'starter_source','supported_operations'}:
                raise ValueError('Variant can only specify source and supported operations.')
            ident=semantic['variants'][language]
            definitions.append({**common,'id':ident,'version':version,'language':language,
                                'runtime':'dbt-drill-sql-v1' if language=='dbt' else 'shared-'+language+'-v1',
                                'truth':'semantic-emulation' if language in {'dbt','sparklab'} else 'real',
                                'semantic':{**semantic,'supported_operations':variant['supported_operations']},
                                'starter_source':variant['starter_source']})
            private[ident]={'solution':expected['solutions'][language],'fixtures':deepcopy(expected['fixtures'])}
    if set(grading)!=seen:raise ValueError('Unmatched private semantic scenario.')
    return definitions,private
