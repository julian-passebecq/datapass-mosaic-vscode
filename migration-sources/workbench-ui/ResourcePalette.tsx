import {creatableResources} from './resourceFactories';
import {useEffect,useRef,useState} from 'react';
import type {Resource} from '../../../../../packages/contracts/src/foundation.ts';
export function ResourcePalette({resources,onOpen,onCreate,onNewNotebook,onClose}:{resources:Resource[];onOpen:(id:string)=>void;onCreate:(kind:typeof creatableResources[number][0])=>void;onNewNotebook?:()=>void;onClose:()=>void}) {
 const [query,setQuery]=useState('');const previous=useRef<HTMLElement|null>(document.activeElement as HTMLElement);
 useEffect(()=>()=>previous.current?.focus(),[]);
 return <div className="dp-palette-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget)onClose()}}><section className="dp-palette" role="dialog" aria-label="Open workspace resource" aria-modal="true" onKeyDown={e=>{
  if(e.key==='Escape'){e.preventDefault();onClose()}
  if(e.key==='Tab'){const items=e.currentTarget.querySelectorAll<HTMLElement>('input,button');const first=items[0],last=items[items.length-1];if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus()}}
 }}><h2>Open a resource</h2><input autoFocus aria-label="Search workspace resources" value={query} onChange={e=>setQuery(e.target.value)} placeholder="Notebook, model, chart, pipeline..."/>{resources.filter(r=>(r.title+' '+r.kind).toLowerCase().includes(query.toLowerCase())).map(r=><button key={r.id} onClick={()=>{onOpen(r.id);onClose()}}><strong>{r.title}</strong><small>{r.kind} / canonical resource</small></button>)}<h3>Create a new source</h3>{onNewNotebook&&<button onClick={()=>{onNewNotebook();onClose()}}>New notebook</button>}{creatableResources.filter(([,label])=>label.toLowerCase().includes(query.toLowerCase())).map(([kind,label])=><button key={kind} onClick={()=>{onCreate(kind);onClose()}}>New {label}</button>)}<button onClick={onClose}>Close / Esc</button></section></div>;
}
