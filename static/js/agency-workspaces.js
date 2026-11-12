import {agencyApi as api,agencyPost as post,escapeHtml as e,human} from './agency-api.js';
import {context,contextName,setClient,setCampaign,refreshContext} from './app-context.js';
import * as P from './agency-production.js';

const GROUPS={
  clients:{title:'Clients & Brands',description:'Keep client knowledge, brand rules and substantiated claims together.',types:['clients','projects','brands','glossary','stakeholders','access','onboarding','evidence','claims']},
  research:{title:'Research',description:'Capture sources, distinguish findings from hypotheses, and retain their provenance.',types:['sources','findings','competitors']},
  strategy:{title:'Strategy',description:'Connect business goals to audiences, positioning, messages and channel decisions.',types:['strategies','objectives','audiences','personas','journey','positionings','messages','offers']},
  campaigns:{title:'Campaigns',description:'Turn strategy into a versioned brief and a practical delivery plan.',types:['campaigns','briefs','channels','deliverables']},
};
const TITLES={clients:'Clients',projects:'Projects',brands:'Brand kits',glossary:'Terminology',stakeholders:'Stakeholders',access:'Access checklist',onboarding:'Onboarding',evidence:'Evidence',claims:'Claims',sources:'Sources',findings:'Findings',competitors:'Competitors',strategies:'Strategy documents',objectives:'Objectives',audiences:'Audience segments',personas:'JTBD / personas',journey:'Journey stages',positionings:'Positioning',messages:'Message pillars',offers:'Offers',campaigns:'Campaigns',briefs:'Creative briefs',channels:'Channel plans',deliverables:'Deliverables'};
const REFS={source_ids:'sources',evidence_ids:'evidence',approved_claim_ids:'claims',claim_ids:'claims',audience_id:'audiences',audience_ids:'audiences',objective_ids:'objectives',positioning_id:'positionings',message_ids:'messages',offer_id:'offers',brand_id:'brands',strategy_id:'strategies'};
const FIELD_LABELS={source_ids:'Sources',evidence_ids:'Supporting evidence',claim_ids:'Approved claims',approved_claim_ids:'Approved claims',audience_id:'Audience segment',audience_ids:'Audience segments',objective_ids:'Objectives',positioning_id:'Positioning',message_ids:'Message pillars',offer_id:'Offer',brand_id:'Brand kit',strategy_id:'Strategy'};
const HIDDEN=new Set(['document_id','snapshot_id','captured_at','legacy_brand_id','generation','consent_recorded_at']);
Object.assign(GROUPS,P.GROUPS);Object.assign(TITLES,P.TITLES);Object.assign(REFS,P.REFS);Object.assign(FIELD_LABELS,P.FIELD_LABELS);
const pages=new Map();let schemas;
const navigate=name=>window.dispatchEvent(new CustomEvent('lexnis:workspace',{detail:{name}}));
const scoped=(client,path)=>`/clients/${client}${path}`;

export async function mountAgencySystem(root){
  try{
    const [health,model]=await Promise.all([api('/health'),api('/local-text/status')]);
    const target=root.querySelector('.vs');if(!target)return;
    const card=document.createElement('section');card.className='vs-card';card.style.marginTop='20px';
    card.innerHTML=`<h2>Agency core & local text</h2><p>SQLite schema ${health.schema_version} · ${e(health.network)} · ${e(health.mode)}</p><h3>${e(model.id)} · ${e(model.license)}</h3><p>Installed: ${model.installed?'Yes':'No'} · Reachable: ${model.reachable?'Yes':'No'} · Verified inference: ${model.verified?'Recorded':'Not verified'}</p><p>${e(model.reason)}</p><p><small>${e(model.lifecycle)} Suggested RAM: ${model.recommended_ram_gb} GB. No model is downloaded at startup. See LOCAL_AI.md for explicit installation.</small></p>`;
    target.append(card);
  }catch{ /* Existing media status remains usable if the additive agency API is unavailable. */ }
}

export async function mountAgency(name,root){
  if(!schemas)schemas=await api('/schemas');
  if(name==='dashboard')return dashboard(root);
  if(!pages.has(name))pages.set(name,new Page(name,root));
  return pages.get(name).activate();
}

