import type { AirflowDefinition } from '../types.js';

export interface ScheduleIntervalPreview {
  start:string;
  end:string;
  runAfter:string;
  kind:'scheduled'|'backfill';
}

interface CronSpec { minute:number; hour:number|null; weekdays:Set<number>|null; }

const pad=(value:number)=>String(value).padStart(2,'0');
const isoMinute=(date:Date)=>`${date.getUTCFullYear()}-${pad(date.getUTCMonth()+1)}-${pad(date.getUTCDate())} ${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())} UTC`;

function parseWeekdays(field:string):Set<number>|null{
  if(field==='*') return null;
  const result=new Set<number>();
  for(const token of field.split(',')){
    if(/^\d$/.test(token)) {
      const value=Number(token);
      if(value<0||value>7) return new Set<number>();
      result.add(value%7);
    } else {
      const match=token.match(/^(\d)-(\d)$/);
      if(!match) return new Set<number>();
      let current=Number(match[1]); const end=Number(match[2]);
      if(current<0||current>7||end<0||end>7||current>end) return new Set<number>();
      for(;current<=end;current+=1) result.add(current%7);
    }
  }
  return result;
}

export function parseBoundedCron(schedule:string):CronSpec|undefined{
  const normalized=schedule.trim()==='@daily'?'0 0 * * *':schedule.trim()==='@hourly'?'0 * * * *':schedule.trim();
  const parts=normalized.split(/\s+/);
  if(parts.length!==5) return undefined;
  const [minuteField,hourField,dayField,monthField,weekdayField]=parts;
  if(!/^\d{1,2}$/.test(minuteField)||!(hourField==='*'||/^\d{1,2}$/.test(hourField))) return undefined;
  if(dayField!=='*'||monthField!=='*') return undefined;
  const minute=Number(minuteField); const hour=hourField==='*'?null:Number(hourField);
  if(minute<0||minute>59||(hour!==null&&(hour<0||hour>23))) return undefined;
  const weekdays=parseWeekdays(weekdayField);
  if(weekdays && weekdays.size===0) return undefined;
  return {minute,hour,weekdays};
}

function matchesBoundary(date:Date,spec:CronSpec):boolean{
  if(date.getUTCMinutes()!==spec.minute) return false;
  if(spec.hour!==null&&date.getUTCHours()!==spec.hour) return false;
  if(spec.weekdays&&!spec.weekdays.has(date.getUTCDay())) return false;
  return true;
}

function previousBoundary(before:Date,spec:CronSpec):Date{
  const cursor=new Date(before.getTime()-60_000);
  cursor.setUTCSeconds(0,0);
  for(let guard=0;guard<60*24*14;guard+=1){
    if(matchesBoundary(cursor,spec)) return new Date(cursor);
    cursor.setUTCMinutes(cursor.getUTCMinutes()-1);
  }
  throw new Error('Bounded cron preview could not find a prior boundary within 14 days.');
}

export function previewDataIntervals(definition:AirflowDefinition,count=3,anchor=new Date('2026-09-17T15:00:00Z')):ScheduleIntervalPreview[]{
  const spec=parseBoundedCron(definition.schedule);
  if(!spec) return [];
  const boundaries:Date[]=[];
  let cursor=new Date(anchor);
  while(boundaries.length<count+1){
    const boundary=previousBoundary(cursor,spec);
    boundaries.unshift(boundary);
    cursor=boundary;
  }
  const intervals:ScheduleIntervalPreview[]=[];
  for(let index=0;index<boundaries.length-1;index+=1){
    const start=boundaries[index]; const end=boundaries[index+1];
    intervals.push({start:isoMinute(start),end:isoMinute(end),runAfter:isoMinute(end),kind:'scheduled'});
  }
  return intervals;
}

export function scheduleDescription(schedule:string):string{
  const spec=parseBoundedCron(schedule);
  if(!spec) return 'This schedule is outside the bounded cron preview; the simulator will not invent timetable intervals.';
  const minute=pad(spec.minute);
  const cadence=spec.hour===null?`hourly at minute ${minute}`:`at ${pad(spec.hour)}:${minute} UTC`;
  if(!spec.weekdays) return cadence;
  const weekdays=[...spec.weekdays].sort((a,b)=>a-b);
  const labels=['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
  return `${cadence} on ${weekdays.map((day)=>labels[day]).join(', ')}`;
}
