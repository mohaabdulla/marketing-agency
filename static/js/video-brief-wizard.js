import {api,post,esc} from './video-api.js';
import {storageKey} from './public-session.js';

const key=()=>storageKey('lexnis.video.brief-wizard');
export class VideoBriefWizard {
  constructor(studio){
    this.studio=studio;this.step=0;this.busy=false;this.loading=true;
    const panel=studio.$('#vs-generate'),advanced=document.createElement('details');
    advanced.id='vbf-advanced';advanced.className='vs-card';
    advanced.innerHTML='<summary>Advanced: individual AI clips and image animation</summary>';
    while(panel.firstChild)advanced.append(panel.firstChild);
    panel.append(advanced);
    this.root=document.createElement('section');this.root.className='vs-card vbf-wizard';panel.prepend(this.root);
    this.root.innerHTML=`<div class="eyebrow">BRAND-GUIDED VIDEO CREATION</div><h2>From campaign brief to finished video</h2>
      <p>Shape the story, review each scene, then render a branded video and client hand-off kit.</p>
      <nav class="vbf-steps" aria-label="Video creation steps">${['Brand & Brief','Format & Style','Storyboard & Audio','Render & Export'].map((name,i)=>`<button type="button" data-step="${i}" ${i>1?'disabled':''}>${i+1}. ${name}</button>`).join('')}</nav>
      <p data-notice role="status" aria-live="polite"></p>
      <section data-panel="0"><h3>1. Brand & Campaign Brief</h3>
        <label>Brand kit<select data-field="brand_id" required><option value="">Loading brand kits…</option></select></label>
        <div class="vs-pair"><label>Campaign type<select data-field="campaign_type"><option value="product_launch">Product Launch</option><option value="hiring">Hiring / Recruitment</option><option value="brand_announcement">Brand Announcement</option><option value="explainer">Explainer</option></select></label>
        <label>Language<select data-field="language"><option value="en">English</option><option value="ar">Arabic</option></select></label></div>
        <div class="vbf-message-help"><h4>Let us help you write the message</h4><p>Paste the company website and add its guidelines. We’ll suggest a starting message you can edit.</p>
          <label>Company website<input type="url" data-field="company_url" maxlength="2000" placeholder="https://your-company.com"></label>
          <label>Company guidelines<select data-field="guideline_id"><option value="">No guideline selected</option></select></label>
          <div class="vs-row"><button type="button" data-guideline-upload>Upload guidelines</button><button type="button" data-guideline-refresh>Refresh guidelines</button></div>
          <input type="file" data-guideline-file accept=".pdf,.docx,.txt,.md,.markdown,.json" hidden>
          <p data-guideline-status role="status"></p>
          <details><summary>Add company notes (optional)</summary><label>Company notes<textarea data-guideline-notes maxlength="4000" placeholder="Any approved details about the company, product or role…"></textarea></label></details>
          <button type="button" class="primary" data-assist="draft">Research company & suggest message</button>
          <p data-assist-status role="status" aria-live="polite"></p>
          <section data-suggestion hidden><p data-suggestion-source></p><label>Suggested message<textarea data-suggested maxlength="2000"></textarea></label><button type="button" data-use-suggestion>Use this message</button><div data-source-links></div><ul data-questions></ul></section>
        </div>
        <label>Core message or vacancy/product details<textarea data-field="core_message" maxlength="2000" required placeholder="Use the suggestion above, or describe your idea in your own words. You can edit everything before rendering."></textarea></label>
        <button type="button" data-assist="enhance">AI enhance message</button>
        <p><small>Enhancement proposes a clearer version for you to review. Your current message stays unchanged until you use it.</small></p>
        <button type="button" class="primary" data-next>Next: Format & Style</button>
      </section>
      <section data-panel="1" hidden><h3>2. Format & Style</h3><div class="vs-pair">
        <label>Platform format<select data-field="platform_target"><option value="9:16">Reels / TikTok · 9:16</option><option value="1:1">Feed · 1:1</option><option value="16:9">Landscape · 16:9</option></select></label>
        <label>Tone<select data-field="tone"><option value="professional">Professional</option><option value="energetic">Energetic</option><option value="warm">Warm</option></select></label>
        <label>Pacing<select data-field="pacing"><option value="balanced">Balanced</option><option value="calm">Calm</option><option value="fast">Fast</option></select></label>
        <label>Transitions<select data-field="transition"><option value="fade">Smooth crossfade</option><option value="cut">Clean cut</option></select></label>
        <label>Total duration (seconds)<input data-field="duration" type="number" min="6" max="60" step="1" value="12"></label>
        <label>Export short edge<select data-field="resolution"><option value="720">720 px</option><option value="1080">1080 px</option></select></label></div>
        <div class="vs-row"><button type="button" data-back>Back</button><button type="button" class="primary" data-plan>Generate storyboard</button></div>
      </section>
      <section data-panel="2" hidden><h3>3. Storyboard Preview & Editing</h3><p data-source></p><div data-scenes class="vbf-scenes"></div>
        <div class="vs-pair"><label>Recorded voiceover<select data-audio="voiceover_asset_id"><option value="">No voiceover</option></select></label><label>Licensed music track<select data-audio="music_asset_id"><option value="">No music</option></select></label></div>
        <button type="button" data-upload>Upload storyboard images or audio</button>
        <p><small>The editable script is not synthesized speech. Select a recorded voiceover to include speech. Scene images are optional; otherwise the renderer uses branded motion graphics.</small></p>
        <div class="vs-row"><button type="button" data-back>Back</button><button type="button" class="primary" data-next>Next: Render & Export</button></div>
      </section>
      <section data-panel="3" hidden><h3>4. Render & Export</h3><label class="vbf-toggle"><input data-subtitles type="checkbox" checked> Burn subtitles into the video</label>
        <div class="vs-row"><button type="button" data-back>Back</button><button type="button" class="primary" data-render>Render complete video</button></div>
        <progress data-progress max="100" value="0" aria-label="Video render progress"></progress><p data-progress-label>Ready when you are.</p>
        <div data-preview class="vs-preview"></div><div data-exports class="vs-row"></div>
      </section>`;
    this.$=s=>this.root.querySelector(s);this.labelControls(this.root);
    this.root.querySelectorAll('[data-assist]').forEach(button=>button.onclick=()=>this.suggest(button.dataset.assist));
    this.$('[data-use-suggestion]').onclick=()=>this.useSuggestion();
    this.$('[data-guideline-upload]').onclick=()=>this.$('[data-guideline-file]').click();
    this.$('[data-guideline-file]').onchange=()=>this.uploadGuideline();
    this.$('[data-guideline-refresh]').onclick=()=>this.refreshGuidelines().catch(error=>this.assistNotice(error.message));
    this.$('[data-upload]').onclick=()=>{studio.pickUpload();studio.$('#vs-upload-input').accept='.png,.jpg,.jpeg,.webp,.mp3,.wav,.ogg,.m4a,.flac';};
    this.root.querySelectorAll('[data-step]').forEach(button=>button.onclick=()=>this.go(+button.dataset.step));
    this.root.querySelectorAll('[data-next]').forEach(button=>button.onclick=()=>this.go(this.step+1));
    this.root.querySelectorAll('[data-back]').forEach(button=>button.onclick=()=>this.go(this.step-1));
    this.$('[data-plan]').onclick=()=>this.plan();this.$('[data-render]').onclick=()=>this.render();
    this.root.addEventListener('change',event=>{
      if(event.target.dataset.field)this.invalidate();
      if(['brand_id','company_url','guideline_id'].includes(event.target.dataset.field)||event.target.hasAttribute('data-guideline-notes'))this.resetSources();
      this.persist();
    });
    this.root.addEventListener('input',event=>{
      if(event.target.dataset.field)this.invalidate();
      if(['brand_id','company_url','guideline_id'].includes(event.target.dataset.field)||event.target.hasAttribute('data-guideline-notes'))this.resetSources();
      this.persist();
    });
    this.go(0);this.ready=this.load();
  }
  notice(text){this.$('[data-notice]').textContent=text;}
  assistNotice(text){this.$('[data-assist-status]').textContent=text;}
  resetSources(){this.messageContext=null;this.suggestionIdentity=null;this.$('[data-suggestion]').hidden=true;}
  sourceValues(){return {brand_id:this.$('[data-field=brand_id]').value,company_url:this.$('[data-field=company_url]').value.trim(),
    guideline_id:this.$('[data-field=guideline_id]').value||null,guideline_notes:this.$('[data-guideline-notes]').value,
    campaign_type:this.$('[data-field=campaign_type]').value,language:this.$('[data-field=language]').value,tone:this.$('[data-field=tone]').value};}
  async refreshGuidelines(selected){
    const response=await fetch('/api/guidelines');const data=await response.json();if(!response.ok)throw new Error('Unable to load guidelines.');
    const select=this.$('[data-field=guideline_id]'),value=selected??select.value;
    select.replaceChildren(new Option('No guideline selected',''));
    for(const document of data)select.add(new Option(document.filename||document.rules.brand_name||'Company guideline',document.id));
    select.value=value||'';
  }
  async uploadGuideline(){
    const input=this.$('[data-guideline-file]'),file=input.files[0];if(!file||this.uploadingGuideline)return;
    const status=this.$('[data-guideline-status]');this.uploadingGuideline=true;status.textContent='Reading company guidelines…';
    this.$('[data-guideline-upload]').disabled=true;
    try{
      const body=new FormData();body.append('file',file);
      const response=await fetch('/api/guidelines',{method:'POST',body});const doc=await response.json();
      if(!response.ok)throw new Error(typeof doc.detail==='string'?doc.detail:'Could not read the guideline file.');
      await this.refreshGuidelines(doc.id);this.resetSources();this.invalidate();this.persist();status.textContent='Loaded '+file.name+'. These guidelines will inform your suggested message.';
    }catch(error){status.textContent=error.message;}
    finally{input.value='';this.uploadingGuideline=false;this.$('[data-guideline-upload]').disabled=false;}
  }
  async suggest(action){
    if(this.assisting||this.busy)return;
    const brand=this.$('[data-field=brand_id]');if(!brand.value){this.assistNotice('Choose a brand kit first.');brand.focus();return;}
    if(this.uploadingGuideline){this.assistNotice('Wait for the guideline upload to finish.');return;}
    const website=this.$('[data-field=company_url]');
    if(website.value.trim()&&!website.value.includes('://'))website.value='https://'+website.value.trim();
    if(!website.reportValidity())return;
    const original=this.$('[data-field=core_message]').value;
    if(action==='enhance'&&!original.trim()){this.assistNotice('Use Research & suggest message first, or enter a few words to enhance.');return;}
    const sources=this.sourceValues(),identity=JSON.stringify(sources);
    this.assisting=true;this.root.querySelectorAll('[data-assist]').forEach(button=>button.disabled=true);
    this.assistNotice(action==='draft'?'Reading company sources and drafting a message…':'Improving clarity using your company context…');
    try{
      const result=await post('/suggest-message',{...sources,core_message:original,action,context_id:action==='enhance'?this.messageContext?.id||null:null});
      if(identity!==JSON.stringify(this.sourceValues())){this.assistNotice('Your company details changed. Request a fresh suggestion.');return;}
      this.messageContext={id:result.context_id};this.suggestionIdentity=identity;
      this.$('[data-suggested]').value=result.message;this.$('[data-suggested]').dir=sources.language==='ar'?'rtl':'ltr';this.$('[data-suggestion]').hidden=false;
      this.$('[data-suggestion-source]').textContent=(result.ai_used?'AI suggestion':'Structured suggestion — no AI inference')+' · '+result.notice;
      const links=this.$('[data-source-links]');links.replaceChildren();
      for(const source of result.sources){const a=document.createElement('a');a.href=source.url;a.textContent=source.title;a.target='_blank';a.rel='noopener noreferrer';links.append(a,document.createElement('br'));}
      const questions=this.$('[data-questions]');questions.replaceChildren();
      for(const question of result.questions){const item=document.createElement('li');item.textContent=question;questions.append(item);}
      if(!original.trim()&&this.$('[data-field=core_message]').value===original){this.applyMessage(result.message);this.assistNotice('A starting message is ready below. Edit any bracketed details, then continue.');}
      else this.assistNotice('Suggestion ready. Review it above and choose Use this message when you want to apply it.');
      if(result.warnings.length)this.assistNotice(this.$('[data-assist-status]').textContent+' '+result.warnings.join(' '));
      this.persist();
    }catch(error){this.assistNotice(error.message);if(this.messageContext)this.messageContext=null;}
    finally{this.assisting=false;this.root.querySelectorAll('[data-assist]').forEach(button=>button.disabled=false);}
  }
  applyMessage(message){this.invalidate();this.$('[data-field=core_message]').value=message;this.persist();}
  useSuggestion(){
    if(this.suggestionIdentity!==JSON.stringify(this.sourceValues())){this.assistNotice('Your brief settings changed. Request a fresh suggestion first.');return;}
    this.applyMessage(this.$('[data-suggested]').value);this.assistNotice('Message applied. You can edit it below or continue to Format & Style.');
  }
  labelControls(root){
    for(const label of root.querySelectorAll('label')){
      const control=label.querySelector('input,select,textarea');
      const text=[...label.childNodes].filter(node=>node.nodeType===Node.TEXT_NODE).map(node=>node.textContent).join(' ').trim();
      if(control&&text)control.setAttribute('aria-label',text);
    }
  }
  invalidate(){
    if(!this.brief)return;
    this.brief=null;this.result=null;this.unlock(false);
    this.$('[data-preview]').querySelector('video')?.pause();
    this.$('[data-preview]').replaceChildren();this.$('[data-exports]').replaceChildren();
    this.notice('Brief changed. Generate a new storyboard before rendering.');
  }
  values(){return Object.fromEntries([...this.root.querySelectorAll('[data-field]')].map(el=>[el.dataset.field,['duration','resolution'].includes(el.dataset.field)?+el.value:el.dataset.field==='guideline_id'?el.value||null:el.value]));}
  unlock(ready){this.root.querySelectorAll('[data-step]').forEach(button=>button.disabled=this.busy||(+button.dataset.step>1&&!ready));}
  go(step){
    if(this.busy||step<0||step>3)return;
    if(this.step===0&&step>0&&!this.$('[data-field=core_message]').value.trim()){this.suggest('draft');return;}
    if(step>0&&!this.valid(0))return;if(step>1&&(!this.brief||!this.valid(1)))return;
    this.step=step;this.root.querySelectorAll('[data-panel]').forEach(el=>el.hidden=+el.dataset.panel!==step);
    this.root.querySelectorAll('[data-step]').forEach(el=>el.setAttribute('aria-current',+el.dataset.step===step?'step':'false'));
    this.persist();
  }
  valid(step){for(const el of this.$(`[data-panel="${step}"]`).querySelectorAll('input,textarea,select'))if(!el.reportValidity())return false;return true;}
  persist(){if(this.loading)return;try{this.audioDraft=Object.fromEntries([...this.root.querySelectorAll('[data-audio]')].map(el=>[el.dataset.audio,el.value]));localStorage.setItem(key(),JSON.stringify({fields:this.values(),brief_id:this.brief?.brief_id,scenes:this.brief?.scenes,job_id:this.jobId,result:this.result,audio:this.audioDraft,burn_subtitles:this.$('[data-subtitles]').checked,company_notes:this.$('[data-guideline-notes]').value,message_context:this.messageContext}));}catch{}}
  async load(){
    try{
      const saved=JSON.parse(localStorage.getItem(key())||'null');
      this.audioDraft=saved?.audio||{};this.$('[data-subtitles]').checked=saved?.burn_subtitles!==false;
      this.messageContext=saved?.message_context||null;this.$('[data-guideline-notes]').value=saved?.company_notes||'';
      const response=await fetch('/api/brands');if(!response.ok)throw new Error('Unable to load brand kits.');
      const {brands}=await response.json();const select=this.$('[data-field=brand_id]');select.replaceChildren(new Option('Choose a brand kit',''));
      for(const brand of brands)select.add(new Option(brand.brand_name,brand.id));
      await this.refreshGuidelines(saved?.fields?.guideline_id);
      for(const [name,value] of Object.entries(saved?.fields||{})){const el=this.$('[data-field="'+name+'"]');if(el)el.value=value;}
      if(saved?.brief_id){this.brief=await api('/briefs/'+saved.brief_id);if(saved.scenes)this.brief.scenes=saved.scenes;this.drawScenes();this.unlock(true);}
      if(saved?.result)this.showResult(saved.result);
      if(saved?.job_id)this.watch(await api('/jobs/'+saved.job_id));
    }catch(error){this.notice(error.message);}
    finally{this.loading=false;}
  }
  refreshAssets(){
    for(const select of this.root.querySelectorAll('[data-audio],[data-scene-image]')){
      const selected=select.value||this.audioDraft?.[select.dataset.audio]||'',isImage=select.hasAttribute('data-scene-image');
      select.replaceChildren(new Option(isImage?'Branded motion artwork':'None',''));
      for(const asset of this.studio.assets.filter(asset=>asset.kind===(isImage?'image':'audio')))select.add(new Option(asset.name,asset.id));
      select.value=selected;
    }
  }
  drawScenes(){
    this.$('[data-source]').textContent=(this.brief.planning_source==='ai-model'?'AI-generated storyboard.':'Local template storyboard.')+' '+this.brief.warnings.join(' ');
    const host=this.$('[data-scenes]');host.replaceChildren();
    this.brief.scenes.forEach((scene,index)=>{
      const card=document.createElement('article');card.className='vbf-scene';
      card.innerHTML=`<h4>Scene ${index+1} · ${scene.start.toFixed(2)}–${(scene.start+scene.duration).toFixed(2)}s</h4><div class="vbf-placeholder" role="img" aria-label="Scene ${index+1} visual placeholder"></div>
        <label>Visual direction<textarea data-edit="visual_prompt" maxlength="1000">${esc(scene.visual_prompt)}</textarea></label>
        <label>Text overlay<textarea data-edit="overlay_text" maxlength="180" dir="${this.brief.request.language==='ar'?'rtl':'ltr'}">${esc(scene.overlay_text)}</textarea></label>
        <label>Voiceover script<textarea data-edit="voiceover" maxlength="450" dir="${this.brief.request.language==='ar'?'rtl':'ltr'}">${esc(scene.voiceover)}</textarea></label>
        <div class="vs-pair"><label>Duration (seconds)<input data-edit="duration" type="number" min="1" max="60" step=".001" value="${scene.duration}"></label>
        <label>Camera movement<select data-edit="motion">${['zoom-in','zoom-out','pan','still'].map(move=>`<option>${move}</option>`).join('')}</select></label></div>
        <label>Scene image<select data-scene-image><option value="">Branded motion artwork</option></select></label>`;
      card.querySelector('[data-edit=motion]').value=scene.motion;
      const placeholder=card.querySelector('.vbf-placeholder');placeholder.style.background=this.brief.brand.primary_hex;placeholder.style.borderColor=this.brief.brand.secondary_hex;placeholder.textContent='Scene '+(index+1)+' · '+scene.overlay_text;
      card.querySelectorAll('[data-edit]').forEach(el=>el.oninput=()=>{
        scene[el.dataset.edit]=el.dataset.edit==='duration'?+el.value:el.value;
        let cursor=0;for(const item of this.brief.scenes){item.start=+cursor.toFixed(3);cursor+=item.duration;}
        this.brief.scenes.forEach((item,i)=>host.children[i].querySelector('h4').textContent=`Scene ${i+1} · ${item.start.toFixed(2)}–${(item.start+item.duration).toFixed(2)}s`);
        if(el.dataset.edit==='overlay_text')placeholder.textContent='Scene '+(index+1)+' · '+scene.overlay_text;
        this.persist();
      });
      card.querySelector('[data-scene-image]').onchange=event=>{scene.asset_id=event.target.value||null;this.persist();};
      host.append(card);
    });
    this.labelControls(host);this.refreshAssets();this.brief.scenes.forEach((scene,i)=>host.children[i].querySelector('[data-scene-image]').value=scene.asset_id||'');
  }
  setBusy(value){this.busy=value;this.root.querySelectorAll('input,select,textarea,[data-back],[data-next],[data-plan],[data-render],[data-upload],[data-guideline-upload],[data-guideline-refresh],[data-use-suggestion],[data-assist]').forEach(el=>el.disabled=value||this.assisting&&el.hasAttribute('data-assist'));this.unlock(!!this.brief);}
  async plan(){
    if(this.busy||!this.valid(0)||!this.valid(1))return;
    this.setBusy(true);this.notice('Preparing your brand-guided storyboard…');
    try{this.brief=await post('/generate-brief',this.values());this.drawScenes();this.notice('Review the visual direction, timings and script before rendering.');this.setBusy(false);this.go(2);this.persist();}
    catch(error){this.notice(error.message);}finally{this.setBusy(false);}
  }
  async render(){
    if(this.busy||!this.brief||!this.valid(2))return;
    this.setBusy(true);this.notice('Queueing your reviewed storyboard…');
    try{
      const audio=Object.fromEntries([...this.root.querySelectorAll('[data-audio]')].map(el=>[el.dataset.audio,el.value||null]));
      const job=await post('/render-sequence',{brief_id:this.brief.brief_id,scenes:this.brief.scenes,burn_subtitles:this.$('[data-subtitles]').checked,...audio});
      this.watch(job);
    }catch(error){this.notice(error.message);this.setBusy(false);}
  }
  watch(job){
    this.jobId=job.id;this.setBusy(true);this.persist();
    this.studio.watch(job,result=>{this.showResult(result);this.jobId=null;this.setBusy(false);this.persist();},status=>{
      const progress=this.$('[data-progress]'),p=status.progress;let percent=p?.percent;
      if(p?.total_scenes)percent=5+20*p.completed_scenes/p.total_scenes;
      if(p?.total_clips)percent=25+45*p.completed_clips/p.total_clips;
      if(status.state==='completed')percent=100;
      if(percent!==undefined)progress.value=percent;else progress.removeAttribute('value');
      this.$('[data-progress-label]').textContent=status.phase||status.state;
      if(['failed','cancelled'].includes(status.state)){this.jobId=null;this.setBusy(false);this.notice(status.error||'Render cancelled.');this.persist();}
    });
  }
  showResult(result){
    this.result=result;this.$('[data-preview]').innerHTML=`<video controls playsinline preload="metadata" src="${esc(result.video_url)}" aria-label="Storyboard video preview"></video>`;
    this.$('[data-exports]').innerHTML=`<a class="vs-button primary" href="${esc(result.mp4_url)}" download>Download MP4</a><a class="vs-button" href="${esc(result.bundle_zip_url)}" download>Download Full Video Kit (.ZIP)</a>`;
    this.$('[data-progress]').value=100;this.notice(`Video ready · ${result.width}×${result.height} · ${result.fps} fps. Rendered with local motion graphics.`);
    this.$('[data-progress-label]').textContent='Render complete.';
  }
}
