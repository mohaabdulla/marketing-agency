import {api,post,esc,report} from './video-api.js';
import {GuidedWorkflow,PromptAssistant,objectiveFields} from './creative-workflow.js';
import {storageKey} from './public-session.js';
import {GenerationGuidelines} from './video-generation-guidelines.js';

export const generationMarkup=`<section id="vs-generate" role="tabpanel" aria-labelledby="vs-tab-generate"><div class="vs-grid"><form class="vs-card" id="vg-form"><h2>From idea to motion</h2><div class="vs-pair"><label>Generation mode<select id="vg-mode"><option value="text-to-video">AI Text-to-Video</option><option value="image-to-video">AI Image-to-Video</option><option value="image-animation">Image Animation · CPU</option></select></label><label>Local model<select id="vg-model"></select></label></div><div id="vg-model-info" class="vs-note"></div><label>Scene prompt<textarea id="vg-prompt" maxlength="2000" placeholder="A cinematic industrial factory, robotic arms moving with precision, realistic materials…"></textarea></label><label>Negative prompt<textarea id="vg-negative" maxlength="1000" style="min-height:65px" placeholder="Artifacts, flickering, distorted shapes"></textarea></label><label>Camera motion description<input id="vg-camera" maxlength="250" placeholder="Slow forward dolly, steady camera"></label><div id="vg-image-fields" hidden><label>Starting image<select id="vg-image"><option value="">Choose from media library</option></select></label><button type="button" id="vg-upload">Upload a starting image</button></div><div id="vg-animation-fields" hidden><div class="vs-pair"><label>Duration (seconds)<input id="vg-duration" type="number" value="4" min="1" max="60" step=".5"></label><label>Motion<select id="vg-motion"><option value="zoom-in">Ken Burns · Zoom in</option><option value="zoom-out">Ken Burns - Zoom out</option><option value="pan">Gentle pan</option><option value="still">Still with fades</option><option value="auto">Auto · varied per scene</option></select></label></div><label>More scenes (optional · Ctrl/Cmd-click to choose several)<select id="vg-more" multiple size="4"></select></label><div class="vs-pair"><label>Logo (optional)<select id="vg-logo"><option value="">Guideline logo or none</option></select></label><label>Music you are licensed to use (optional)<select id="vg-music"><option value="">No music</option></select></label></div><p><small>Several images become scenes with crossfades. The key message from the brief opens the video and the call to action closes it, placed away from faces and the platform interface. Music is never added for you.</small></p></div><div class="vs-pair"><label>Export aspect<select id="vg-aspect"><option>16:9</option><option>9:16</option><option>1:1</option><option>4:5</option></select></label><label>Export short edge<select id="vg-resolution"><option value="720">720 px</option><option value="1080">1080 px</option></select></label><label>Seed<input id="vg-seed" type="number" min="0" max="2147483647" value="42"></label><label>Quality<select id="vg-quality"><option value="standard">Standard · 50 steps</option><option value="draft">Draft · 20 steps</option></select></label></div><p><small>AI clips generate at the native dimensions shown above. Aspect changes use padding and resizing afterward.</small></p><button id="vg-generate" class="primary" type="submit" disabled>Generate clip</button></form><div class="vs-card"><h2>Your motion canvas</h2><div id="vg-preview" class="vs-preview"><div class="vs-empty">Your next story starts here.<br><small>Upload an image for a CPU animation, or install a local AI model.</small></div></div><div id="vg-result" class="vs-job-result"></div><div class="vs-note">AI generation uses diffusion models. Image Animation applies camera motion to your existing image and preserves its content, including employee photos.</div><h3 style="margin-top:25px">Production queue</h3><div id="vs-jobs"><p><small>No active jobs.</small></p></div></div></div></section>`;

