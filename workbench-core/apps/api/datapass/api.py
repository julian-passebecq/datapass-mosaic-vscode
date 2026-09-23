from __future__ import annotations
from contextlib import asynccontextmanager
from dataclasses import asdict
import json
import os
from pathlib import Path
import secrets
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .content import ROOT, CONTENT, get_case, cases
from .documents import Documents, RevisionConflict
from . import exercises
from .foundation import RootWorkbench, validate_workspace_references
from .exercise_contracts import ExerciseDefinition, ExerciseAttempt, ExerciseResult
from .kernels import KernelManager, KernelTimeout
from .airflow_remote import AirflowRemote
from .spark_remote import SparkRemote
from .guided_spark import GuidedSpark,ADAPTER as GUIDED_ADAPTER
from .local_jobs import LocalJobs
from .dbt_runner import DbtRunner
from .local_routes import local_router
from services.sparklab.runtime import load_cluster_profiles


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class CreateWorkspace(StrictModel):
    case_id: str | None = Field(default=None,min_length=1,max_length=64)
    title: str | None = Field(default=None,min_length=1,max_length=120)


class ExerciseRequest(StrictModel):
    exercise_id: str = Field(max_length=100)
    exercise_version: str = Field(max_length=40)
    notebook_id: str = Field(min_length=1,max_length=100,pattern=r'^[A-Za-z0-9_-]+$')
    cell_id: str = Field(min_length=1,max_length=100,pattern=r'^[A-Za-z0-9_-]+$')
    code: str = Field(min_length=1,max_length=39000)
    language: Literal['sql','sparklab','python','polars','dbt']
    source_revision: int = Field(ge=0)
    mode: Literal['run','submit']
    profile: str = Field(default='generic_8x8',max_length=80)
    aqe: bool = True
    remote_consent: bool = False


class CsvImport(StrictModel):
    asset: str = Field(pattern=r'^bronze\.[A-Za-z][A-Za-z0-9_]{0,63}$')
    text: str = Field(min_length=1,max_length=1000000)
    workspace_revision: int = Field(ge=0)

class GuidedConsent(StrictModel):
    consent: bool


class ReviewRequest(StrictModel):
    revision: int = Field(ge=0)
    review: bool
    confidence: Literal['low','medium','high'] = 'low'
    difficulty: Literal['easy','medium','hard'] = 'easy'


class SaveNotebook(StrictModel):
    revision: int = Field(ge=0)
    notebook: dict


class SaveWorkbench(StrictModel):
    revision: int = Field(ge=0)
    workbench: RootWorkbench


class ExecuteCell(StrictModel):
    notebook_id: str = Field(min_length=1,max_length=100,pattern=r'^[A-Za-z0-9_-]+$')
    cell_id: str = Field(min_length=1,max_length=100,pattern=r'^[A-Za-z0-9_-]+$')
    step_id: str | None = Field(default=None,max_length=100)
    language: Literal['sql','sparklab','python','polars','dbt']
    code: str = Field(min_length=1,max_length=40000)
    output_asset: str | None = Field(default=None,max_length=100)
    profile: str = Field(default='generic_8x8',max_length=80)
    aqe: bool = True


class AirflowRemoteRun(StrictModel):
    dag_id: str = Field(min_length=1,max_length=100,pattern=r'^[A-Za-z_][A-Za-z0-9_.-]{0,99}$')
    logical_date: str = Field(default='2026-01-01T00:00:00+00:00',min_length=10,max_length=80)
    source: str = Field(min_length=1,max_length=30000)


class SparkRemoteRun(StrictModel):
    notebook_id: str = Field(default='case-notebook',min_length=1,max_length=100,pattern=r'^[A-Za-z0-9_-]+$')
    code: str = Field(min_length=1,max_length=20000)
    collect_limit: int = Field(default=100,ge=1,le=200)


class RunWorkflow(StrictModel):
    notebook_id: str = Field(default='case-notebook',min_length=1,max_length=100,pattern=r'^[A-Za-z0-9_-]+$')
    overrides: dict[str,str] = Field(default_factory=dict)
    profile: str = Field(default='generic_8x8',max_length=80)
    aqe: bool = True

    @field_validator('overrides')
    @classmethod
    def bounded_overrides(cls,value):
        if len(value)>30 or any(len(code)>40000 for code in value.values()):
            raise ValueError('Workflow overrides exceed the source limit.')
        return value


