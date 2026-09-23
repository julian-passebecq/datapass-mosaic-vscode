"""Pure, bounded AST compiler for Datapass's teaching DSL. NEVER eval/exec.

Syntax is intentionally Python-like, not an Airflow import/runtime. Schedule is
metadata. Only literal task declarations and >> dependencies are accepted.
"""
from __future__ import annotations
import ast
from dataclasses import dataclass
import hashlib
import re
from .analytics_contracts import PipelineIR

TASKS={'sql','quality','python','polars','dbt'}
NAMES=re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,63}$')
RESOURCES=re.compile(r'^[A-Za-z0-9_-]{1,100}$')

class CompileError(ValueError):
    def __init__(self,message,node=None,line=None,column=None):
        self.line=line or getattr(node,'lineno',1)
        self.column=column or (getattr(node,'col_offset',0)+1)
        self.message=message
        super().__init__(f'Line {self.line}:{self.column}: {message}')


def source_hash(source:str)->str:
    return hashlib.sha256(source.encode('utf-8')).hexdigest()


def literal(node):
    if isinstance(node,ast.Constant) and type(node.value) in (str,int,float,type(None)):
        return node.value
    raise CompileError('Only literal strings/numbers/null are accepted; no calls, variables, interpolation or Python evaluation.',node)


def call(node,allowed):
    if not isinstance(node,ast.Call) or not isinstance(node.func,ast.Name) or node.func.id not in allowed:
        raise CompileError('Unsupported call. Use pipeline(), sql(), quality(), python(), polars() or dbt().',node)
    if any(isinstance(a,ast.Starred) for a in node.args) or any(k.arg is None for k in node.keywords):
        raise CompileError('Argument expansion is not supported.',node)
    args=[literal(v) for v in node.args]
    kwargs={}
    for keyword in node.keywords:
        if keyword.arg in kwargs:
            raise CompileError('Duplicate keyword argument.',keyword)
        kwargs[keyword.arg]=literal(keyword.value)
    return node.func.id,args,kwargs


def topological(ir:dict)->list[str]:
    ids=[t['id'] for t in ir['tasks']]
    parents={id:set() for id in ids}
    for edge in ir['edges']:
        if edge['source'] not in parents or edge['target'] not in parents:
            raise ValueError('Missing dependency endpoint.')
        parents[edge['target']].add(edge['source'])
    ordered=[]
    while len(ordered)<len(ids):
        ready=[id for id in ids if id not in ordered and parents[id].issubset(ordered)]
        if not ready:
            raise ValueError('Pipeline contains a dependency cycle.')
        ordered.extend(ready)
    return ordered


