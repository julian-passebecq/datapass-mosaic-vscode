import type { AirflowDefinition, AirflowRunState, AirflowTaskDefinition, AirflowTaskRuntime, AirflowTaskState, CaseStudy, ScenarioDefinition } from '../types.js';

const terminal = new Set<AirflowTaskState>(['success','failed','upstream_failed','skipped']);

export function createAirflowRun(definition: AirflowDefinition, runIndex = 1): AirflowRunState {
  return {
    runId:`sim__${new Date().toISOString().slice(0,19)}__${runIndex}`,
    status:'idle', step:0, elapsedSeconds:0,
    tasks:Object.fromEntries(definition.tasks.map((task) => [task.id,{state:'idle',attempts:0,sensorPokes:0}])),
    logs:[{step:0,level:'INFO',message:'SIMULATED DAG EXECUTION — no Airflow scheduler or worker is running.'}],
  };
}

function depStates(task: AirflowTaskDefinition, state: AirflowRunState): AirflowTaskState[] {
  return task.dependsOn.map((dep) => state.tasks[dep]?.state).filter((value): value is AirflowTaskState => value !== undefined);
}

function upstreamReadyAt(task:AirflowTaskDefinition,state:AirflowRunState):number{
  return task.dependsOn.reduce((latest,dep)=>Math.max(latest,state.tasks[dep]?.completedAtSeconds ?? 0),0);
}

function logicalStartAt(task:AirflowTaskDefinition,runtime:AirflowTaskRuntime,state:AirflowRunState):number{
  return Math.max(upstreamReadyAt(task,state),runtime.nextEligibleAtSeconds ?? 0);
}

function markTerminal(runtime:AirflowTaskRuntime,state:AirflowRunState,task:AirflowTaskDefinition,value:'success'|'failed',completedAt:number):void{
  runtime.state=value;
  runtime.completedAtSeconds=completedAt;
  runtime.nextEligibleAtSeconds=undefined;
  state.elapsedSeconds=Math.max(state.elapsedSeconds,completedAt);
}

function depsSatisfied(task: AirflowTaskDefinition, state: AirflowRunState): boolean {
  if (task.dependsOn.length === 0) return true;
  const states=depStates(task,state);
  if (states.length !== task.dependsOn.length) return false;
  const triggerRule=task.triggerRule ?? 'all_success';
  if (triggerRule === 'all_done') return states.every((value)=>terminal.has(value));
  if (triggerRule === 'none_failed_min_one_success') return states.every((value)=>terminal.has(value)) && !states.includes('failed') && !states.includes('upstream_failed') && states.includes('success');
  return states.every((value)=>value === 'success');
}

function blockedStateFromTriggerRule(task: AirflowTaskDefinition, state: AirflowRunState): 'upstream_failed'|'skipped'|undefined {
  if (task.dependsOn.length === 0) return undefined;
  const states=depStates(task,state);
  if (states.length !== task.dependsOn.length || !states.every((value)=>terminal.has(value))) return undefined;
  const triggerRule=task.triggerRule ?? 'all_success';
  if (triggerRule === 'all_done') return undefined;
  if (triggerRule === 'none_failed_min_one_success') {
    if(states.includes('failed')||states.includes('upstream_failed')) return 'upstream_failed';
    if(states.every((value)=>value==='skipped')) return 'skipped';
    if(!states.includes('success')) return 'upstream_failed';
    return undefined;
  }
  if(states.includes('failed')||states.includes('upstream_failed')) return 'upstream_failed';
  if(states.includes('skipped')) return 'skipped';
  return undefined;
}

function propagateTriggerRuleSkips(definition: AirflowDefinition, state: AirflowRunState): void {
  let changed=true;
  while(changed){
    changed=false;
    for(const task of definition.tasks){
      const runtime=state.tasks[task.id];
      if(runtime.state!=='idle') continue;
      const blockedState=blockedStateFromTriggerRule(task,state);
      if(blockedState){
        runtime.state=blockedState;
        runtime.completedAtSeconds=upstreamReadyAt(task,state);
        const reason=blockedState==='upstream_failed'?'an upstream task failed':'an upstream task was skipped';
        state.logs.push({step:state.step,taskId:task.id,level:'INFO',message:`${blockedState} because ${reason} and trigger_rule=${task.triggerRule ?? 'all_success'} was not satisfied.`});
        changed=true;
      }
    }
  }
}

