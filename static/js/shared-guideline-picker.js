import {escapeHtml as e} from './agency-api.js';
const target=document.getElementById('guidelines-card');
if(target){
  const row=document.createElement('div');row.className='vs-row';row.innerHTML='<label style="flex:1">Shared guideline library<select data-shared-guidelines><option value="">Choose a saved guideline</option></select></label><button type="button" data-refresh-guidelines>Refresh</button><button type="button" data-use-guidelines>Use in Image & GIF</button><span role="status" data-shared-status></span>';target.append(row);
  const load=async()=>{const response=await fetch('/api/guidelines');if(!response.ok)throw new Error('Guideline library unavailable');const list=await response.json();row.querySelector('select').innerHTML='<option value="">Choose a saved guideline</option>'+list.map(d=>'<option value="'+d.id+'">'+e(d.rules.brand_name||d.filename)+' · v'+d.version+'</option>').join('');};
  const run=fn=>async()=>{try{await fn();row.querySelector('[role=status]').textContent='Ready.';}catch(error){row.querySelector('[role=status]').textContent=error.message;}};
  row.querySelector('[data-refresh-guidelines]').onclick=run(load);
  row.querySelector('[data-use-guidelines]').onclick=run(async()=>{const id=row.querySelector('select').value;if(!id)throw new Error('Choose a guideline first');const response=await fetch('/api/guidelines/'+id);if(!response.ok)throw new Error('Guideline not available');const data=await response.json();window.dispatchEvent(new CustomEvent('lexnis:guideline-selected',{detail:data}));});
  load().catch(()=>{});
}
