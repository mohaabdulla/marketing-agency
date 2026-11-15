import {storageKey} from './public-session.js';
import {escapeHtml as esc} from './agency-api.js';

const tasks={image:'Image',gif:'GIF', 'video-generation':'Video Generation','video-edit':'Video Editing',campaign:'Campaign',copy:'Copy & Storyboard',audio:'Audio',web:'Web & SEO',crm:'Email & CRM'};
let capabilities;
async function request(path,body){
  const r=await fetch('/api/creative/assistant/'+path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});
  const data=await r.json().catch(()=>({}));
  if(!r.ok)throw new Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail||'Assistant unavailable'));
  return data;
}
export const suggestPrompt=body=>request('suggest',body);

// Nodes are moved, never cloned or re-created: values, files and existing handlers survive.
export class GuidedWorkflow{
  constructor(host,key,steps){
    this.host=host;this.key=key;this.steps=[];this.current=0;
    this.root=document.createElement('div');this.root.className='creative-flow';this.root.dataset.workflow=key;
    const toolbar=document.createElement('div');toolbar.className='flow-toolbar';toolbar.innerHTML='<nav aria-label="Creative workflow steps"></nav><label><input type="checkbox" data-focused> Focus on one step</label><p role="status" data-flow-status></p>';
    this.root.append(toolbar);host.prepend(this.root);this.nav=toolbar.querySelector('nav');
    steps.forEach((step,i)=>{
      const section=document.createElement('section');section.className='flow-step';section.dataset.flowStep=String(i+1);section.id=key+'-step-'+(i+1);
      const title=document.createElement('h2');title.tabIndex=-1;title.textContent=(i+1)+'. '+step.title;section.append(title);
      if(step.description){const note=document.createElement('p');note.className='flow-help';note.textContent=step.description;section.append(note);}
      for(const node of step.nodes||[])if(node)section.append(node);
      const footer=document.createElement('div');footer.className='flow-controls';
      for(const [label,delta] of [['Back',-1],['Next',1]]){const button=document.createElement('button');button.type='button';button.textContent=label;button.disabled=i+delta<0||i+delta>=steps.length;button.onclick=()=>this.go(i+delta);footer.append(button);}
      section.append(footer);this.root.append(section);this.steps.push(section);
      const button=document.createElement('button');button.type='button';button.textContent=(i+1)+'. '+step.title;button.setAttribute('aria-controls',section.id);button.onclick=()=>this.go(i);this.nav.append(button);
    });
    this.focused=toolbar.querySelector('[data-focused]');
    this.focused.onchange=()=>{this.draw();this.persist();};
    try{const state=JSON.parse(localStorage.getItem(storageKey('lexnis.flow.'+key))||'null');if(state){this.current=Math.min(steps.length-1,Math.max(0,state.step||0));this.focused.checked=!!state.focused;}}catch{}
    this.draw();
  }
  persist(){try{localStorage.setItem(storageKey('lexnis.flow.'+this.key),JSON.stringify({step:this.current,focused:this.focused.checked}));}catch{}}
  draw(){this.steps.forEach((section,i)=>{section.hidden=this.focused.checked&&i!==this.current;section.classList.toggle('flow-active',i===this.current);this.nav.children[i].setAttribute('aria-current',i===this.current?'step':'false');});this.root.querySelector('[data-flow-status]').textContent='Step '+(this.current+1)+' of '+this.steps.length+'. Your inputs stay in place when moving between steps.';}
  go(index,focus=true){this.current=index;this.draw();this.persist();if(focus)this.steps[index].querySelector('h2').focus({preventScroll:false});}
  reveal(node){const index=this.steps.findIndex(section=>section.contains(node));if(index>=0)this.go(index,false);}
}

export function objectiveFields(host,initial={},onchange=()=>{}){
  const panel=document.createElement('div');panel.className='creative-objective';
  panel.innerHTML='<div class="flow-fields">'+[['objective','Creative objective','What should this achieve?'],['audience','Target audience','Who is it for?'],['key_message','Key message','Use approved facts only'],['style','Preferred style','Optional visual or editorial direction'],['platform','Target platform','e.g. LinkedIn, Instagram'],['cta','Call to action','Approved next step']].map(([key,label,placeholder])=>'<label>'+label+'<input data-objective="'+key+'" maxlength="'+(['objective','key_message'].includes(key)?1000:key==='platform'?100:500)+'" placeholder="'+placeholder+'" dir="auto"></label>').join('')+'<label>Language<select data-objective="language"><option value="en">English</option><option value="ar">Arabic</option><option value="ar-BH">Arabic · Bahrain</option></select></label></div>';
  host.append(panel);const value=()=>Object.fromEntries([...panel.querySelectorAll('[data-objective]')].map(el=>[el.dataset.objective,el.value]));
  const set=values=>panel.querySelectorAll('[data-objective]').forEach(el=>el.value=values?.[el.dataset.objective]|| (el.dataset.objective==='language'?'en':''));
  set(initial);panel.addEventListener('input',()=>onchange(value()));panel.addEventListener('change',()=>onchange(value()));return {root:panel,value,set};
}