export function stepAirflow(caseStudy: CaseStudy, scenario: ScenarioDefinition, previous: AirflowRunState): AirflowRunState {
  const definition = caseStudy.airflow;
  const state: AirflowRunState = JSON.parse(JSON.stringify(previous));
  if (definition.tasks.length === 0) {
    state.status = 'success';
    state.logs.push({step:state.step,level:'INFO',message:'Scratch mode: arbitrary code is not converted into simulated tasks.'});
    return state;
  }
  if (state.status === 'success' || state.status === 'failed') return state;

  state.step += 1;
  if (state.status === 'idle') { state.status='running'; state.startedAt=new Date().toISOString(); }

  for (const task of definition.tasks) {
    const runtime = state.tasks[task.id];
    if (runtime.state === 'retrying' || runtime.state === 'waiting') {
      const previousState = runtime.state;
      runtime.state='idle';
      state.logs.push({step:state.step,taskId:task.id,level:'INFO',message:previousState==='retrying'?'Simulated retry delay elapsed; the task is eligible for its next attempt.':'Sensor reschedule interval elapsed; the next poke is eligible.'});
    }
  }

  propagateTriggerRuleSkips(definition,state);
  const runnable = definition.tasks
    .filter((task) => state.tasks[task.id].state === 'idle' && depsSatisfied(task,state))
    .map((task,index)=>({task,index,startAt:logicalStartAt(task,state.tasks[task.id],state)}))
    .sort((a,b)=>a.startAt-b.startAt||a.index-b.index)[0]?.task;
  if (!runnable) return finalize(definition,state);
  const runtime = state.tasks[runnable.id];
  const startAt=logicalStartAt(runnable,runtime,state);
  runtime.firstStartedAtSeconds ??= startAt;

  if (scenario.effect === 'late_input' && scenario.targetTask === runnable.id && runtime.sensorPokes < 2) {
    runtime.sensorPokes += 1;
    runtime.state='waiting';
    runtime.nextEligibleAtSeconds=startAt+(runnable.sensorPokeIntervalSeconds ?? 60);
    state.elapsedSeconds=Math.max(state.elapsedSeconds,runtime.nextEligibleAtSeconds);
    state.logs.push({step:state.step,taskId:runnable.id,level:'INFO',message:`Sensor poke ${runtime.sensorPokes}: condition false at logical t+${startAt}s; rescheduled for t+${runtime.nextEligibleAtSeconds}s.`});
    return state;
  }

  if (scenario.effect === 'sensor_timeout' && scenario.targetTask === runnable.id) {
    const timeoutAfter=Math.max(1,scenario.sensorTimeoutPokes ?? 3);
    runtime.sensorPokes += 1;
    if(runtime.sensorPokes < timeoutAfter){
      runtime.state='waiting';
      runtime.nextEligibleAtSeconds=startAt+(runnable.sensorPokeIntervalSeconds ?? 60);
      state.elapsedSeconds=Math.max(state.elapsedSeconds,runtime.nextEligibleAtSeconds);
      state.logs.push({step:state.step,taskId:runnable.id,level:'INFO',message:`Sensor poke ${runtime.sensorPokes}/${timeoutAfter}: condition still false; next poke eligible at t+${runtime.nextEligibleAtSeconds}s.`});
      return state;
    }
    runtime.attempts += 1;
    const completedAt=startAt+runnable.durationSeconds;
    markTerminal(runtime,state,runnable,'failed',completedAt);
    state.logs.push({step:state.step,taskId:runnable.id,level:'ERROR',message:`Sensor timed out after ${runtime.sensorPokes} simulated pokes at logical t+${completedAt}s; downstream trigger rules now determine skip/run behavior.`});
    propagateTriggerRuleSkips(definition,state);
    return finalize(definition,state);
  }

  runtime.attempts += 1;
  runtime.state='running';
  const attemptEnd=startAt+runnable.durationSeconds;
  state.elapsedSeconds=Math.max(state.elapsedSeconds,attemptEnd);
  state.logs.push({step:state.step,taskId:runnable.id,level:'INFO',message:`Starting simulated task attempt ${runtime.attempts} at logical t+${startAt}s; expected duration ${runnable.durationSeconds}s.`});

  if (scenario.effect === 'transient' && scenario.targetTask === runnable.id && runtime.attempts === 1) {
    if(runnable.retries > 0){
      runtime.state='retrying';
      runtime.nextEligibleAtSeconds=attemptEnd+(runnable.retryDelaySeconds ?? 0);
      state.elapsedSeconds=Math.max(state.elapsedSeconds,runtime.nextEligibleAtSeconds);
      state.logs.push({step:state.step,taskId:runnable.id,level:'WARNING',message:`Transient failure injected at t+${attemptEnd}s. Retry 1/${runnable.retries} is eligible at t+${runtime.nextEligibleAtSeconds}s.`});
      return state;
    }
    markTerminal(runtime,state,runnable,'failed',attemptEnd);
    state.logs.push({step:state.step,taskId:runnable.id,level:'ERROR',message:'Transient failure injected, but this task has no retries configured; it fails on the first attempt.'});
    propagateTriggerRuleSkips(definition,state);
    return finalize(definition,state);
  }

  if ((scenario.effect === 'permanent' || scenario.effect === 'bad_quality') && scenario.targetTask === runnable.id) {
    if (scenario.effect === 'permanent' && runtime.attempts <= runnable.retries) {
      runtime.state='retrying';
      runtime.nextEligibleAtSeconds=attemptEnd+(runnable.retryDelaySeconds ?? 0);
      state.elapsedSeconds=Math.max(state.elapsedSeconds,runtime.nextEligibleAtSeconds);
      state.logs.push({step:state.step,taskId:runnable.id,level:'WARNING',message:`Failure persists at t+${attemptEnd}s. Retry ${runtime.attempts}/${runnable.retries} is eligible at t+${runtime.nextEligibleAtSeconds}s; the next attempt will still fail in this scenario.`});
      return state;
    }
    markTerminal(runtime,state,runnable,'failed',attemptEnd);
    state.logs.push({step:state.step,taskId:runnable.id,level:'ERROR',message:'Deterministic failure remains after configured retries; downstream trigger rules determine what is skipped.'});
    propagateTriggerRuleSkips(definition,state);
    return finalize(definition,state);
  }

  markTerminal(runtime,state,runnable,'success',attemptEnd);
  if(runnable.xcomPush) runtime.xcomValue=`simulated ${runnable.xcomPush}`;
  state.logs.push({step:state.step,taskId:runnable.id,level:'INFO',message:runnable.xcomPush ? `Task succeeded at t+${attemptEnd}s. Simulated XCom metadata: ${runnable.xcomPush}.` : `Task succeeded at t+${attemptEnd}s.`});

  const branchTask=scenario.branchTask ?? (scenario.effect==='branch'?scenario.targetTask:undefined);
  if (runnable.type === 'branch' && branchTask === runnable.id) {
    for (const id of scenario.branchSkip ?? []) {
      if (state.tasks[id]?.state === 'idle') {
        state.tasks[id].state='skipped';
        state.tasks[id].completedAtSeconds=attemptEnd;
      }
    }
    state.logs.push({step:state.step,taskId:runnable.id,level:'INFO',message:`Branch decision applied; direct non-selected task(s) skipped: ${(scenario.branchSkip ?? []).join(', ')}.`});
    propagateTriggerRuleSkips(definition,state);
  }
  return finalize(definition,state);
}

