"""Opt-in adapter to the inspected fastapispark 0.1.0 contract.

Source provenance: julian-passebecq/fastapispark at
80ebbbcaf58b1d1922d014a83c9aab49943a81e1 (main.py). This is an original
client/validator, not a copy or fork of the service. The default endpoint was
explicitly supplied by the user and live-qualified on 2026-09-21.
Only installed teaching fixtures are sent; no workspace table is uploaded.
"""
from __future__ import annotations
import ast
from copy import deepcopy
import hashlib
import json
import math
import os
import re
import threading
import time
import uuid
from urllib.parse import urlsplit
import httpx
from .local_jobs import CapabilityUnavailable, now

DEFAULT_GUIDED_SPARK_URL='https://fastapispark.fastapicloud.dev'
SERVICE='datapass-fake-spark'
VERSION='0.1.0'
ADAPTER='fastapispark-guided-v1'
SOURCE_SHA='80ebbbcaf58b1d1922d014a83c9aab49943a81e1'
COLS=['order_id','customer_id','net_amount']
STARTER='df = spark.table("orders")\ndf = df.filter("net_amount > 0")\ndf = df.select("order_id", "customer_id", "net_amount")'
PROBE=[dict(order_id=1,customer_id=101,net_amount=420),dict(order_id=2,customer_id=102,net_amount=275),dict(order_id=3,customer_id=101,net_amount=-10)]

def compile_guard(source:str)->tuple[str,dict]:
    """Qualify a linear, single-call-per-line subset before the regex service.

    This prevents chained calls and ignored statements from silently losing
    operations in the service's first compiler version. AST is never executed.
    """
    if not source.strip() or len(source)>20000:raise ValueError('Guided source limit is 20 KB.')
    try:tree=ast.parse(source)
    except (SyntaxError,RecursionError) as e:raise ValueError('Invalid guided Spark syntax.') from e
    if not 1<=len(tree.body)<=21:raise ValueError('Use a source and at most 20 operations.')
    ops=[];last=None;canonical=[]
    for i,stmt in enumerate(tree.body):
        if not isinstance(stmt,ast.Assign) or len(stmt.targets)!=1 or not isinstance(stmt.targets[0],ast.Name) or not re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,30}',stmt.targets[0].id):
            raise ValueError('Each line must assign one supported call to a DataFrame name. Actions, imports and control flow are not supported.')
        target=stmt.targets[0].id;call=stmt.value
        if target in ('spark','F'):raise ValueError('Do not overwrite the teaching source namespace.')
        if not isinstance(call,ast.Call) or not isinstance(call.func,ast.Attribute) or not isinstance(call.func.value,ast.Name) or call.keywords or any(not isinstance(a,ast.Constant) for a in call.args):
            raise ValueError('Use one call per line, literal arguments and no chaining or dynamic expressions.')
        args=[a.value for a in call.args];name=call.func.value.id;op=call.func.attr
        if i==0:
            if name!='spark' or op!='table' or args!=['orders']:raise ValueError('Start with df = spark.table("orders").')
        else:
            if name!=last:raise ValueError('This guided compiler supports one linear DataFrame chain, not branching/reused earlier variables.')
            if op in ('filter','where'):
                if len(args)!=1 or not isinstance(args[0],str):raise ValueError('Use a literal SQL filter string.')
                condition=args[0].strip()
                # Single simple predicate or AND/OR chain over fixture columns.
                atom=r'(?:order_id|customer_id|net_amount)\s*(?:(?:>=|<=|<>|!=|=|>|<)\s*-?\d+(?:\.\d+)?|IS\s+(?:NOT\s+)?NULL)'
                if len(condition)>500 or not re.fullmatch(atom+r'(?:\s+(?:AND|OR)\s+'+atom+r')*',condition,re.I):
                    raise ValueError('Use comparisons against numbers or IS NULL on the three fixture columns, joined by AND/OR.')
                args=[condition];ops.append({'op':'filter','args':{'condition':condition}})
            elif op=='select':
                if not args or any(a not in COLS for a in args) or len(set(args))!=len(args):raise ValueError('Select unique fixture column names.')
                ops.append({'op':'select','args':{'columns':args}})
            elif op in ('orderBy','sort'):
                if len(args)!=1 or args[0] not in COLS:raise ValueError('Order by one literal fixture column.')
                ops.append({'op':'order_by','args':{'columns':[{'column':args[0],'direction':'asc'}]}})
            elif op=='limit':
                if len(args)!=1 or type(args[0]) is not int or not 0<=args[0]<=100:raise ValueError('Guided LIMIT must be an integer from 0 to 100.')
                ops.append({'op':'limit','args':{'count':args[0]}})
            else:raise ValueError('This lesson supports filter/select/orderBy/limit only.')
        canonical.append(target+' = '+name+'.'+op+'('+', '.join(json.dumps(a) for a in args)+')')
        last=target
    return '\n'.join(canonical),{'source_table':'orders','operations':ops,'warnings':[]}

