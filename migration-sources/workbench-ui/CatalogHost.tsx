import {useEffect,useRef,useState} from 'react';
import type {Asset} from '../../../../../packages/contracts/src/index.ts';
import type {CatalogPreview} from '../../../../../packages/contracts/src/local.ts';
import type {ResourceServices} from './ResourceHost';
import {DataTable} from '../../ResultView';
export function CatalogHost({assets,services,disabled}:{assets:Asset[];services:ResourceServices;disabled:boolean}) {
 const [selected,setSelected]=useState(''),[preview,setPreview]=useState<CatalogPreview>(),[error,setError]=useState(''),[busy,setBusy]=useState(false),[asset,setAsset]=useState('bronze.imported_data'),[notice,setNotice]=useState('');const file=useRef<HTMLInputElement>(null),serial=useRef(0);
 const operation=useRef(0),ownerRef=useRef(services.workspaceId);ownerRef.current=services.workspaceId;
 useEffect(()=>{setSelected('');setPreview(undefined);setBusy(false);setNotice('');setError('');return()=>{serial.current++;operation.current++}},[services.workspaceId]);
 async function inspect(name:string){const ticket=++serial.current;setSelected(name);setError('');setPreview(undefined);try{const data=await services.api.previewCatalog(services.workspaceId,name);if(ticket===serial.current)setPreview(data)}catch(e){if(ticket===serial.current)setError(String(e))}}
 async function upload(f:File){
  const owner=services.workspaceId,ticket=++operation.current,current=()=>ownerRef.current===owner&&ticket===operation.current;
  setBusy(true);setError('');
  try{
   if(f.size>1_000_000)throw new Error('CSV limit: 1 MB, 5,000 rows.');
   const text=await f.text();if(!current())return;
   await services.save();if(!current())return;
   const w=await services.api.workspace(owner);if(!current())return;
   const result=await services.api.importCsv(owner,asset,text,w.revision);if(!current())return;
   await services.refresh();if(!current())return;
   setNotice(`Imported ${result.rows_imported} rows into ${result.asset}. All fields are VARCHAR; use explicit SQL casts for numeric/date types.`);
   await inspect(result.asset);
  }catch(e){if(current())setError(String(e))}finally{if(current())setBusy(false)}
 }

 return <section className="dp-catalog-host"><h2>Shared workspace catalog</h2><p>One catalog for notebooks, dbt, Polars and Pipeline Lab. Previews are bounded to 200 rows; they are not full table exports.</p><fieldset disabled={disabled||busy}><label>New table <input aria-label="CSV import table" value={asset} onChange={e=>setAsset(e.target.value)} placeholder="bronze.imported_data"/></label><button onClick={()=>file.current?.click()}>Import local CSV</button><input hidden ref={file} type="file" accept=".csv,text/csv" onChange={e=>{const f=e.target.files?.[0];e.target.value='';if(f)void upload(f)}}/><p>UTF-8 CSV, header required, up to 40 simple column names. Text is preserved; empty fields remain empty strings. Existing tables are never overwritten. No file or data is sent to a cloud service.</p><div className="table-scroller"><table><thead><tr><th>Table</th><th>Rows</th><th>Freshness</th></tr></thead><tbody>{assets.map(a=><tr key={a.name}><td><button aria-pressed={selected===a.name} onClick={()=>void inspect(a.name)}>{a.name}</button></td><td>{a.row_count}</td><td>{a.fresh?'Current':'Stale'}</td></tr>)}</tbody></table></div></fieldset>{error&&<p role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}{preview&&<><h3>{preview.asset} / {preview.engine}</h3><p>{preview.fresh?'Current registered input versions':'Stale registered input versions'}</p><details open><summary>Schema</summary><dl>{preview.schema.map(c=><div key={c.name}><dt>{c.name}</dt><dd>{c.type}</dd></div>)}</dl></details><DataTable result={preview.result}/></>}</section>;
}
