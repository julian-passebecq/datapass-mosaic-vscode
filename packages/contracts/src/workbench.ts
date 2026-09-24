/** Pure resource/view operations. No runtime, filesystem, DOM or private dataset ownership. */
import {isGraph,projectGraph,projectPipeline,type GraphResource,type Resource,type RootWorkbench,type ViewInstance} from './foundation.ts';
export const newId=(prefix='id')=>`${prefix}-${crypto.randomUUID()}`;
const clone=<T>(x:T):T=>structuredClone(x);
const unique=(ids:string[],label:string)=>{if(new Set(ids).size!==ids.length)throw new Error(`Duplicate ${label}`)};
export function assertGraph(resource:GraphResource):void {
 const {nodes,edges}=projectGraph(resource);if(nodes.length>200||edges.length>500)throw new Error('Graph limit is 200 nodes / 500 edges.');
 unique(nodes.map(n=>n.id),'node ID');unique(edges.map(e=>e.id),'edge ID');
 const ids=new Set(nodes.map(n=>n.id));const pairs=new Set<string>();
 for(const e of edges){if(!ids.has(e.source)||!ids.has(e.target))throw new Error('Edge endpoint does not exist.');const rel=resource.kind==='data-model'?resource.relationships.find(r=>r.id===e.id):undefined;const pair=JSON.stringify([e.source,e.target,...(rel?[rel.source_column,rel.target_column]:[])]);if(pairs.has(pair))throw new Error('Duplicate directed edge.');pairs.add(pair)}
 if(resource.kind==='data-model'){
  for(const table of resource.tables)unique(table.columns.map(c=>c.id),'column ID');
  for(const e of resource.relationships){if(!resource.tables.find(t=>t.id===e.source)?.columns.some(c=>c.id===e.source_column)||!resource.tables.find(t=>t.id===e.target)?.columns.some(c=>c.id===e.target_column))throw new Error('Relationship column does not exist.');}
  return; // Relationship cycles are not workflow cycles.
 }
 const degree=new Map(nodes.map(n=>[n.id,0]));const children=new Map(nodes.map(n=>[n.id,[] as string[]]));
 for(const e of edges){degree.set(e.target,degree.get(e.target)!+1);children.get(e.source)!.push(e.target)}
 const ready=nodes.filter(n=>degree.get(n.id)===0).map(n=>n.id);let seen=0;
 while(ready.length){const id=ready.shift()!;seen++;for(const child of children.get(id)!){degree.set(child,degree.get(child)!-1);if(degree.get(child)===0)ready.push(child)}}
 if(seen!==nodes.length)throw new Error(`${resource.kind==='workflow'?'Dependency':'Dataset derivation'} cycle. Use versioned datasets to describe recurring lineage.`);
}
export function assertWorkbench(state:RootWorkbench):void {
 if(state.schema_version!==1)throw new Error('Unsupported foundation schema.');
 if(state.resources.length>60||state.views.length>120||state.panes.length<1||state.panes.length>3)throw new Error('Workbench limits: 60 resources, 120 views, 1-3 panes.');
 unique(state.resources.map(r=>r.id),'resource ID');unique(state.views.map(v=>v.id),'view ID');unique(state.panes.map(p=>p.id),'pane ID');
 unique(state.resources.filter(r=>r.kind==='notebook').map(r=>r.notebook_id),'canonical notebook reference');
 const resources=new Map(state.resources.map(r=>[r.id,r]));const views=new Map(state.views.map(v=>[v.id,v]));
 for(const r of state.resources){if(isGraph(r))assertGraph(r);if(r.kind==='workflow')for(const t of r.tasks)if(t.notebook_resource_id&&resources.get(t.notebook_resource_id)?.kind!=='notebook')throw new Error('Task references a missing notebook resource.');}
 for(const r of state.resources)if(r.kind==='pipeline')for(const t of r.last_valid_ir?.tasks??[])if(t.kind==='dbt'&&resources.get(t.resource_id??'')?.kind!=='dbt-project')throw new Error('Pipeline references a missing dbt project.');
 for(const v of state.views)if(!resources.has(v.resource_id))throw new Error('View references a missing resource.');
 const placed=state.panes.flatMap(p=>p.view_ids);unique(placed,'tab placement');
 if(placed.length!==views.size||placed.some(id=>!views.has(id)))throw new Error('Each view must belong to exactly one pane.');
 if(!state.panes.some(p=>p.id===state.active_pane_id))throw new Error('Active pane is missing.');
 for(const p of state.panes)if((p.view_ids.length&&!p.active_view_id)||p.active_view_id&&!p.view_ids.includes(p.active_view_id))throw new Error('Active tab is not in this pane.');
}
export function emptyWorkbench():RootWorkbench {return {schema_version:1,resources:[],views:[],panes:[{id:'pane-main',view_ids:[],active_view_id:null,weight:1}],active_pane_id:'pane-main',persona:'neutral',direction:'horizontal'}}
export function addResource(state:RootWorkbench,resource:Resource):RootWorkbench {const next={...state,resources:[...state.resources,resource]};assertWorkbench(next);return next}
export function replaceResource(state:RootWorkbench,resource:Resource):RootWorkbench {
 if(!state.resources.some(r=>r.id===resource.id&&r.kind===resource.kind))throw new Error('Cannot change resource identity or kind.');
 const next=clone(state),prior=next.resources.find(r=>r.id===resource.id)!;
 next.resources=next.resources.map(r=>r.id===resource.id?{...clone(resource),revision:prior.revision+1}:r);
 // Per-view selections/layout cannot retain dangling nodes after semantic deletion.
 if(isGraph(resource)||resource.kind==='pipeline'){const graph=resource.kind==='pipeline'?projectPipeline(resource):projectGraph(resource),nodes=new Set(graph.nodes.map(n=>n.id)),edges=new Set(graph.edges.map(e=>e.id));for(const v of next.views.filter(v=>v.resource_id===resource.id)){v.positions=Object.fromEntries(Object.entries(v.positions).filter(([id])=>nodes.has(id)));if(v.selected_node&&!nodes.has(v.selected_node))v.selected_node=null;if(v.selected_edge&&!edges.has(v.selected_edge))v.selected_edge=null}}
 assertWorkbench(next);return next;
}
export function openResource(state:RootWorkbench,resourceId:string,paneId=state.active_pane_id,duplicate=false):RootWorkbench {
 const next=clone(state),pane=next.panes.find(p=>p.id===paneId);if(!pane)throw new Error('Pane does not exist.');
 if(!next.resources.some(r=>r.id===resourceId))throw new Error('Resource does not exist.');
 const existing=next.views.find(v=>v.resource_id===resourceId&&pane.view_ids.includes(v.id));
 if(existing&&!duplicate)pane.active_view_id=existing.id;
 else{const view:ViewInstance={id:newId('view'),resource_id:resourceId,mode:'visual',positions:{},viewport:null,selected_node:null,selected_edge:null};next.views.push(view);pane.view_ids.push(view.id);pane.active_view_id=view.id}
 next.active_pane_id=paneId;assertWorkbench(next);return next;
}
export function patchView(state:RootWorkbench,id:string,patch:Partial<Omit<ViewInstance,'id'|'resource_id'>>):RootWorkbench {
 const next={...state,views:state.views.map(v=>v.id===id?{...v,...patch}:v)};assertWorkbench(next);return next;
}
export function splitPane(state:RootWorkbench):RootWorkbench {
 if(state.panes.length>=3)throw new Error('Three panes are the bounded foundation limit.');
 const next=clone(state),old=next.panes.find(p=>p.id===state.active_pane_id)!,id=newId('pane');
 next.panes.push({id,view_ids:[],active_view_id:null,weight:1});next.active_pane_id=id;
 const view=next.views.find(v=>v.id===old.active_view_id);return view?openResource(next,view.resource_id,id,true):next;
}
export function closeView(state:RootWorkbench,id:string):RootWorkbench {
 const next=clone(state);next.views=next.views.filter(v=>v.id!==id);
 for(const p of next.panes){p.view_ids=p.view_ids.filter(v=>v!==id);if(p.active_view_id===id)p.active_view_id=p.view_ids.at(-1)??null}
 assertWorkbench(next);return next; // Closing a tab does not delete source.
}
export function moveView(state:RootWorkbench,id:string,paneId:string):RootWorkbench {
 const view=state.views.find(v=>v.id===id);if(!view)throw new Error('View is missing.');
 const next=closeView(state,id),pane=next.panes.find(p=>p.id===paneId);if(!pane)throw new Error('Target pane missing.');
 next.views.push(clone(view));pane.view_ids.push(id);pane.active_view_id=id;next.active_pane_id=paneId;assertWorkbench(next);return next;
}
export function closePane(state:RootWorkbench,id:string):RootWorkbench {
 if(state.panes.length===1)throw new Error('Keep at least one pane.');
 const next=clone(state),closing=next.panes.find(p=>p.id===id);if(!closing)throw new Error('Pane is missing.');
 const target=next.panes.find(p=>p.id!==id)!;target.view_ids.push(...closing.view_ids);if(!target.active_view_id)target.active_view_id=target.view_ids[0]??null;
 next.panes=next.panes.filter(p=>p.id!==id);if(next.active_pane_id===id)next.active_pane_id=target.id;assertWorkbench(next);return next;
}
export function exampleResource(kind:GraphResource['kind']):GraphResource {
 const base={id:newId(kind),title:kind==='workflow'?'Ingest and transform':kind==='lineage'?'Bronze to gold lineage':'Sales star model',schema_version:1 as const,revision:0};
 if(kind==='workflow')return {...base,kind,tasks:[{id:'ingest',label:'Ingest source',runtime:'local.sql',notebook_resource_id:null},{id:'transform',label:'Transform in notebook',runtime:'local.sparklab',notebook_resource_id:null}],dependencies:[{id:'dep-1',source:'ingest',target:'transform',condition:'success'}]};
 if(kind==='lineage')return {...base,kind,datasets:[{id:'bronze',label:'Raw orders',asset_ref:null},{id:'silver',label:'Validated orders',asset_ref:null},{id:'gold',label:'Daily sales',asset_ref:null}],derivations:[{id:'derive-1',source:'bronze',target:'silver',note:'validate'},{id:'derive-2',source:'silver',target:'gold',note:'aggregate'}]};
 return {...base,kind,tables:[{id:'customer',label:'Dim Customer',asset_ref:null,grain:'One row per customer version',role:'dimension',scd:2,columns:[{id:'customer_key',data_type:'BIGINT',key:'primary',nullable:false}]},{id:'sales',label:'Fact Sales',asset_ref:null,grain:'One row per order line',role:'fact',scd:0,columns:[{id:'customer_key',data_type:'BIGINT',key:'foreign',nullable:false},{id:'amount',data_type:'DECIMAL(18,2)',key:'none',nullable:false}]}],relationships:[{id:'rel-1',source:'customer',source_column:'customer_key',target:'sales',target_column:'customer_key',cardinality:'one-to-many'}]};
}
export function addGraphNode(resource:GraphResource):GraphResource {
 const id=newId('node');if(resource.kind==='workflow')return {...resource,tasks:[...resource.tasks,{id,label:'New task',runtime:'local.sql',notebook_resource_id:null}]};
 if(resource.kind==='lineage')return {...resource,datasets:[...resource.datasets,{id,label:'New dataset',asset_ref:null}]};
 return {...resource,tables:[...resource.tables,{id,label:'New table',asset_ref:null,grain:'',role:'table',scd:0,columns:[{id:'id',data_type:'BIGINT',key:'primary',nullable:false}]}]};
}
export function connectGraph(resource:GraphResource,source:string,target:string):GraphResource {
 const id=newId('edge');let next:GraphResource;
 if(resource.kind==='workflow')next={...resource,dependencies:[...resource.dependencies,{id,source,target,condition:'success'}]};
 else if(resource.kind==='lineage')next={...resource,derivations:[...resource.derivations,{id,source,target,note:'derives'}]};
 else{const a=resource.tables.find(t=>t.id===source)?.columns[0],b=resource.tables.find(t=>t.id===target)?.columns[0];if(!a||!b)throw new Error('Both tables need a column.');next={...resource,relationships:[...resource.relationships,{id,source,target,source_column:a.id,target_column:b.id,cardinality:'one-to-many'}]}}
 assertGraph(next);return next;
}
export function deleteGraphItems(resource:GraphResource,nodes:string[],edges:string[]):GraphResource {
 const keep=(e:{id:string;source:string;target:string})=>!edges.includes(e.id)&&!nodes.includes(e.source)&&!nodes.includes(e.target);
 if(resource.kind==='workflow')return {...resource,tasks:resource.tasks.filter(n=>!nodes.includes(n.id)),dependencies:resource.dependencies.filter(keep)};
 if(resource.kind==='lineage')return {...resource,datasets:resource.datasets.filter(n=>!nodes.includes(n.id)),derivations:resource.derivations.filter(keep)};
 return {...resource,tables:resource.tables.filter(n=>!nodes.includes(n.id)),relationships:resource.relationships.filter(keep)};
}
/** Detach a resource reference/design; never delete a notebook, catalog table or run. */
export function removeResource(state:RootWorkbench,id:string):RootWorkbench {
 if(state.resources.some(r=>(r.kind==='workflow'&&r.tasks.some(t=>t.notebook_resource_id===id))||(r.kind==='pipeline'&&r.last_valid_ir?.tasks.some(t=>t.resource_id===id))))throw new Error('Unlink workflow task references before removing this notebook reference.');
 let next=state;for(const view of state.views.filter(v=>v.resource_id===id))next=closeView(next,view.id);
 next={...next,resources:next.resources.filter(r=>r.id!==id),migrations:next.migrations?.map(m=>({...m,resources:Object.fromEntries(Object.entries(m.resources).filter(([,r])=>r!==id))}))};assertWorkbench(next);return next;
}