def create_app(data_dir: Path | None = None, token: str | None = None, *, mode=None, trusted_python=None, timeout=20.0, trusted_dbt=None, job_timeout=300.0):
    data_dir = data_dir or Path(os.environ.get('DATAPASS_DATA_DIR',str(ROOT/'.local'/'workspaces')))
    token = token or os.environ.get('DATAPASS_TOKEN') or secrets.token_urlsafe(32)
    mode = mode or os.environ.get('DATAPASS_STORAGE','auto')
    trusted = trusted_python if trusted_python is not None else os.environ.get('DATAPASS_TRUSTED_PYTHON')=='1'
    docs = Documents(data_dir)
    manager = KernelManager(mode, trusted, timeout)
    airflow_remote = AirflowRemote(timeout=timeout)
    spark_remote = SparkRemote(timeout=timeout)
    guided = GuidedSpark(timeout=timeout)
    jobs = LocalJobs(docs, manager, timeout=job_timeout)
    dbt = DbtRunner(docs, manager, trusted=trusted_dbt if trusted_dbt is not None else os.environ.get('DATAPASS_TRUSTED_DBT')=='1')

    @asynccontextmanager
    async def lifespan(app):
        yield
        jobs.close()
        manager.close()

    app = FastAPI(title='Datapass Studio Root',version='0.1.0',lifespan=lifespan)
    app.state.manager,app.state.documents,app.state.airflow_remote,app.state.spark_remote = manager,docs,airflow_remote,spark_remote
    app.state.local_jobs,app.state.dbt,app.state.guided_spark = jobs,dbt,guided
    app.include_router(local_router(docs,manager,jobs,dbt))
    port = int(os.environ.get('DATAPASS_PORT', '8000'))
    if not 1 <= port <= 65535:
        raise ValueError('DATAPASS_PORT must be between 1 and 65535.')
    origins = [f'http://127.0.0.1:{port}',f'http://localhost:{port}','http://127.0.0.1:5173','http://localhost:5173']
    app.add_middleware(CORSMiddleware,allow_origins=origins,allow_methods=['GET','POST','PUT','OPTIONS'],allow_headers=['Authorization','Content-Type'])
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=['127.0.0.1','localhost'])

    @app.middleware('http')
    async def local_boundary(request: Request, call_next):
        origin = request.headers.get('origin')
        if origin and origin not in origins:
            return JSONResponse({'detail':'Untrusted browser origin.'},status_code=403)
        if request.url.path.startswith('/api/') and request.url.path != '/api/health' and request.method != 'OPTIONS':
            auth = request.headers.get('authorization','')
            if not secrets.compare_digest(auth, f'Bearer {token}'):
                return JSONResponse({'detail':'A local session token is required. Use the URL printed by start.py.'},status_code=401)
        try:
            body_size = int(request.headers.get('content-length','0') or '0')
        except ValueError:
            return JSONResponse({'detail':'Invalid Content-Length.'},status_code=400)
        if body_size > 2_500_000:
            return JSONResponse({'detail':'Request exceeds 2.5 MB.'},status_code=413)
        response = await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Cache-Control']='no-store'
        return response

    @app.exception_handler(RevisionConflict)
    async def conflict(request,error):
        return JSONResponse({'detail':str(error)},status_code=409)

    @app.exception_handler(ValueError)
    async def bad_input(request,error):
        return JSONResponse({'detail':str(error)},status_code=422)

    @app.exception_handler(KeyError)
    @app.exception_handler(FileNotFoundError)
    async def not_found(request,error):
        return JSONResponse({'detail':'Workspace, case or step not found.'},status_code=404)

    @app.exception_handler(KernelTimeout)
    async def timed_out(request,error):
        return JSONResponse({'detail':str(error)},status_code=408)

    @app.exception_handler(RuntimeError)
    async def unavailable(request,error):
        return JSONResponse({'detail':str(error)},status_code=503)

    def command(id,body):
        docs.get(id)
        return manager.call(id,docs.folder(id)/'data',body)

    @app.get('/api/health')
    def health():
        return {'status':'ok','application':'Datapass Studio Root','version':'0.1.0','scope':'local single-user'}

    @app.get('/api/cases')
    def list_cases():
        return cases()

    @app.get('/api/workspaces/{id}/catalog/preview')
    def catalog_preview(id: str,asset: str):
        return command(id,{'op':'catalog_preview','asset':asset})

    @app.post('/api/workspaces/{id}/catalog/import-csv')
    def catalog_import(id: str,body: CsvImport):
        import hashlib,uuid
        from .local_jobs import now
        from .local_data import parse_csv
        parse_csv(body.text)  # Reject malformed input before starting a kernel.
        with manager.workspace_lease(id):
            workspace=docs.get(id)
            if workspace['revision']!=body.workspace_revision:raise RevisionConflict('Workspace changed. Refresh before importing data.')
            value=command(id,{'op':'import_csv','asset':body.asset,'text':body.text})
            run=dict(id=uuid.uuid4().hex,cell_id='catalog-import',notebook_id='catalog-import',source_hash=value['sha256'],input_versions={},session_generation=value['session_generation'],sequence=0,created_at=now(),engine=value['engine'],language='sql',status='success',result=value['result'],stdout='CSV import: '+body.asset+'; '+str(value['rows_imported'])+' rows; all fields VARCHAR. SHA-256: '+value['sha256'])
            value['workspace_revision']=docs.record(id,run,None)
            return value

    @app.get('/api/guided-spark/capabilities')
    def guided_capabilities():
        return guided.capabilities()

    @app.post('/api/guided-spark/qualify')
    def guided_qualify(body: GuidedConsent):
        return guided.qualify(body.consent)

    @app.get('/api/exercises',response_model=list[ExerciseDefinition],response_model_exclude_none=True)
    def list_exercises():
        return exercises.definitions()

    @app.get('/api/exercise-packs')
    def list_exercise_packs():
        return exercises.PACKS.discovery()

    @app.get('/api/workspaces/{id}/practice/progress')
    def practice_progress(id: str):
        return docs.practice_progress(id)

    @app.post('/api/exercises/{exercise_id}/solution')
    def reveal_solution(exercise_id: str):
        return exercises.solution(exercise_id)

    @app.get('/api/workspaces/{id}/attempts',response_model=list[ExerciseAttempt],response_model_exclude_none=True)
    def attempts(id: str):
        return docs.attempts(id)

    @app.put('/api/workspaces/{id}/practice/{exercise_id}/review')
    def review(id: str, exercise_id: str, body: ReviewRequest):
        return docs.review(id, exercise_id, body.revision, body.model_dump(exclude={'revision'}))

    @app.post('/api/workspaces/{id}/exercise',response_model=ExerciseResult,response_model_exclude_none=True)
    def exercise_action(id: str, body: ExerciseRequest):
        workspace = docs.get(id)
        spec = exercises.definition(body.exercise_id)
        if body.exercise_version != spec['version'] or body.language != spec['language']:
            raise ValueError('Exercise version or kernel does not match the installed definition.')
        if workspace['revision'] != body.source_revision:
            raise RevisionConflict('Save the current source before Run or Submit.')
        notebook = workspace.get('notebook') or {}
        block = next((b for b in notebook.get('blocks',[]) if b.get('id')==body.cell_id), {})
        source = notebook.get('blockState',{}).get(f"mosaic:v2:code:{body.cell_id}")
        if notebook.get('id') != body.notebook_id or not block or source != body.code:
            raise ValueError('The submitted source must match the saved notebook checkpoint.')
        request = {**body.model_dump(),'op':'exercise'}
        try:
            if spec['runtime']==GUIDED_ADAPTER:
                with manager.workspace_lease(id):
                    result = guided.grade(request)
            else:
                result = command(id, request)
        except (KernelTimeout, RuntimeError) as error:
            result = dict(status='error',checks=[],runs=[],truth='unsupported',elapsed_ms=0,
                          runtime={'adapter':spec['runtime'],'engine':'unavailable','engine_version':'unavailable','session_generation':''},
                          error={'type':type(error).__name__,'message':str(error)})
        for run in result['runs']:
            run['workspace_revision'] = docs.record(id,run,None)
        if body.mode == 'submit':
            result['attempt'] = exercises.attempt(request,result)
            if result.get('error'):
                result['attempt']['error'] = result['error']
            docs.record_attempt(id,result['attempt'])
        result['workspace_revision'] = docs.get(id)['revision']
        return result

    @app.get('/api/modules')
    def modules():
        return json.loads((CONTENT/'modules.json').read_text())

    @app.get('/api/profiles')
    def profiles():
        return [p.contract() for p in load_cluster_profiles(str(ROOT/'services/sparklab/cluster_profiles.json')).values()]

    @app.get('/api/airflow/capabilities')
    def airflow_capabilities():
        return airflow_remote.capabilities()

    @app.post('/api/airflow/runs',status_code=202)
    def airflow_run(body: AirflowRemoteRun):
        return airflow_remote.dispatch(
            dag_id=body.dag_id,
            source=body.source,
            logical_date=body.logical_date,
        )

    @app.get('/api/airflow/runs/{run_id}')
    def airflow_status(run_id: int):
        return airflow_remote.status(run_id)

    @app.get('/api/airflow/runs/{run_id}/result/{request_id}')
    def airflow_result(run_id: int, request_id: str):
        return airflow_remote.result(run_id, request_id)

    @app.get('/api/spark/remote/capabilities')
    def spark_remote_capabilities():
        return spark_remote.capabilities()

    @app.post('/api/workspaces/{id}/spark/remote',status_code=202)
    def spark_remote_run(id: str, body: SparkRemoteRun):
        docs.get(id)
        fixture = command(id,{
            'op':'spark_verify_fixture',
            'notebook_id':body.notebook_id,
            'code':body.code,
        })
        result = spark_remote.dispatch(
            code=fixture['code'],
            tables=fixture['tables'],
            collect_limit=body.collect_limit,
        )
        result['fixture_truth'] = fixture['truth']
        result['sources'] = fixture['sources']
        return result

    @app.get('/api/workspaces/{id}/spark/remote/{job_id}')
    def spark_remote_status(id: str, job_id: str):
        docs.get(id)
        return spark_remote.status(job_id)

    @app.get('/api/workspaces/{id}/spark/remote/{job_id}/result/{request_id}')
    def spark_remote_result(id: str, job_id: str, request_id: str):
        docs.get(id)
        return spark_remote.result(job_id, request_id)

    @app.get('/api/workspaces')
    def workspaces():
        return docs.all()

    @app.post('/api/workspaces',status_code=201)
    def new_workspace(body:CreateWorkspace):
        return docs.create(body.case_id, body.title)

    @app.get('/api/workspaces/{id}')
    def workspace(id:str):
        return docs.get(id)

    @app.put('/api/workspaces/{id}/notebook')
    def save(id:str,body:SaveNotebook):
        return docs.save_notebook(id,body.revision,body.notebook)

    @app.get('/api/foundation/schema')
    def foundation_schema():
        return RootWorkbench.model_json_schema()

    @app.post('/api/workspaces/{id}/workbench/validate')
    def validate_workbench(id: str, body: RootWorkbench):
        validate_workspace_references(body, docs.get(id))
        return {'status': 'valid', 'truth': 'design_only', 'workbench': body.model_dump(mode='json')}

    @app.put('/api/workspaces/{id}/workbench')
    def save_workbench(id: str, body: SaveWorkbench):
        return docs.save_workbench(id, body.revision, body.workbench.model_dump(mode='json'))

    @app.get('/api/workspaces/{id}/capabilities')
    def capabilities(id:str):
        return command(id,{'op':'capabilities'})

    @app.get('/api/workspaces/{id}/catalog')
    def catalog(id:str):
        return command(id,{'op':'catalog'})

    @app.get('/api/workspaces/{id}/lakehouse')
    def lakehouse(id:str):
        return command(id,{'op':'lakehouse'})

    @app.post('/api/workspaces/{id}/execute')
    def execute(id:str,body:ExecuteCell):
        workspace = docs.get(id)
        case = get_case(workspace['case_id']) if workspace['case_id'] else {'id':None,'steps':[]}
        steps = {s['id']:s for s in case['steps']}
        request = {**body.model_dump(),'op':'execute','case_id':case['id']}
        if body.step_id:
            if body.step_id not in steps:
                raise KeyError('Unknown step.')
            expected_asset = steps[body.step_id].get('output_asset')
            if body.output_asset != expected_asset:
                raise ValueError('A graded step must publish to its registered output asset. Add an ungraded cell for experiments.')
            request['check'] = steps[body.step_id].get('check')
            request['truth_pack'] = steps[body.step_id].get('truth_pack') if body.language=='sparklab' else None
        result = command(id,request)
        result['workspace_revision'] = docs.record(id,result,body.step_id)
        return result

    @app.post('/api/workspaces/{id}/workflow')
    def workflow(id:str,body:RunWorkflow):
        workspace = docs.get(id)
        result = command(id,{'op':'workflow','case_id':workspace['case_id'],**body.model_dump()})
        revision = workspace['revision']
        for run in result['runs']:
            revision = docs.record(id,run,run['cell_id'])
        result['workspace_revision'] = revision
        return result

    @app.post('/api/workspaces/{id}/check')
    def check(id:str):
        workspace = docs.get(id)
        return command(id,{'op':'check','case_id':workspace['case_id']})

    @app.post('/api/workspaces/{id}/restart')
    def restart(id:str):
        docs.get(id)
        return manager.restart(id)

    @app.get('/diagnostic')
    def diagnostic():
        return FileResponse(ROOT/'diagnostic/index.html')

    app.mount('/diagnostic-assets',StaticFiles(directory=ROOT/'diagnostic'),name='diagnostic-assets')
    dist = ROOT/'apps/web/dist'
    if dist.exists():
        app.mount('/',StaticFiles(directory=dist,html=True),name='web')
    else:
        @app.get('/')
        def unbuilt():
            return FileResponse(ROOT/'diagnostic/index.html')
    return app


app = create_app()
