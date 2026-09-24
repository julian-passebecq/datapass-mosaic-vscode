/** Safe source -> validated IR -> presentation-only graph -> explicit saved run. */
import {useEffect,useMemo,useState} from 'react';
import type {PipelineResource,Resource} from '../../../../../packages/contracts/src/foundation.ts';
import {projectPipeline} from '../../../../../packages/contracts/src/foundation.ts';
import {patchView,replaceResource} from '../../../../../packages/contracts/src/workbench.ts';
import type {PipelineCompilation} from '../../../../../packages/contracts/src/local.ts';
import {CodeEditor} from '../../CodeEditor';
import {GraphCanvas} from '../../foundation/GraphCanvas';
import {LocalRunEvidence,useLocalRuns} from './LocalExecution';
import type {ResourceHostProps} from './ResourceHost';
export function PipelineStudio({resource,view,change,services,disabled,resources}:ResourceHostProps&{resource:PipelineResource;resources:Resource[]}){
 const runs=useLocalRuns(resource,services);
 const [compilation,setCompilation]=useState<{source:string;response:PipelineCompilation}|null>(null),[error,setError]=useState('');
 useEffect(()=>{
  let disposed=false;setCompilation(null);setError('');
  const source=resource.source,id=resource.id;
  const timer=setTimeout(()=>{void services.api.compilePipeline(services.workspaceId,source).then(response=>{
   if(disposed)return;setCompilation({source,response});
   const ir=response.ir;if(!response.valid||!ir)return;
   try{change(state=>{const current=state.resources.find(r=>r.id===id);
    if(current?.kind!=='pipeline'||current.source!==source||JSON.stringify(current.last_valid_ir)===JSON.stringify(ir))return state;
    // A successful compile is derived state. Invalid edits preserve the previous IR.
    return replaceResource(state,{...current,last_valid_ir:ir,diagnostics:[]});
   },false)}catch(e){setError(String(e))}
  },e=>{if(!disposed)setError(String(e))})},400);
  return()=>{disposed=true;clearTimeout(timer)};
 },[resource.source,resource.id,services.api,services.workspaceId]);
 const ready=compilation?.source===resource.source&&compilation.response.valid&&!!compilation.response.ir&&JSON.stringify(resource.last_valid_ir)===JSON.stringify(compilation.response.ir);
 const graph=useMemo(()=>projectPipeline(resource),[resource.last_valid_ir]);
 const layer=view.state?.layer??'both';
 const setLayer=(layer:string)=>change(s=>patchView(s,view.id,{state:{...view.state,layer}}),false);
 const run=()=>{if(ready&&!disabled&&!runs.busy)void runs.start(body=>services.api.runPipeline(services.workspaceId,body));};
 return <section className="dp-pipeline" aria-label="Pipeline Lab"><h2>Pipeline Lab</h2>
 <p>Python-like declarations are parsed, never executed to discover the DAG. Manual, sequential local execution; schedule text is metadata, not an Airflow scheduler.</p>
 <div className="an-actions"><button aria-pressed={layer==='both'} onClick={()=>setLayer('both')}>Code + graph</button><button aria-pressed={layer==='code'} onClick={()=>setLayer('code')}>Code</button><button aria-pressed={layer==='graph'} onClick={()=>setLayer('graph')}>Graph</button><button disabled={disabled||runs.busy||!ready} onClick={run}>Run saved pipeline</button><span className={ready?'an-badge':'an-warning'}>{ready?'Current source compiled / design only':resource.last_valid_ir?'Last valid graph retained / current source not runnable':'Compile required'}</span></div>
 {error&&<p role="alert" className="an-error">{error}</p>}
 {compilation?.response.diagnostics.map((d,i)=><p role="alert" key={i} className="an-error">Line {d.line}, column {d.column}: {d.message}</p>)}
 <div className={`dp-pipeline-editors mode-${layer}`}>
 {layer!=='graph'&&<CodeEditor language="python" modelId={`${services.workspaceId}/pipeline/${resource.id}/${view.id}`} value={resource.source} readOnly={disabled} canRun={!!ready&&!runs.busy} onRun={run} onChange={source=>change(s=>{const current=s.resources.find(r=>r.id===resource.id);return current?.kind==='pipeline'?replaceResource(s,{...current,source}):s})}/>}
 {layer!=='code'&&<GraphCanvas graph={graph} view={view} disabled={disabled} connectable={false} onConnect={()=>{}} onView={patch=>change(s=>patchView(s,view.id,patch))}/>}
 </div>
 <details><summary>Task vocabulary and shared dbt projects</summary><p><code>sql</code>, <code>quality</code> (zero failing rows), <code>python</code>, <code>polars</code>, <code>dbt</code>. Use <code>a &gt;&gt; [b, c]</code> for dependencies. Retry count 0 to 3. Python/Polars/dbt are trusted local capabilities, not a sandbox.</p><pre>{'pipeline("example", schedule="@daily")\na = sql("create", "CREATE TABLE bronze.sample AS SELECT 1 AS id")\nb = quality("check", "SELECT * FROM bronze.sample WHERE id IS NULL")\na >> b'}</pre>{resources.filter(r=>r.kind==='dbt-project').map(r=><p key={r.id}>{r.title}: <code>{`dbt("build", project="${r.id}", action="build")`}</code></p>)}<p>Graph dragging and selections change this view only. To change task semantics or dependencies, edit the canonical source.</p></details>
 <LocalRunEvidence controller={runs} revision={resource.revision}/>
 </section>;
}
