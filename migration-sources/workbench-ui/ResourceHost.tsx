import {FigureHost} from '../figures/FigureHost';
/** The native resource host reuses M2 editors, not its notebook-attached shell. */
import {ExercisePortal} from './ExercisePortal';
import {PipelineStudio} from './PipelineStudio';
import {useState} from 'react';
import {useLocalRuns,DbtExecution,LocalRunEvidence,type VerifiedDbtEvidence} from './LocalExecution';
import {replaceResource} from '../../../../../packages/contracts/src/workbench.ts';
import type {Resource,ViewInstance,RootWorkbench} from '../../../../../packages/contracts/src/foundation.ts';
import {projectForResource,applyProjectEdit} from '../../foundation/workspaceResources';
import {patchView} from '../../../../../packages/contracts/src/workbench.ts';
import {DbtStudio,LineageStudio} from '../analytics/DbtStudio';
import {ModelStudio,ScdStudio} from '../analytics/ModelStudio';
import {ChartsStudio} from '../analytics/ChartsStudio';
import type {ApiClient} from '../../api';
import '../analytics/analytics.css';
export interface ResourceServices {api:ApiClient;workspaceId:string;assets?:Array<{name:string;version?:string;fresh:boolean}>;save:()=>Promise<void>;refresh:()=>Promise<void>;openExercise?:(id:string)=>void}
export interface ResourceHostProps {resource:Resource;resources:Resource[];view:ViewInstance;change:(fn:(s:RootWorkbench)=>RootWorkbench,record?:boolean)=>void;services:ResourceServices;disabled:boolean}
export const hostedKinds=new Set<Resource['kind']>(['dbt-project','model-design','chart-board','pipeline','exercise','figure']);
export function ResourceHost(props:ResourceHostProps) {
 if(props.resource.kind==='figure')return <FigureHost key={props.resource.id} {...props} resource={props.resource}/>;
 if(props.resource.kind==='exercise')return <ExercisePortal key={props.resource.id} {...props} resource={props.resource}/>;
 if(props.resource.kind==='pipeline')return <PipelineStudio {...props} resource={props.resource}/>;
 return <AnalyticsResourceHost key={props.resource.id} {...props}/>;
}
function AnalyticsResourceHost(props:ResourceHostProps) {
 const {resource,view,change,disabled,services}=props;const [error,setError]=useState('');
 const runs=useLocalRuns(resource,services);const [evidence,setEvidence]=useState<VerifiedDbtEvidence|undefined>();
 const project=projectForResource(resource,view);
 const onChange=(next:typeof project)=>{if(disabled)return;try{change(s=>applyProjectEdit(s,resource.id,view.id,next));setError('')}catch(e){setError(String(e))}};
 const lab={project,onChange,onError:setError,evidence:evidence?{...evidence,stale:evidence.resourceRevision!==resource.revision}:undefined,nativeRunner:true,catalogInputs:services.assets};
 const layer=view.state?.layer;
 const choose=(value:string)=>change(s=>patchView(s,view.id,{state:{...view.state,layer:value}}),false);
 return <div className="dp-resource-host"><fieldset disabled={disabled}>{error&&<p className="an-error" role="alert">{error}</p>}
 {resource.kind==='dbt-project'&&<><DbtExecution resource={resource} services={services} disabled={disabled} controller={runs} onEvidence={setEvidence}/><div className="an-actions"><button onClick={()=>choose('dbt')}>Project files</button><button onClick={()=>choose('lineage')}>Lineage view</button></div>{layer==='lineage'?<LineageStudio {...lab}/>:<DbtStudio {...lab}/>}</>}
 {resource.kind==='model-design'&&<><div className="an-actions"><button onClick={()=>choose('model')}>Star schema</button><button onClick={()=>choose('scd')}>SCD 1 / 2 / 3</button></div>{layer==='scd'?<ScdStudio {...lab}/>:<ModelStudio {...lab}/>}</>}
 {resource.kind==='chart-board'&&<><div className="an-actions"><button disabled={disabled||runs.busy} onClick={()=>void runs.start(body=>services.api.queryBoard(services.workspaceId,body))}>Run SQL on shared catalog</button><button disabled={disabled||runs.busy||runs.job?.status!=='success'||!runs.job?.result?.snapshot||runs.job.result.snapshot.query!==resource.board.query} onClick={()=>{const snapshot=runs.job?.result?.snapshot;if(!snapshot)return;change(s=>{const target=s.resources.find(r=>r.id===resource.id);if(target?.kind!=='chart-board')return s;return replaceResource(s,{...target,board:{...target.board,snapshot}})})}}>Use result in board</button></div><LocalRunEvidence controller={runs} revision={resource.revision}/><ChartsStudio {...lab}/></>}
 </fieldset></div>;
}
