import {reviewGuideline} from './guideline-review.js';
import {api,post,esc,report} from './video-api.js';
import {GuidedWorkflow,PromptAssistant,objectiveFields} from './creative-workflow.js';
async function shared(path, options={}){
  const response=await fetch('/api/guidelines'+path,options),data=await response.json();
  if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail));
  return data;
}
export class VideoBrandEditor{
  constructor(editor,options={}){
    this.editor=editor;this.doc=null;this.pending=null;
    this.root=document.createElement('section');this.root.className='vs-card';this.root.id='ve-brand-editor';this.root.style.marginTop='18px';
    this.root.innerHTML='<h2>Brand Guidelines</h2><p>Reuse one reviewed guideline across Image, GIF and Video Studio. Original files remain available.</p><div class="vs-row"><button type="button" data-upload>Upload / Replace Guidelines</button><select data-library aria-label="Select existing guidelines"><option value="">Select existing guidelines</option></select><button type="button" data-refresh>Refresh library</button><button type="button" data-view>View Guidelines</button><button type="button" data-kit>Select Existing Brand Kit</button><button type="button" data-remove>Remove Guidelines</button></div><input type="file" data-file accept=".pdf,.docx,.txt,.md,.markdown,.json" hidden><div data-review></div><div data-associated></div><h2 style="margin-top:20px">AI Video Editor</h2><label>Tell AI How to Edit Your Video<textarea data-instruction maxlength="1000" placeholder="Follow the guidelines, improve the introduction and add the approved CTA."></textarea></label><p data-model></p><div class="vs-row"><button type="button" data-analyze>Analyze Video</button><button type="button" data-captions>Import SRT captions</button><input data-srt type="file" accept=".srt" hidden><button type="button" data-ai disabled>Edit with AI</button><button type="button" data-polish>Auto Polish / Apply Guidelines</button><button type="button" data-compliance>Check Against Guidelines</button><button type="button" data-repair>Fix Issues (preview)</button></div><div data-plan></div><div data-preview></div><div class="vs-row" style="margin-top:14px"><button type="button" data-undo>Undo</button><button type="button" data-redo>Redo</button><button type="button" data-history>Revision history</button></div><div data-history-list></div><div data-compliance-result></div><p data-status role="status"></p>';
    if(options.generation)this.root.id='vg-brand-guidelines';
    (options.host||editor.root).append(this.root);
    this.options=options;
    // Keep the shared, reviewed upload controls visible in both generation and editing.
    const children=[...this.root.children],boundary=children.findIndex(el=>el.tagName==='H2'&&el.textContent==='AI Video Editor');
    this.guidelineControls=document.createElement('div');this.guidelineControls.dataset.guidelineControls='';
    this.editControls=document.createElement('div');this.editControls.dataset.editControls='';
    children.forEach((node,i)=>(i<boundary?this.guidelineControls:this.editControls).append(node));
    this.root.append(this.guidelineControls,this.editControls);
    if(options.generation){this.editControls.hidden=true;this.root.append(this.root.querySelector('[data-status]'));this.root.querySelectorAll('button').forEach(b=>b.type='button');}
    this.$=s=>this.root.querySelector(s);
    const bind=(selector,fn)=>this.$(selector).onclick=()=>this.run(fn);
    bind('[data-upload]',()=>this.$('[data-file]').click());
    this.$('[data-file]').onchange=()=>this.run(async()=>{
      const file=this.$('[data-file]').files[0];if(!file)return;
      const form=new FormData();form.append('file',file);this.doc=await shared('',{method:'POST',body:form});await this.refresh();this.review();
      this.$('[data-file]').value='';
    });
    bind('[data-refresh]',()=>this.refresh());
    bind('[data-view]',async()=>{const key=this.doc?.id||this.editor.project.guideline_id||this.$('[data-library]').value;if(!key)throw new Error('Upload or select a guideline first');this.doc=await shared('/'+key);this.review();});
    this.$('[data-library]').onchange=()=>this.run(async()=>{const key=this.$('[data-library]').value;if(key){this.doc=await shared('/'+key);this.review();}});
    bind('[data-kit]',async()=>{
      await editor.loadBrands();const brands=editor.brands||[];
      if(!brands.length)throw new Error('Create a brand kit in Image & GIF Studio first.');
      const panel=this.$('[data-review]');panel.innerHTML='<label>Brand kit<select data-kit-id>'+brands.map(b=>'<option value="'+esc(b.id)+'">'+esc(b.brand_name)+'</option>').join('')+'</select></label><button type="button" data-import-kit>Review brand kit rules</button>';
      panel.querySelector('button').onclick=()=>this.run(async()=>{this.doc=await shared('/from-brand/'+panel.querySelector('select').value,{method:'POST'});await this.refresh();this.review();});
    });
    bind('[data-remove]',async()=>{await this.ensureSaved();const saved=await post('/projects/'+editor.projectId+'/guidelines',{guideline_id:null});editor.open(saved);this.doc=null;this.$('[data-review]').innerHTML='';this.sync();});
    bind('[data-analyze]',()=>this.analyze(false));
    bind('[data-captions]',()=>this.$('[data-srt]').click());
    this.$('[data-srt]').onchange=()=>this.run(async()=>{const file=this.$('[data-srt]').files[0];if(!file)return;await this.ensureSaved();const form=new FormData();form.append('file',file);const saved=await api('/projects/'+editor.projectId+'/captions/import',{method:'POST',body:form});editor.open(saved);this.$('[data-srt]').value='';});
    bind('[data-ai]',()=>this.plan('local_ai'));
    bind('[data-polish]',()=>this.plan('rule_engine'));
    bind('[data-repair]',()=>this.plan('rule_engine',true));
    bind('[data-compliance]',()=>this.compliance());
    for(const key of ['undo','redo'])bind('[data-'+key+']',async()=>{if(!editor.projectId)throw new Error('Save a project first');const saved=await post('/projects/'+editor.projectId+'/'+key,{});editor.open(saved);this.pending=null;this.$('[data-plan]').innerHTML='';});
    bind('[data-history]',async()=>{if(!editor.projectId)return;const result=await api('/projects/'+editor.projectId+'/revisions');this.$('[data-history-list]').innerHTML='<h3>Saved revisions</h3>'+result.revisions.map(r=>'<p>'+esc(r.label||r.instruction||r.actor)+' · '+esc(new Date(r.created_at*1000).toLocaleString())+'</p>').join('');});
    if(!options.generation)this.guidedEditor();
    this.run(async()=>{await this.refresh();if(!options.generation){const cap=await api('/editor/capabilities');this.$('[data-ai]').disabled=!cap.ai.available;this.$('[data-model]').textContent=cap.ai.reason;}this.sync();});
  }
  guidedEditor(){
    const e=this.editor,root=e.root,goal=document.createElement('div'),assist=document.createElement('div');
    this.objective=objectiveFields(goal,e.project.creative_context,values=>{e.project.creative_context=values;e.changed();});
    const instruction=this.$('[data-instruction]').closest('label');goal.append(instruction);
    this.assistant=new PromptAssistant(assist,instruction.querySelector('textarea'),()=>({...this.objective.value(),task:'video-edit',guideline_id:e.project.guideline_id||null,output_format:root.querySelector('#ve-format').value}));
    const row=root.querySelector('#ve-name').closest('.vs-row'),media=root.querySelector('.vs-editor>aside'),preview=root.querySelector('#ve-preview').closest('.vs-card'),props=root.querySelector('.vs-properties-panel'),timeline=root.querySelector('.vs-timeline'),exports=root.querySelector('#ve-export').closest('.vs-card');
    const settings=document.createElement('div');settings.append(root.querySelector('#ve-canvas').closest('label'),root.querySelector('#ve-fps').closest('label'));
    const advanced=document.createElement('details');advanced.innerHTML='<summary>Advanced manual clip properties</summary>';advanced.append(props);settings.append(advanced);
    this.workflow=new GuidedWorkflow(this.root,'video-edit',[
      {title:'Choose footage',nodes:[row,media],description:'Import your video, images or audio. Originals remain unchanged.'},
      {title:'Brand guidelines',nodes:[this.guidelineControls]},
      {title:'Creative objective',nodes:[goal]},
      {title:'Prompt assistant',nodes:[assist]},
      {title:'Settings',nodes:[settings]},
      {title:'Analyze & edit',nodes:[this.editControls],description:'Analyze footage, review a proposed edit, then apply or reject it. Auto Polish works without an AI model.'},
      {title:'Preview & improve',nodes:[preview,timeline],description:'Render the full composition, adjust the timeline, and check brand compliance before export.'},
      {title:'Export',nodes:[exports]}
    ]);
    root.querySelector('.vs-editor')?.remove();
  }
  async run(fn){this.$('[data-status]').textContent='Working…';try{await fn();this.$('[data-status]').textContent='Ready.';}catch(error){this.$('[data-status]').textContent=error.message;report(error);}}
  async ensureSaved(){if(!this.editor.projectId||this.editor.dirty)await this.editor.save();}
  sync(){this.$('[data-associated]').textContent=this.editor.project.guideline_id?'Applied guideline v'+this.editor.project.guideline_version+' · '+(this.editor.project.brand_rules?.brand_name||'Reviewed brand'):'No guideline applied. Upload or select a document to begin.';this.objective?.set(this.editor.project.creative_context);}
  async refresh(){const list=await shared('');const select=this.$('[data-library]');select.innerHTML='<option value="">Select existing guidelines</option>'+list.map(d=>'<option value="'+d.id+'">'+esc(d.rules.brand_name||d.filename)+' · v'+d.version+(d.confirmed?' · reviewed':' · needs review')+'</option>').join('');select.value=this.doc?.id||this.editor.project.guideline_id||'';}
  review(){
    const doc=this.doc;
    reviewGuideline(this.$('[data-review]'),doc,this.editor.studio.assets.filter(a=>a.kind==='image'),rules=>this.run(async()=>{
      this.doc=await shared('/'+doc.id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_version:doc.version,rules,confirmed:true})});
      await this.ensureSaved();const saved=await post('/projects/'+this.editor.projectId+'/guidelines',{guideline_id:doc.id});this.editor.open(saved);await this.refresh();this.review();this.sync();
    }));
  }
  async plan(engine,repair_only=false){
    await this.ensureSaved();if(engine==='local_ai')await this.analyze(true);const instruction=this.$('[data-instruction]').value.trim()||'Apply the reviewed brand guidelines with professional, subtle styling.';
    this.pending=await post('/projects/'+this.editor.projectId+'/brand-edit/preview',{instruction,engine,repair_only});
    const pending=this.pending,root=this.$('[data-plan]');
    root.innerHTML='<h3>Proposed changes · '+(engine==='local_ai'?'Local AI':'Deterministic rules')+'</h3><ol>'+pending.plan.operations.map(op=>'<li>'+esc(op.reason)+' · '+esc(op.operation_type.replaceAll('_',' ').toLowerCase())+'</li>').join('')+'</ol><p>'+pending.plan.warnings.concat(pending.plan.unfulfilled_requests,pending.compliance.findings.filter(f=>f.state==='FAIL'||f.state==='WARNING').map(f=>f.state+': '+f.message)).map(esc).join('<br>')+'</p>'+(pending.conflicts.length?'<label><input type="checkbox" data-ack> '+esc(pending.conflicts.join(' '))+' Acknowledge this conflict.</label>':'')+'<div class="vs-row"><button type="button" data-preview-plan>Render proposed preview</button><button type="button" data-apply-plan class="primary">Apply changes</button><button type="button" data-reject-plan>Reject</button></div>';
    root.querySelector('[data-reject-plan]').onclick=()=>this.run(async()=>{await api('/projects/'+this.editor.projectId+'/brand-edit/plans/'+pending.id,{method:'DELETE'});this.pending=null;root.innerHTML='Proposal rejected. The saved timeline is unchanged.';this.$('[data-preview]').innerHTML='';});
    root.querySelector('[data-preview-plan]').onclick=()=>this.run(async()=>{const job=await post('/export',{project:pending.proposed_project,container:'mp4',preview:true,audio:true});this.editor.studio.watch(job,asset=>this.$('[data-preview]').innerHTML='<video controls style="max-width:100%;max-height:360px" src="'+esc(asset.url)+'"></video>');});
    root.querySelector('[data-apply-plan]').onclick=()=>this.run(async()=>{if(this.editor.dirty)throw new Error('Manual timeline changes were made after the preview. Save and generate a fresh proposal before applying.');const saved=await post('/projects/'+this.editor.projectId+'/brand-edit/apply',{plan_id:pending.id,confirm_conflicts:!!root.querySelector('[data-ack]')?.checked});this.editor.open(saved);this.pending=null;root.innerHTML='Edits applied. Preview or export using the timeline controls.';await this.compliance();});
  }
  async analyze(wait){
    const assets=[...new Set(this.editor.project.clips.filter(c=>c.kind==='video').map(c=>c.asset_id))].filter(id=>this.editor.studio.assets.some(a=>a.id===id&&a.kind==='video')).slice(0,6);
    if(!assets.length){this.$('[data-status]').textContent='Static sources use their validated dimensions; no video scene analysis is needed.';return;}
    for(const id of assets){
      const job=await post('/assets/'+id+'/analyze',{});this.editor.studio.watch(job,result=>{this.$('[data-status]').textContent='Footage analysis complete: '+(result.shots?.length||0)+' measured shots. No semantic content or speech has been invented.';});
      if(wait){
        const started=Date.now();
        while(true){
          const state=await api('/jobs/'+job.id);this.$('[data-status]').textContent='Analyzing footage: '+state.state;
          if(state.state==='completed')break;
          if(['failed','cancelled'].includes(state.state))throw new Error(state.error||'Analysis was cancelled');
          if(Date.now()-started>120000)throw new Error('Analysis is still queued or running. Retry after the job finishes.');
          await new Promise(resolve=>setTimeout(resolve,500));
        }
      }
    }
  }
  async compliance(){await this.ensureSaved();const result=await api('/projects/'+this.editor.projectId+'/brand-compliance');this.$('[data-compliance-result]').innerHTML='<h3>Brand compliance</h3><p>'+esc(result.scope)+'</p>'+result.findings.map(f=>'<p><strong>'+esc(f.state)+'</strong> — '+esc(f.message)+'</p>').join('');}
}
