import type { DbtDefinition, DbtModelDefinition } from '../types.js';

export interface CompileResult { ok: boolean; sql: string; errors: string[]; replacements: string[]; }
export type ModelSqlOverrides = Record<string,string>;

export function compileDbtModel(model: DbtModelDefinition, project: DbtDefinition, incremental = false, overrides:ModelSqlOverrides = {}): CompileResult {
  return compileInternal(model,project,incremental,overrides,new Set());
}

function compileInternal(model:DbtModelDefinition, project:DbtDefinition, incremental:boolean, overrides:ModelSqlOverrides, stack:Set<string>):CompileResult{
  if(stack.has(model.id)) return {ok:false,sql:overrides[model.id]??model.sql,errors:[`Circular ref() encountered while compiling ${model.id}.`],replacements:[]};
  const nextStack=new Set(stack); nextStack.add(model.id);
  let sql = overrides[model.id] ?? model.sql;
  const errors: string[] = [];
  const replacements: string[] = [];
  const parsedDependencies=new Set(referencedResources(sql));
  const declaredDependencies=new Set(model.dependsOn);
  if(parsedDependencies.size!==declaredDependencies.size||[...parsedDependencies].some((dep)=>!declaredDependencies.has(dep))){
    errors.push(`Edited ref()/source() dependencies differ from the structured learning graph. Expected: ${[...declaredDependencies].join(', ')||'none'}; found: ${[...parsedDependencies].join(', ')||'none'}. Restore the example or keep dependencies unchanged.`);
  }

  sql = sql.replace(/\{\{\s*config\([\s\S]*?\)\s*\}\}/g, () => { replacements.push('Removed config() block at compile time'); return ''; });
  sql = sql.replace(/\{%\s*if\s+is_incremental\(\)\s*%\}([\s\S]*?)\{%\s*endif\s*%\}/g, (_match, body: string) => {
    replacements.push(incremental ? 'Included is_incremental() branch' : 'Excluded is_incremental() branch for full build');
    return incremental ? body : '';
  });
  sql = sql.replace(/\{\{\s*cents_to_currency\(['"]([^'"]+)['"]\)\s*\}\}/g, (_match, columnName:string) => {
    if(!project.macros.includes('cents_to_currency.sql')) errors.push('cents_to_currency() is used but macros/cents_to_currency.sql is not declared.');
    replacements.push(`Expanded supported macro cents_to_currency('${columnName}')`);
    return `(${columnName} / 100.0)`;
  });
  sql = sql.replace(/\{\{\s*normalized_reference\(['"]([^'"]+)['"]\)\s*\}\}/g, (_match, columnName:string) => {
    if(!project.macros.includes('normalized_reference.sql')) errors.push('normalized_reference() is used but macros/normalized_reference.sql is not declared.');
    replacements.push(`Expanded supported macro normalized_reference('${columnName}')`);
    return `upper(trim(${columnName}))`;
  });
  sql = sql.replace(/\{\{\s*session_key\(['"]([^'"]+)['"]\s*,\s*['"]([^'"]+)['"]\)\s*\}\}/g, (_match, userColumn:string, sessionColumn:string) => {
    if(!project.macros.includes('session_key.sql')) errors.push('session_key() is used but macros/session_key.sql is not declared.');
    replacements.push(`Expanded supported macro session_key('${userColumn}', '${sessionColumn}')`);
    return `concat(${userColumn}, '-', cast(${sessionColumn} as string))`;
  });
  sql = sql.replace(/\{\{\s*ref\(['"]([^'"]+)['"]\)\s*\}\}/g, (_match, name: string) => {
    const target=project.models.find((item) => item.id === name);
    const seed=project.seeds.find((file)=>seedId(file)===name);
    if (!target && !seed) {
      errors.push(`ref('${name}') does not match a model or seed in this project.`);
      return `__missing_ref__${name}`;
    }
    if(seed){
      replacements.push(`Resolved seed ref('${name}')`);
      return `analytics.${name}`;
    }
    if(target?.materialization==='ephemeral'){
      const compiled=compileInternal(target,project,incremental,overrides,nextStack);
      if(!compiled.ok) errors.push(...compiled.errors.map((error)=>`ephemeral ${name}: ${error}`));
      replacements.push(`Inlined ephemeral ref('${name}') as a derived relation (teaching approximation of dbt CTE injection)`);
      replacements.push(...compiled.replacements.map((item)=>`${name}: ${item}`));
      return `(\n${indent(compiled.sql,2)}\n)`;
    }
    replacements.push(`Resolved ref('${name}')`);
    return `analytics.${name}`;
  });
  sql = sql.replace(/\{\{\s*source\(['"]([^'"]+)['"]\s*,\s*['"]([^'"]+)['"]\)\s*\}\}/g, (_match, sourceName: string, tableName: string) => {
    const sourceId = `source.${sourceName}.${tableName}`;
    if (!project.sources.some((item) => item.id === sourceId)) errors.push(`source('${sourceName}', '${tableName}') is not declared.`);
    replacements.push(`Resolved source('${sourceName}', '${tableName}')`);
    return `${sourceName}.${tableName}`;
  });
  sql = sql.replace(/\{\{\s*this\s*\}\}/g, () => { replacements.push('Resolved this'); return `analytics.${model.id}`; });

  const unsupported = sql.match(/(\{\{[\s\S]*?\}\}|\{%[\s\S]*?%\})/g);
  if (unsupported) errors.push(`Unsupported Jinja in bounded compiler: ${unsupported.join(', ')}`);

  return { ok: errors.length === 0, sql: sql.trim(), errors:unique(errors), replacements:unique(replacements) };
}

function indent(value:string,spaces:number):string{
  const pad=' '.repeat(spaces);
  return value.split('\n').map((line)=>`${pad}${line}`).join('\n');
}
function unique(values:string[]):string[]{return [...new Set(values)];}
export function seedId(fileName:string):string{return fileName.replace(/\.csv$/i,'');}

export function referencedResources(sql: string): string[] {
  const refs = [...sql.matchAll(/\{\{\s*ref\(['"]([^'"]+)['"]\)\s*\}\}/g)].map((match) => match[1]);
  const sources = [...sql.matchAll(/\{\{\s*source\(['"]([^'"]+)['"]\s*,\s*['"]([^'"]+)['"]\)\s*\}\}/g)].map((match) => `source.${match[1]}.${match[2]}`);
  return [...refs, ...sources];
}

export function topologicalModels(project: DbtDefinition): DbtModelDefinition[] {
  const result: DbtModelDefinition[] = [];
  const remaining = new Map(project.models.map((model) => [model.id, model]));
  let guard = 0;
  while (remaining.size && guard < 100) {
    guard += 1;
    let progress = false;
    for (const [id, model] of remaining) {
      const modelIds=new Set(project.models.map((item)=>item.id));
      const internalDeps = model.dependsOn.filter((dep) => modelIds.has(dep));
      if (internalDeps.every((dep) => result.some((item) => item.id === dep))) {
        result.push(model); remaining.delete(id); progress = true;
      }
    }
    if (!progress) throw new Error(`dbt model graph contains a cycle or unknown dependency: ${[...remaining.keys()].join(', ')}`);
  }
  return result;
}
