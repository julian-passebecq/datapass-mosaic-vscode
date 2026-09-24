"""Local workbench execution routes. Request bodies reference saved resources only."""
from __future__ import annotations
from typing import Literal
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .dbt_runner import selector
from .pipeline_compiler import compile_response
from .pipeline_runner import PipelineRunner
from .local_jobs import CapabilityUnavailable, now

class StartJob(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    resource_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')
    resource_revision: int = Field(ge=0,le=2**53-1)
    workspace_revision: int = Field(ge=0,le=2**53-1)

class StartDbt(StartJob):
    action: Literal['parse','compile','seed','run','build','test'] = 'build'
    select: str = Field(default='',max_length=200)
    _select = field_validator('select')(selector)


class CompilePipeline(BaseModel):
    model_config = ConfigDict(extra='forbid',strict=True)
    source: str = Field(max_length=80000)

def local_router(documents, manager, jobs, dbt):
    pipeline = PipelineRunner(documents,manager,dbt)
    router = APIRouter(prefix='/api/workspaces/{id}')

    @router.get('/local/capabilities')
    def capabilities(id: str):
        documents.get(id)
        return {'dbt': dbt.capabilities(), 'runner': {'name':'Datapass Local Orchestrator',
                'manual_only':True,'scheduler':False,'max_tasks':40,'max_retries':3,'timeout_seconds':jobs.timeout}}

    @router.get('/jobs')
    def list_jobs(id: str, resource_id: str | None = None):
        return jobs.list(id,resource_id)

    @router.get('/jobs/{job_id}')
    def job(id: str, job_id: str):
        return jobs.get(id,job_id)

    @router.post('/jobs/{job_id}/cancel')
    def cancel(id: str, job_id: str):
        return jobs.cancel(id,job_id)

    @router.get('/jobs/{job_id}/artifacts/{name}')
    def artifact(id: str, job_id: str, name: str):
        return jobs.read_artifact(id,job_id,name)

    @router.post('/dbt/run')
    def run_dbt(id: str, body: StartDbt):
        if body.action == 'parse' and body.select:
            raise ValueError('parse does not accept a selection.')
        return jobs.submit(id,body.resource_id,body.workspace_revision,body.resource_revision,'dbt',body.action,
                           lambda job,resource,workspace: dbt.run(job,resource,workspace,action=body.action,select=body.select))

    @router.post('/charts/query')
    def query_board(id: str, body: StartJob):
        def run(job,resource,workspace):
            query = resource['board']['query']
            if not query.strip():
                raise ValueError('Enter a SELECT query first.')
            job.check()
            result = manager.call(id,documents.folder(id)/'data',{'op':'read_query','query':query})
            job.check()
            job.update(truth='real_local', runtime={'adapter':'catalog-query','engine':result['engine'],
                       'session_generation':result['session_generation']})
            if result['result']['truncated']:
                raise ValueError('Chart result exceeds 200 rows. Aggregate/filter explicitly; a truncated preview is not a complete board.')
            snapshot = dict(label=resource['title'],columns=result['result']['columns'],rows=result['result']['rows'],
                            origin='real_local',query=query,run_id=job.record['id'],workspace_id=id,importedAt=now(),
                            input_versions=result.get('input_versions',{}))
            job.log(f'[query] {len(snapshot["rows"])} complete rows from {result["engine"]}\n')
            return {'snapshot':snapshot,'input_versions':result.get('input_versions',{}),'engine':result['engine']}
        return jobs.submit(id,body.resource_id,body.workspace_revision,body.resource_revision,'query','query',run)

    @router.post('/pipelines/compile')
    def compile_dag(id: str, body: CompilePipeline):
        documents.get(id)
        return compile_response(body.source)

    @router.post('/pipelines/run')
    def run_pipeline(id: str, body: StartJob):
        return jobs.submit(id,body.resource_id,body.workspace_revision,body.resource_revision,'pipeline','run',pipeline.run)

    return router