export class PromptAssistant{
  constructor(host,input,context){
    this.input=input;this.context=context;this.root=document.createElement('details');this.root.className='creative-assistant';this.root.dataset.promptAssistant='';
    this.root.innerHTML='<summary>Prompt Assistant</summary><p data-assistant-task></p><p data-assistant-availability role="status">Checking local AI availability…</p><label>Assistance method<select data-engine><option value="template">Editable template · no AI inference</option><option value="local_ai" disabled>Local AI · checking availability</option></select></label><div class="flow-controls">'+[['generate','Generate Prompt'],['improve','Improve Prompt'],['professional','Make More Professional'],['brand','Apply Brand Guidelines'],['simplify','Simplify Prompt']].map(([key,label])=>'<button type="button" data-assist="'+key+'">'+label+'</button>').join('')+'</div><p data-assistant-status role="status"></p><div data-suggestion hidden><label>Review suggested instructions<textarea data-suggested rows="7" dir="auto"></textarea></label><ul data-missing></ul><div class="flow-controls"><button type="button" data-use>Use Suggested Prompt</button><button type="button" data-manual>Edit Manually</button></div></div>';
    if(host.tagName==='LABEL')host.after(this.root);else host.append(this.root);this.$=s=>this.root.querySelector(s);
    this.root.querySelectorAll('[data-assist]').forEach(button=>button.onclick=()=>this.suggest(button.dataset.assist));
    this.$('[data-use]').onclick=()=>{const text=this.$('[data-suggested]').value;if(input.maxLength>0&&text.length>input.maxLength){this.$('[data-assistant-status]').textContent='Suggested instructions exceed the '+input.maxLength+' character limit. Shorten them before using.';return;}input.value=text;input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));input.focus();this.$('[data-assistant-status]').textContent='Suggested instructions are now in the actual '+(tasks[this.context().task]||'creative')+' prompt field. Review them before processing.';};
    this.$('[data-manual]').onclick=()=>input.focus();
    (capabilities ||= request('capabilities').catch(error=>{capabilities=null;throw error;})).then(cap=>{
      const option=this.$('[data-engine] option[value=local_ai]');option.disabled=!cap.ai.available;option.textContent=cap.ai.available?'Local AI · available':'Local AI · unavailable';this.$('[data-assistant-availability]').textContent=cap.ai.reason+' Editable templates remain available.';
    }).catch(error=>this.$('[data-assistant-availability]').textContent=error.message+' Editable templates remain available.');
    this.$('[data-assistant-task]').textContent=(tasks[context().task]||'Creative')+' instructions use this workflow’s objective, format and selected brand context.';
  }
  async suggest(action){
    this.root.open=true;this.$('[data-assistant-status]').textContent='Preparing instructions…';this.$('[data-suggestion]').hidden=true;
    const buttons=this.root.querySelectorAll('[data-assist]');buttons.forEach(b=>b.disabled=true);
    try{const data=await request('suggest',{...this.context(),prompt:this.input.value,max_chars:Math.max(100,Math.min(6000,this.input.maxLength>0?this.input.maxLength:6000)),action,engine:this.$('[data-engine]').value});this.$('[data-suggested]').value=data.prompt;this.$('[data-missing]').innerHTML=data.missing_details.map(x=>'<li>'+esc(x)+'</li>').join('');this.$('[data-suggestion]').hidden=false;this.$('[data-assistant-status]').textContent=data.notice;}
    catch(error){this.$('[data-assistant-status]').textContent=error.message;}
    finally{buttons.forEach(b=>b.disabled=false);}
  }
}

// Prompt-bearing agency forms use the same assistant, with task-specific instructions.
export function assistAgencyForm(form,kind){
  const task=['scripts','storyboards','copy','concepts','shots'].includes(kind)?'copy':['landing-pages','seo-briefs'].includes(kind)?'web':kind.includes('email')?'crm':kind.includes('audio')?'audio':'campaign';
  const fields=[...form.querySelectorAll('textarea[data-field],textarea[data-sub],input[data-field]')].filter(el=>!el.multiple&&!el.dataset.lines&&/brief|objective|message|description|direction|body|instruction|script|content|headline/.test(el.dataset.field||el.dataset.sub));
  const assistants=[];
  for(const input of fields){if(input.dataset.hasAssistant)continue;input.dataset.hasAssistant='true';assistants.push(new PromptAssistant(input.parentElement,input,()=>({task,output_format:kind,language:document.querySelector('#agency-context-language')?.value||'en',client_id:document.querySelector('#agency-context-client')?.value||null,campaign_id:form.querySelector('[data-scope=campaign_id]')?.value||document.querySelector('#agency-context-campaign')?.value||null,brand_kit_id:form.querySelector('[data-field=brand_id]')?.value||null,objective:form.querySelector('[data-field=campaign_objective]')?.value||'',audience:form.querySelector('[data-field=audience]')?.value||'',cta:form.querySelector('[data-field=cta]')?.value||''})).root);}
  const creative=new Set(['briefs','concepts','copy','scripts','storyboards','shots','landing-pages','email-templates','seo-briefs','creator-briefs','paid-plans','campaigns']);
  if(creative.has(kind)&&assistants.length){
    const group=form.querySelector('.ag-fields'),scope=document.createElement('div'),helper=document.createElement('div');
    helper.innerHTML='<p>Choose the assistant for the field you want to improve. Accepting a suggestion updates that exact saved record field; it does not publish or render media.</p>';
    for(const el of [...group.children])if(el.querySelector('[name=record_name],[data-scope]'))scope.append(el);
    for(const panel of assistants)helper.append(panel);
    const save=form.querySelector('button[type=submit]').closest('.ag-row');
    new GuidedWorkflow(form,'agency-'+kind,[
      {title:'Choose scope',nodes:[scope],description:'This form edits a '+kind.replaceAll('-',' ')+' record in the selected client. Choose another supported record type using the tabs above.'},
      {title:'Creative objective & settings',nodes:[group],description:'Use approved facts and select the relevant saved brand, brief and campaign references.'},
      {title:'Prompt assistant',nodes:[helper]},
      {title:'Save & review',nodes:[save],description:'Save a real revision. Checks, supported previews and exports appear below the form for saved records.'}
    ]);
  }
}