async function dashboard(root){
  const ctx=context();root.innerHTML='<div class="ag"><h1>Agency Dashboard</h1><p>Loading saved agency work…</p></div>';
  try{
    const data=await api('/dashboard'+(ctx.client_id?'?client_id='+ctx.client_id:''));
    root.innerHTML=`<div class="ag"><div class="ag-header"><div><div class="ag-eyebrow">LEXNIS / AGENCY OPERATIONS</div><h1>Agency Dashboard</h1><p>${e(contextName())} · Plan from evidence, then produce.</p></div><span class="ag-badge">LOCAL CORE</span></div><div class="ag-metrics">${[['Active clients',data.active_clients],['Campaigns',data.counts.campaigns||0],['Research findings',data.counts.findings||0],['Creative briefs',data.counts.briefs||0]].map(([label,value])=>`<div class="ag-panel ag-metric"><small>${label}</small><strong>${value}</strong></div>`).join('')}</div><div class="ag-grid"><div class="ag-panel"><h2>Next steps</h2><p>Create a client, collect evidence and define a strategy before producing creative work.</p><div class="ag-row"><button class="primary" data-go="agency-clients">Clients & Brands</button><button data-go="agency-research">Research</button><button data-go="agency-campaigns">Campaigns</button></div><div class="ag-note">Planning works without an AI model or paid API. Image and Video Studio retain their existing capabilities and provider choices.</div><button id="ag-backup">Create agency backup</button><div id="ag-backup-result" role="status"></div></div><div class="ag-panel"><h2>Recent saved work</h2>${data.recent.length?data.recent.map(r=>`<div class="ag-item"><h3>${e(r.name)}</h3><small>${e(TITLES[r.kind]||r.kind)} · v${r.version} · ${e(new Date(r.updated_at).toLocaleString())}</small></div>`).join(''):'<div class="ag-empty">No saved work yet. Start with your first client.</div>'}</div></div></div>`;
    root.querySelectorAll('[data-go]').forEach(b=>b.onclick=()=>navigate(b.dataset.go));
    root.querySelector('.ag-metrics').insertAdjacentHTML('afterend','<div data-overview></div>');P.dashboard(root,ctx);
    root.querySelector('#ag-backup').onclick=async event=>{event.target.disabled=true;const result=root.querySelector('#ag-backup-result');result.textContent='Creating and checking backup…';try{const backup=await post('/backups');result.innerHTML=`<p><a class="ag-button" href="/api/agency/backups/${backup.id}/download">Download backup · ${(backup.size/1024).toFixed(1)} KB</a><br><small>Database + ${backup.documents} research originals. Existing image/video stores are separate; see backup documentation.</small></p>`;}catch(error){result.textContent=error.message;}finally{event.target.disabled=false;}};
  }catch(error){root.innerHTML=`<div class="ag"><h1>Agency Dashboard</h1><p role="alert">${e(error.message)}</p></div>`;}
}

