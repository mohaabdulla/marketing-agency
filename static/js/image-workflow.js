import {GuidedWorkflow,PromptAssistant,objectiveFields,suggestPrompt} from './creative-workflow.js';
import {storageKey} from './public-session.js';

// Adapt the existing Image/GIF controls. Their listeners and backend remain intact.
export function mountImageWorkflow(){
  const root=document.getElementById('image-workspace'),prompt=document.getElementById('prompt-input');
  if(!prompt||root.dataset.guided)return;root.dataset.guided='true';
  const guidelines=document.getElementById('guidelines-card'),identity=root.querySelector('section'),objective=prompt.closest('section'),visual=document.getElementById('visual-assets-section'),results=document.getElementById('results-section');
  const chooser=document.createElement('div');chooser.innerHTML='<label>Create<select id="creative-output-kind"><option value="image">Image campaign + companion</option><option value="gif">Animated GIF + matching static cards</option></select></label><p>Both choices use the existing social kit renderer. GIFs animate the completed card and preserve your source image.</p>';
  chooser.append(document.getElementById('post-type-grid'));
  const assistantHost=document.createElement('div'),goal=document.createElement('div');
  let draft={};try{draft=JSON.parse(localStorage.getItem(storageKey('lexnis.image.workflow'))||'{}');}catch{}
  const fields=objectiveFields(goal,draft.objective,()=>persist());objective.append(goal);
  const task=chooser.querySelector('#creative-output-kind');task.value=draft.task||'image';
  let guideline=null;
  window.addEventListener('lexnis:guideline-selected',event=>{guideline=event.detail;persist();});
  // Newly uploaded shared documents and existing selected documents use the same ID.
  window.addEventListener('lexnis:image-guideline',event=>{guideline=event.detail;persist();});
  window.addEventListener('lexnis:guideline-cleared',()=>{guideline=null;persist();});
  if(draft.guideline_id)fetch('/api/guidelines/'+draft.guideline_id).then(r=>r.ok?r.json():null).then(doc=>{if(doc){guideline=doc;window.dispatchEvent(new CustomEvent('lexnis:guideline-selected',{detail:doc}));}}).catch(()=>{});
  const assistant=new PromptAssistant(assistantHost,prompt,()=>{
    const values=fields.value(),context={...values,task:task.value,output_format:task.value==='gif'?'Looping GIF + JPEG kit':document.getElementById('format-select').value};
    if(guideline?.confirmed)context.guideline_id=guideline.id;
    else if(window.brandProfile){const bp=window.brandProfile;context.brand_rules={brand_name:bp.brand_name||'',primary_colors:[bp.primary_color||bp.primary_hex].filter(x=>/^#[0-9a-f]{6}$/i.test(x||'')),font_preferences:Array.isArray(bp.font_preferences)?bp.font_preferences:[],tone_of_voice:bp.brand_tone||''};}
    return context;
  });
  const settings=document.createElement('div');settings.append(visual,document.getElementById('format-select').parentElement,document.getElementById('image-model-select').parentElement);
  const launch=document.createElement('div');for(const id of ['visual-engine-status-bar','status-bar','error-banner','quick-swap-result-box']){const node=document.getElementById(id);if(node)launch.append(node);}
  const exportArea=document.createElement('div');exportArea.innerHTML='<p>Generate a kit to download JPEG cards, the looping GIF, MP4 motion where available, or the complete ZIP. Use the format-specific download controls on the previews.</p>';
  // Move the existing main download buttons, preserving their wired handlers.
  for(const id of ['download-en-main-btn','download-ar-main-btn']){const node=document.getElementById(id);if(node)exportArea.append(node);}
  const host=guidelines.parentElement;
  const flow=new GuidedWorkflow(host,'image-gif',[
    {title:'Choose what to create',nodes:[chooser]},
    {title:'Brand guidelines',nodes:[identity,guidelines]},
    {title:'Creative objective',nodes:[objective]},
    {title:'Prompt assistant',nodes:[assistantHost]},
    {title:'Settings & media',nodes:[settings]},
    {title:'Generate',nodes:[launch]},
    {title:'Preview & improve',nodes:[results]},
    {title:'Export',nodes:[exportArea]}
  ]);
  const enhance=document.getElementById('enhance-prompt-btn');
  window.lexnisImageAssist=async(raw,style='')=>{
    const data=await suggestPrompt({...assistant.context(),prompt:raw,style:style||fields.value().style,action:'improve',engine:assistant.$('[data-engine]').value,max_chars:6000});
    return {enhanced_prompt:data.prompt,ai_used:data.ai_used,engine:data.engine,detected_brand:guideline?.rules?.brand_name||window.brandProfile?.brand_name||'',improvements:[data.notice,...data.missing_details],target_audience:fields.value().audience,visual_art_direction:fields.value().style};
  };
  enhance?.addEventListener('click',event=>{event.preventDefault();event.stopImmediatePropagation();flow.go(3);assistant.suggest('improve');},true);
  if(draft.prompt&&!prompt.value)prompt.value=draft.prompt;
  function persist(){try{localStorage.setItem(storageKey('lexnis.image.workflow'),JSON.stringify({prompt:prompt.value,task:task.value,objective:fields.value(),guideline_id:guideline?.id||null}));}catch{}}
  prompt.addEventListener('input',persist);task.onchange=persist;
  document.getElementById('guidelines-remove-btn')?.addEventListener('click',()=>{guideline=null;persist();});
  new MutationObserver(()=>{if(!results.classList.contains('hidden'))flow.reveal(results);}).observe(results,{attributes:true,attributeFilter:['class']});
}