def valid_result(value:dict)->dict:
    if not isinstance(value,dict) or value.get('physical_engine')!='duckdb':raise ValueError('The service did not report actual DuckDB execution.')
    if not re.fullmatch(r'dps_[0-9a-f]{16}',str(value.get('execution_id',''))):raise ValueError('Invalid service execution identity.')
    cols=value.get('columns');rows=value.get('rows');truncated=value.get('truncated')
    if not isinstance(cols,list) or not 1<=len(cols)<=10 or any(not isinstance(c,str) or len(c)>100 for c in cols) or len(set(cols))!=len(cols):raise ValueError('Invalid or duplicate result columns.')
    if type(truncated) is not bool or not isinstance(rows,list) or len(rows)>200:raise ValueError('Invalid bounded result envelope.')
    for row in rows:
        if not isinstance(row,dict) or set(row)!=set(cols) or any(not isinstance(v,(str,int,float,bool,type(None))) or isinstance(v,float) and not math.isfinite(v) or isinstance(v,str) and len(v)>2000 for v in row.values()):
            raise ValueError('Nonrectangular, nonfinite or oversized result data.')
    metrics=value.get('metrics')
    if not isinstance(metrics,dict) or metrics.get('runtime_id')!='datapass-free' or 'simulat' not in str(metrics.get('disclaimer','')).lower():raise ValueError('Simulation metrics must have the teaching disclaimer and runtime identity.')
    fields=['total_duration_ms','total_tasks','total_shuffle_bytes','total_spill_bytes','simulated_credits']
    if any(type(metrics.get(k)) not in (int,float) or not math.isfinite(metrics[k]) or not 0<=metrics[k]<=10**15 for k in fields):raise ValueError('Invalid simulation summary.')
    stages=metrics.get('stages')
    if not isinstance(stages,list) or not 1<=len(stages)<=50:raise ValueError('Invalid simulated stages.')
    for stage in stages:
        if not isinstance(stage,dict) or any(type(stage.get(k)) not in (int,float) or not math.isfinite(stage[k]) or not 0<=stage[k]<=10**15 for k in ('stage_id','tasks','duration_ms','shuffle_read_bytes','shuffle_write_bytes','spill_bytes')):raise ValueError('Invalid simulated stage values.')
    return deepcopy(value)