function finalize(definition: AirflowDefinition, state: AirflowRunState): AirflowRunState {
  const values = definition.tasks.map((task) => state.tasks[task.id].state);
  if (values.every((value) => terminal.has(value))) {
    const upstreamIds=new Set(definition.tasks.flatMap((task)=>task.dependsOn));
    const leaves=definition.tasks.filter((task)=>!upstreamIds.has(task.id));
    const leafStates=leaves.map((task)=>state.tasks[task.id].state);
    state.status = leafStates.some((value)=>value==='failed'||value==='upstream_failed') ? 'failed' : 'success';
    state.completedAt = new Date().toISOString();
    state.elapsedSeconds=Math.max(0,...definition.tasks.map((task)=>state.tasks[task.id].completedAtSeconds ?? 0));
    state.logs.push({step:state.step,level:'INFO',message:`DAG run state evaluated from leaf task states: ${leaves.map((task)=>`${task.id}=${state.tasks[task.id].state}`).join(', ')}.`});
  }
  return state;
}

export function simulationStepBudget(caseStudy:CaseStudy,scenario:ScenarioDefinition):number{
  const retryAttempts=caseStudy.airflow.tasks.reduce((total,task)=>total+Math.max(0,task.retries)+1,0);
  const sensorPokes=scenario.effect==='sensor_timeout' ? Math.max(1,scenario.sensorTimeoutPokes ?? 3) : scenario.effect==='late_input' ? 3 : 0;
  const branchPropagation=caseStudy.airflow.tasks.length;
  // Each structured action consumes one simulator step. Keep a generous deterministic margin for
  // trigger-rule propagation while allowing intentionally long sensor lessons without a false deadlock.
  return Math.max(25,retryAttempts+sensorPokes+branchPropagation*3+10);
}