class Page{
  constructor(name,root){
    this.name=name;this.root=root;this.kind=GROUPS[name].types[0];this.client='';this.opened=null;this.offset=0;this.request=0;this.lastContext='';this.listResult={items:[],total:0};this.options={};
    const group=GROUPS[name];
    root.innerHTML=`<div class="ag"><div class="ag-header"><div><div class="ag-eyebrow">LEXNIS / AGENCY PLANNING</div><h1>${group.title}</h1><p>${group.description}</p></div><span class="ag-badge">LOCAL CORE</span></div><div class="ag-tabs" role="tablist" aria-label="${group.title} record types">${group.types.map((kind,i)=>`<button type="button" role="tab" data-kind="${kind}" aria-selected="${!i}" class="${!i?'active':''}">${TITLES[kind]}</button>`).join('')}</div><div class="ag-status" role="status"></div><div class="ag-grid"><div class="ag-panel"><div class="ag-row"><label style="flex:1;margin:0">Search<input data-search placeholder="Search saved names…"></label><button data-new class="primary">+ New</button></div><label class="ag-check" style="margin-top:12px"><input type="checkbox" data-archived> Include archived</label><div data-extra></div><div class="ag-list" data-list></div><div class="ag-row" style="margin-top:15px"><button data-previous>Previous</button><small data-count></small><button data-next>Next</button></div></div><div class="ag-panel ag-editor" data-editor><div class="ag-empty">Create or open a record to begin.</div></div></div></div>`;
    this.$=selector=>root.querySelector(selector);
    root.querySelectorAll('[data-kind]').forEach(b=>b.onclick=()=>this.selectKind(b.dataset.kind));
    this.$('[data-new]').onclick=()=>this.edit(null).catch(error=>this.status(error.message,true));
    let timer;this.$('[data-search]').oninput=()=>{clearTimeout(timer);timer=setTimeout(()=>{this.offset=0;this.load().catch(error=>this.status(error.message,true));},250);};
    this.$('[data-archived]').onchange=()=>{this.offset=0;this.load().catch(error=>this.status(error.message,true));};
    this.$('[data-previous]').onclick=()=>{this.offset=Math.max(0,this.offset-25);this.load().catch(error=>this.status(error.message,true));};
    this.$('[data-next]').onclick=()=>{this.offset+=25;this.load().catch(error=>this.status(error.message,true));};
    window.addEventListener('lexnis:agency-context',()=>{if(!root.hidden)this.activate().catch(error=>this.status(error.message,true));});
  }
  status(message,error=false){this.$('.ag-status').textContent=message;this.$('.ag-status').dataset.error=String(error);}
  async activate(){const ctx=context();this.root.querySelector('.ag').dir=ctx.language.startsWith('ar')?'rtl':'ltr';if(this.client!==ctx.client_id){this.client=ctx.client_id;this.opened=null;this.options={};this.offset=0;this.$('[data-editor]').innerHTML='<div class="ag-empty">Choose a saved record or create a new one.</div>';}this.lastContext=JSON.stringify(ctx);await this.load();P.activated(this);}
  async selectKind(kind){this.kind=kind;this.opened=null;this.offset=0;this.$('[data-search]').value='';this.root.querySelectorAll('[data-kind]').forEach(b=>{b.classList.toggle('active',b.dataset.kind===kind);b.setAttribute('aria-selected',String(b.dataset.kind===kind));});this.$('[data-editor]').innerHTML='<div class="ag-empty">Choose a saved record or create a new one.</div>';try{await this.load();}catch(error){this.status(error.message,true);}}
  async load(){
    const request=++this.request,ctx=context();this.client=ctx.client_id;
    if(this.kind!=='clients'&&!this.client){this.status('Choose a client in Agency Context before creating or opening work.');this.$('[data-list]').innerHTML='<div class="ag-empty">Client context is required. Create a client in Clients & Brands.</div>';this.$('[data-new]').disabled=true;this.$('[data-extra]').innerHTML='';return;}
    this.$('[data-new]').disabled=this.kind==='approvals';this.status(`${this.kind==='clients'?'Client directory':contextName()} · ${TITLES[this.kind]} · Manual, local planning`);
    const query=new URLSearchParams({limit:'25',offset:String(this.offset),q:this.$('[data-search]').value,archived:String(this.$('[data-archived]').checked)});
    const path=this.kind==='clients'?'/clients?'+query:scoped(this.client,'/records?summary=true&kind='+this.kind+'&'+query);
    const result=await api(path);if(request!==this.request)return;this.listResult=result;
    this.$('[data-list]').innerHTML=result.items.length?result.items.map(item=>`<article class="ag-item ${this.opened?.id===item.id?'selected':''}"><h3>${e(item.name)}</h3><small>v${item.version} · ${e(item.effective_status||item.data?.status||item.status||item.data?.classification||item.data?.state||'Saved')} · ${e(new Date(item.updated_at).toLocaleDateString())}</small>${item.data?.statement?`<p>${e(item.data.statement.slice(0,200))}</p>`:''}<div class="ag-row" style="margin-top:10px"><button data-open="${item.id}">Open</button>${this.kind==='clients'?`<button data-use-client="${item.id}" ${item.status==='archived'?'disabled':''}>Use client</button>`:''}${this.kind==='campaigns'?`<button data-use-campaign="${item.id}">Use campaign</button>`:''}</div></article>`).join(''):'<div class="ag-empty">No records yet. Create the first one with + New.</div>';
    this.$('[data-count]').textContent=`${result.total?this.offset+1:0}–${Math.min(this.offset+25,result.total)} / ${result.total}`;this.$('[data-previous]').disabled=!this.offset;this.$('[data-next]').disabled=this.offset+25>=result.total;
    this.$('[data-list]').querySelectorAll('[data-open]').forEach(b=>b.onclick=async()=>{try{const item=this.kind==='clients'?result.items.find(x=>x.id===b.dataset.open):await api(scoped(this.client,'/record/'+b.dataset.open));await this.edit(item);}catch(error){this.status(error.message,true);}});
    this.$('[data-list]').querySelectorAll('[data-use-client]').forEach(b=>b.onclick=()=>setClient(b.dataset.useClient).catch(error=>this.status(error.message,true)));
    this.$('[data-list]').querySelectorAll('[data-use-campaign]').forEach(b=>b.onclick=()=>setCampaign(result.items.find(x=>x.id===b.dataset.useCampaign)).catch(error=>this.status(error.message,true)));
    this.extras();
  }
  extras(){const extra=this.$('[data-extra]');extra.innerHTML=this.kind==='sources'?'<label class="ag-note">Import client-wide research · UTF-8 TXT / CSV<input type="file" data-import accept=".txt,.csv"></label>':this.kind==='brands'?'<button data-legacy style="margin-top:12px">Copy a legacy brand into this client</button>':this.kind==='deliverables'?'<button data-calendar style="margin-top:12px">View planned due dates</button>':'';
    if(this.$('[data-import]'))this.$('[data-import]').onchange=async event=>{const file=event.target.files[0];if(!file)return;const client=this.client;try{this.status('Validating and importing research…');const form=new FormData();form.append('file',file);const saved=await api(scoped(client,'/research/import'),{method:'POST',body:form});if(client!==context().client_id)return;await this.load();await this.edit(saved);this.status('Imported original retained; extracted text is untrusted source data.');}catch(error){this.status(error.message,true);}};
    if(this.$('[data-legacy]'))this.$('[data-legacy]').onclick=()=>this.copyLegacy().catch(error=>this.status(error.message,true));
    if(this.$('[data-calendar]'))this.$('[data-calendar]').onclick=()=>this.calendar().catch(error=>this.status(error.message,true));
    P.extras(this);
  }
  schema(){return this.kind==='clients'?schemas.client:schemas.records[this.kind];}
  resolve(field){return field.anyOf?.find(x=>x.type!=='null')||field;}
  draftKey(item){return `lexnis.agency.draft.${this.client||'directory'}.${this.kind}.${item?.id||'new'}`;}
  async choices(kind){const key=this.client+':'+kind;if(!this.options[key])this.options[key]=(await api(scoped(this.client,'/records?summary=true&kind='+kind+'&limit=100'))).items;return this.options[key];}
  async edit(item){
    const client=this.client,kind=this.kind;this.opened=item;if(await P.customEdit(this,item))return;const schema=this.schema();let values=item?(kind==='clients'?item:item.data):{};let draft;
    try{draft=JSON.parse(localStorage.getItem(this.draftKey(item))||'null');}catch{}
    if(draft&&draft.expected_version===(item?.version||0))values={...values,...draft.data};
    const ctx=context(),fields=[];
    if(kind!=='clients')fields.push(`<label class="ag-wide">Name<input name="record_name" required maxlength="160" value="${e(draft?.name??item?.name??'')}"></label>`);
    for(const [key,raw] of Object.entries(schema.properties)){
      if(HIDDEN.has(key)||(kind==='assets'&&P.HIDDEN.includes(key)))continue;const field=this.resolve(raw),value=values[key]??raw.default??(field.type==='array'?[]:field.type==='boolean'?false:'');const required=schema.required?.includes(key)?'required':'';const label=FIELD_LABELS[key]||human(key);let input;const custom=P.field(this,key,raw,field,value);if(custom!==null){fields.push(`<div class="ag-wide ag-group"><span class="ag-group-title">${e(label)}</span>${custom}</div>`);continue;}
      if(REFS[key]){const records=await this.choices(REFS[key]);const selected=Array.isArray(value)?value:[value].filter(Boolean);for(const selectedId of selected)if(!records.some(r=>r.id===selectedId)){try{records.push(await api(scoped(client,'/record/'+selectedId)));}catch{}}
        input=`<input type="search" data-ref-search="${key}" aria-label="Search ${e(TITLES[REFS[key]])}" placeholder="Search ${e(TITLES[REFS[key]])}…"><select aria-label="${e(label)}" data-field="${key}" data-ref="${REFS[key]}" ${field.type==='array'?'multiple':''}>${field.type!=='array'?'<option value="">Not selected</option>':''}${records.map(r=>`<option value="${r.id}" ${selected.includes(r.id)?'selected':''}>${e(r.name)}</option>`).join('')}</select><small>${field.type==='array'?'Ctrl/Cmd-click to select several saved records. ':''}References stay within this client.</small>`;
      }else if(field.enum){input=`<select data-field="${key}">${field.enum.map(x=>`<option value="${e(x)}" ${x===value?'selected':''}>${e(human(x))}</option>`).join('')}</select>`;
      }else if(field.type==='array'&&field.items?.enum){input=`<select data-field="${key}" multiple>${field.items.enum.map(x=>`<option value="${e(x)}" ${value.includes(x)?'selected':''}>${e(x)}</option>`).join('')}</select>`;
      }else if(field.type==='array'){input=`<textarea data-field="${key}" data-lines="true" placeholder="One entry per line" dir="auto">${e(value.join('\n'))}</textarea>`;
      }else if(field.type==='boolean'){input=`<input data-field="${key}" type="checkbox" ${value?'checked':''}>`;
      }else if(['number','integer'].includes(field.type)){input=`<input data-field="${key}" type="number" ${required} step="${field.type==='integer'?'1':'any'}" ${field.minimum!==undefined?'min="'+field.minimum+'"':''} ${field.maximum!==undefined?'max="'+field.maximum+'"':''} value="${e(value)}">`;
      }else if(field.format==='date'){input=`<input data-field="${key}" type="date" value="${e(value)}">`;
      }else if((field.maxLength||0)>500){input=`<textarea data-field="${key}" ${required} maxlength="${field.maxLength}" dir="auto">${e(value)}</textarea>`;
      }else{input=`<input data-field="${key}" ${required} maxlength="${field.maxLength||250}" value="${e(value)}" dir="auto">`;}
      fields.push(`<label class="${field.type==='array'||(field.maxLength||0)>500?'ag-wide':''}">${e(label)}${input}</label>`);
    }
    if(kind!=='clients'&&kind!=='projects')for(const [key,type,label] of [['project_id','projects','Project scope'],['campaign_id','campaigns','Campaign scope']]){
      if(kind==='campaigns'&&key==='campaign_id')continue;const records=await this.choices(type);const selected=draft?.[key]??item?.[key]??ctx[key]??'';
      fields.push(`<label>${label}<select data-scope="${key}"><option value="">Client-wide / none</option>${records.map(r=>`<option value="${r.id}" ${selected===r.id?'selected':''}>${e(r.name)}</option>`).join('')}</select></label>`);
    }
    if(client!==this.client||kind!==this.kind)return;
    const editor=this.$('[data-editor]');editor.innerHTML=`<h2>${item?'Edit':'New'} ${e(TITLES[kind])}</h2><p><small>${kind==='clients'?'Client profile':e(contextName())} ${item?'· v'+item.version:''}. ${draft?'Browser draft restored.':''}</small></p><form data-form><div class="ag-fields">${fields.join('')}</div><div class="ag-row"><button type="submit" class="primary" ${item?.archived?'disabled':''}>Save ${item?'new revision':'record'}</button>${item&&kind!=='clients'?`<button type="button" data-archive>${item.archived?'Restore':'Archive'}</button>`:''}</div></form><div data-actions class="ag-row" style="margin-top:15px"></div>${item?'<details data-history><summary>Version history & source revisions</summary><div data-versions></div></details>':''}`;
    const form=editor.querySelector('form');form.oninput=()=>this.persistDraft();form.onchange=()=>this.persistDraft();form.onsubmit=event=>{event.preventDefault();this.save().catch(error=>this.status(error.message,true));};
    for(const search of editor.querySelectorAll('[data-ref-search]')){
      let timer;search.onkeydown=event=>{if(event.key==='Enter')event.preventDefault();};
      search.oninput=()=>{clearTimeout(timer);timer=setTimeout(async()=>{try{
        const select=editor.querySelector(`[data-field="${search.dataset.refSearch}"]`);if(!select)return;
        const selected=[...select.selectedOptions].map(o=>({id:o.value,name:o.textContent}));
        const found=await api(scoped(client,'/records?summary=true&limit=25&kind='+select.dataset.ref+'&q='+encodeURIComponent(search.value)));
        if(client!==this.client||kind!==this.kind)return;
        const options=[...selected,...found.items.filter(r=>!selected.some(x=>x.id===r.id))];
        select.innerHTML=(select.multiple?'':'<option value="">Not selected</option>')+options.map(r=>`<option value="${r.id}" ${selected.some(x=>x.id===r.id)?'selected':''}>${e(r.name)}</option>`).join('');
      }catch(error){this.status(error.message,true);}},250);};
    }
    if(this.$('[data-archive]'))this.$('[data-archive]').onclick=async()=>{try{await post(scoped(client,`/record/${item.id}/archive`),{expected_version:item.version,archived:!item.archived});this.opened=null;editor.innerHTML='<div class="ag-empty">Record archive state updated. Original data is retained.</div>';await this.load();}catch(error){this.status(error.message,true);}};
    if(this.$('[data-history]'))this.$('[data-history]').ontoggle=()=>{if(this.$('[data-history]').open)this.history(item).catch(error=>this.status(error.message,true));};
    this.actions(item);P.bind(this);P.actions(this,item).catch(error=>this.status(error.message,true));
  }
  collect(){const data={},schema=this.schema();for(const input of this.$('[data-editor]').querySelectorAll('[data-field]')){const key=input.dataset.field,raw=schema.properties[key],field=this.resolve(raw);let value=input.type==='checkbox'?input.checked:input.multiple?[...input.selectedOptions].map(o=>o.value):input.value;
      if(input.dataset.lines)value=value.split('\n').map(x=>x.trim()).filter(Boolean);
      if(field.format==='date'&&value===''&&!raw.anyOf)continue;
      if(['number','integer'].includes(field.type))value=value===''?null:Number(value);
      if((raw.anyOf?.some(x=>x.type==='null'))&&value==='')value=null;
      data[key]=value;}
    P.collect(this,data);
    for(const key of [...HIDDEN,...(this.kind==='assets'?P.HIDDEN:[])])if(this.opened?.data?.[key]!==undefined)data[key]=this.opened.data[key];
    const output={name:this.kind==='clients'?data.name:this.$('[name=record_name]').value,data,project_id:null,campaign_id:null};
    this.$('[data-editor]').querySelectorAll('[data-scope]').forEach(input=>output[input.dataset.scope]=input.value||null);return output;
  }
  persistDraft(){try{const body=this.collect();localStorage.setItem(this.draftKey(this.opened),JSON.stringify({...body,expected_version:this.opened?.version||0}));this.status('Unsaved browser draft · '+contextName());}catch{}}
  async save(){const client=this.client,kind=this.kind,item=this.opened,body=this.collect();if(kind!=='clients'&&client!==context().client_id)throw new Error('Client context changed. Reopen this record before saving.');
    const path=kind==='clients'?'/clients'+(item?'/'+item.id:''):scoped(client,'/records/'+kind+(item?'/'+item.id:''));const payload=kind==='clients'?body.data:body;if(item)payload.expected_version=item.version;
    const button=this.$('button[type=submit]');button.disabled=true;
    try{const saved=await api(path,{method:item?'PUT':'POST',body:JSON.stringify(payload)});try{localStorage.removeItem(this.draftKey(item));}catch{}this.options={};if(kind==='clients'&&!item)await setClient(saved.id);else await refreshContext();if(kind==='clients'&&saved.status==='archived'&&context().client_id===saved.id)await setClient('');await this.load();await this.edit(saved);this.status('Saved · v'+saved.version+' · prior revisions retained.');}finally{if(button.isConnected)button.disabled=false;}
  }
  async history(item,offset=0){const history=await api(scoped(this.client,'/history/'+item.id+'?limit=25&offset='+offset));this.$('[data-versions]').innerHTML=history.items.map(v=>`<div class="ag-history"><strong>Version ${v.version}</strong> · ${e(new Date(v.created_at).toLocaleString())}<br><small>SHA-256 ${e(v.sha256)}</small><details><summary>Saved values and referenced revisions</summary><pre>${e(JSON.stringify(v.snapshot,null,2))}</pre></details></div>`).join('')+`<div class="ag-row"><button type="button" data-history-previous ${offset?'':'disabled'}>Previous versions</button><small>${offset+1}–${Math.min(offset+25,history.total)} / ${history.total}</small><button type="button" data-history-next ${offset+25>=history.total?'disabled':''}>Older versions</button></div>`;this.$('[data-history-previous]').onclick=()=>this.history(item,Math.max(0,offset-25)).catch(error=>this.status(error.message,true));this.$('[data-history-next]').onclick=()=>this.history(item,offset+25).catch(error=>this.status(error.message,true));}
  actions(item){const area=this.$('[data-actions]');if(!item)return;
    if(this.kind==='sources'){for(const [key,label] of [['document_id','Download original'],['snapshot_id','Download snapshot']])if(item.data[key])area.insertAdjacentHTML('beforeend',`<a class="ag-button" href="/api/agency/clients/${this.client}/documents/${item.data[key]}">${label}</a>`);
      if(item.data.source_type==='url'){area.insertAdjacentHTML('beforeend','<label class="ag-check"><input type="checkbox" data-terms> Site terms and configured research policy reviewed</label><button data-capture>Capture URL · optional online</button>');this.$('[data-capture]').onclick=async()=>{try{const job=await post(scoped(this.client,`/sources/${item.id}/capture`),{expected_version:item.version,terms_reviewed:this.$('[data-terms]').checked});this.watch(job);}catch(error){this.status(error.message,true);}};}}
    if(this.kind==='campaigns'){area.innerHTML=`<button data-build-brief>Create brief from saved strategy</button><a class="ag-button" href="/api/agency/clients/${this.client}/campaigns/${item.id}/package?draft_only=true">Export review plan (.zip)</a>`;this.$('[data-build-brief]').onclick=async()=>{try{const brief=await post(scoped(this.client,`/campaigns/${item.id}/brief`));await setCampaign(item);await this.selectKind('briefs');await this.edit(brief);}catch(error){this.status(error.message,true);}};}
    if(this.kind==='briefs'){area.innerHTML='<button data-checks>Run claim & terminology checks</button><button data-image>Prepare Image Studio</button><div data-check-result class="ag-note" hidden></div>';this.$('[data-checks]').onclick=()=>this.checks().catch(error=>this.status(error.message,true));this.$('[data-image]').onclick=()=>this.sendImage(item).catch(error=>this.status(error.message,true));this.localDraftControls(item).catch(error=>this.status(error.message,true));}
  }
  async localDraftControls(item){
    const info=await api('/local-text/status');if(this.opened?.id!==item.id||this.opened?.version!==item.version||this.kind!=='briefs')return;
    const node=document.createElement('div');node.className='ag-note';node.style.width='100%';
    node.innerHTML=`<h3>Optional local text · ${e(info.id)}</h3><p><small>${e(info.license)} · CPU ·${info.verified?'Real smoke test recorded':'Real model inference not verified'}. ${e(info.reason)}</small></p><label>Draft instruction<textarea data-draft-instruction maxlength="1500">Improve clarity while preserving approved claims. Treat other suggestions as assumptions.</textarea></label><div class="ag-fields"><label>Maximum output tokens<input data-draft-tokens type="number" min="64" max="1024" value="512"></label><label>Temperature<input data-draft-temperature type="number" min="0" max="1" step="0.1" value="0.4"></label><label>Seed<input data-draft-seed type="number" min="0" max="2147483647" value="42"></label></div><button data-draft-generate ${info.available?'':'disabled'}>Create a separate local-model draft</button><p><small>Uses the saved brief and current approved claims. The current version is retained. Setup: see LOCAL_AI.md. No hosted fallback or automatic model download.</small></p>`;
    this.$('[data-actions]').append(node);
    if(item.data.generation)node.insertAdjacentHTML('afterbegin',`<p><strong>Unreviewed local-model draft</strong> · source brief v${item.data.generation.source_brief_version} · ${e(item.data.generation.revision)}</p>`);
    node.querySelector('[data-draft-generate]').onclick=async()=>{try{const job=await post(scoped(this.client,'/local-text/draft'),{brief_id:item.id,instruction:node.querySelector('[data-draft-instruction]').value,max_tokens:Number(node.querySelector('[data-draft-tokens]').value),temperature:Number(node.querySelector('[data-draft-temperature]').value),seed:Number(node.querySelector('[data-draft-seed]').value)});this.watch(job);}catch(error){this.status(error.message,true);}};
  }
  async checks(){const d=this.collect().data;const campaign=await api(scoped(this.client,'/record/'+(this.opened.campaign_id)));const text=[d.primary_message,...d.supporting_messages,...d.reasons_to_believe,d.offer].join('\n');const result=await post(scoped(this.client,'/checks'),{text,claim_ids:d.claim_ids,brand_id:campaign.data.brand_id,cta:d.cta,language:context().language});const box=this.$('[data-check-result]');box.hidden=false;box.innerHTML=`<strong>${e(human(result.export_state))}</strong>${result.flags.length?'<ul>'+result.flags.map(f=>`<li>${e(f.message)}</li>`).join('')+'</ul>':'<p>No configured flags found.</p>'}<small>${e(result.scope)}</small>`;}
  async sendImage(item){const client=this.client,campaign=await api(scoped(client,'/record/'+item.campaign_id));const brand=campaign.data.brand_id?await api(scoped(client,'/record/'+campaign.data.brand_id)):null;const d=item.data;const prompt=[d.campaign_objective,d.primary_message,d.visual_direction,d.audience?'Audience: '+d.audience:'',d.mandatory_elements.length?'Mandatory: '+d.mandatory_elements.join('; '):''].filter(Boolean).join('\n');if(context().client_id!==client)throw new Error('Client context changed; reopen the brief.');window.dispatchEvent(new CustomEvent('lexnis:agency-image',{detail:{prompt,brand:brand?{name:brand.name,...brand.data}:{name:contextName()},language:context().language,context:{client_id:client,campaign_id:campaign.id,brief_id:item.id,brief_version:item.version}}}));navigate('image');this.status('Saved brief prepared in Image Studio. No generation was started.');}
  async copyLegacy(){const response=await api('/legacy-brands');const editor=this.$('[data-editor]');editor.innerHTML='<h2>Copy legacy brand</h2><p>Choose a brand to copy into '+e(contextName())+'. The original Image Studio brand is retained.</p><label>Legacy brand<select data-legacy-select>'+response.items.map(b=>`<option value="${e(b.id)}">${e(b.brand_name)}</option>`).join('')+'</select></label><button class="primary" data-copy>Copy brand</button>';this.$('[data-copy]').onclick=async()=>{try{const b=response.items.find(x=>x.id===this.$('[data-legacy-select]').value);const saved=await post(scoped(this.client,'/records/brands'),{name:b.brand_name,data:{legacy_brand_id:b.id,brand_name_ar:b.brand_name_ar||'',primary_color:b.primary_hex,accent_color:b.accent_hex,logo_url:b.logo_path||'',tagline:b.tagline||'',hashtag:b.hashtag||''}});await this.load();await this.edit(saved);}catch(error){this.status(error.message,true);}};}
  async calendar(){const result=await api(scoped(this.client,'/calendar?limit=100')+(context().campaign_id?'&campaign_id='+context().campaign_id:''));const rows=result.items;this.$('[data-editor]').innerHTML=`<h2>Planned delivery dates</h2><small>${result.total} planned dates · showing up to 100. Use the paginated Deliverables list for all records.</small><p>Planning dates only; nothing is scheduled on an external platform.</p><div class="ag-table-wrap"><table class="ag-table"><thead><tr><th>Due</th><th>Deliverable</th><th>Platform</th><th>Status</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${e(r.data.due_date)}</td><td>${e(r.name)}</td><td>${e(r.data.platform)}</td><td>${e(r.data.state)}</td></tr>`).join('')}</tbody></table>${rows.length?'':'<p>No due dates saved yet.</p>'}</div>`;}
  watch(job){const client=this.client;const tick=async()=>{if(client!==context().client_id||client!==this.client)return;try{const status=await api(scoped(client,'/jobs/'+job.id));this.status(`${status.kind}: ${status.state} · ${status.stage||''}${status.error?' · '+status.error:''}`,status.state==='failed');if(!['completed','failed','cancelled'].includes(status.state)){this.$('[data-actions]').innerHTML='<button data-cancel-task>Cancel task</button>';this.$('[data-cancel-task]').onclick=()=>post(scoped(client,'/jobs/'+job.id+'/cancel')).catch(error=>this.status(error.message,true));setTimeout(tick,700);}else if(status.state==='completed'&&client===context().client_id){await this.load();await this.edit(status.result);}}catch(error){this.status(error.message,true);}};tick();}
}
