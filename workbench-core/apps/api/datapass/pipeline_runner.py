"""Manual sequential/topological execution of a validated canonical PipelineIR."""
from __future__ import annotations
from copy import deepcopy
import time
from .analytics_contracts import PipelineIR
from .documents import RevisionConflict
from .local_jobs import JobContext, JobCancelled, JobDeadline, CapabilityUnavailable, digest
from .pipeline_compiler import compile_pipeline, topological

class PipelineRunner:
    def __init__(self,documents,manager,dbt):
        self.documents,self.manager,self.dbt=documents,manager,dbt

    def run(self,job:JobContext,resource:dict,workspace:dict):
        ir=compile_pipeline(resource['source'])
        cache=resource.get('last_valid_ir')
        if cache is None or PipelineIR.model_validate(cache).model_dump(mode='json')!=ir:
            raise RevisionConflict('Compile and save the current source first. A stale/mutated graph cannot be executed.')
        resources={r['id']:r for r in workspace['workbench']['resources']}
        for task in ir['tasks']:
            if task['kind']=='dbt' and resources.get(task['resource_id'],{}).get('kind')!='dbt-project':
                raise ValueError('Pipeline dbt task references a missing canonical dbt project.')
        wid=workspace['id'];data=self.documents.folder(wid)/'data'
        try:
            capabilities=self.manager.call(wid,data,{'op':'capabilities'})
        except Exception as error:
            raise CapabilityUnavailable('Shared catalog could not start: ' + str(error)) from error
        availability={k['id']:k['available'] for k in capabilities['kernels']}
        for task in ir['tasks']:
            if task['kind'] in ('python','polars') and not availability.get(task['kind']):
                raise CapabilityUnavailable(f'{task["kind"]} task is unavailable; enable trusted local Python and install required engines. No partial pipeline was started.')
            if task['kind']=='dbt' and not self.dbt.capabilities()['available']:
                raise CapabilityUnavailable(self.dbt.capabilities()['reason'])
        steps={t['id']:dict(id=t['id'],kind=t['kind'],status='queued',attempts=[],elapsed_ms=0) for t in ir['tasks']}
        parents={t['id']:{e['source'] for e in ir['edges'] if e['target']==t['id']} for t in ir['tasks']}
        by_id={t['id']:t for t in ir['tasks']}
        job.update(runtime={'adapter':'datapass-local-orchestrator','version':'1','scheduler':False,
                            'schedule_metadata':ir['schedule'],'engine':capabilities['storage'],
                            'session_generation':capabilities['session_generation']},steps=list(steps.values()))
        job.log('[pipeline] Manual run. Schedule is metadata; completed writes are not a whole-DAG transaction.\n')
        failed=[]
        try:
            for id in topological(ir):
                job.check()
                task=by_id[id];step=steps[id];started=time.monotonic()
                if any(steps[parent]['status']!='success' for parent in parents[id]):
                    step.update(status='skipped',error='An upstream dependency did not succeed.')
                    job.update(steps=list(steps.values()));continue
                step['status']='running';job.update(steps=list(steps.values()))
                for attempt in range(1,task['retries']+2):
                    job.check();tick=time.monotonic()
                    entry={'attempt':attempt,'status':'running','elapsed_ms':0}
                    step['attempts'].append(entry);job.update(steps=list(steps.values()))
                    job.log(f'[task {id}] attempt {attempt}\n')
                    try:
                        if task['kind']=='dbt':
                            result=self.dbt.run(job,resources[task['resource_id']],workspace,action=task['action'],prefix=f'{id}-{attempt}-')
                        elif task['kind']=='quality':
                            result=self.manager.call(wid,data,{'op':'read_query','query':task['source']})
                            job.update(truth='real_local')
                            if result['result']['truncated'] or result['result']['rows']:
                                raise ValueError('Quality tasks return failing rows. Expected zero rows; a truncated result never passes.')
                        else:
                            result=self.manager.call(wid,data,{'op':'execute','language':task['kind'],'code':task['source'],
                                     'notebook_id':'pipeline-'+job.record['id'], 'cell_id':id})
                            job.update(truth='real_local')
                            if result['status']!='success':raise RuntimeError(result.get('error',{}).get('message','Task execution failed.'))
                            job.log(result.get('stdout',''))
                            entry['run_id']=result['id']
                        job.check();entry['status']='success';step.update(status='success',result=result)
                        break
                    except (JobCancelled,JobDeadline,CapabilityUnavailable):
                        raise
                    except Exception as error:
                        job.check()
                        entry.update(status='failed',error=str(error)[:4000]);step['error']=str(error)[:4000]
                        job.log(f'[task {id}] {type(error).__name__}: {error}\n')
                        if attempt>task['retries']:
                            step['status']='failed';failed.append(id)
                        else:
                            step['status']='retrying';job.update(steps=list(steps.values()));job.wait(task['retry_delay']);step['status']='running'
                    finally:
                        entry['elapsed_ms']=round((time.monotonic()-tick)*1000,3)
                        job.update(steps=list(steps.values()))
                step['elapsed_ms']=round((time.monotonic()-started)*1000,3)
                if step['status']=='success':step.pop('error',None)
                job.update(steps=list(steps.values()))
        except (JobCancelled,JobDeadline,CapabilityUnavailable) as interruption:
            for step in steps.values():
                if step['status'] in ('queued','running','retrying'):
                    step.update(status='unavailable' if isinstance(interruption,CapabilityUnavailable) else 'cancelled' if job.cancelled.is_set() else 'timed_out',error='Run interrupted; no automatic replay.')
                    if step['attempts'] and step['attempts'][-1]['status']=='running':step['attempts'][-1]['status']=step['status']
            job.update(steps=list(steps.values()));raise
        result={'ir_source_hash':ir['source_hash'],'failed_tasks':failed,'task_count':len(steps),'truth':'real_local',
                'scheduler':False,'schedule_metadata':ir['schedule']}
        job.update(result=result)
        if failed:raise RuntimeError('Pipeline failed tasks: '+', '.join(failed)+'. Their downstream tasks were skipped; independent tasks still ran.')
        return result