export function runAirflowToEnd(caseStudy: CaseStudy, scenario: ScenarioDefinition, start: AirflowRunState): AirflowRunState {
  let state = start;
  const budget=simulationStepBudget(caseStudy,scenario);
  for (let i=0;i<budget && state.status !== 'success' && state.status !== 'failed';i+=1) state = stepAirflow(caseStudy,scenario,state);
  if(state.status === 'running'){
    const next:AirflowRunState=JSON.parse(JSON.stringify(state));
    next.status='failed';
    next.completedAt=new Date().toISOString();
    next.logs.push({step:next.step,level:'ERROR',message:`Simulation guard stopped after ${budget} steps. The structured DAG is likely deadlocked or invalid.`});
    return next;
  }
  return state;
}

export function validateAirflowDefinition(definition:AirflowDefinition):string[]{
  const errors:string[]=[];
  const ids=definition.tasks.map((task)=>task.id);
  const idSet=new Set(ids);
  if(idSet.size!==ids.length) errors.push('Airflow task IDs must be unique.');
  for(const task of definition.tasks){
    for(const dep of task.dependsOn) if(!idSet.has(dep)) errors.push(`${task.id} depends on missing task ${dep}.`);
    if(task.dependsOn.includes(task.id)) errors.push(`${task.id} cannot depend on itself.`);
    if(task.retries<0) errors.push(`${task.id} retries cannot be negative.`);
    if((task.retryDelaySeconds ?? 0)<0) errors.push(`${task.id} retryDelaySeconds cannot be negative.`);
    if(task.durationSeconds<0) errors.push(`${task.id} durationSeconds cannot be negative.`);
    if(task.type==='sensor'&&(task.sensorPokeIntervalSeconds ?? 0)<=0) errors.push(`${task.id} sensorPokeIntervalSeconds must be positive.`);
  }
  const remaining=new Map(definition.tasks.map((task)=>[task.id,task]));
  const resolved=new Set<string>();
  let progress=true;
  while(remaining.size&&progress){
    progress=false;
    for(const [id,task] of [...remaining]){
      if(task.dependsOn.every((dep)=>resolved.has(dep))){resolved.add(id);remaining.delete(id);progress=true;}
    }
  }
  if(remaining.size) errors.push(`Airflow DAG contains a dependency cycle or unresolved dependency: ${[...remaining.keys()].join(', ')}.`);
  return errors;
}
