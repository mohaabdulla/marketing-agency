import {api,post,upload,esc} from './video-api.js';
import {storageKey} from './public-session.js';

// Reuse the existing controls and project state; advanced editing stays available.
export class QuickVideoEditor{
  constructor(brand,{purpose,goal,instruction}){
    this.brand=brand;this.editor=brand.editor;this.moves=[];this.sourceId='';
    this.bar=document.createElement('div');this.bar.className='vs-row ve-mode-bar';
    this.bar.innerHTML='<strong>Video editing</strong><button type="button" data-mode-quick>Quick edit</button><button type="button" data-mode-advanced>Advanced editor</button><span>Upload, describe, watch the edited result.</span>';
    brand.root.prepend(this.bar);
    this.root=document.createElement('div');this.root.className='ve-quick';this.root.dataset.quickEditor='';
    this.root.innerHTML='<ol class="ve-steps" aria-label="Editing steps"><li>Source</li><li>Brand guidelines</li><li>Brief</li><li>AI assistant</li><li>Settings</li><li>Preview</li><li>QA</li><li>Export</li></ol><section class="vs-card" data-step="source"><h2>1. Source video</h2><button type="button" data-quick-upload>Upload video</button><input type="file" data-quick-file accept=".mp4,.mov,.webm,.gif" hidden><label>Source video<select data-quick-source><option value="">Upload or choose a video</option></select></label><p data-quick-source-info></p><p><small>The original file is never changed. Every edit is a new timeline revision you can undo.</small></p></section><section class="vs-card" data-step="brand"><h2>2. Brand guidelines &amp; logo</h2><p>Upload or choose the same reviewed guidelines used for Image &amp; GIF. Their rules steer titles, captions, logo and compliance checks.</p><div data-quick-guidelines></div><h3>Logo</h3><div data-quick-logo></div></section><section class="vs-card" data-step="brief"><h2>3. Goal &amp; creative brief</h2><div data-quick-details></div><div data-quick-instruction></div></section><section class="vs-card" data-step="assistant"><h2>4. AI prompt assistant</h2><p>Turn a short request into an editable brief before anything is edited.</p><div data-quick-assist-slot></div></section><section class="vs-card" data-step="settings"><h2>5. Edit settings</h2><div class="vs-row ve-quick-options"><label><input type="checkbox" data-quick-captions checked> Captions</label><label><input type="checkbox" data-quick-pauses checked> Tighten pauses</label><label><input type="checkbox" data-quick-zooms checked> Punch-ins at cuts and new thoughts</label><label><input type="checkbox" data-quick-tail checked> Trim recording ending</label></div><div class="vs-pair"><label>Speech language<select data-quick-language><option value="en">English</option><option value="ar">Arabic</option><option value="auto">Detect automatically</option></select></label><label>Framing<select data-quick-aspect><option value="source">Keep original / use preset</option><option value="9:16">Vertical reel · 9:16</option><option value="16:9">Landscape · 16:9</option><option value="1:1">Square</option><option value="4:5">Portrait · 4:5</option></select></label><label>Delivery preset<select data-quick-delivery></select></label><label>Largest punch-in<select data-quick-punch><option value="">From the edit style</option><option value="1.03">Very subtle · 3%</option><option value="1.06">Subtle · 6%</option><option value="1.1">Noticeable · 10%</option></select></label><label>Edit style<select data-quick-style><option value="auto">From my brief</option></select></label><label>Platform safe zones<select data-quick-platform><option value="auto">From my brief</option></select></label><label>Lighting<select data-quick-lighting><option value="auto">Correct if measurement shows a problem</option><option value="off">Leave as recorded</option></select></label><label>Background<select data-quick-background><option value="auto">Only if I ask for it</option><option value="none">Leave as recorded</option><option value="blur-dim">Blur and dim behind the speaker</option><option value="replace">Replace with an approved image</option></select></label><label data-quick-background-image-wrap hidden>Approved background image<select data-quick-background-image><option value="">Choose an uploaded image</option></select></label><label>Canvas size<select data-quick-canvas><option value="native">Native master · keep source resolution</option><option value="platform">Platform canvas · scale up (no added detail)</option></select></label></div><div class="vs-row ve-quick-options"><label><input type="checkbox" data-quick-voice> Dialogue clarity (high-pass + gentle compression)</label></div><p data-quick-capabilities><small></small></p><p data-quick-preset-note><small></small></p><div class="vs-row"><button type="button" data-quick-plan>Preview the edit plan</button><button type="button" class="primary" data-quick-run>Create edited video</button></div><p role="status" data-quick-status></p></section><section class="vs-card" data-step="preview"><h2>6. Before / after</h2><div class="vs-row"><button type="button" data-quick-original disabled>Original</button><button type="button" data-quick-edited disabled>Edited</button></div><div data-quick-requests></div><p data-quick-preview-label></p><div class="vs-preview" data-quick-preview><p>Your edited video appears here after processing.</p></div><div data-quick-review></div><div data-quick-report></div></section><section class="vs-card" data-step="qa"><h2>7. Brand &amp; technical QA</h2><div data-quick-gates></div><div data-quick-editorial></div><h3>Technical delivery QA</h3><div data-quick-qa><p>After rendering, the exported file itself is measured and checked here.</p></div></section><section class="vs-card" data-step="export"><h2>8. Export</h2><a class="vs-button primary" data-quick-download hidden>Download edited MP4</a><p data-quick-export-note>Download the MP4 from here and compare it before sending it through a messaging app, which re-compresses video.</p></section>';
    this.bar.after(this.root);this.$=selector=>this.root.querySelector(selector);
    this.$('[data-quick-plan]').insertAdjacentHTML('afterend','<button type="button" data-quick-variants>Compare four edit plans</button>');
    this.$('[data-quick-plan]').parentElement.insertAdjacentHTML('afterend','<div data-quick-variant-plans></div>');
    this.$('[data-quick-edited]').insertAdjacentHTML('afterend','<button type="button" data-quick-previous disabled>Previous revision</button><button type="button" data-quick-sync disabled>Play original and current together</button>');
    this.$('[data-quick-download]').insertAdjacentHTML('afterend','<div data-quick-review-state></div>');
    this.$('[data-quick-style]').closest('label').insertAdjacentHTML('afterend','<label>Brand motion<select data-quick-motion><option value="minimal">Minimal</option><option value="balanced">Balanced</option><option value="expressive">Expressive</option></select></label>');
    const advanced=document.createElement('details');advanced.innerHTML='<summary>More edit settings</summary><div class="vs-pair" data-extra-settings></div>';
    this.$('[data-quick-capabilities]').before(advanced);
    for(const key of ['punch','style','motion','platform','lighting','background','background-image','canvas'])advanced.querySelector('[data-extra-settings]').append(this.$('[data-quick-'+key+']').closest('label'));
    advanced.querySelector('[data-extra-settings]').insertAdjacentHTML('beforeend','<label>Graphic entrance<select data-quick-graphic-motion><option value="fade">Minimal fade</option><option value="slide-up">Slide up</option><option value="masked-reveal">Masked reveal</option><option value="soft-scale">Soft scale</option></select></label>');
    advanced.querySelector('[data-extra-settings]').insertAdjacentHTML('beforeend','<label>Automatic cuts<select data-quick-policy><option value="safe">Safe · only very confident cleanup</option><option value="balanced" selected>Balanced · review uncertain speech cuts</option><option value="aggressive">Aggressive · stronger shortening</option></select></label><label>Semantic story planner<select data-quick-semantic><option value="auto">Use local model when available</option><option value="off">Measured rules only</option><option value="local">Request local semantic plan</option></select></label><label>Caption reading target (characters/second)<input type="number" data-quick-cps min="8" max="30" placeholder="Language default"></label><label>Color intent<select data-quick-look><option value="auto">From edit style</option><option value="organic">Organic</option><option value="polished-organic">Polished organic</option><option value="corporate-clean">Corporate clean</option><option value="warm-lifestyle">Warm lifestyle</option><option value="high-energy">High-energy social</option><option value="cinematic-brand">Cinematic brand · SDR</option></select></label><label>Performance tier<select data-quick-tier><option value="basic-cpu">Basic CPU</option><option value="enhanced-cpu" selected>Enhanced CPU</option><option value="gpu-professional">GPU professional · requires optional setup</option></select></label><label><input type="checkbox" data-quick-denoise> Gentle dialogue noise reduction</label><label>Hum notch<select data-quick-hum><option value="0">Off</option><option value="50">50 Hz · only if heard/measured</option><option value="60">60 Hz · only if heard/measured</option></select></label><label><input type="checkbox" data-quick-deess> Gentle de-essing</label>');
    advanced.insertAdjacentHTML('beforeend','<details><summary>Optional reference video</summary><p>Transfer measured pacing and energy. Reference media, copy and music are never copied; undetected properties stay unmeasured.</p><button type="button" data-reference-upload>Upload reference</button><input type="file" data-reference-file accept=".mp4,.mov,.webm" hidden><label>Reference<select data-reference-select><option value="">No reference</option></select></label><label><input type="checkbox" data-reference-property="pacing"> Use this pacing</label><label><input type="checkbox" data-reference-property="energy"> Use this visual energy</label><label><input type="checkbox" data-reference-property="caption-hierarchy"> Review its caption hierarchy</label><label><input type="checkbox" data-reference-property="color-mood"> Review its color mood</label></details>');
    this.$('[data-quick-requests]').insertAdjacentHTML('afterend','<div data-quick-director></div><div data-quick-plan-stills class="vs-pair"></div>');
    this.$('[data-quick-assist-slot]').insertAdjacentHTML('beforebegin','<div class="vs-row" data-director-assistant>'+[['typography','Improve typography'],['lighting','Improve lighting'],['background','Improve background'],['pacing','Improve pacing'],['audio','Improve audio'],['hook','Improve hook']].map(([task,label])=>'<button type="button" data-director-task="'+task+'">'+label+'</button>').join('')+'</div><p data-director-advice></p>');
    this.slots=[{node:brand.logoPanel,slot:this.$('[data-quick-logo]')},{node:instruction,slot:this.$('[data-quick-instruction]')},
      {node:brand.assistant.root,slot:this.$('[data-quick-assist-slot]')},
      {node:brand.guidelineControls,slot:this.$('[data-quick-guidelines]')},
      ...[purpose,goal,brand.personPanel].map(node=>({node,slot:this.$('[data-quick-details]')}))];
    for(const item of this.slots){item.marker=document.createComment('advanced-control-position');item.node.before(item.marker);}
    this.bar.querySelector('[data-mode-quick]').onclick=()=>this.mode('quick');this.bar.querySelector('[data-mode-advanced]').onclick=()=>this.mode('advanced');
    this.$('[data-quick-upload]').onclick=()=>this.$('[data-quick-file]').click();
    this.$('[data-quick-file]').onchange=async event=>{
      const file=event.target.files[0];if(!file)return;
      try{this.status('Uploading and validating video...');const asset=await upload(file);if(asset.kind!=='video')throw new Error('Choose a video; use the separate logo upload for images.');this.sourceId=asset.id;if(!this.editor.projectId&&this.editor.project.name==='Untitled video')this.editor.project.name=asset.name.replace(/\.[^.]+$/,'').slice(0,110);await this.editor.studio.refreshAssets();if(!this.editor.project.clips.length)this.editor.add(asset);this.refreshSources();this.status('Video ready. Describe the edit below.');}
      catch(error){this.status(error.message);}finally{event.target.value='';}
    };
    this.$('[data-quick-source]').onchange=event=>{this.sourceId=event.target.value;this.refreshSources();};
    this.$('[data-quick-run]').onclick=()=>this.run();
    this.$('[data-quick-plan]').onclick=()=>this.run(true);
    this.$('[data-reference-upload]').onclick=()=>this.$('[data-reference-file]').click();
    this.$('[data-reference-file]').onchange=async event=>{const file=event.target.files[0];if(!file)return;try{const a=await upload(file);if(a.kind!=='video')throw new Error('Choose a video reference.');await this.editor.studio.refreshAssets();this.references(a.id);this.status('Reference ready. Choose which measured properties to transfer.');}catch(e){this.status(e.message);}finally{event.target.value='';}};
    this.$('[data-reference-select]').onfocus=()=>this.references(this.$('[data-reference-select]').value);
    this.root.querySelectorAll('[data-director-task]').forEach(button=>button.onclick=()=>this.directorAdvice(button.dataset.directorTask));
    this.$('[data-quick-variants]').onclick=()=>this.run(true,true);
    this.$('[data-quick-previous]').onclick=()=>this.showVideo(this.previous?.url,'Previous rendered revision');
    this.$('[data-quick-sync]').onclick=()=>this.comparePlayback();
    this.approved=new Set();this.corrections={};this.reviewed=false;this.storyRoles={};
    this.root.addEventListener('change',event=>{if(event.target.dataset.storyRole)this.storyRoles[event.target.dataset.storyRole]=event.target.value;});
    this.$('[data-quick-background]').onchange=()=>this.backgroundChoice();
    this.loadPresets();this.loadCapabilities();
    this.$('[data-quick-original]').onclick=()=>this.showVideo(this.sourceAsset()?.url,'Original source · no edits');
    this.$('[data-quick-edited]').onclick=()=>this.showVideo(this.result?.url,'Edited result · captions, cuts and branding rendered into the file');
    let mode=new URLSearchParams(location.search).get('editmode');if(!mode){try{mode=localStorage.getItem(storageKey('lexnis.video.editor-mode'))||'quick';}catch{mode='quick';}}
    this.mode(mode==='advanced'?'advanced':'quick');this.refreshSources();
  }
  mode(mode){
    const quick=mode==='quick';
    for(const item of this.slots){if(quick)item.slot.append(item.node);else item.marker.parentNode.insertBefore(item.node,item.marker);}
    this.root.hidden=!quick;this.brand.workflow.root.hidden=quick;
    this.bar.querySelector('[data-mode-quick]').classList.toggle('primary',quick);this.bar.querySelector('[data-mode-advanced]').classList.toggle('primary',!quick);
    if(quick)this.brand.assistant.root.open=true;
    try{localStorage.setItem(storageKey('lexnis.video.editor-mode'),mode);}catch{}
  }
  async loadPresets(){
    try{const data=await api('/export-presets'),select=this.$('[data-quick-delivery]');this.presets=data.presets;
      select.innerHTML=data.presets.map(p=>'<option value="'+p.id+'" '+(p.id===data.default?'selected':'')+'>'+esc(p.label)+'</option>').join('');
      const note=()=>{const p=this.presets.find(x=>x.id===select.value);this.$('[data-quick-preset-note] small').textContent=p?p.video+' · '+p.audio+' · '+(p.loudness_target_lufs===null?'loudness as recorded':p.loudness_target_lufs+' LUFS')+' · true peak ≤ '+p.true_peak_ceiling_dbtp+' dBTP. '+p.note+' '+data.note:'';};
      select.onchange=note;note();}catch(error){this.status(error.message);}
  }
  async loadCapabilities(){
    try{const c=await api('/editing-capabilities');this.capabilities=c;
      this.$('[data-quick-style]').innerHTML='<option value="auto">From my brief</option>'+c.styles.map(x=>'<option value="'+x.id+'">'+esc(x.label)+'</option>').join('');
      this.$('[data-quick-platform]').innerHTML='<option value="auto">From my brief</option>'+c.platforms.profiles.map(x=>'<option value="'+x.id+'">'+esc(x.label)+'</option>').join('');
      this.$('[data-quick-capabilities] small').textContent=(c.matting.available?'Subject mask available ('+c.matting.model+', local): background blur and replacement work. ':c.matting.reason+' ')+c.semantic_planner.reason+' Safe zones: '+c.platforms.basis.toLowerCase()+', not official platform specifications.';
      for(const option of this.$('[data-quick-background]').options)if(['blur-dim','replace'].includes(option.value))option.disabled=!c.matting.available;
    }catch(error){this.status(error.message);}
  }
  backgroundChoice(){
    const replace=this.$('[data-quick-background]').value==='replace',wrap=this.$('[data-quick-background-image-wrap]');wrap.hidden=!replace;
    if(replace)this.$('[data-quick-background-image]').innerHTML='<option value="">Choose an approved image or video</option>'+this.editor.studio.assets.filter(a=>['image','video'].includes(a.kind)).map(a=>'<option value="'+a.id+'">'+esc(a.name)+'</option>').join('');
  }
  references(selected=''){this.$('[data-reference-select]').innerHTML='<option value="">No reference</option>'+this.editor.studio.assets.filter(a=>a.kind==='video'&&a.id!==this.sourceId).map(a=>'<option value="'+a.id+'">'+esc(a.name)+'</option>').join('');this.$('[data-reference-select]').value=selected;}
  directorAdvice(task){
    const actions={typography:'Improve text hierarchy and avoid collisions between captions, speaker identity and CTA.',lighting:'Improve subject lighting while preserving natural skin and background color.',background:'Clean the background while preserving a natural environment.',pacing:'Improve pacing without changing meaning; keep uncertain cuts for review.',audio:'Improve dialogue clarity with gentle EQ and compression.',hook:'Review the opening hook against the source transcript; do not invent words or rearrange meaning.'};
    if(task==='lighting')this.$('[data-quick-lighting]').value='auto';if(task==='background')this.$('[data-quick-background]').value='auto';if(task==='pacing')this.$('[data-quick-pauses]').checked=true;if(task==='audio')this.$('[data-quick-voice]').checked=true;
    const field=this.brand.$('[data-instruction]');if(!field.value.includes(actions[task]))field.value=(field.value.trim()+'\n'+actions[task]).trim();field.dispatchEvent(new Event('input',{bubbles:true}));
    this.$('[data-director-advice]').textContent=task==='hook'&&!this.capabilities?.semantic_planner.available?'Added an editable hook-review request. Semantic inference is unavailable; meaning and hook strength need your review.':'Added an editable '+task+' direction. Preview the plan to see actual decisions and limitations.';
  }
  sourceAsset(){return this.editor.studio.assets.find(asset=>asset.id===this.sourceId&&asset.kind==='video');}
  refreshSources(){
    const videos=this.editor.studio.assets.filter(asset=>asset.kind==='video'),select=this.$('[data-quick-source]');
    if(!videos.some(asset=>asset.id===this.sourceId))this.sourceId=this.editor.project.clips.map(clip=>clip.asset_id).find(id=>videos.some(asset=>asset.id===id))||videos[0]?.id||'';
    if(this.lastSourceId&&this.lastSourceId!==this.sourceId){this.approved=new Set();this.corrections={};this.reviewed=false;this.storyRoles={};this.previous=null;this.$('[data-quick-previous]').disabled=true;this.$('[data-quick-sync]').disabled=true;this.$('[data-quick-review-state]').innerHTML='';this.$('[data-quick-variant-plans]').innerHTML='';}
    this.lastSourceId=this.sourceId;
    select.innerHTML='<option value="">Upload or choose a video</option>'+videos.map(asset=>'<option value="'+asset.id+'">'+esc(asset.name)+'</option>').join('');select.value=this.sourceId;
    const asset=this.sourceAsset();this.$('[data-quick-source-info]').textContent=asset?`${asset.width} × ${asset.height} · ${asset.duration.toFixed(2)}s · ${asset.fps.toFixed(2)} fps · original quality`:'No video selected yet.';
    this.$('[data-quick-original]').disabled=!asset;
    if(this.result&&this.result.source_asset_id!==this.sourceId){this.result=null;this.$('[data-quick-download]').hidden=true;this.$('[data-quick-edited]').disabled=true;this.$('[data-quick-preview]').innerHTML='<p>Create an edit for the selected source.</p>';for(const key of ['report','requests','review','gates','editorial'])this.$('[data-quick-'+key+']').innerHTML='';this.$('[data-quick-qa]').innerHTML='<p>After rendering, the exported file itself is measured and checked here.</p>';this.approved=new Set();this.corrections={};this.reviewed=false;}
    if(!this.result){try{const saved=JSON.parse(localStorage.getItem(storageKey('lexnis.video.quick-result'))||'null'),result=this.editor.studio.assets.find(a=>a.id===saved?.id&&a.source_asset_id===this.sourceId);if(result?.edit_report)this.showResult(result);}catch{}}
  }
  sync(){if(this.projectId!==this.editor.projectId){this.projectId=this.editor.projectId;this.sourceId=this.editor.project.clips.map(c=>c.asset_id).find(id=>this.editor.studio.assets.some(a=>a.id===id&&a.kind==='video'))||this.sourceId;}this.refreshSources();this.$('[data-quick-language]').value=this.editor.project.creative_context?.language?.startsWith('ar')?'ar':'en';}
  status(message){this.$('[data-quick-status]').textContent=message;}
  showVideo(url,label){if(!url)return;const preview=this.$('[data-quick-preview]'),asset=[this.result,this.previous,this.sourceAsset()].find(a=>a?.url===url);preview.innerHTML='<video controls preload="metadata" '+(asset?.thumbnail_url?'poster="'+esc(asset.thumbnail_url)+'" ':'')+'src="'+esc(url)+'"></video>';if(asset?.width&&asset?.height){preview.style.aspectRatio=asset.width+'/'+asset.height;preview.style.maxWidth=asset.height>asset.width?Math.round(600*asset.width/asset.height)+'px':'100%';preview.style.margin='12px auto';}this.$('[data-quick-preview-label]').textContent=label;}
  comparePlayback(){
    if(!this.result||!this.sourceAsset())return;
    const preview=this.$('[data-quick-preview]');preview.style.aspectRatio='auto';preview.style.maxWidth='100%';
    preview.innerHTML='<div class="vs-pair"><div><p>Original (muted)</p><video data-compare-source muted playsinline src="'+esc(this.sourceAsset().url)+'"></video></div><div><p>Current edit · playback controls</p><video data-compare-edit controls playsinline src="'+esc(this.result.url)+'"></video></div></div>';
    const source=preview.querySelector('[data-compare-source]'),edited=preview.querySelector('[data-compare-edit]');
    const cuts=[...(this.result.edit_report?.cuts||[])].sort((a,b)=>a.start-b.start);
    const sync=()=>{let original=edited.currentTime;for(const cut of cuts){if(original+.001>=cut.start)original+=cut.end-cut.start;}if(Math.abs(source.currentTime-original)>.18)source.currentTime=Math.min(original,source.duration||original);source.playbackRate=edited.playbackRate;};
    edited.addEventListener('timeupdate',sync);edited.addEventListener('seeking',sync);edited.addEventListener('ratechange',sync);
    edited.addEventListener('play',()=>{sync();source.play().catch(()=>{});});edited.addEventListener('pause',()=>source.pause());edited.addEventListener('ended',()=>source.pause());
    this.$('[data-quick-preview-label]').textContent='Playback follows the edited timeline; original skips the removed ranges. Only edited audio plays.';
  }
  async loadReviewState(result){
    const box=this.$('[data-quick-review-state]');box.innerHTML='';
    if(!result.render_revision_id)return;
    try{
      const record=await api('/assets/'+result.id+'/review');if(this.result?.id!==result.id)return;
      const states=['DRAFT','INTERNAL_REVIEW','CLIENT_REVIEW','APPROVED','FINAL'],next=states[states.indexOf(record.state)+1];
      box.innerHTML='<h3>Review status: '+esc(record.state.replaceAll('_',' '))+'</h3><p>Caption status: '+esc((record.caption_state||'NOT_APPLICABLE').replaceAll('_',' '))+'. Review belongs to this rendered version. A new edit starts as a draft.</p><label>Review note<input data-review-note maxlength="1000"></label>'
        +(next?'<button type="button" data-review-next>Move to '+esc(next.replaceAll('_',' ').toLowerCase())+'</button>':'')
        +(record.state!=='DRAFT'?'<button type="button" data-review-draft>Return to draft</button>':'')
        +'<details><summary>Review history ('+record.events.length+')</summary>'+record.events.map(e=>'<p>'+esc(e.state.replaceAll('_',' '))+' · '+esc(new Date(e.timestamp*1000).toLocaleString())+' '+esc(e.note)+'</p>').join('')+'</details><p role="status" data-review-message></p>';
      const move=async state=>{try{await post('/assets/'+result.id+'/review',{state,note:box.querySelector('[data-review-note]').value});await this.loadReviewState(result);}catch(error){box.querySelector('[data-review-message]').textContent=error.message;}};
      if(next)box.querySelector('[data-review-next]').onclick=()=>move(next);
      if(record.state!=='DRAFT')box.querySelector('[data-review-draft]').onclick=()=>move('DRAFT');
      const categories=['story','hook','pacing','composition','typography','captions','framing','lighting','color','background','audio','brand','platform-fit','professional-finish'];
      box.insertAdjacentHTML('beforeend','<details><summary>Your creative review · 1–5</summary><p>Optional human judgment for this render. No automated quality rating is filled in.</p><div class="vs-pair">'+categories.map(key=>'<label>'+esc(key.replaceAll('-',' '))+'<select data-rubric-score="'+key+'"><option value="">Not reviewed</option>'+[1,2,3,4,5].map(n=>'<option '+(record.rubric?.scores?.[key]===n?'selected':'')+'>'+n+'</option>').join('')+'</select></label>').join('')+'</div><label>Creative review notes<textarea data-rubric-notes maxlength="2000">'+esc(record.rubric?.notes||'')+'</textarea></label><button type="button" data-save-rubric>Save my ratings</button><p role="status" data-rubric-status></p></details>');
      box.querySelector('[data-save-rubric]').onclick=async()=>{try{const scores={};box.querySelectorAll('[data-rubric-score]').forEach(n=>{if(n.value)scores[n.dataset.rubricScore]=Number(n.value);});await post('/assets/'+result.id+'/rubric',{scores,notes:box.querySelector('[data-rubric-notes]').value});box.querySelector('[data-rubric-status]').textContent='Your review was saved for this rendered revision.';}catch(e){box.querySelector('[data-rubric-status]').textContent=e.message;}};
    }catch(error){if(this.result?.id===result.id)box.textContent=error.message;}
  }
  requestStatus(report){
    const names={FULFILLED:'DONE',PARTIALLY_FULFILLED:'PARTLY DONE',UNSUPPORTED:'NOT AVAILABLE',NOT_NEEDED:'NOT NEEDED',NOT_APPLIED:'NOT APPLIED',AWAITING_REVIEW:'AWAITING REVIEW'};
    const tone={FULFILLED:'PASS',PARTIALLY_FULFILLED:'WARNING',UNSUPPORTED:'FAIL',NOT_NEEDED:'NOT_CHECKED',NOT_APPLIED:'NOT_CHECKED',AWAITING_REVIEW:'WARNING'};
    const rows=(report.request_fulfilment||[]).map(r=>'<details class="ve-request"><summary><span>'+esc(r.label)+'</span><span class="ve-qa" data-status="'+tone[r.status]+'">'+names[r.status]+'</span></summary><p>'+esc(r.detail)+'</p></details>').join('');
    return '<h3>Your request</h3>'+(rows||'<p>No specific change was recognised in the instruction; the default clean-up was applied.</p>')+'<p><small>Style: '+esc(report.style_profile.label)+' ('+esc(report.style_profile.basis)+') · '+report.style_profile.summary.map(esc).join('; ')+'. '+esc(report.semantic_planner)+'</small></p>';
  }
  decisionTable(report){
    const time=t=>Number(t).toFixed(2)+'s';
    const rows=(report.decisions||[]).map(d=>'<tr><td>'+esc(d.type.replaceAll('_',' '))+(d.requires_review?'<br><span class="ve-qa" data-status="WARNING">REVIEW</span>':'')+'</td><td>'+time(d.start)+' → '+time(d.end)+'</td><td>'+esc(d.purpose||d.reason)+'<br><small>'+esc(d.evidence)+'</small></td><td>'+Math.round(d.confidence*100)+'%</td><td>'+esc(d.effect)+'</td></tr>').join('');
    return rows?'<div class="ve-table"><table><thead><tr><th>What</th><th>When</th><th>Why · evidence</th><th>Confidence</th><th>Expected effect</th></tr></thead><tbody>'+rows+'</tbody></table></div>':'';
  }
  reviewTools(report){
    const box=this.$('[data-quick-review]'),proposed=report.proposed_cuts||[],unresolved=report.caption_review?.unresolved||[],hasCaptions=report.caption_count>0;
    if(!proposed.length&&!unresolved.length&&!(hasCaptions&&report.caption_state!=='reviewed')){box.innerHTML='';return;}
    box.innerHTML='<h3>Needs your decision</h3>'
      +proposed.map(c=>'<label class="ve-approve"><input type="checkbox" data-approve-cut="'+c.id+'" '+(this.approved.has(c.id)?'checked':'')+'> Apply this cut: '+esc(c.reason)+' at '+c.start.toFixed(2)+'s, removes '+c.removed_seconds.toFixed(2)+'s · '+Math.round(c.confidence*100)+'% confidence<br><small>'+esc(c.evidence)+'. Not applied automatically because the evidence is weak.</small></label>').join('')
      +(unresolved.length?'<p><strong>Caption review required.</strong> These likely names were recognised with low confidence. Type what was actually said; nothing is guessed.</p>'+unresolved.map(n=>'<label class="ve-approve">Heard: “'+esc(n.heard)+'” · '+Math.round(n.confidence*100)+'% at '+n.start+'s<input data-correct="'+esc(n.heard)+'" maxlength="60" placeholder="Correct spelling, or the same word if it is right" value="'+esc(this.corrections[n.heard]||'')+'"></label>').join(''):'')
      +(hasCaptions?'<details><summary>All caption cues</summary>'+(report.caption_review.cues||[]).map(c=>'<p><small>'+c.start.toFixed(2)+'s</small> '+esc(c.text)+'</p>').join('')+'</details><label class="ve-approve"><input type="checkbox" data-captions-reviewed '+(this.reviewed?'checked':'')+'> I have read every caption against the audio</label>':'')
      +'<button type="button" class="primary" data-apply-review>Apply my decisions and render again</button>';
    box.querySelector('[data-apply-review]').onclick=()=>{
      box.querySelectorAll('[data-approve-cut]').forEach(i=>i.checked?this.approved.add(i.dataset.approveCut):this.approved.delete(i.dataset.approveCut));
      box.querySelectorAll('[data-correct]').forEach(i=>{if(i.value.trim())this.corrections[i.dataset.correct]=i.value.trim();else delete this.corrections[i.dataset.correct];});
      this.reviewed=!!box.querySelector('[data-captions-reviewed]')?.checked;this.run();
    };
  }
  whatChanged(report){
    return '<h3>What changed</h3><p>'+report.source_duration.toFixed(2)+'s original → '+report.edited_duration.toFixed(2)+'s edited · '+(report.duration_removed??Math.max(0,report.source_duration-report.edited_duration)).toFixed(2)+'s removed by '+report.cuts.length+' cut(s) · '+report.caption_count+' caption cues · '+report.zoom_segments+' framing change(s).</p>'
      +(report.caption_count?(report.caption_state==='reviewed'?'<p>Captions were marked as reviewed.</p>':'<p>Speech captions are a draft. Review names and wording.</p>'):report.captions_requested?'<p role="alert"><strong>Captions were requested but not created.</strong> '+esc(report.caption_diagnostic||'See the notes below.')+'</p>':'<p>Captions are disabled.</p>')
      +(report.uncertain_words?.length?'<p>Check these recognized words: '+report.uncertain_words.map(esc).join(', ')+'</p>':'')
      +this.decisionTable(report)
      +(report.story_map?'<details><summary>Story map · suggested structure</summary><p>'+esc(report.story_map.notice)+'</p>'+report.story_map.segments.map(s=>'<label>Role<select data-story-role="'+s.id+'">'+['HOOK','SETUP','VALUE','PAYOFF','CTA'].map(role=>'<option '+(role===(this.storyRoles[s.id]||s.suggested_role)?'selected':'')+'>'+role+'</option>').join('')+'</select></label><p>'+s.start.toFixed(2)+'–'+s.end.toFixed(2)+'s · '+Math.round(s.transcript_confidence*100)+'% speech confidence<br>'+esc(s.text)+'</p>').join('')+'<p>Role changes are saved with your next plan or render. They do not reorder the footage.</p></details>':'')
      +(report.canvas?'<p><small>'+esc(report.canvas.note)+' Platform profile: '+esc(report.platform_profile.label)+' ('+esc(report.platform_profile.basis.toLowerCase())+').</small></p>':'')
      +'<details><summary>Notes and limits</summary>'+report.warnings.map(w=>'<p>'+esc(w)+'</p>').join('')+'</details>';
  }
  showPlan(report){
    this.$('[data-quick-requests]').innerHTML='<p><span class="ve-qa" data-status="NOT_CHECKED">PLAN ONLY</span> No video has been rendered for this plan. Composition stills preview the graphic design over source frames.</p>'+this.requestStatus(report);
    this.$('[data-quick-download]').hidden=true;this.$('[data-quick-edited]').disabled=true;this.$('[data-quick-sync]').disabled=true;
    this.$('[data-quick-preview-label]').textContent='Plan only. Any video below is the previous rendered revision, not this proposed edit.';
    this.reviewTools(report);this.$('[data-quick-report]').innerHTML=this.whatChanged(report);
    this.$('[data-quick-requests]').scrollIntoView({block:'nearest'});
  }
  directorPreview(report,frames=[]){
    const timing=report.caption_timing?.profile?report.caption_timing:{words_retained:0,changes:[],unresolved:[],profile:{max_cps:'off'}},layout=report.layout,document=report.edit_document;
    this.$('[data-quick-director]').innerHTML=document?'<details><summary>Creative director plan · evidence and composition</summary><p>'+esc(report.semantic_planner)+'</p>'
      +'<p>Cut policy: '+esc(report.cut_policy)+'. '+esc(layout.method)+'. Unmeasured: '+layout.not_measured.map(esc).join(', ')+'.</p>'
      +'<h4>Caption timing</h4><p>'+timing.words_retained+' words retained · '+timing.changes.length+' timing adjustment(s) · '+timing.unresolved.length+' unresolved density/fit item(s) · target '+timing.profile.max_cps+' characters/second.</p>'
      +'<h4>Graphic roles</h4><div class="ve-table"><table><thead><tr><th>Role</th><th>Time</th><th>Font</th><th>Layout</th></tr></thead><tbody>'+layout.elements.map(e=>'<tr><td>'+esc(e.role)+'</td><td>'+e.start.toFixed(2)+'–'+e.end.toFixed(2)+'s</td><td>'+(e.font_size_px?e.font_size_px+' px':'Artwork')+'</td><td>'+e.box.map(n=>Math.round(n)).join(', ')+(e.requires_review?' · needs review':'')+'</td></tr>').join('')+'</tbody></table></div>'
      +'<h4>Color and background</h4><p>'+esc(report.color_pipeline.regional?'Subject and background grades are planned separately in Rec.709 SDR.':'Regional grading unavailable for this plan; review the limitation.')+' Background intent: '+esc(report.background.interpreted_intent?.intent||report.background.mode)+'.</p>'
      +'<h4>Audio intent</h4><p>'+esc(report.audio_plan.speech_cleanup)+'; noise reduction '+esc(report.audio_plan.noise_reduction)+'; de-reverb '+esc(report.audio_plan.dereverb)+'. '+esc(report.audio_plan.notice)+'</p>'
      +(report.reference_style?.profile?'<p>Reference pacing: '+report.reference_style.profile.average_shot_seconds+'s average shot; applied properties: '+report.reference_style.applied_properties.map(esc).join(', ')+'. '+esc(report.reference_style.limitations)+'</p>':'')
      +'<p>'+esc(report.performance?.notice||'')+'</p></details>':'';
    this.$('[data-quick-plan-stills]').innerHTML=frames.map(f=>'<figure><img src="'+esc(f.asset.url)+'" alt="Composition preview at '+f.time.toFixed(2)+' seconds" style="max-width:100%;height:auto"><figcaption>'+f.time.toFixed(2)+'s · '+esc(f.notice)+'</figcaption></figure>').join('');
  }
  showResult(result){
    if(this.result?.id!==result.id&&this.result?.source_asset_id===result.source_asset_id)this.previous=this.result;
    this.result=result;this.showVideo(result.url,'Edited result · this is the rendered file');
    if(result.parent_asset_id)this.previous=this.editor.studio.assets.find(a=>a.id===result.parent_asset_id)||this.previous;
    this.$('[data-quick-previous]').disabled=!this.previous||this.previous.source_asset_id!==result.source_asset_id;
    this.$('[data-quick-sync]').disabled=!this.sourceAsset();this.loadReviewState(result);
    this.$('[data-quick-edited]').disabled=false;const link=this.$('[data-quick-download]');link.href='/api/video/download/'+result.id;link.hidden=false;
    const report=result.edit_report,editorial=result.editorial_report,qa=result.qa_report;
    this.directorPreview(report,[]);
    const ready=editorial?.publish_readiness==='READY';link.download=ready?'edited.mp4':'edited-DRAFT.mp4';link.textContent=ready?'Download edited MP4':'Download draft MP4';
    this.$('[data-quick-requests]').innerHTML=report.request_fulfilment?this.requestStatus(report):'';
    if(report.decisions)this.reviewTools(report);else this.$('[data-quick-review]').innerHTML='';
    this.$('[data-quick-report]').innerHTML=report.decisions?this.whatChanged(report):'<p>'+report.source_duration.toFixed(2)+'s original → '+report.edited_duration.toFixed(2)+'s edited. This result was made before the editing upgrade; create it again for the full report.</p>';
    const gates=this.$('[data-quick-gates]'),edBox=this.$('[data-quick-editorial]'),box=this.$('[data-quick-qa]');
    const show=v=>v===null||v===undefined?'':typeof v==='object'?JSON.stringify(v):String(v);
    if(editorial){
      const tone=v=>({PASS:'PASS',READY:'PASS',DONE:'PASS','NEEDS REVIEW':'WARNING',RECOMMENDED:'WARNING',WARNING:'WARNING',DRAFT:'WARNING',REQUIRED:'FAIL',FAIL:'FAIL'}[v]||'NOT_CHECKED');
      const gate=(label,value)=>'<div class="ve-gate"><small>'+label+'</small><span class="ve-qa" data-status="'+tone(value)+'">'+esc(String(value||'NOT CHECKED').replaceAll('_',' '))+'</span></div>';
      gates.innerHTML='<div class="ve-gates">'+gate('Technical delivery QA',editorial.technical_status)+gate('Editorial quality',editorial.editorial_status)+gate('Brand',editorial.brand_status)+gate('Caption review',editorial.caption_review)+gate('Publish readiness',editorial.publish_readiness)+'</div>'
        +(editorial.blockers.length?'<p><strong>Still a draft because:</strong> '+editorial.blockers.map(esc).join('; ')+'.</p>':'<p>No open review items. A person should still watch it once before publishing.</p>')
        +'<p><small>A technically correct file is not the same as a well-edited video: the two are reported separately and there is no combined score.</small></p>';
      const order=[...new Set(editorial.checks.map(c=>c.category))];
      edBox.innerHTML='<h3>Editorial, brand and platform review</h3>'+order.map(category=>'<details class="ve-category" '+(['FAIL','WARNING'].includes(editorial.categories[category].status)?'open':'')+'><summary><span>'+esc(category)+'</span><span class="ve-qa" data-status="'+editorial.categories[category].status+'">'+editorial.categories[category].status.replace('_',' ')+'</span></summary><div class="ve-table"><table><tbody>'
        +editorial.checks.filter(c=>c.category===category).map(c=>'<tr><td><span class="ve-qa" data-status="'+c.status+'">'+c.status.replace('_',' ')+'</span></td><td>'+esc(c.label)+(c.detail?'<br><small>'+esc(c.detail)+'</small>':'')+'</td><td>'+esc(show(c.measured))+'</td></tr>').join('')+'</tbody></table></div></details>').join('')
        +'<p><small>'+esc(editorial.methodology)+' '+esc(editorial.scope)+'</small></p>';
    }else{gates.innerHTML='';edBox.innerHTML='';}
    if(qa){
      box.innerHTML='<p><span class="ve-qa" data-status="'+qa.overall+'">'+qa.overall+'</span> '+qa.counts.PASS+' passed · '+qa.counts.WARNING+' warnings · '+qa.counts.FAIL+' failed · '+qa.counts.NOT_CHECKED+' not checked · preset: '+esc(qa.preset.label)+'</p>'
        +(qa.true_peak_safety_pass?.applied?'<p><small>'+esc(qa.true_peak_safety_pass.reason)+'</small></p>':'')
        +'<details><summary>All technical checks</summary><div class="ve-table"><table><thead><tr><th>Result</th><th>Check</th><th>Measured</th><th>Expected</th></tr></thead><tbody>'+qa.checks.map(c=>'<tr><td><span class="ve-qa" data-status="'+c.status+'">'+c.status.replace('_',' ')+'</span></td><td>'+esc(c.label)+(c.detail?'<br><small>'+esc(c.detail)+'</small>':'')+'</td><td>'+esc(show(c.measured))+'</td><td>'+esc(show(c.expected))+'</td></tr>').join('')+'</tbody></table></div></details><p><small>'+esc(qa.scope)+'</small></p>';}
    else box.innerHTML='<p>No measurement report is attached to this result.</p>';
    try{localStorage.setItem(storageKey('lexnis.video.quick-result'),JSON.stringify({id:result.id}));}catch{}
  }
  async run(dryRun=false,variants=false){
    const button=this.$('[data-quick-run]'),planButton=this.$('[data-quick-plan]');if(button.disabled)return;button.disabled=planButton.disabled=true;
    try{
      const asset=this.sourceAsset();if(!asset)throw new Error('Upload or select a source video first.');
      const instruction=this.brand.$('[data-instruction]').value.trim()||'Add readable captions, tighten pauses and use subtle zooms.';
      this.brand.brief().instruction=instruction.slice(0,1000);await this.brand.ensureSaved();
      const job=await post('/projects/'+this.editor.projectId+'/quick-edit',{asset_id:asset.id,instruction,
        captions:this.$('[data-quick-captions]').checked,tighten_pauses:this.$('[data-quick-pauses]').checked,
        subtle_zooms:this.$('[data-quick-zooms]').checked,trim_recording_tail:this.$('[data-quick-tail]').checked,
        language:this.$('[data-quick-language]').value,aspect:this.$('[data-quick-aspect]').value,
        delivery:this.$('[data-quick-delivery]').value||'web-youtube',max_punch_in:this.$('[data-quick-punch]').value?Number(this.$('[data-quick-punch]').value):null,
        style:this.$('[data-quick-style]').value,motion_intensity:this.$('[data-quick-motion]').value,platform_profile:this.$('[data-quick-platform]').value,lighting:this.$('[data-quick-lighting]').value,
        background:this.$('[data-quick-background]').value,background_asset_id:this.$('[data-quick-background-image]').value||null,
        canvas_mode:this.$('[data-quick-canvas]').value,dialogue_polish:this.$('[data-quick-voice]').checked,
        cut_policy:this.$('[data-quick-policy]').value,semantic_planner:this.$('[data-quick-semantic]').value,
        graphic_motion:this.$('[data-quick-graphic-motion]').value,
        caption_max_cps:this.$('[data-quick-cps]').value?Number(this.$('[data-quick-cps]').value):null,color_look:this.$('[data-quick-look]').value,
        performance_tier:this.$('[data-quick-tier]').value,dialogue_noise_reduction:this.$('[data-quick-denoise]').checked,
        dialogue_hum_hz:Number(this.$('[data-quick-hum]').value),dialogue_deess:this.$('[data-quick-deess]').checked,
        reference_asset_id:this.$('[data-reference-select]').value||null,reference_preferences:[...this.root.querySelectorAll('[data-reference-property]:checked')].map(n=>n.dataset.referenceProperty),preview_frames:dryRun&&!variants,
        approved_cuts:[...this.approved],caption_corrections:this.corrections,captions_reviewed:this.reviewed,story_roles:this.storyRoles,dry_run:dryRun,plan_variants:variants,
        parent_asset_id:this.result?.source_asset_id===asset.id?this.result.id:null});
      this.editor.studio.watch(job);const started=Date.now();
      while(true){
        const state=await api('/jobs/'+job.id);this.status(state.phase||state.state);
        if(state.state==='completed'){this.pendingResult=state.result;break;}
        if(['failed','cancelled'].includes(state.state))throw new Error(state.error||'Edit cancelled.');
        if(Date.now()-started>1800000)throw new Error('The edit is still processing. Check the production queue.');
        await new Promise(resolve=>setTimeout(resolve,700));
      }
      const result=this.pendingResult;this.pendingResult=null;
      if(result.dry_run){
        this.showPlan(result.edit_report);
        this.directorPreview(result.edit_report,result.preview_frames||[]);
        const box=this.$('[data-quick-variant-plans]');box.innerHTML=variants?'<h3>Choose a plan to render</h3>'+result.variants.map(v=>'<div class="vs-card"><h4>'+esc(v.report.style_profile.label)+'</h4><p>'+v.report.cuts.length+' cuts · '+v.report.zoom_segments+' framing changes · '+v.report.caption_count+' caption cues. '+v.report.style_profile.summary.map(esc).join('; ')+'.</p><button type="button" data-choose-style="'+v.style+'">Use this plan</button></div>').join(''):'';
        box.querySelectorAll('[data-choose-style]').forEach(b=>b.onclick=()=>{this.$('[data-quick-style]').value=b.dataset.chooseStyle;this.status('Style selected. Create edited video when ready.');});
        this.status('Edit plan ready. No full video was rendered. Review the composition stills and decisions, then create the edited video.');return;
      }
      this.showResult(result);
      if(this.result.project_id)this.editor.open(await api('/projects/'+this.result.project_id));
      this.status('Edited video ready. Watch it here, compare with Original, or download the MP4.');
    }catch(error){this.status(error.message);}finally{button.disabled=planButton.disabled=false;}
  }
}
