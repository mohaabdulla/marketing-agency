import {escapeHtml as e} from './agency-api.js';
import {reviewGuideline} from './guideline-review.js';
const target=document.getElementById('guidelines-card');
if(target){
  const row=document.createElement('div');row.className='vs-row';row.innerHTML='<label style="flex:1">Shared guideline library<select data-shared-guidelines><option value="">Choose a saved guideline</option></select></label><button type="button" data-refresh-guidelines>Refresh</button><button type="button" data-use-guidelines>Use in Image & GIF</button><button type="button" data-review-brand-kit>Review selected brand kit</button><span role="status" data-shared-status></span>';target.append(row);
  const review=document.createElement('div');review.className='vs';review.style.minHeight='0';review.dataset.imageGuidelineReview='';target.append(review);
  const read=async(response)=>{const data=await response.json().catch(()=>({}));if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail||'Guideline unavailable'));return data;};
  const show=async doc=>{
    const response=await fetch('/api/video/assets');const assets=response.ok?(await response.json()).filter(a=>a.kind==='image'):[];
    reviewGuideline(review,doc,assets,rules=>run(async()=>{
      const updated=await read(await fetch('/api/guidelines/'+doc.id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_version:doc.version,rules,confirmed:true})}));
      window.dispatchEvent(new CustomEvent('lexnis:guideline-selected',{detail:updated}));await show(updated);await load();
    })());
  };
  const load=async()=>{const response=await fetch('/api/guidelines');if(!response.ok)throw new Error('Guideline library unavailable');const list=await response.json();row.querySelector('select').innerHTML='<option value="">Choose a saved guideline</option>'+list.map(d=>'<option value="'+d.id+'">'+e(d.rules.brand_name||d.filename)+' · v'+d.version+'</option>').join('');};
  const run=fn=>async()=>{try{await fn();row.querySelector('[role=status]').textContent='Ready.';}catch(error){row.querySelector('[role=status]').textContent=error.message;}};
  row.querySelector('[data-refresh-guidelines]').onclick=run(load);
  row.querySelector('[data-use-guidelines]').onclick=run(async()=>{const id=row.querySelector('select').value;if(!id)throw new Error('Choose a guideline first');const data=await read(await fetch('/api/guidelines/'+id));await show(data);if(data.confirmed)window.dispatchEvent(new CustomEvent('lexnis:guideline-selected',{detail:data}));else row.querySelector('[role=status]').textContent='Review and confirm the extracted rules below.';});
  row.querySelector('[data-review-brand-kit]').onclick=run(async()=>{const id=document.getElementById('agency-brand-select')?.value;if(!id)throw new Error('Select a brand kit in Company & Brand Identity first');await show(await read(await fetch('/api/guidelines/from-brand/'+id,{method:'POST'})));});
  window.addEventListener('lexnis:image-guideline',event=>run(async()=>{await show(event.detail);await load();})());
  document.getElementById('guidelines-remove-btn')?.addEventListener('click',()=>{review.innerHTML='';});
  window.addEventListener('lexnis:guideline-cleared',()=>{review.innerHTML='';});
  load().catch(()=>{});
}