class GuidedSpark:
    def __init__(self,url=None,key=None,*,transport=None,timeout=20):
        self.url=(url if url is not None else os.getenv('DATAPASS_GUIDED_SPARK_URL',DEFAULT_GUIDED_SPARK_URL)).rstrip('/')
        self.key=key if key is not None else os.getenv('DATAPASS_GUIDED_SPARK_KEY','')
        self.transport=transport;self.timeout=min(60,max(1,timeout));self.qualified_until=0;self.lock=threading.RLock();self.reason='Explicit connection qualification required.'
        if self.url:
            parsed=urlsplit(self.url)
            if parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.hostname or not (parsed.scheme=='https' or parsed.scheme=='http' and parsed.hostname in ('localhost','127.0.0.1','::1')):
                raise ValueError('Guided service URL must be HTTPS, or explicit loopback HTTP; no URL credentials/query/fragment.')
    def capabilities(self):
        available=bool(self.url) and time.monotonic()<self.qualified_until
        return dict(configured=bool(self.url),available=available,service_version=VERSION,source_commit=SOURCE_SHA,adapter=ADAPTER,
                    reason='' if available else self.reason if self.url else 'No endpoint configured. Set DATAPASS_GUIDED_SPARK_URL on the local API server; no network fallback.',
                    location='loopback service' if urlsplit(self.url).hostname in ('localhost','127.0.0.1','::1') else 'configured remote service',
                    privacy='Only curated lesson source and built-in teaching fixtures, including hidden checks, are sent. No workspace tables.',
                    limits={'operations':20,'result_rows':100,'fixture_rows':200,'timeout_seconds':self.timeout},
                    limitations=['Not general PySpark','Empty input tables are not qualified by service 0.1.0','Distributed metrics are simulated; DuckDB version is not reported'])
    def request(self,method,path,deadline,body=None):
        if not self.url:raise CapabilityUnavailable(self.capabilities()['reason'])
        remaining=deadline-time.monotonic()
        if remaining<=0:raise CapabilityUnavailable('Guided service deadline exceeded; no fallback result.')
        headers={'Content-Type':'application/json'}
        if self.key:headers['Authorization']='Bearer '+self.key
        try:
            with httpx.Client(timeout=remaining,follow_redirects=False,trust_env=False,transport=self.transport) as client:
                with client.stream(method,self.url+path,json=body,headers=headers) as response:
                    if response.status_code!=200:raise CapabilityUnavailable(f'Guided service {path} returned HTTP {response.status_code}; no fallback.')
                    chunks=[];size=0
                    for chunk in response.iter_bytes():
                        size+=len(chunk)
                        if size>2_000_000 or time.monotonic()>deadline:raise CapabilityUnavailable('Guided response exceeds size/time bounds.')
                        chunks.append(chunk)
                    return json.loads(b''.join(chunks),parse_constant=lambda v:(_ for _ in ()).throw(ValueError('Nonfinite JSON')))
        except (httpx.HTTPError,ValueError) as e:raise CapabilityUnavailable('Guided protocol/connection failed: '+type(e).__name__) from e
    def negotiate(self,deadline):
        root=self.request('GET','/',deadline);health=self.request('GET','/health',deadline);runtimes=self.request('GET','/v1/runtimes',deadline)
        if not all(isinstance(v,dict) for v in (root,health,runtimes)) or not isinstance(runtimes.get('items'),list) or any(not isinstance(r,dict) for r in runtimes.get('items',[])) or root.get('service')!=SERVICE or root.get('version')!=VERSION or root.get('status')!='ok' or health.get('status')!='ok' or health.get('service')!=SERVICE or not any(r.get('id')=='datapass-free' for r in runtimes.get('items',[])):
            raise CapabilityUnavailable('fastapispark version/service/runtime negotiation failed. Expected the inspected 0.1.0 contract.')
    def plan(self,source,deadline):
        canonical,expected=compile_guard(source)
        actual=self.request('POST','/v1/spark/compile',deadline,{'code':canonical})
        if actual!=expected:raise CapabilityUnavailable('Service compiler differs from the guarded lesson plan or emitted warnings. Nothing is executed.')
        return expected
    def execute(self,plan,rows,deadline,limit=100):
        if not 1<=len(rows)<=200:raise ValueError('This service lesson only qualifies nonempty fixture tables, at most 200 rows.')
        return valid_result(self.request('POST','/v1/spark/execute',deadline,{**{k:v for k,v in plan.items() if k!='warnings'},'runtime_id':'datapass-free','tables':[{'name':'orders','rows':rows}],'collect_limit':limit,'hints':{}}))
    def qualify(self,consent:bool):
        if not consent:raise ValueError('Explicit consent is required to contact the service and send public probe fixtures.')
        with self.lock:
            self.qualified_until=0;deadline=time.monotonic()+self.timeout
            try:
                self.negotiate(deadline);plan=self.plan(STARTER,deadline)
                response=self.execute(plan,PROBE,deadline)
                if response['truncated'] or response['columns']!=COLS or response['rows']!=PROBE[:2]:raise ValueError('Service semantic probe failed.')
                truncated=self.execute(plan,PROBE,deadline,limit=1)
                if not truncated['truncated'] or len(truncated['rows'])!=1:raise ValueError('Service truncation probe failed.')
                empty=self.execute(plan,[dict(order_id=8,customer_id=2,net_amount=-2)],deadline)
                if empty['rows'] or empty['truncated'] or empty['columns']!=COLS:raise ValueError('Service empty-result/schema probe failed.')
                self.qualified_until=time.monotonic()+600;self.reason='';return self.capabilities()
            except Exception as e:
                self.reason=str(e);raise CapabilityUnavailable('Guided connection is not qualified: '+str(e)) from e
    def grade(self,request):
        from .exercises import PACKS
        from .exercise_validation import validate_result
        if request.get('remote_consent') is not True:raise ValueError('Approve sending this lesson source and built-in fixtures before Run/Submit.')
        if not self.capabilities()['available']:raise CapabilityUnavailable(self.capabilities()['reason'] or 'Guided qualification expired; explicitly verify again.')
        spec,private=PACKS.get(request['exercise_id'])
        if spec.runtime!=ADAPTER or spec.version!=request['exercise_version'] or spec.language!=request['language']:raise ValueError('Mismatched guided exercise adapter/version.')
        deadline=time.monotonic()+self.timeout;started=time.monotonic();session=uuid.uuid4().hex;checks=[];runs=[]
        # Reject local unsupported source before any service call.
        compile_guard(request['code'])
        self.negotiate(deadline);plan=self.plan(request['code'],deadline)
        for fixture in private.fixtures:
            if request['mode']!='submit' and fixture.visibility!='visible':continue
            tick=time.monotonic();value=self.execute(plan,fixture.input_rows,deadline)
            result=dict(columns=value['columns'],rows=value['rows'],truncated=value['truncated'],total_rows=None if value['truncated'] else len(value['rows']))
            passed=validate_result(result,fixture.expected,spec.validation,request['code'],'sparklab');elapsed=round((time.monotonic()-tick)*1000,3);rid=uuid.uuid4().hex
            check=dict(id=fixture.id,visibility=fixture.visibility,passed=passed,status='passed' if passed else 'failed',execution_id=rid,execution_status='success',elapsed_ms=elapsed,message='Full bounded result matches.' if passed else 'Complete semantic result differs; truncation cannot pass.',input_versions={})
            if fixture.visibility=='visible':
                check.update(actual=result['rows'],expected=fixture.expected)
                runs.append(dict(id=rid,cell_id=request['cell_id'],notebook_id=request['notebook_id'],source_hash=hashlib.sha256(request['code'].encode()).hexdigest(),session_generation=session,sequence=1,created_at=now(),engine='DuckDB via '+self.capabilities()['location'],language='sparklab',status='success',result=result,elapsed_ms=elapsed,input_versions={},
                                 guided_evidence=dict(adapter=ADAPTER,service_version=VERSION,source_commit=SOURCE_SHA,execution_id=value['execution_id'],fixture_version=spec.fixtures[0].version,physical_engine='duckdb',engine_version='not reported by service',metrics=value['metrics'],truth='bounded results; distributed metrics simulated')))
            checks.append(check)
        return dict(status='passed' if all(c['passed'] for c in checks) else 'failed',checks=checks,runs=runs,truth='semantic-emulation',runtime=dict(adapter=ADAPTER+' / '+self.capabilities()['location'],engine='duckdb',engine_version='not reported; service '+VERSION,session_generation=session),elapsed_ms=round((time.monotonic()-started)*1000,3))
