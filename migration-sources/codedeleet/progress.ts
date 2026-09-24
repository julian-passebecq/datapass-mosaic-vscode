/** Independent, bounded backup boundary. No Practice Draft or engine dependency. */
import type { LearningState, Lesson, LessonProgress } from './types.js';
const labs=['code','model','pipeline','architecture'];
const object=(v:unknown):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v);
const safe=(v:unknown):v is string=>typeof v==='string'&&/^[a-zA-Z][a-zA-Z0-9_-]{0,79}$/.test(v)&&!['prototype',...Object.getOwnPropertyNames(Object.prototype)].includes(v);
function require(v:unknown,message:string):asserts v {if(!v)throw Error('Learning state: '+message);}
export const emptyLearning=():LearningState=>({progress:{},lastLessonByLab:{},lastCategoryByLab:{}});
export function normalizeLearning(value:unknown):LearningState {
 if(value===undefined)return emptyLearning();
 require(object(value),'expected an object');const result=emptyLearning();
 require(object(value.progress)&&Object.keys(value.progress).length<=2000,'invalid progress map');
 for(const [id,p]of Object.entries(value.progress)){
  require(safe(id)&&object(p),'unsafe lesson identifier');
  require(['not-started','in-progress','completed'].includes(String(p.status)),'unknown status');
  require(typeof p.updatedAt==='string'&&p.updatedAt.length<=40&&Number.isFinite(Date.parse(p.updatedAt)),'invalid timestamp');
  require(p.lastSection===undefined||safe(p.lastSection),'invalid section');
  require(p.notes===undefined||typeof p.notes==='string'&&p.notes.length<=20000,'notes exceed limit');
  result.progress[id]={status:p.status as LessonProgress['status'],updatedAt:p.updatedAt,...(p.lastSection?{lastSection:p.lastSection as string}:{}),...(p.notes!==undefined?{notes:p.notes as string}:{})};
 }
 for(const field of ['lastLessonByLab','lastCategoryByLab'] as const){
  if(value[field]===undefined)continue;require(object(value[field])&&Object.keys(value[field]).length<=4,'invalid lab memory');
  for(const [lab,id]of Object.entries(value[field])){require(labs.includes(lab)&&safe(id),'unsafe lab memory');(result[field] as Record<string,string>)[lab]=id;}
 }
 require(value.notes===undefined||typeof value.notes==='string'&&value.notes.length<=20000,'notebook exceeds limit');
 require(value.notesUpdatedAt===undefined||typeof value.notesUpdatedAt==='string'&&Number.isFinite(Date.parse(value.notesUpdatedAt))&&value.notesUpdatedAt.length<=40,'invalid notebook timestamp');
 if(typeof value.notes==='string')result.notes=value.notes;
 if(typeof value.notesUpdatedAt==='string')result.notesUpdatedAt=value.notesUpdatedAt;
 return result;
}
export function mergeLearning(a:unknown,b:unknown):LearningState {
 const result=normalizeLearning(a),other=normalizeLearning(b);
 for(const [id,p]of Object.entries(other.progress)){const old=result.progress[id];if(!old||Date.parse(p.updatedAt)>Date.parse(old.updatedAt))result.progress[id]={...p};}
 for(const lab of labs as (keyof LearningState['lastLessonByLab'])[]){
  const next=other.lastLessonByLab[lab],prior=result.lastLessonByLab[lab];
  if(next&&(!prior||Date.parse(other.progress[next]?.updatedAt??'1970-01-01')>Date.parse(normalizeLearning(a).progress[prior]?.updatedAt??'1970-01-01'))){result.lastLessonByLab[lab]=next;if(other.lastCategoryByLab[lab])result.lastCategoryByLab[lab]=other.lastCategoryByLab[lab];}
 }
 if(other.notes!==undefined&&(!result.notesUpdatedAt||Date.parse(other.notesUpdatedAt??'1970-01-01')>Date.parse(result.notesUpdatedAt))){result.notes=other.notes;result.notesUpdatedAt=other.notesUpdatedAt;}
 return result;
}
export function updateLesson(state:LearningState,lesson:Lesson,patch:Partial<Omit<LessonProgress,'updatedAt'>>={},now=new Date().toISOString()):void {
 const previous=state.progress[lesson.id];
 state.progress[lesson.id]={...previous,status:previous?.status==='completed'?'completed':'in-progress',...patch,updatedAt:now};
 state.lastLessonByLab[lesson.workspace]=lesson.id;state.lastCategoryByLab[lesson.workspace]=lesson.categoryId;
}