export class VideoGenerator{
  constructor(studio){
    this.studio=studio;this.$=s=>studio.$(s);this.models=[];
    this.setupGeneration();
    this.$('#vg-mode').onchange=()=>this.updateGenerate();
    this.$('#vg-model').onchange=()=>this.updateGenerate(false);
    this.$('#vg-form').onsubmit=async e=>{e.preventDefault();if(this.generating)return;this.generating=true;this.updateGenerate(false);try{const mode=this.$('#vg-mode').value,context=this.objective.value(),brand=this.guidelines.selection;const body={mode,model:this.$('#vg-model').value||'cogvideox-2b',prompt:this.$('#vg-prompt').value,negative_prompt:this.$('#vg-negative').value,camera:this.$('#vg-camera').value,asset_id:this.$('#vg-image').value||null,duration:+this.$('#vg-duration').value,aspect:this.$('#vg-aspect').value,resolution:+this.$('#vg-resolution').value,seed:+this.$('#vg-seed').value,quality:this.$('#vg-quality').value,motion:this.$('#vg-motion').value,...(mode==='image-animation'?{asset_ids:[...this.$('#vg-more').selectedOptions].map(o=>o.value).filter(v=>v&&v!==this.$('#vg-image').value).slice(0,7),logo_asset_id:this.$('#vg-logo').value||null,music_asset_id:this.$('#vg-music').value||null}:{}),guideline_id:brand?.guideline_id||null,guideline_version:brand?.guideline_version||null,objective:context.objective,audience:context.audience,key_message:context.key_message,style:context.style,cta:context.cta,platform:context.platform,language:context.language};const job=await post('/generate',body);this.watch(job);report(new Error(''));}catch(error){this.generating=false;this.updateGenerate(false);report(error);}};
  }
  refreshAssets(){const selected=this.$('#vg-image').value;this.$('#vg-image').innerHTML='<option value="">Choose a still image</option>'+this.studio.assets.filter(a=>a.kind==='image').map(a=>`<option value="${a.id}">${esc(a.name)}</option>`).join('');this.$('#vg-image').value=selected;{const images=this.studio.assets.filter(a=>a.kind==='image'),option=a=>`<option value="${a.id}">${esc(a.name)}</option>`;const more=new Set([...this.$('#vg-more').selectedOptions].map(o=>o.value)),logo=this.$('#vg-logo').value,music=this.$('#vg-music').value;this.$('#vg-more').innerHTML=images.map(option).join('');for(const o of this.$('#vg-more').options)o.selected=more.has(o.value);this.$('#vg-logo').innerHTML='<option value="">Guideline logo or none</option>'+images.map(option).join('');this.$('#vg-logo').value=logo;this.$('#vg-music').innerHTML='<option value="">No music</option>'+this.studio.assets.filter(a=>a.kind==='audio').map(option).join('');this.$('#vg-music').value=music;}}
  async load(){
    await this.guidelines.ready;
    await this.refreshModels();
    this.restoreGeneration(true);this.updateGenerate(false);
    try{const id=localStorage.getItem(storageKey('lexnis.video.last-result')),asset=this.studio.assets.find(a=>a.id===id);if(asset)this.showResult(asset);}catch{}
  }
  async refreshModels(){
    const selected=this.$('#vg-model').value;
    this.models=await api('/models');
    this.$('#vg-model').innerHTML=this.models.map(m=>`<option value="${m.id}">${esc(m.id)}${m.available?'':' - unavailable'}</option>`).join('');
    const mode=this.$('#vg-mode').value;
    const preferred=this.models.find(m=>m.id===selected&&m.available&&m.modes.includes(mode))||this.models.find(m=>m.available&&m.modes.includes(mode))||this.models.find(m=>m.modes.includes(mode));
    if(preferred)this.$('#vg-model').value=preferred.id;
    this.updateGenerate(false);
  }
  watch(job){this.jobId=job.id;this.generating=true;this.updateGenerate(false);this.studio.watch(job,asset=>this.showResult(asset));}
  jobFinished(id){if(id===this.jobId){this.generating=false;this.updateGenerate(false);}}
  setupGeneration(){
    const form=this.$('#vg-form'),brandHost=document.createElement('div'),goal=document.createElement('div'),assistantHost=document.createElement('div');
    const grid=form.parentElement,oldCanvas=this.$('#vg-preview').parentElement,intro=form.querySelector('h2'),nativeNote=[...form.children].find(el=>el.tagName==='P');
    this.guidelines=new GenerationGuidelines(brandHost,()=>this.studio.assets);
    this.objective=objectiveFields(goal,{},()=>this.persistGeneration());
    const scenePrompt=this.$('#vg-prompt');goal.append(scenePrompt.closest('label'));
    this.promptAssistant=new PromptAssistant(assistantHost,scenePrompt,()=>({...this.objective.value(),task:'video-generation',guideline_id:this.guidelines.selection?.guideline_id||null,output_format:'MP4 '+this.$('#vg-aspect').value+' '+this.$('#vg-mode').value}));
    const mode=this.$('#vg-mode').closest('.vs-pair'),modelInfo=this.$('#vg-model-info'),image=this.$('#vg-image-fields'),animation=this.$('#vg-animation-fields'),settings=this.$('#vg-aspect').closest('.vs-pair');
    const advanced=document.createElement('details');advanced.innerHTML='<summary>Advanced generation settings</summary>';advanced.append(this.$('#vg-negative').closest('label'),this.$('#vg-camera').closest('label'),this.$('#vg-seed').closest('label'),this.$('#vg-quality').closest('label'));
    const action=this.$('#vg-generate'),preview=this.$('#vg-preview'),result=this.$('#vg-result');
    const readiness=document.createElement('p');readiness.id='vg-readiness';readiness.setAttribute('role','status');
    action.setAttribute('aria-describedby','vg-readiness');
    const recovery=document.createElement('div');recovery.className='vs-row';recovery.innerHTML='<button type="button" id="vg-refresh-models">Check model availability</button><button type="button" id="vg-use-animation">Use Image Animation (no AI model)</button>';
    recovery.querySelector('#vg-refresh-models').onclick=async event=>{const button=event.currentTarget;button.disabled=true;try{await this.refreshModels();}catch(error){readiness.textContent='Could not check model availability: '+error.message;}finally{button.disabled=false;}};
    recovery.querySelector('#vg-use-animation').onclick=()=>{this.$('#vg-mode').value='image-animation';this.updateGenerate();this.persistGeneration();this.generationFlow.reveal(this.$('#vg-image-fields'));};

    const previewPanel=document.createElement('div');previewPanel.append(preview);
    for(const note of oldCanvas.querySelectorAll('.vs-note'))previewPanel.append(note);
    if(nativeNote)advanced.append(nativeNote);
    this.generationFlow=new GuidedWorkflow(form,'video-generate',[
      {title:'Choose what to create',nodes:[mode,modelInfo,image],description:'Local AI clips require an installed compatible model. Image Animation is a working CPU option.'},
      {title:'Brand guidelines',nodes:[brandHost],description:'Upload or select reviewed guidelines. This selection belongs to the generation draft.'},
      {title:'Creative objective',nodes:[goal]},
      {title:'Prompt assistant',nodes:[assistantHost]},
      {title:'Settings',nodes:[settings,animation,advanced]},
      {title:'Generate',nodes:[readiness,action,recovery],description:'Real progress appears in the production queue above. CPU motion uses the selected motion setting; prompt text is retained as context.'},
      {title:'Preview & improve',nodes:[previewPanel],description:'Preview the output, or open its saved brand-aware timeline for revisions.'},
      {title:'Export',nodes:[result],description:'Download the completed MP4. Dimensions and file size appear after processing.'}
    ]);
    oldCanvas.remove();intro.remove();grid.classList.remove('vs-grid');form.classList.remove('vs-card');
    form.querySelectorAll('button:not([type])').forEach(b=>b.type='button');
    this.generationEdited=new Set();this.restoreGeneration();this.updateGenerate(false);
    const remember=event=>{if(event.target.id)this.generationEdited.add(event.target.id);this.persistGeneration();};form.addEventListener('input',remember);form.addEventListener('change',remember);
  }
  persistGeneration(){try{const fields=Object.fromEntries([...this.$('#vg-form').querySelectorAll('[id^=vg-]')].filter(el=>['INPUT','TEXTAREA','SELECT'].includes(el.tagName)&&el.type!=='file').map(el=>[el.id,el.value]));localStorage.setItem(storageKey('lexnis.video.generation'),JSON.stringify({fields,objective:this.objective.value()}));}catch{}}
  restoreGeneration(dynamicOnly=false){try{const draft=this.savedGenerationDraft??JSON.parse(localStorage.getItem(storageKey('lexnis.video.generation'))||'null');this.savedGenerationDraft=draft;if(draft){for(const [key,value] of Object.entries(draft.fields||{})){if(dynamicOnly&&!['vg-model','vg-image'].includes(key))continue;const el=this.$('#'+key);if(el&&(!dynamicOnly||!this.generationEdited.has(key)))el.value=value;}if(!dynamicOnly)this.objective.set(draft.objective);}}catch{}}
  updateGenerate(reset=true){const mode=this.$('#vg-mode').value,animation=mode==='image-animation';this.$('#vg-image-fields').hidden=mode==='text-to-video';this.$('#vg-animation-fields').hidden=!animation;for(const key of ['model','negative','camera','seed','quality'])this.$(`#vg-${key}`).disabled=animation;for(const option of this.$('#vg-model').options){option.hidden=!this.models.find(m=>m.id===option.value)?.modes.includes(mode)&&!animation;}if(!animation&&(reset||!this.models.some(m=>m.id===this.$('#vg-model').value&&m.modes.includes(mode)))){const model=this.models.find(m=>m.available&&m.modes.includes(mode))||this.models.find(m=>m.modes.includes(mode));if(model)this.$('#vg-model').value=model.id;}
    const model=this.models.find(m=>m.id===this.$('#vg-model').value),unavailable=!animation&&(!model?.available||!model?.modes.includes(mode));
    this.$('#vg-readiness').textContent=this.generating?'Generation is running. Follow its progress in Generation jobs.':animation?'Ready for image animation. This animates your supplied images without an AI model.':unavailable?'AI generation is unavailable: '+(model?.reasons?.join('; ')||'No compatible model is ready')+'. Install a compatible model, then check availability, or choose Image Animation.':'Ready to generate locally. Loading and inference can take several minutes.';
    this.$('#vg-use-animation').hidden=animation||!unavailable;
    this.$('#vg-generate').title=unavailable?this.$('#vg-readiness').textContent:'';
    this.$('#vg-generate').disabled=!!this.generating||(!animation&&(!model?.available||!model?.modes.includes(mode)));this.$('#vg-generate').textContent=animation?'Animate image · CPU':'Generate AI clip';this.$('#vg-model-info').textContent=animation?'Deterministic image animation: Ken Burns / pan / fades. No GPU or AI model required.':model?`${model.width} × ${model.height} native · ${model.frames} frames / ${model.fps} fps · ${(model.frames/model.fps).toFixed(3)}s · ${model.license}. ${model.note} ${model.reasons.join('; ')}. Real inference ${model.verified?'smoke-test recorded':'not verified on this installation'}.`:'No compatible model registered';}
  showGenerationQA(asset){
    const box=document.createElement('div'),qa=asset.qa_report;
    box.id='vg-quality-report';
    if(qa){
      const status=['PASS','WARNING','FAIL'].includes(qa.overall)?qa.overall:'NOT_CHECKED';
      const measurement=value=>esc(value===null||value===undefined?'Not measured':typeof value==='object'?JSON.stringify(value):String(value));
      box.innerHTML='<h3>Export quality</h3><p><span class="ve-qa" data-status="'+status+'">'+status+'</span> '+Number(qa.counts.PASS||0)+' passed | '+Number(qa.counts.WARNING||0)+' warnings | '+Number(qa.counts.FAIL||0)+' failed</p>'
        +'<details><summary>Inspect measured checks</summary>'+qa.checks.map(c=>'<p><strong>'+esc(c.status)+' | '+esc(c.label)+'</strong>'+'<br><small>Measured: '+measurement(c.measured)+(c.expected!==undefined?' | Expected: '+measurement(c.expected):'')+'</small>'+(c.detail?'<br><small>'+esc(c.detail)+'</small>':'')+'</p>').join('')+'</details><p><small>'+esc(qa.scope)+'</small></p>';
    }else box.textContent='This result has no measured quality report. Review the video before delivery.';
    this.$('#vg-result').append(box);
    const link=this.$('#vg-result a');
    if(link&&qa?.overall==='FAIL'){link.textContent='Download draft video';link.download='generated-DRAFT.mp4';}
  }
  showResult(asset){if(asset.kind!=='video')return;try{localStorage.setItem(storageKey('lexnis.video.last-result'),asset.id);}catch{}this.$('#vg-preview').innerHTML=`<video controls src="${esc(asset.url)}" preload="metadata"></video>`;this.$('#vg-result').innerHTML=`<p><small>Encoded: ${asset.width}×${asset.height} · ${asset.fps.toFixed(2)} fps · ${asset.duration.toFixed(2)} seconds</small></p><div class="vs-row"><a class="vs-button primary" href="/api/video/download/${asset.id}">Download video</a><button id="vg-add-result">Add to Editor</button></div>`;this.$('#vg-add-result').onclick=async()=>{try{const editor=this.studio.ensureEditor();if(asset.project_id){if(editor.dirty&&!confirm('Open this generated project? Save your existing timeline first to keep it.'))return;editor.open(await api('/projects/'+asset.project_id));}else editor.add(asset);this.studio.showTab('editor');}catch(error){report(error);}};const info=document.createElement('p');info.className='flow-export-info';info.textContent='MP4 - '+asset.width+'x'+asset.height+' - '+((asset.size||0)/1024**2).toFixed(2)+' MB'+(asset.guideline_id?' - reviewed brand v'+asset.guideline_version:'');this.$('#vg-result').append(info);for(const warning of asset.brand_warnings||[]){const note=document.createElement('p');note.textContent=warning;this.$('#vg-result').append(note);}this.showGenerationQA(asset);this.generationFlow.reveal(this.$('#vg-preview'));}
}
