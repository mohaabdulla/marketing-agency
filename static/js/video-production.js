import {storageKey} from './public-session.js';

const BASE='/api/video';
const steps=['Brief','Script','Shot planning','Generation','Editing','Review','Delivery'];
const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function api(path,body,method=body?'POST':'GET'){
  const response=await fetch(BASE+path,{method,headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});
  const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'The video production request failed.');return data;
}
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));

class VideoProduction {
  constructor(host){
    this.host=host;this.record=null;this.step=0;this.busy=false;this.models=[];this.assets=[];this.shotDrafts=new Map();
    host.innerHTML=`<div class="vp-workspace"><header><p class="vp-eyebrow">LOCAL VIDEO PRODUCTION</p><h1>Video Production</h1>
      <p>Plan the story, direct each shot, review the takes, finish in the editor, then release the approved client kit.</p></header>
      <div class="vp-toolbar"><label>Saved production<select data-vp-saved><option value="">New production</option></select></label><button type="button" data-vp-refresh>Refresh</button>
      <label>Reviewer name<input data-vp-reviewer maxlength="100" placeholder="Your name for the review history"></label></div>
      <nav aria-label="Video production steps">${steps.map((step,i)=>`<button type="button" data-vp-step="${i}">${i+1}. ${step}</button>`).join('')}</nav>
      <p data-vp-status role="status" aria-live="polite"></p><progress data-vp-progress max="100" value="0" hidden aria-label="Producer job progress"></progress><button type="button" data-vp-cancel hidden>Cancel production job</button>
      <section data-vp-panel="0"><h2>Brand brief and script</h2>
        <div class="vp-grid"><label>Production name<input data-vp="name" value="Company campaign video" maxlength="100"></label><label>Production brand kit<select data-vp="brand_id"><option value="">Choose a brand kit</option></select></label>
        <label>Campaign goal<select data-vp="campaign_type"><option value="company_intro">Introduce the company</option><option value="product_launch">Product launch</option><option value="hiring">Hiring</option><option value="explainer">Explainer</option><option value="brand_announcement">Brand announcement</option></select></label>
        <label>Production language<select data-vp="language"><option value="en">English</option><option value="ar">Arabic</option></select></label>
        <label>Target audience<input data-vp="target_audience" maxlength="500"></label><label>Tone<select data-vp="tone"><option value="professional">Professional</option><option value="warm">Warm</option><option value="energetic">Energetic</option></select></label>
        <label>Runtime in seconds<input data-vp="duration" type="number" value="15" min="6" max="60"></label><label>Master format<select data-vp="platform_target"><option>16:9</option><option>9:16</option><option>1:1</option></select></label>
        <label>Master quality<select data-vp="resolution"><option value="1080">1080p delivery</option><option value="720">720p delivery</option></select></label><label>Reviewed production guideline<select data-vp="guideline_id"><option value="">Use the selected brand kit</option></select></label></div>
        <label>Core objective and key messages<textarea data-vp="core_message" maxlength="2000" rows="3" placeholder="What should viewers understand or do next?"></textarea></label>
        <label>Optional supplied script<textarea data-vp="script_text" maxlength="6000" rows="4" placeholder="Up to six short paragraphs. Supplied words are retained for your review."></textarea></label>
        <label>Continuity across the whole film<textarea data-vp="continuity_notes" maxlength="1500" rows="2" placeholder="Recurring person, location, wardrobe, props, lighting, and screen direction"></textarea></label>
        <label><input data-vp="use_local_ai" type="checkbox" checked> Ask the configured local script model; use an editable structured draft when it is unavailable</label>
        <div class="vp-toolbar"><label>Upload production guideline<input data-vp-guide-file type="file" accept=".pdf,.txt,.md,.markdown,.json,.docx"></label><button type="button" data-vp-confirm-guide hidden>Confirm extracted production rules</button></div>
        <pre data-vp-guide-review></pre><button type="button" data-vp-example>Use an example brief for this goal</button><button type="button" class="primary" data-vp-create>Create script and storyboard</button><p>Video generation stays local. No hosted script provider is used in this workspace.</p></section>
      <section data-vp-panel="1" hidden><h2>Review the script</h2><div data-vp-script></div><div data-vp-governance></div><button type="button" data-vp-approve-script>Approve current production script</button></section>
      <section data-vp-panel="2" hidden><h2>Direct the shots</h2><p>Save each edited shot, then approve the script again. Accuracy-critical scenes need real footage or an approved still.</p>
        <label>Upload a production reference, footage, logo, or audio<input data-vp-media-file type="file" accept=".png,.jpg,.jpeg,.webp,.mp4,.mov,.webm,.mp3,.wav,.ogg,.m4a,.flac"></label><div data-vp-shots></div></section>
      <section data-vp-panel="3" hidden><h2>Generate and review takes</h2><p>Each shot follows concept → continuity → final. Approvals record your name against the exact take and shot revision.</p>
        <details><summary>Local model availability</summary><div data-vp-models></div></details><button type="button" data-vp-batch>Generate concept drafts for all shots</button><p>Batch drafting creates candidates only. Each take still needs your review.</p><div data-vp-takes></div></section>
      <section data-vp-panel="4" hidden><h2>Finish the timeline</h2><p>Titles, brand colours, captions and logos are composited as editable layers. Camera framing, transitions, audio, colour and undo/redo are available in Video Editor.</p>
        <div class="vp-grid"><label>Offline production narrator<select data-vp-narrator><option value="">No synthesized narration</option></select></label><label>Recorded production voiceover<select data-vp-voiceover><option value="">None</option></select></label>
        <label>Licensed production music<select data-vp-music><option value="">None</option></select></label><label>Music level<input data-vp-music-level type="range" min="0" max="1" step=".05" value=".2"></label></div>
        <label><input type="checkbox" data-vp-captions checked> Burn in branded subtitles</label>
        <fieldset><legend>Additional platform variants</legend><label><input data-vp-variant type="checkbox" value="9:16"> Vertical 9:16</label><label><input data-vp-variant type="checkbox" value="1:1"> Square 1:1</label></fieldset>
        <div class="vp-toolbar"><button type="button" data-vp-render>Build and render current master</button><button type="button" data-vp-editor>Open production timeline in Video Editor</button><button type="button" data-vp-reset>Rebuild timeline from approved shots</button></div>
        <p>Audio choices apply when building the timeline. After editing, save in Video Editor and return here to render the current revision. Rebuilding keeps the old project and its revision history.</p></section>
      <section data-vp-panel="5" hidden><h2>Brand compliance and final review</h2><button type="button" data-vp-check>Check production brand compliance</button><div data-vp-checks></div><div data-vp-master></div>
        <fieldset><legend>Named human release review</legend>${[['story_checked','Story matches the approved campaign goal'],['continuity_checked','Appearance, setting, props and cuts are consistent'],['text_checked','Text, spelling, brand typography and captions are readable'],['audio_checked','Voice, music and silence have been reviewed'],['rights_checked','Usage rights for the supplied media are confirmed']].map(([key,label])=>`<label><input data-vp-release-check="${key}" type="checkbox"> ${label}</label>`).join('')}</fieldset>
        <label>Final review note<textarea data-vp-release-note maxlength="1500" rows="2"></textarea></label><button type="button" data-vp-release>Approve release and build client kit</button></section>
      <section data-vp-panel="6" hidden><h2>Reviewed client delivery</h2><div data-vp-delivery></div><p>The archive includes master and variants, script and storyboard PDFs, SRT/VTT subtitles, source media, frozen governance, take provenance and review history. Technical checks do not replace watching the complete film.</p></section></div>`;
    this.$=selector=>host.querySelector(selector);
    this.$('[data-vp-create]').onclick=()=>this.run(()=>this.create());this.$('[data-vp-refresh]').onclick=()=>this.run(()=>this.refresh());
    this.$('[data-vp-example]').onclick=()=>this.run(()=>this.exampleBrief());
    this.$('[data-vp-saved]').onchange=()=>this.run(()=>this.open(this.$('[data-vp-saved]').value));
    host.querySelectorAll('[data-vp-step]').forEach(button=>button.onclick=()=>this.go(+button.dataset.vpStep));
    this.$('[data-vp-approve-script]').onclick=()=>this.run(()=>this.mutate('/approve-script',{reviewer:this.reviewer()},1));
    this.$('[data-vp-render]').onclick=()=>this.run(()=>this.render());
    this.$('[data-vp-batch]').onclick=()=>this.run(async()=>{this.requireSaved();for(const shot_id of this.record.shots.map(shot=>shot.id)){const job=await api('/productions/'+this.record.id+'/shots/'+shot_id+'/generate',{expected_version:this.record.version,pass_name:'concept'});await this.watch(job.id);}});
    this.$('[data-vp-reset]').onclick=()=>this.run(()=>this.mutate('/reset-timeline',{},4));
    this.$('[data-vp-check]').onclick=()=>this.run(()=>this.check());
    this.$('[data-vp-release]').onclick=()=>this.run(()=>this.release());
    this.$('[data-vp-editor]').onclick=()=>{if(this.record?.timeline_project_id)window.dispatchEvent(new CustomEvent('lexnis:producer-project',{detail:{project_id:this.record.timeline_project_id}}));else this.status('Build the production timeline first.');};
    this.$('[data-vp-media-file]').onchange=()=>this.run(()=>this.uploadMedia());
    this.$('[data-vp-guide-file]').onchange=()=>this.run(()=>this.uploadGuideline());
    this.$('[data-vp=guideline_id]').onchange=()=>this.run(()=>this.previewGuideline());
    this.$('[data-vp-confirm-guide]').onclick=()=>this.run(()=>this.confirmGuideline());
    this.labelControls(host);this.go(0);this.ready=this.run(()=>this.load());
  }
  labelControls(root){for(const label of root.querySelectorAll('label')){const control=label.querySelector('input,textarea,select');if(control){const text=[...label.childNodes].filter(node=>node.nodeType===Node.TEXT_NODE).map(node=>node.textContent).join(' ').trim();if(text)control.setAttribute('aria-label',text);}}}
  status(text){this.$('[data-vp-status]').textContent=text;}
  exampleBrief(){
    const brand=this.$('[data-vp=brand_id]');if(!brand.value)throw new Error('Choose a brand kit before loading an example.');
    const field=this.$('[data-vp=core_message]');if(field.value.trim())throw new Error('Clear the core message before loading an example. Your current draft has been preserved.');
    const name=brand.selectedOptions[0].textContent,ar=this.$('[data-vp=language]').value==='ar';
    const examples=ar?{
      company_intro:`عرّف الجمهور بشركة ${name} والخدمات المذكورة في المعلومات المعتمدة، ثم ادعُ المشاهدين للتواصل مع الفريق. استخدم الحقائق المؤكدة فقط.`,
      product_launch:`قدّم المنتج الجديد من ${name} للجمهور المقصود، واشرح فائدته المؤكدة ثم اختم بدعوة واضحة لمعرفة التفاصيل.`,
      hiring:`قدّم فرصة العمل لدى ${name}، ووضّح المسمى والمسؤوليات والمتطلبات المعتمدة وطريقة التقديم.`,
      explainer:`اشرح كيف تساعد خدمة ${name} في المهمة الموضحة في المعلومات المعتمدة، ثم وضّح الخطوة التالية للمشاهد.`,
      brand_announcement:`أعلن خبر ${name}، واشرح التغيير المؤكد وأثره على الجمهور، ثم قدّم الخطوة التالية.`
    }:{
      company_intro:`Introduce ${name}, explain the services in the approved company brief and who they help, then invite viewers to contact the team. Use confirmed facts only.`,
      product_launch:`Introduce the new product from ${name}, show its confirmed benefit for the intended audience, then invite viewers to learn more. Add the approved product details before creating the script.`,
      hiring:`Introduce the opportunity at ${name}. Add the approved job title, responsibilities, requirements and application method before creating the script.`,
      explainer:`Explain how the service from ${name} helps with the task described in the approved brief, then show the next step for the viewer.`,
      brand_announcement:`Announce the confirmed news from ${name}, explain what changes for the audience, then give viewers a clear next step.`
    };
    field.value=examples[this.$('[data-vp=campaign_type]').value];field.focus();this.status('Example brief loaded. Replace general directions with approved company or product details before creating the script.');
  }
  requireSaved(){if(this.shotDrafts.size)throw new Error('Save the edited shots before generating, approving or rendering.');}
  reviewer(){this.requireSaved();const value=this.$('[data-vp-reviewer]').value.trim();if(!value)throw new Error('Enter the reviewer name before approving.');return value;}
  async run(action){if(this.busy)return;this.busy=true;this.host.querySelectorAll('button').forEach(b=>b.disabled=true);try{await action();}catch(error){this.status(error.message);}finally{this.busy=false;this.host.querySelectorAll('button').forEach(b=>b.disabled=false);this.syncSteps();}}
  go(step){if(step>0&&!this.record){this.status('Create or open a production first.');return;}this.step=step;this.host.querySelectorAll('[data-vp-panel]').forEach(p=>p.hidden=+p.dataset.vpPanel!==step);this.host.querySelectorAll('[data-vp-step]').forEach(b=>b.setAttribute('aria-current',+b.dataset.vpStep===step?'step':'false'));}
  syncSteps(){this.host.querySelectorAll('[data-vp-step]').forEach(b=>b.disabled=this.busy||(+b.dataset.vpStep>0&&!this.record));}
  async load(){
    const [brands,guidelines,assets,list]=await Promise.all([fetch('/api/brands').then(r=>r.json()),fetch('/api/guidelines').then(r=>r.json()),api('/assets'),api('/productions')]);
    for(const brand of brands.brands||[])this.$('[data-vp=brand_id]').add(new Option(brand.brand_name,brand.id));this.guidelines=guidelines;this.assets=assets;this.fillSaved(list);this.fillGuidelines();this.fillAudio();
    api('/models').then(models=>{this.models=models;this.drawModels();for(const select of this.host.querySelectorAll('[data-shot-input="model"]'))this.modelOptions(select,select.value);}).catch(error=>{this.$('[data-vp-models]').textContent=error.message;});
    let remembered;try{remembered=localStorage.getItem(storageKey('lexnis.video.production'));}catch{}
    if(remembered)try{await this.open(remembered);}catch{this.status('The previous production is unavailable in this workspace.');}
  }
  fillSaved(list){const select=this.$('[data-vp-saved]');select.replaceChildren(new Option('New production',''));for(const item of list)select.add(new Option(item.name+' · '+item.stage,item.id));if(this.record)select.value=this.record.id;}
  fillGuidelines(selected){const select=this.$('[data-vp=guideline_id]'),value=selected??select.value;select.replaceChildren(new Option('Use the selected brand kit',''));for(const doc of this.guidelines||[])select.add(new Option((doc.filename||'Guideline')+(doc.confirmed?' · reviewed':' · needs review'),doc.id));select.value=value;}
  fillAudio(){for(const key of ['voiceover','music']){const select=this.$('[data-vp-'+key+']'),value=select.value;select.replaceChildren(new Option('None',''));for(const asset of this.assets.filter(a=>a.kind==='audio'))select.add(new Option(asset.name,asset.id));select.value=value;}}
  async open(id){this.shotDrafts.clear();if(!id){this.record=null;this.go(0);return;}this.record=await api('/productions/'+id);try{localStorage.setItem(storageKey('lexnis.video.production'),id);}catch{}this.$('[data-vp-saved]').value=id;const options=this.record.audio_options;if(options){this.$('[data-vp-voiceover]').value=options.voiceover_asset_id||'';this.$('[data-vp-music]').value=options.music_asset_id||'';this.$('[data-vp-music-level]').value=options.music_volume;this.$('[data-vp-captions]').checked=options.burn_subtitles;}this.draw();if(this.record.busy_job)await this.watch(this.record.busy_job);}
  async refresh(){if(this.record)this.record=await api('/productions/'+this.record.id);this.assets=await api('/assets');this.fillSaved(await api('/productions'));this.fillAudio();if(this.record)this.draw();}
  async create(){
    const fields=Object.fromEntries([...this.host.querySelectorAll('[data-vp]')].map(el=>[el.dataset.vp,el.type==='checkbox'?el.checked:el.value]));
    if(!fields.brand_id||!fields.core_message.trim())throw new Error('Choose a brand kit and enter the core campaign message.');
    const brief=Object.fromEntries(['brand_id','campaign_type','language','target_audience','tone','platform_target','core_message'].map(k=>[k,fields[k]]));
    Object.assign(brief,{duration:+fields.duration,resolution:+fields.resolution,guideline_id:fields.guideline_id||null});
    this.status('Building an editable local script and freezing the brand pack…');
    this.record=await api('/productions',{name:fields.name,brief,script_text:fields.script_text,continuity_notes:fields.continuity_notes,use_local_ai:fields.use_local_ai});this.shotDrafts.clear();
    this.fillSaved(await api('/productions'));this.draw();this.go(1);this.status('Production created. Review the supplied words and frozen brand rules before approving.');
    try{localStorage.setItem(storageKey('lexnis.video.production'),this.record.id);}catch{}
  }
  async mutate(path,body,step=this.step,method='POST'){this.record=await api('/productions/'+this.record.id+path,{...body,expected_version:this.record.version},method);this.draw();this.go(step);this.status('Saved to the production review history.');}
  draw(){
    const record=this.record;if(!record)return;
    const script=this.$('[data-vp-script]');script.replaceChildren();
    const title=document.createElement('p');title.textContent=record.name+' · '+record.script_source+' · version '+record.version;script.append(title);
    for(const shot of record.shots){const p=document.createElement('p');p.textContent=`${shot.sequence}. ${shot.input.overlay_text}\n${shot.input.voiceover}`;p.style.whiteSpace='pre-line';p.dir='auto';script.append(p);}
    for(const warning of record.script_warnings||[]){const p=document.createElement('p');p.textContent=warning;script.append(p);}
    const governance=this.$('[data-vp-governance]');governance.replaceChildren();const heading=document.createElement('h3');heading.textContent='Frozen governance pack';const brand=record.governance.brand,rules=record.governance.rules;
    const identity=document.createElement('p');identity.textContent=brand.brand_name+' · Font: '+brand.font_family+(rules.logo_placement?' · Logo: '+rules.logo_placement:'');governance.append(heading,identity);
    const palette=document.createElement('p');palette.className='vp-brand-colors';for(const color of [...rules.primary_colors,...rules.secondary_colors]){const chip=document.createElement('span');chip.textContent=color;chip.style.borderLeft='20px solid '+color;palette.append(chip);}governance.append(palette);
    if(brand.logo_asset_id){const logo=document.createElement('img');logo.src=BASE+'/media/'+brand.logo_asset_id;logo.alt='Approved '+brand.brand_name+' logo';logo.style.cssText='max-width:160px;max-height:80px;object-fit:contain';governance.append(logo);}
    for(const [label,value] of [['Call to action',rules.cta],['Required disclosures',(rules.required_disclosures||[]).join('; ')],['Avoid',(rules.prohibited_elements||[]).join('; ')],['Typography notes',(record.governance.warnings||[]).join('; ')]]){if(value){const p=document.createElement('p');p.textContent=label+': '+value;governance.append(p);}}
    const details=document.createElement('details'),summary=document.createElement('summary');summary.textContent='Inspect frozen rules and revision';const pre=document.createElement('pre');pre.textContent=JSON.stringify(record.governance,null,2);details.append(summary,pre);governance.append(details);
    this.drawShots();this.drawTakes();this.drawMaster();this.drawDelivery();
    api('/voices?language='+record.request.language).then(result=>{if(this.record?.id!==record.id)return;const select=this.$('[data-vp-narrator]'),value=select.value||record.audio_options?.narrator_voice||'';select.replaceChildren(new Option('No synthesized narration',''));for(const voice of result.voices||[])select.add(new Option(voice.name,voice.id));select.value=value;}).catch(()=>{});
    this.syncSteps();
  }
  drawModels(){const host=this.$('[data-vp-models]');host.replaceChildren();for(const model of this.models){const p=document.createElement('p');p.textContent=model.id+': '+(model.available?'hardware eligible':model.reasons.join('; '))+'. '+model.note+' Verification: '+(model.verified?'smoke test recorded':model.last_run?.success===false?'last local run failed; retry needs verification':'not verified');host.append(p);if(!model.installed){const code=document.createElement('code');code.textContent='python scripts/setup_local_video.py --model '+model.id+' --accept-license';host.append(code);}}}
  drawShots(){
    const host=this.$('[data-vp-shots]');host.replaceChildren();
    for(const shot of this.record.shots){const draft=this.shotDrafts.get(shot.id),input=draft?.input||shot.input,baseRevision=draft?.revision??shot.input_revision,card=document.createElement('article');card.className='vp-card';
      card.innerHTML=`<h3>Shot ${shot.sequence} · ${shot.id.slice(0,8)}</h3><div class="vp-grid">${[['overlay_text','On-screen headline'],['voiceover','Narration'],['visual_prompt','Visual plate direction'],['subject','Subject'],['action','Action'],['location','Location'],['wardrobe','Wardrobe'],['props','Props'],['camera_angle','Camera angle'],['camera_motion','Camera motion'],['continuity_notes','Shot continuity notes']].map(([key,label])=>`<label>${label}<textarea data-shot-input="${key}" rows="2">${escape(input[key])}</textarea></label>`).join('')}
        <label>Duration<input data-shot-input="duration" type="number" min="1" max="30" step=".1" value="${input.duration}"></label><label>Seed<input data-shot-input="seed" type="number" min="0" max="2147483647" value="${input.seed}"></label>
        <label>Shot generation method<select data-shot-input="method">${['auto','motion-graphics','real-footage','image-animation','text-to-video','image-to-video'].map(v=>`<option ${v===input.method?'selected':''}>${v}</option>`).join('')}</select></label>
        <label>Local video model<select data-shot-input="model">${this.models.length?this.models.map(m=>`<option value="${m.id}" ${m.id===input.model?'selected':''}>${m.id}${m.available?'':' · unavailable'}</option>`).join(''):`<option>${escape(input.model)}</option>`}</select></label>
        <label>Framing<select data-shot-input="framing">${['wide','medium','close-up','detail'].map(v=>`<option ${v===input.framing?'selected':''}>${v}</option>`).join('')}</select></label>
        <label>Still-image motion<select data-shot-input="motion">${['zoom-in','zoom-out','pan','still'].map(v=>`<option ${v===input.motion?'selected':''}>${v}</option>`).join('')}</select></label>
        <label>Motion-graphics background<select data-shot-input="background_style">${['brand-gradient','minimal','geometric'].map(v=>`<option ${v===input.background_style?'selected':''}>${v}</option>`).join('')}</select></label>
        <label>Screen direction<select data-shot-input="screen_direction">${['neutral','left-to-right','right-to-left','toward-camera'].map(v=>`<option ${v===input.screen_direction?'selected':''}>${v}</option>`).join('')}</select></label>
        <label>Transition<select data-shot-input="transition"><option ${input.transition==='fade'?'selected':''}>fade</option><option ${input.transition==='cut'?'selected':''}>cut</option></select></label>
        <label>Transition seconds<input data-shot-input="transition_seconds" type="number" min="0" max="1" step=".1" value="${input.transition_seconds}"></label>
        <label>Reference still<select data-shot-input="reference_asset_id"><option value="">None</option>${this.assets.filter(a=>a.kind==='image').map(a=>`<option value="${a.id}" ${a.id===input.reference_asset_id?'selected':''}>${escape(a.name)}</option>`).join('')}</select></label>
        <label>Source footage or still<select data-shot-input="source_asset_id"><option value="">None</option>${this.assets.filter(a=>['image','video'].includes(a.kind)).map(a=>`<option value="${a.id}" ${a.id===input.source_asset_id?'selected':''}>${escape(a.name)}</option>`).join('')}</select></label></div>
        <label><input data-shot-input="accuracy_critical" type="checkbox" ${input.accuracy_critical?'checked':''}> Accuracy-critical product, screen, person or location</label><button type="button" data-save-shot>Save shot ${shot.sequence}</button><button type="button" data-discard-shot>Discard unsaved edits for shot ${shot.sequence}</button><p data-draft-status></p>`;
      if(draft&&baseRevision!==shot.input_revision)card.querySelector('[data-draft-status]').textContent='This shot changed in another session. Your unsaved draft is preserved; discard it to load the current saved revision.';
      const readDraft=()=>{const next={...input};for(const el of card.querySelectorAll('[data-shot-input]')){const k=el.dataset.shotInput;next[k]=el.type==='checkbox'?el.checked:el.type==='number'?+el.value:['reference_asset_id','source_asset_id'].includes(k)?el.value||null:el.value;}return next;};
      const retain=()=>this.shotDrafts.set(shot.id,{input:readDraft(),revision:baseRevision});card.addEventListener('input',retain);card.addEventListener('change',retain);
      card.querySelector('[data-discard-shot]').onclick=()=>{this.shotDrafts.delete(shot.id);this.drawShots();this.status('Unsaved shot edits discarded. The current saved revision is displayed.');};
      card.querySelector('[data-save-shot]').onclick=()=>this.run(async()=>{if(baseRevision!==shot.input_revision)throw new Error('This shot changed since you started editing. Discard the unsaved draft before editing the current revision.');const next=readDraft();this.shotDrafts.delete(shot.id);try{await this.mutate('/shots/'+shot.id,{shot:next},2,'PUT');}catch(error){this.shotDrafts.set(shot.id,{input:next,revision:baseRevision});throw error;}});this.labelControls(card);host.append(card);if(this.models.length)this.modelOptions(card.querySelector('[data-shot-input="model"]'),input.model);
    }
  }
  drawTakes(){
    const host=this.$('[data-vp-takes]');host.replaceChildren();
    for(const shot of this.record.shots){const card=document.createElement('article');card.className='vp-card';const title=document.createElement('h3');title.textContent=`Shot ${shot.sequence} · ${shot.input.overlay_text}`;card.append(title);
      for(const pass of ['concept','continuity','final']){const box=document.createElement('section');box.dataset.reviewShot=shot.id;box.dataset.reviewPass=pass;box.innerHTML=`<h4>${pass[0].toUpperCase()+pass.slice(1)} pass ${shot.approvals[pass]?'· approved':''}</h4><button type="button" data-generate>Generate ${pass} · shot ${shot.sequence}</button>
        <label>Candidate for ${pass}<select data-candidate><option value="">Select a take</option>${shot.candidates.filter(c=>c.pass_name===pass).map(c=>`<option value="${c.id}">${c.method} · ${c.metadata.width}×${c.metadata.height} · ${c.id.slice(0,8)}</option>`).join('')}</select></label>
        <label><input data-framing-guides type="checkbox"> Show rule-of-thirds guides (preview only)</label><div data-take-preview></div><label><input data-intent type="checkbox"> Shot intent checked</label>${pass!=='concept'?'<label><input data-continuity type="checkbox"> Continuity and screen direction checked</label>':''}${pass==='final'?'<label><input data-readability type="checkbox"> Identity text remains separate compositor artwork</label>':''}
        <label>Review feedback<textarea data-review-note maxlength="1200" rows="2" placeholder="Describe what works or what needs changing"></textarea></label>
        <label>Correction area<select data-review-issue>${['intent','continuity','readability','motion','brand','other'].map(issue=>`<option ${issue===(pass==='concept'?'intent':pass==='continuity'?'continuity':'readability')?'selected':''}>${issue}</option>`).join('')}</select></label>
        <button type="button" data-approve>Approve ${pass} · shot ${shot.sequence}</button><button type="button" data-reject>Reject ${pass} · shot ${shot.sequence}</button>`;
        const select=box.querySelector('[data-candidate]'),preview=box.querySelector('[data-take-preview]'),guides=box.querySelector('[data-framing-guides]');
        guides.onchange=()=>{const grid=preview.querySelector('.vp-framing-grid');if(grid)grid.hidden=!guides.checked;};
        select.onchange=()=>{preview.replaceChildren();const take=shot.candidates.find(c=>c.id===select.value);if(take){const video=document.createElement('video');video.src=take.url;video.controls=true;video.muted=true;video.preload='metadata';const frame=document.createElement('div');frame.className='vp-preview-frame';frame.style.maxWidth=(420*(take.metadata.width/take.metadata.height||16/9))+'px';const grid=document.createElement('div');grid.className='vp-framing-grid';grid.hidden=!guides.checked;grid.setAttribute('aria-hidden','true');frame.append(video,grid);const note=document.createElement('p');note.textContent=take.notice+' · seed '+take.seed;preview.append(frame,note);for(const review of take.reviews||[]){const item=document.createElement('p');item.dataset.takeReview='';item.textContent=(review.approved?'Approved':'Rejected')+' by '+review.reviewer+(review.note?': '+review.note:'')+(review.suggestion?' Next: '+review.suggestion:'');preview.append(item);}}};
        const latest=shot.candidates.filter(c=>c.pass_name===pass).at(-1),selected=shot.approvals[pass]?.candidate_id||latest?.id;if(selected){select.value=selected;select.onchange();}
        box.querySelector('[data-generate]').onclick=()=>this.run(async()=>{this.requireSaved();const job=await api('/productions/'+this.record.id+'/shots/'+shot.id+'/generate',{expected_version:this.record.version,pass_name:pass});await this.watch(job.id);});
        const review=approved=>this.run(async()=>{if(!select.value)throw new Error('Select a candidate take before reviewing.');await this.mutate('/shots/'+shot.id+'/review',{gate:pass,candidate_id:select.value,reviewer:this.reviewer(),approved,
          note:box.querySelector('[data-review-note]').value,issue:approved?null:box.querySelector('[data-review-issue]').value,
          intent_checked:box.querySelector('[data-intent]').checked,continuity_checked:!!box.querySelector('[data-continuity]')?.checked,readability_checked:!!box.querySelector('[data-readability]')?.checked},3);});
        box.querySelector('[data-approve]').onclick=()=>review(true);box.querySelector('[data-reject]').onclick=()=>review(false);this.labelControls(box);card.append(box);
      }host.append(card);
    }
  }
  modelOptions(select,value){select.replaceChildren();for(const model of this.models){const option=new Option(model.id+(model.available?'':' · unavailable'),model.id);option.disabled=!model.available;option.title=(model.reasons||[]).join('; ');select.add(option);}select.value=value;}
  async watch(id){const progress=this.$('[data-vp-progress]'),cancel=this.$('[data-vp-cancel]');progress.hidden=false;progress.removeAttribute('value');cancel.hidden=false;cancel.disabled=false;cancel.onclick=()=>api('/jobs/'+id+'/cancel',{}).catch(error=>this.status(error.message));try{for(;;){const job=await api('/jobs/'+id);this.status(job.phase||job.state);if(job.progress?.total_steps)progress.value=100*job.progress.step/job.progress.total_steps;if(job.state==='completed'){progress.value=100;await this.refresh();this.status('Production job completed. Review the saved result.');return;}if(['failed','cancelled'].includes(job.state)){await this.refresh();throw new Error(job.error||'Production job cancelled.');}await wait(1000);}}finally{progress.hidden=true;cancel.hidden=true;}}
  async render(){if(!this.record)return;this.requireSaved();const job=await api('/productions/'+this.record.id+'/render',{expected_version:this.record.version,
    narrator_voice:this.$('[data-vp-narrator]').value||null,music_asset_id:this.$('[data-vp-music]').value||null,voiceover_asset_id:this.$('[data-vp-voiceover]').value||null,
    music_volume:+this.$('[data-vp-music-level]').value,burn_subtitles:this.$('[data-vp-captions]').checked,variants:[...this.host.querySelectorAll('[data-vp-variant]:checked')].map(el=>el.value)});await this.watch(job.id);this.go(5);}
  drawMaster(){const host=this.$('[data-vp-master]');host.replaceChildren();if(!this.record.render)return;const output=this.record.render;
    for(const [label,result] of [['Master',output],...Object.entries(output.variants||{})]){const h=document.createElement('h3');h.textContent=label;const video=document.createElement('video');video.src=result.url;video.controls=true;video.preload='metadata';const p=document.createElement('p');p.textContent='Technical QA: '+(result.qa?.overall||'Not available');host.append(h,video,p);const details=document.createElement('details'),summary=document.createElement('summary');summary.textContent='Inspect technical measurements and review warnings';details.append(summary);for(const check of result.qa?.checks||[]){const item=document.createElement('p');item.textContent=check.status+' · '+check.label+(check.detail?' — '+check.detail:'')+(check.measured!=null?' · '+JSON.stringify(check.measured):'');details.append(item);}host.append(details);}}
  async check(){const result=await api('/productions/'+this.record.id+'/check',{});const host=this.$('[data-vp-checks]');host.replaceChildren();for(const item of result.findings){const p=document.createElement('p');p.textContent=item.state+': '+item.message;host.append(p);}const p=document.createElement('p');p.textContent=result.render_matches_timeline?'The rendered master matches the current timeline.':'Render the current timeline before release.';host.append(p);this.status(result.notice);}
  async release(){const checks=Object.fromEntries([...this.host.querySelectorAll('[data-vp-release-check]')].map(el=>[el.dataset.vpReleaseCheck,el.checked]));const job=await api('/productions/'+this.record.id+'/release',{expected_version:this.record.version,reviewer:this.reviewer(),note:this.$('[data-vp-release-note]').value,...checks});await this.watch(job.id);this.go(6);}
  drawDelivery(){const host=this.$('[data-vp-delivery]');host.replaceChildren();if(!this.record.release){host.textContent='Client downloads unlock after the exact master and platform variants pass final release review.';return;}for(const [kind,label] of [['zip','Download approved client kit (.ZIP)'],['master','Download approved master (.MP4)'],...Object.keys(this.record.render.variants||{}).map(aspect=>[aspect.replace(':','x'),'Download '+aspect])]){const a=document.createElement('a');a.href=BASE+'/productions/'+this.record.id+'/delivery/'+kind;a.download='';a.textContent=label;host.append(a);}}
  async uploadMedia(){const input=this.$('[data-vp-media-file]'),file=input.files[0];if(!file)return;const body=new FormData();body.append('file',file);const response=await fetch(BASE+'/upload',{method:'POST',body});const value=await response.json();if(!response.ok)throw new Error(value.detail||'Upload failed');this.assets=await api('/assets');this.fillAudio();if(this.record)this.drawShots();input.value='';this.status('Media validated and added to this workspace.');}
  async uploadGuideline(){const input=this.$('[data-vp-guide-file]'),file=input.files[0];if(!file)return;const body=new FormData();body.append('file',file);const response=await fetch('/api/guidelines',{method:'POST',body});const value=await response.json();if(!response.ok)throw new Error(value.detail||'Guideline upload failed');this.guidelines=await fetch('/api/guidelines').then(r=>r.json());this.fillGuidelines(value.id);await this.previewGuideline();input.value='';}
  async previewGuideline(){const id=this.$('[data-vp=guideline_id]').value;if(!id){this.guide=null;this.$('[data-vp-guide-review]').textContent='';this.$('[data-vp-confirm-guide]').hidden=true;return;}const response=await fetch('/api/guidelines/'+id);this.guide=await response.json();if(!response.ok)throw new Error('Could not read the guideline.');this.$('[data-vp-guide-review]').textContent=JSON.stringify(this.guide.rules,null,2);this.$('[data-vp-confirm-guide]').hidden=this.guide.confirmed;}
  async confirmGuideline(){if(!this.guide)return;const response=await fetch('/api/guidelines/'+this.guide.id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_version:this.guide.version,rules:this.guide.rules,confirmed:true})});if(!response.ok)throw new Error('Guidelines changed. Load the latest rules before confirming.');await this.previewGuideline();this.status('Extracted brand rules confirmed. They will be frozen when you create the production.');}
}

let instance;
export async function mountVideoProduction(host){if(!instance)instance=new VideoProduction(host);await instance.ready;return instance;}
