import {agencyApi as api,agencyPost as post,escapeHtml as e} from './agency-api.js';
export const GROUPS={
  web:{title:'SEO & Landing Pages',description:'Inspect supplied HTML, prepare evidence-led SEO briefs and build offline landing pages.',types:['seo-audits','seo-briefs','landing-pages']},
  crm:{title:'Email & CRM',description:'Client contacts, recorded consent, deterministic segments and email test packages. Export only; no email is sent.',types:['contacts','segments','email-templates']},
  audio:{title:'Audio & Subtitles',description:'Trim and normalize registered audio, edit timed captions, and export SRT or WebVTT. Optional Whisper uses explicitly installed local weights.',types:['audio-projects','subtitles']},
  privacy:{title:'Privacy & Retention',description:'Review retention, export client data, and explicitly erase a client. Prior backups and downloaded copies need separate handling.',types:['retention']},
  paid:{title:'Paid Media Planning',description:'Creative, audience, placement and budget scenarios. Ad spend is external; nothing here connects an account or authorizes spending.',types:['paid-plans']},
  creators:{title:'Creators & UGC',description:'Manually entered creator details, deliverables, disclosures and usage-rights briefs. No outreach is sent.',types:['creators','creator-briefs']}
};
export const TITLES={'seo-audits':'HTML audits','seo-briefs':'SEO briefs','landing-pages':'Landing pages',contacts:'Contacts',segments:'Segments','email-templates':'Email templates','audio-projects':'Audio projects',subtitles:'Subtitles',retention:'Retention policy','paid-plans':'Ad plans','creators':'Creators','creator-briefs':'Creator briefs','content-pillars':'Content pillars','content-series':'Content series'};
export const REFS={pillar_id:'content-pillars',source_copy_id:'copy',source_script_id:'scripts',landing_page_id:'landing-pages',creator_id:'creators'};
const prefix=page=>'/clients/'+page.client;
async function download(path,filename,method='GET'){
  const response=await fetch('/api/agency'+path,{method});
  if(!response.ok){const data=await response.json();throw new Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail));}
  const url=URL.createObjectURL(await response.blob()),link=document.createElement('a');
  link.href=url;link.download=filename;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),4000);
}
function show(page,value){let panel=page.$('[data-acquisition-result]');if(!panel){panel=document.createElement('div');panel.dataset.acquisitionResult='';page.$('[data-editor]').append(panel);}panel.innerHTML='<pre style="white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px">'+e(JSON.stringify(value,null,2))+'</pre>';}
function frame(page,url,html){
  let panel=page.$('[data-acquisition-result]');if(!panel){panel=document.createElement('div');panel.dataset.acquisitionResult='';page.$('[data-editor]').append(panel);}
  panel.innerHTML='<label>Preview width<select data-preview-width><option value="100%">Desktop</option><option value="768px">Tablet</option><option value="375px">Mobile</option></select></label><iframe title="Isolated local preview" sandbox="allow-scripts" style="width:100%;max-width:100%;height:600px;background:white;border:1px solid #456"></iframe>';
  const iframe=panel.querySelector('iframe');if(url)iframe.src=url;else iframe.srcdoc=html;
  panel.querySelector('select').onchange=event=>iframe.style.width=event.target.value;
}
function watch(page,item,job){
  const client=page.client;
  const tick=async()=>{
    if(page.client!==client||page.opened?.id!==item.id)return;
    try{
      const result=await api('/clients/'+client+'/jobs/'+job.id);
      page.status(result.kind+': '+result.state+' · '+(result.stage||''));
      if(result.state==='completed'){
        show(page,{saved_record:result.result.name,id:result.result.id,kind:result.result.kind});
        if(result.result.kind==='assets'){
          const link=document.createElement('a');link.className='ag-button';link.textContent='Download processed audio';link.href='/api/agency/clients/'+client+'/assets/'+result.result.id+'/file?download=true';page.$('[data-acquisition-result]').append(link);
        }else page.status('Transcription saved in Audio & Subtitles. Review the words and timings before use.');
      }else if(result.state==='failed')page.status(result.error,true);
      else if(result.state!=='cancelled')setTimeout(tick,500);
    }catch(error){page.status(error.message,true);}
  };
  tick();
  const button=document.createElement('button');button.type='button';button.textContent='Cancel audio job';
  button.onclick=()=>post('/clients/'+client+'/jobs/'+job.id+'/cancel').catch(error=>page.status(error.message,true));
  page.$('[data-actions]').append(button);
}
export function actions(page,item){
  if(!item)return;
  const area=page.$('[data-actions]'),path=prefix(page),fail=error=>page.status(error.message,true);
  if(!area)return;
  const add=(label,attr,fn)=>{const button=document.createElement('button');button.type='button';button.textContent=label;button.setAttribute(attr,'');button.onclick=()=>Promise.resolve().then(fn).catch(fail);area.append(button);};
  if(['paid-plans','creators','creator-briefs','content-pillars','content-series'].includes(page.kind))add('Export draft plan (.zip)','data-export-plan',()=>download(path+'/planning/'+item.id+'/export','draft-plan.zip'));
  if(page.kind==='paid-plans')add('Calculate budget scenario & UTM','data-paid-scenario',async()=>show(page,await api(path+'/paid-plans/'+item.id+'/scenario')));
  if(page.kind==='audio-projects')add('Render processed audio','data-render-audio',async()=>watch(page,item,await post(path+'/audio-projects/'+item.id+'/render')));
  if(page.kind==='subtitles')for(const format of ['srt','vtt'])add('Download '+format.toUpperCase(),'data-subtitle-'+format,()=>download(path+'/subtitles/'+item.id+'/export?format='+format,'captions.'+format));
  if(page.kind==='assets'&&['audio','video'].includes(item.data.asset_type)){
    api('/audio/capabilities').then(caps=>{
      if(page.opened?.id!==item.id)return;
      if(caps.asr.available)add('Transcribe locally ('+item.data.language+')','data-transcribe',async()=>watch(page,item,await post(path+'/assets/'+item.id+'/transcribe',{language:item.data.language})));
      else{const note=document.createElement('p');note.className='ag-note';note.textContent='Local transcription unavailable: configure the optional Whisper runtime and weights. Audio edits and manual subtitles remain available.';area.append(note);}
    }).catch(fail);
  }
  if(page.kind==='seo-audits')add('Inspect saved HTML','data-inspect-html',async()=>show(page,await api(path+'/seo/audits/'+item.id+'/inspect')));
  if(page.kind==='landing-pages'){
    add('Preview page','data-preview-page',()=>frame(page,'/api/agency'+path+'/landing-pages/'+item.id+'/preview'));
    add('Export static page (.zip)','data-export-page',()=>download(path+'/landing-pages/'+item.id+'/export','landing-page.zip'));
  }
  if(page.kind==='contacts'){
    const note=document.createElement('p');note.className='ag-note';note.textContent='Consent recorded: '+(item.data.consent_recorded_at||'unknown')+'. Changes are retained in version history. Unsubscribe and suppression override segment membership.';area.append(note);
  }
  if(page.kind==='segments')add('Preview eligible contacts','data-preview-segment',async()=>show(page,await api(path+'/segments/'+item.id+'/preview')));
  if(page.kind==='email-templates'){
    add('Preview email & checks','data-preview-email',async()=>{const result=await api(path+'/email-templates/'+item.id+'/preview');frame(page,null,result.html);page.status(result.checks.length?result.checks.join(' · '):result.method);});
    add('Export email test kit','data-export-email',()=>download(path+'/email-templates/'+item.id+'/export','email-test-kit.zip','POST'));
    const box=document.createElement('div');box.className='ag-wide';box.innerHTML='<label>Recipient segment (optional)<select data-email-segment><option value="">Template only</option></select></label><button type="button" data-export-recipients>Export with eligible recipient snapshot</button>';area.append(box);
    api(path+'/records?kind=segments&limit=100').then(result=>{if(page.opened?.id!==item.id)return;const select=box.querySelector('select');for(const s of result.items){const option=document.createElement('option');option.value=s.id;option.textContent=s.name;select.append(option);}}).catch(fail);
    box.querySelector('button').onclick=()=>{const id=box.querySelector('select').value;if(!id){page.status('Choose a segment to include a recipient snapshot.',true);return;}download(path+'/email-templates/'+item.id+'/export?segment_id='+id,'email-test-kit.zip','POST').then(()=>page.status('Downloaded test kit. Consent was checked now; recheck before any external send. No email was sent.')).catch(fail);};
  }
}
export function extras(page){
  if(page.kind==='retention'){
    const client=page.client,path=prefix(page),extra=page.$('[data-extra]');
    extra.innerHTML='<div class="ag-note">Exports contain client data and revision history. Keep them private.</div><button data-client-export>Export client data (.zip)</button><button data-retention-review>Review retention candidates</button><button data-erase-preview>Review client erasure</button>';
    extra.querySelector('[data-client-export]').onclick=()=>download(path+'/privacy/export','client-data.zip','POST').catch(error=>page.status(error.message,true));
    extra.querySelector('[data-retention-review]').onclick=()=>api(path+'/privacy/retention-review').then(result=>show(page,result)).catch(error=>page.status(error.message,true));
    extra.querySelector('[data-erase-preview]').onclick=async()=>{
      try{
        const result=await api(path+'/privacy/erasure-preview');if(page.client!==client)return;
        const editor=page.$('[data-editor]');editor.innerHTML='<h2>Permanent client erasure</h2><p>'+e(result.name)+'</p><p>'+e(result.effect)+'</p><div class="ag-note">'+e(result.retained)+'</div><pre>'+e(JSON.stringify(result.counts,null,2))+'</pre><label>Type '+e(result.confirmation)+'<input data-erasure-phrase autocomplete="off"></label><button data-erase-client disabled>Permanently erase this client</button>';
        const input=editor.querySelector('input'),button=editor.querySelector('button');
        input.oninput=()=>button.disabled=input.value!==result.confirmation;
        button.onclick=async()=>{if(page.client!==client)return;button.disabled=true;try{const response=await post(path+'/privacy/erase',{expected_version:result.version,confirmation:input.value,review_token:result.review_token});editor.textContent='Client erased. '+response.retained;if(response.files_requiring_manual_removal.length)editor.textContent+=' Files requiring manual removal: '+response.files_requiring_manual_removal.join(', ');window.dispatchEvent(new CustomEvent('lexnis:agency-client-erased',{detail:{client_id:client,message:editor.textContent}}));}catch(error){page.status(error.message,true);button.disabled=false;}};
      }catch(error){page.status(error.message,true);}
    };
  }
  if(['audio-projects','subtitles'].includes(page.kind)){
    const extra=page.$('[data-extra]');
    extra.innerHTML='<button data-audio-status style="margin-top:12px">Audio capabilities & model status</button>';
    extra.querySelector('button').onclick=()=>api('/audio/capabilities').then(result=>show(page,result)).catch(error=>page.status(error.message,true));
  }
  if(page.kind==='contacts'){
    const extra=page.$('[data-extra]');
    extra.innerHTML='<label class="ag-note">Import UTF-8 contacts CSV: name,email; optional language,source,tags (separate tags with |). Imported consent stays unknown.<input type="file" data-contacts-import accept=".csv"></label>';
    extra.querySelector('input').onchange=async event=>{
      const file=event.target.files[0];if(!file)return;
      try{const body=new FormData();body.append('file',file);const result=await api(prefix(page)+'/contacts/import',{method:'POST',body});await page.load();page.status('Imported '+result.imported+' contacts with unknown consent.');}
      catch(error){page.status(error.message,true);}finally{event.target.value='';}
    };
  }
  if(page.kind!=='seo-audits')return;
  const extra=page.$('[data-extra]');extra.innerHTML='<button data-compare-seo style="margin-top:12px">Compare saved audits</button><button data-source-seo>Audit a captured Research source</button>';
  extra.querySelector('[data-compare-seo]').onclick=()=>api(prefix(page)+'/seo/compare').then(result=>show(page,result)).catch(error=>page.status(error.message,true));
  extra.querySelector('[data-source-seo]').onclick=async()=>{
    try{
      const client=page.client,result=await api(prefix(page)+'/records?kind=sources&limit=100');
      const sources=result.items.filter(s=>s.data.snapshot_id&&s.data.url);
      if(!sources.length){page.status('Capture a website source in Research first. Online capture follows the configured allowlist and robots policy.');return;}
      const editor=page.$('[data-editor]');editor.innerHTML='<h2>Audit captured source</h2><label>Research source<select data-seo-source>'+sources.map(s=>'<option value="'+s.id+'">'+e(s.name)+'</option>').join('')+'</select></label><button data-create-audit>Create HTML audit</button>';
      editor.querySelector('button').onclick=async()=>{try{if(page.client!==client)return;const saved=await post(prefix(page)+'/seo/audit-source',{source_id:editor.querySelector('select').value});await page.load();await page.edit(saved);}catch(error){page.status(error.message,true);}};
    }catch(error){page.status(error.message,true);}
  };
}
