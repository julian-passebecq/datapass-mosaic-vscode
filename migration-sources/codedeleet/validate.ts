import {safeId,safeHTTPS,WORKSPACES} from '../core.js';
import {categoryFor} from '../navigation/taxonomy.js';
import type {Question} from '../types.js';
import type {Lesson,LessonBlock} from './types.js';
function assert(v:unknown,m:string):asserts v {if(!v)throw Error('Lesson content: '+m);}
const obj=(v:unknown):v is Record<string,any>=>!!v&&typeof v==='object'&&!Array.isArray(v);
const text=(v:unknown,max=6000):v is string=>typeof v==='string'&&v.trim().length>0&&v.length<=max&&!/<\/?[a-z][^>]*>/i.test(v);
const texts=(v:unknown,max=20):v is string[]=>Array.isArray(v)&&v.length>0&&v.length<=max&&v.every(x=>text(x));
function scan(v:unknown):void{if(typeof v==='string')assert(v.length<=16000&&!/<\/?[a-z][^>]*>/i.test(v),'raw HTML / oversized string rejected');else if(Array.isArray(v))v.forEach(scan);else if(obj(v)){for(const [k,x]of Object.entries(v)){assert(!['__proto__','prototype','constructor'].includes(k),'unsafe key');scan(x);}}}
const kinds=['intro','concept','bullets','steps','code','table','diagram','comparison','whenToUse','pitfall','workedExample','checkpoint','keyTakeaways','relatedPractice'];
export function validateLesson(value:unknown,questions:Question[]):Lesson {
 assert(obj(value)&&JSON.stringify(value).length<=120000,'invalid or oversized lesson');scan(value);const l=value;
 assert(safeId(l.id),'invalid lesson ID');assert(Object.hasOwn(WORKSPACES,l.workspace),'invalid workspace');assert(categoryFor(l.workspace,l.categoryId),'invalid workspace/category pair');
 assert(Number.isInteger(l.version)&&l.version>0&&l.version<=1000,'invalid version');assert(Number.isInteger(l.minutes)&&l.minutes>0&&l.minutes<=60,'invalid reading time');
 assert(text(l.title,160)&&text(l.summary,800)&&texts(l.objectives,8),'missing title, summary or objectives');
 assert(l.prerequisites===undefined||texts(l.prerequisites,8),'invalid prerequisites');assert(Array.isArray(l.blocks)&&l.blocks.length>=1&&l.blocks.length<=40,'invalid blocks');
 const ids=new Set<string>(),qids=new Set(questions.map(q=>q.id));
 for(const b of l.blocks){assert(obj(b)&&safeId(b.id)&&!ids.has(b.id),'duplicate/invalid block ID');ids.add(b.id);assert(kinds.includes(b.kind),'unknown block kind');assert(b.title===undefined||text(b.title,160),'invalid block title');
  switch(b.kind){
   case 'intro':case 'concept':case 'pitfall':assert(text(b.text),'invalid paragraph');for(const k of ['mentalModel','correction'])assert(b[k]===undefined||text(b[k]),'invalid '+k);break;
   case 'bullets':case 'keyTakeaways':assert(texts(b.items,b.kind==='keyTakeaways'?5:16),'invalid bullet items');break;
   case 'steps':assert(Array.isArray(b.steps)&&b.steps.length>0&&b.steps.length<=15&&b.steps.every((s:unknown)=>obj(s)&&text(s.title,160)&&text(s.text)),'invalid steps');break;
   case 'code':assert(text(b.language,40)&&text(b.code,16000),'invalid code');assert(b.caption===undefined||text(b.caption),'invalid caption');break;
   case 'table':assert(texts(b.columns,8)&&Array.isArray(b.rows)&&b.rows.length>0&&b.rows.length<=40&&b.rows.every((r:unknown)=>texts(r,8)&&r.length===b.columns.length),'invalid table');break;
   case 'comparison':for(const col of [b.left,b.right])assert(obj(col)&&text(col.title,160)&&texts(col.items,10),'invalid comparison');break;
   case 'whenToUse':assert(Array.isArray(b.items)&&b.items.length>0&&b.items.length<=12&&b.items.every((i:unknown)=>obj(i)&&text(i.signal)&&text(i.choice)),'invalid decision rows');break;
   case 'workedExample':assert(texts(b.steps,15)&&(!b.result||text(b.result)),'invalid worked example');break;
   case 'checkpoint':assert(text(b.question)&&text(b.answer)&&text(b.explanation)&&(b.choices===undefined||texts(b.choices,6)),'invalid checkpoint');break;
   case 'relatedPractice':assert(Array.isArray(b.exerciseIds)&&b.exerciseIds.length<=5&&b.exerciseIds.every((id:unknown)=>safeId(id)&&qids.has(id)),'broken related exercise ID');break;
   case 'diagram':{
    const d=b.diagram;assert(obj(d)&&text(d.label,300)&&Array.isArray(d.nodes)&&d.nodes.length>0&&d.nodes.length<=12&&Array.isArray(d.edges)&&d.edges.length<=24,'invalid diagram bounds');
    const nodes=new Set<string>();for(const n of d.nodes){assert(obj(n)&&safeId(n.id)&&!nodes.has(n.id)&&text(n.label,48)&&(n.detail===undefined||text(n.detail,70)),'invalid diagram node');nodes.add(n.id);}
    for(const edge of d.edges)assert(obj(edge)&&nodes.has(edge.from)&&nodes.has(edge.to)&&edge.from!==edge.to&&(edge.label===undefined||text(edge.label,50)),'invalid diagram edge');
    assert(b.caption===undefined||text(b.caption),'invalid diagram caption');break;
   }
  }
 }
 assert(Array.isArray(l.sources)&&l.sources.length<=12&&l.sources.every((s:unknown)=>obj(s)&&text(s.label,160)&&safeHTTPS(s.url)),'invalid HTTPS sources');
 return JSON.parse(JSON.stringify(value)) as Lesson;
}
export function validateCatalog(input:unknown,questions:Question[]):Lesson[]{
 assert(Array.isArray(input)&&input.length<=200,'invalid catalog');const lessons=input.map(l=>validateLesson(l,questions));
 assert(new Set(lessons.map(l=>l.id)).size===lessons.length,'duplicate lesson ID');return lessons;
}
export function blockTitle(b:LessonBlock):string{return b.title??({intro:'Start here',concept:'Mental model',bullets:'Patterns',steps:'Step by step',code:'Code example',table:'At a glance',diagram:'Follow the flow',comparison:'Compare approaches',whenToUse:'When to use',pitfall:'Common mistake',workedExample:'Worked example',checkpoint:'Check your understanding',keyTakeaways:'Key takeaways',relatedPractice:'Put it into practice'}[b.kind]);}
