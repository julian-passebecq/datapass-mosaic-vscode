/** Case task answers never live in the standalone drafts map. */
import type { Draft,Question,Store,Workspace } from '../types.js';
export interface CasePage {id:string;title:string;body:string;table?:{columns:string[];rows:unknown[][]};}
export interface CaseTask {id:string;title:string;questionRef:string;pageRefs?:string[];artifactScope?:'independent';}
export interface CaseStudy {schemaVersion:1;id:string;version:number;workspace:Workspace;title:string;pages:CasePage[];tasks:CaseTask[];feedbackPolicy?:'learning';}
export interface CaseCheckpoint {id:string;at:string;taskId:string;reason:string;draft:Draft;}
export interface CaseSession {caseVersion:number;currentPageId:string;currentTaskId:string;drafts:Record<string,Draft>;checkpoints:CaseCheckpoint[];updatedAt:string;[key:string]:unknown;}
const clone=<T>(v:T):T=>JSON.parse(JSON.stringify(v));
const id=(v:unknown):v is string=>typeof v==='string'&&/^[A-Za-z][A-Za-z0-9_-]{0,79}$/.test(v)&&!['prototype',...Object.getOwnPropertyNames(Object.prototype)].includes(v);
function assert(c:unknown,m:string):asserts c{if(!c)throw Error(m);}
export function validateCase(value:unknown,questions:Question[]):CaseStudy{
 const c=value as CaseStudy;assert(c&&c.schemaVersion===1&&id(c.id),'Invalid case identifier/schema.');assert(Number.isInteger(c.version)&&c.version>0,'Invalid case version.');assert(['code','model','pipeline','architecture'].includes(c.workspace),'Invalid case lab.');assert(typeof c.title==='string'&&c.title.length<200,'Invalid case title.');assert(Array.isArray(c.pages)&&c.pages.length>0&&c.pages.length<=30&&Array.isArray(c.tasks)&&c.tasks.length>0&&c.tasks.length<=30,'Case limit: 1-30 pages/tasks.');
 const pages=new Set<string>(),tasks=new Set<string>();
 for(const p of c.pages){assert(id(p.id)&&!pages.has(p.id)&&typeof p.title==='string'&&typeof p.body==='string'&&p.body.length<=30000,'Invalid case page.');pages.add(p.id);if(p.table){assert(Array.isArray(p.table.columns)&&p.table.columns.length>0&&p.table.columns.length<=30&&p.table.columns.every(x=>typeof x==='string'&&x.length<200),'Invalid exhibit columns.');assert(Array.isArray(p.table.rows)&&p.table.rows.length<=200&&p.table.rows.every(row=>Array.isArray(row)&&row.length===p.table!.columns.length&&row.every(x=>x===null||typeof x==='boolean'||typeof x==='number'&&Number.isFinite(x)||typeof x==='string'&&x.length<=10000)),'Invalid exhibit rows.');}}
 for(const t of c.tasks){assert(id(t.id)&&!tasks.has(t.id)&&typeof t.title==='string'&&id(t.questionRef),'Invalid case task.');tasks.add(t.id);assert(questions.some(q=>q.id===t.questionRef&&q.workspace===c.workspace),'Case task references a missing exercise or another lab: '+t.questionRef);assert(!t.pageRefs||t.pageRefs.every(p=>pages.has(p)),'Unknown case exhibit.');}
 return clone(c);
}
export function validateSessions(value:unknown,checkDrafts:(drafts:Record<string,Draft>)=>void):void{
 if(value===undefined)return;assert(value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).length<=100,'Invalid case sessions.');
 for(const [key,s] of Object.entries(value as Record<string,CaseSession>)){
  assert(id(key)&&s&&typeof s==='object'&&Number.isInteger(s.caseVersion)&&s.caseVersion>0,'Invalid case session.');assert(id(s.currentPageId)&&id(s.currentTaskId)&&typeof s.updatedAt==='string'&&Number.isFinite(Date.parse(s.updatedAt)),'Invalid case session cursor.');checkDrafts(s.drafts);
  assert(Array.isArray(s.checkpoints)&&s.checkpoints.length<=100,'Case checkpoint limit exceeded.');for(const cp of s.checkpoints){assert(id(cp.id)&&id(cp.taskId)&&typeof cp.reason==='string'&&Number.isFinite(Date.parse(cp.at)),'Invalid case checkpoint.');checkDrafts({checkpoint:cp.draft});}
 }
}
export function ensureSession(store:Store,c:CaseStudy):CaseSession{
 store.caseSessions??={};let s=store.caseSessions[c.id];
 if(!s){s={caseVersion:c.version,currentPageId:c.pages[0].id,currentTaskId:c.tasks[0].id,drafts:{},checkpoints:[],updatedAt:new Date().toISOString()};store.caseSessions[c.id]=s;}
 // No draft removal, even for unknown task IDs in a newer/older backup.
 if(!c.pages.some(p=>p.id===s.currentPageId))s.currentPageId=c.pages[0].id;
 if(!c.tasks.some(t=>t.id===s.currentTaskId))s.currentTaskId=c.tasks[0].id;
 return s;
}
export function taskDraft(store:Store,c:CaseStudy):Draft{const s=ensureSession(store,c);return s.drafts[s.currentTaskId]??{};}
export function patchTask(store:Store,c:CaseStudy,patch:Partial<Draft>):void{const s=ensureSession(store,c),now=new Date().toISOString();s.drafts[s.currentTaskId]={...s.drafts[s.currentTaskId],...clone(patch),updatedAt:now};s.updatedAt=now;}
export function selectPage(store:Store,c:CaseStudy,pageId:string):void{assert(c.pages.some(p=>p.id===pageId),'Unknown exhibit.');const s=ensureSession(store,c);s.currentPageId=pageId;s.updatedAt=new Date().toISOString();}
export function selectTask(store:Store,c:CaseStudy,taskId:string):void{assert(c.tasks.some(t=>t.id===taskId),'Unknown case task.');const s=ensureSession(store,c);s.currentTaskId=taskId;s.updatedAt=new Date().toISOString();}
export function copyStandalone(store:Store,c:CaseStudy,q:Question):void{
 const s=ensureSession(store,c),old=s.drafts[s.currentTaskId]??{},now=new Date().toISOString();
 s.checkpoints=[...s.checkpoints,{id:'checkpoint-'+Date.now().toString(36)+'-'+s.checkpoints.length,at:now,taskId:s.currentTaskId,reason:'Before explicit copy of standalone attempt',draft:clone(old)}].slice(-100);
 const source=clone(store.drafts[q.id]??{});s.drafts[s.currentTaskId]={...source,code:source.code??q.starter,updatedAt:now,attempts:[...(source.attempts??[]),{at:now,kind:'Explicit standalone copy',passed:null,summary:'Copied into case; standalone answer unchanged. Previous case draft checkpoint retained.'}].slice(-100)};s.updatedAt=now;
}
export function restoreCheckpoint(store:Store,c:CaseStudy,checkpointId:string):void{const s=ensureSession(store,c),cp=s.checkpoints.find(x=>x.id===checkpointId&&x.taskId===s.currentTaskId);assert(cp,'Checkpoint not found for this task.');const current=clone(s.drafts[s.currentTaskId]??{}),now=new Date().toISOString();s.checkpoints=[...s.checkpoints,{id:'restore-'+Date.now().toString(36),at:now,taskId:s.currentTaskId,reason:'Before restoring checkpoint',draft:current}].slice(-100);s.drafts[s.currentTaskId]={...clone(cp.draft),updatedAt:now};s.updatedAt=now;}
export function mergeSessions(current:Record<string,CaseSession>={},incoming:Record<string,CaseSession>={}):Record<string,CaseSession>{
 const result=clone(current);for(const [id,s]of Object.entries(incoming)){const old=result[id];if(!old){result[id]=clone(s);continue;}const newer=Date.parse(s.updatedAt)>Date.parse(old.updatedAt);const merged={...(newer?s:old),drafts:clone(old.drafts),checkpoints:clone(old.checkpoints)};
  for(const [tid,d]of Object.entries(s.drafts)){const prior=merged.drafts[tid];if(!prior||Date.parse(d.updatedAt??'1970-01-01')>Date.parse(prior.updatedAt??'1970-01-01'))merged.drafts[tid]=clone(d);}
  for(const cp of s.checkpoints)if(!merged.checkpoints.some(x=>x.id===cp.id))merged.checkpoints.push(clone(cp));merged.checkpoints=merged.checkpoints.slice(-100);result[id]=merged;
 }return result;
}
