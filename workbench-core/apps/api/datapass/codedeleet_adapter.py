"""Explicit, bounded V3.2 content adapter, never an importer of application state.

Accepts JSON exports with exercises/workstations and verified language variants.
Unknown legacy formats are reported rather than guessed or executed.
"""
from copy import deepcopy
from dataclasses import dataclass, field, asdict
from .exercise_packs import PackRegistry


@dataclass
class MigrationReport:
    migrated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def migrate_pack(source, pack_id, version, source_reference):
    report = MigrationReport()
    definitions, grading = [], {}
    manifest = dict(schema_version=1, id=pack_id, version=version, title=source.get('title', pack_id),
                    enabled=False, provenance={'source':source_reference,'adapter':'codedeleet-v32-bounded-v1'})
    registry = PackRegistry()
    records = source.get('exercises', source.get('workstations', []))
    if not isinstance(records, list):
        raise ValueError('Expected an exercises/workstations array')
    for record in records:
        old_id = str(record.get('id', 'missing-id'))
        variants = record.get('variants', [])
        if isinstance(variants, dict):
            variants = [dict(v, language=k) for k,v in variants.items()]
        if not variants:
            report.skipped.append(old_id+': no explicit variants')
        for variant in variants:
            language = variant.get('language')
            label = old_id+'/'+str(language)
            if language not in {'sql','python','polars','sparklab'}:
                report.unsupported.append(label+': no shared grading adapter; PySpark is not assumed to be SparkLab')
                continue
            if variant.get('verified') is not True:
                report.skipped.append(label+': variant is not explicitly verified')
                continue
            try:
                id = old_id+'-'+language
                fixtures = deepcopy(variant.get('fixtures', record.get('fixtures', [])))
                if not fixtures or not record.get('prompt') or not variant.get('solution'):
                    raise ValueError('Authored prompt, solution and fixture outputs are required')
                placement = record.get('canonical_placement') or {'domain':record['domain'],'topic':record['lab']}
                truth = record.get('truth','local')
                mapped_truth = {'local':'real','simulation':'simulated','evidence':'unsupported','optional-cloud':'unsupported','semantic-emulation':'semantic-emulation'}.get(truth)
                if mapped_truth is None or mapped_truth in {'simulated','unsupported'}:
                    report.unsupported.append(label+': execution truth '+truth+' requires an explicit supported adapter')
                    continue
                d = dict(schema_version=1,id=id,version=version,title=record['title'],difficulty=record.get('difficulty','medium'),
                         topics=record.get('topics',[placement['topic']]),tags=record.get('tags',[]),origin='migrated',
                         language=language,runtime='shared-'+language+'-v1',prompt=record['prompt'],sections=record.get('sections',[]),
                         starter_source=variant['starter'],fixtures=[{'id':id+'-fixtures','version':version}],
                         visible_checks=[{'id':f['id'],'description':f.get('description','Public fixture')} for f in fixtures if f['visibility']=='visible'],
                         hidden_check_refs=[f['id'] for f in fixtures if f['visibility']=='hidden'],edge_check_refs=[f['id'] for f in fixtures if f['visibility']=='edge'],
                         hints=record.get('hints',[]),solution={'available':True,'reveal':'explicit'},explanation=record.get('explanation',''),
                         follow_ups=record.get('follow_ups',[]),canonical_placement=placement,related_associations=record.get('related_practice',[]),
                         recommendation=record.get('recommendation'),validator_version='rows-v2',validation=record.get('validation',{}),
                         constraints={k:str(v) for k,v in record.get('constraints',{}).items()},data_context=record.get('data_context',[]),
                         output_schema=record.get('output_schema',{}),context_refs=record.get('context_refs',[]),
                         runtime_requirements=[language]+(['trusted-local-python'] if language in {'python','polars'} else []),
                         provenance={'source':source_reference,'legacy_id':old_id,'workstation_id':str(record.get('workstation_id',old_id)),
                                     'domain':str(record.get('domain','')),'lab':str(record.get('lab','')),'taxonomy':str(record.get('taxonomy',''))},
                         truth='semantic-emulation' if language=='sparklab' else 'real')
                private = {'solution':variant['solution'],'fixtures':[{k:f[k] for k in ('id','visibility','input_rows','expected')} for f in fixtures]}
                # Validate each candidate through the actual registry, then reject duplicates.
                check = PackRegistry();check.register(manifest,[d],{id:private})
                if id in grading: raise ValueError('Duplicate migrated exercise ID')
                definitions.append(d);grading[id]=private;report.migrated.append(label)
                for key in ('notebook','dbt_project','graph','guided_steps','relation_tests'):
                    if key in record: report.warnings.append(label+': '+key+' retained in source only; not converted')
            except (KeyError, ValueError, TypeError) as error:
                report.skipped.append(label+': '+str(error))
    registry.register(manifest, definitions, grading)
    return {'manifest':manifest,'exercises':definitions,'grading':grading,'report':asdict(report)}