def compile_pipeline(source:str)->dict:
    if not isinstance(source,str) or not source.strip() or len(source.encode('utf-8'))>80_000:
        raise CompileError('Pipeline source must contain 1..80 KB.')
    try:
        tree=ast.parse(source,filename='pipeline.py',mode='exec')
    except (SyntaxError,RecursionError,ValueError) as error:
        raise CompileError(str(error),line=getattr(error,'lineno',1),column=getattr(error,'offset',1)) from error
    queue=[(tree,0)];count=0
    while queue:
        node,depth=queue.pop();count+=1
        if count>4000 or depth>40:
            raise CompileError('Pipeline AST exceeds the bounded syntax limit.',node)
        queue.extend((child,depth+1) for child in ast.iter_child_nodes(node))
    metadata=None;tasks=[];aliases={};dependencies=[];metadata_aliases=set()
    def declaration(expr):
        nonlocal metadata
        _,args,kwargs=call(expr,{'pipeline','DAG'})
        if metadata is not None:
            raise CompileError('Declare exactly one pipeline.',expr)
        if len(args)!=1 or not isinstance(args[0],str) or not NAMES.fullmatch(args[0]) or set(kwargs)-{'schedule'}:
            raise CompileError('Use pipeline("simple_id", schedule="@daily"). Schedule is metadata only.',expr)
        schedule=kwargs.get('schedule')
        if schedule is not None and (not isinstance(schedule,str) or len(schedule)>100):
            raise CompileError('Schedule must be a string up to 100 characters, or None.',expr)
        metadata={'id':args[0],'schedule':schedule}
    def statements(body,inside=False):
        for node in body:
            if isinstance(node,ast.Expr) and isinstance(node.value,ast.Constant) and isinstance(node.value.value,str):
                continue  # Documentation string, not evaluated.
            if isinstance(node,ast.With):
                if inside or len(node.items)!=1:
                    raise CompileError('Only one pipeline/DAG context is supported; no arbitrary context managers.',node)
                item=node.items[0];declaration(item.context_expr)
                if item.optional_vars:
                    if not isinstance(item.optional_vars,ast.Name):raise CompileError('Pipeline alias must be a name.',node)
                    metadata_aliases.add(item.optional_vars.id)
                statements(node.body,True)
            elif isinstance(node,ast.Expr) and isinstance(node.value,ast.Call):
                declaration(node.value)
            elif isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
                variable=node.targets[0].id
                if variable in aliases or variable in metadata_aliases or variable in TASKS|{'pipeline','DAG'}:
                    raise CompileError('Duplicate/reserved task variable.',node)
                kind,args,kwargs=call(node.value,TASKS)
                allowed={'retries','retry_delay'}|({'project','action'} if kind=='dbt' else set())
                if set(kwargs)-allowed:
                    raise CompileError('Unsupported task keyword; supported: retries, retry_delay, dbt project/action.',node)
                if len(args)!=(1 if kind=='dbt' else 2) or not isinstance(args[0],str) or not NAMES.fullmatch(args[0]):
                    raise CompileError('Use task_name = sql("id", "SQL text") or dbt("id", project="resource-id").',node)
                if any(t['id']==args[0] for t in tasks):
                    raise CompileError('Duplicate task ID.',node)
                code='' if kind=='dbt' else args[1]
                if not isinstance(code,str) or len(code)>40000 or (kind!='dbt' and not code.strip()):
                    raise CompileError('Task source must be a nonempty literal string up to 40,000 characters.',node)
                retries,delay=kwargs.get('retries',0),kwargs.get('retry_delay',0)
                if type(retries) is not int or not 0<=retries<=3 or type(delay) not in (int,float) or not 0<=delay<=5:
                    raise CompileError('Retries must be 0..3; retry_delay is 0..5 seconds.',node)
                project=kwargs.get('project');action=kwargs.get('action','build') if kind=='dbt' else None
                if kind=='dbt' and (not isinstance(project,str) or not RESOURCES.fullmatch(project) or action not in ('parse','compile','seed','run','build','test')):
                    raise CompileError('dbt needs a canonical project resource ID and an allowlisted action.',node)
                aliases[variable]=args[0]
                tasks.append(dict(id=args[0],kind=kind,source=code,retries=retries,retry_delay=delay,resource_id=project,action=action))
                if len(tasks)>40:raise CompileError('V1 supports at most 40 tasks per pipeline.',node)
            elif isinstance(node,ast.Expr) and isinstance(node.value,ast.BinOp):
                dependencies.append(node.value)
            else:
                raise CompileError(f'{type(node).__name__} is not supported. Imports, loops, functions and arbitrary calls are not executed.',node)
    statements(tree.body)
    if metadata is None or not tasks:
        raise CompileError('Declare one pipeline and at least one task.')
    edges=[]
    def group(node):
        if isinstance(node,ast.Name):
            if node.id not in aliases:raise CompileError(f'Unknown task variable: {node.id}.',node)
            return [aliases[node.id]]
        if isinstance(node,(ast.List,ast.Tuple)):
            values=[]
            for item in node.elts:
                if not isinstance(item,ast.Name):raise CompileError('Dependency groups contain task names only.',item)
                values.extend(group(item))
            if not values:raise CompileError('Dependency group cannot be empty.',node)
            return list(dict.fromkeys(values))
        if isinstance(node,ast.BinOp) and isinstance(node.op,ast.RShift):
            left,right=group(node.left),group(node.right)
            for a in left:
                for b in right:
                    if a==b:raise CompileError('A task cannot depend on itself.',node)
                    edge={'source':a,'target':b}
                    if edge not in edges:edges.append(edge)
                    if len(edges)>120:raise CompileError('V1 supports at most 120 dependency edges.',node)
            return right
        raise CompileError('Dependencies use task names, [task, task] groups and >> only.',node)
    for expression in dependencies:group(expression)
    ir=dict(schema_version=1,**metadata,tasks=tasks,edges=edges,source_hash=source_hash(source))
    try:
        topological(ir)
        return PipelineIR.model_validate(ir).model_dump(mode='json')
    except ValueError as error:
        raise CompileError(str(error)) from error


def compile_response(source:str)->dict:
    try:
        ir=compile_pipeline(source)
        return {'valid':True,'source_hash':ir['source_hash'],'ir':ir,'diagnostics':[],'truth':'compiled_design_only'}
    except CompileError as error:
        return {'valid':False,'source_hash':source_hash(source),'ir':None,
                'diagnostics':[{'line':error.line,'column':error.column,'message':error.message}], 'truth':'unavailable'}
