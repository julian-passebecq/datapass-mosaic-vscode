/** A semantic lesson reference. Code stays in the existing per-variant notebook. */
import {useEffect,useState} from 'react';
import type {ExerciseDefinition,ExerciseAttempt} from '../../../../../packages/contracts/src/index.ts';
import type {ExerciseResource} from '../../../../../packages/contracts/src/foundation.ts';
import {patchView} from '../../../../../packages/contracts/src/workbench.ts';
import type {ResourceHostProps} from './ResourceHost';
import {ExerciseContext} from '../../InterviewPractice';
export function ExercisePortal({resource,view,change,services,disabled}:ResourceHostProps&{resource:ExerciseResource}){
 const [exercises,setExercises]=useState<ExerciseDefinition[]>([]),[attempts,setAttempts]=useState<ExerciseAttempt[]>([]),[error,setError]=useState('');
 useEffect(()=>{let alive=true;void Promise.all([services.api.exercises(),services.api.attempts(services.workspaceId)]).then(([es,as])=>{if(alive){setExercises(es);setAttempts(as)}},e=>{if(alive)setError(String(e))});return()=>{alive=false}},[services.api,services.workspaceId,resource.id]);
 const family=exercises.filter(e=>(e.semantic?.id===resource.exercise_id||e.id===resource.exercise_id)&&e.fixtures.some(f=>f.version===resource.fixture_version));
 const selected=family.find(e=>e.language===(view.state?.variant??resource.variant))??family[0];
 return <section className="dp-exercise-portal" aria-label="Unified Arena scenario"><h2>{selected?.title??resource.title}</h2>{error&&<p role="alert">{error}</p>}
 <p>One semantic exercise; language-specific code is kept in its canonical notebook. Opening again resumes the same saved draft, not another exercise copy.</p>
 <div className="an-actions">{family.map(e=><button key={e.id} aria-pressed={e.id===selected?.id} onClick={()=>change(s=>patchView(s,view.id,{state:{...view.state,variant:e.language}}),false)}>{e.language}</button>)}</div>
 {selected?<><p>{selected.prompt}</p><p className="an-note">{selected.runtime==='datapass-dag-design-v1'?'DAG design grading only. Task bodies are never executed; run pipelines in Pipeline Lab.':selected.runtime==='fastapispark-guided-v1'?'Requires explicitly qualified fastapispark. Real bounded DuckDB rows and separately simulated Spark metrics.':selected.language==='dbt'?'Bounded dbt drill: literal fixture refs and real SQL results. Not a dbt Core invocation.':selected.language==='sparklab'?'Local bounded Spark semantics. Distributed execution metrics, when available, are simulations.':selected.language==='polars'?'Requires real local Polars and trusted Python opt-in.':'Actual local runtime required; no simulated answer fallback.'}</p>
 <button disabled={disabled||!services.openExercise} onClick={()=>services.openExercise?.(selected.id)}>Open / resume {selected.language} notebook</button><ExerciseContext exercise={selected}/>
 <details><summary>Learning goals and reflection</summary>{selected.semantic?.learning_objectives.map(t=><p key={t}>{t}</p>)}<p>{selected.semantic?.optimization}</p><p>{selected.semantic?.reflection}</p></details>
 <p>Recent saved submissions for this variant: {attempts.filter(a=>a.exercise_id===selected.id&&a.exercise_version===selected.version).length}. Full attempt evidence appears with the notebook; switching views never resets it.</p></>:<p role="status">No matching installed scenario / fixture version. This reference is retained; no replacement exercise was silently loaded.</p>}
 </section>;
}
