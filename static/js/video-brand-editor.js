import {api,post,esc,report} from './video-api.js';
async function shared(path, options={}){
  const response=await fetch('/api/guidelines'+path,options),data=await response.json();
  if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail));
  return data;
}
export class VideoBrandEditor{
  constructor(editor){
    this.editor=editor;this.doc=null;this.pending=null;
    this.root=document.createElement('section');this.root.className='vs-card';this.root.id='ve-brand-editor';this.root.style.marginTop='18px';
    this.root.innerHTML='<h2>Brand Guidelines</h2><p>Reuse one reviewed guideline across Image, GIF and Video Studio. Original files remain available.</p><div class="vs-row"><button data-upload>Upload / Replace Guidelines</button><select data-library aria-label="Select existing guidelines"><option value="">Select existing guidelines</option></select><button data-refresh>Refresh library</button><button data-kit>Select Existing Brand Kit</button><button data-remove>Remove Guidelines</button></div><input type="file" data-file accept=".pdf,.docx,.txt,.md,.markdown,.json" hidden><div data-review></div><div data-associated></div><h2 style="margin-top:20px">AI Video Editor</h2><label>Tell AI How to Edit Your Video<textarea data-instruction maxlength="1000" placeholder="Follow the guidelines, improve the introduction and add the approved CTA."></textarea></label><p data-model></p><div class="vs-row"><button data-analyze>Analyze Video</button><button data-captions>Import SRT captions</button><input data-srt type="file" accept=".srt" hidden><button data-ai disabled>Edit with AI</button><button data-polish>Auto Polish / Apply Guidelines</button><button data-compliance>Check Against Guidelines</button><button data-repair>Fix Issues (preview)</button></div><div data-plan></div><div data-preview></div><div class="vs-row" style="margin-top:14px"><button data-undo>Undo</button><button data-redo>Redo</button><button data-history>Revision history</button></div><div data-history-list></div><div data-compliance-result></div><p data-status role="status"></p>';
    editor.root.append(this.root);
    this.$=s=>this.root.querySelector(s);
    const bind=(selector,fn)=>this.$(selector).onclick=()=>this.run(fn);
    bind('[data-upload]',()=>this.$('[data-file]').click());
    this.$('[data-file]').onchange=()=>this.run(async()=>{
      const file=this.$('[data-file]').files[0];if(!file)return;
      const form=new FormData();form.append('file',file);this.doc=await shared('',{method:'POST',body:form});await this.refresh();this.review();
      this.$('[data-file]').value='';
    });
    bind('[data-refresh]',()=>this.refresh());
    this.$('[data-library]').onchange=()=>this.run(async()=>{const key=this.$('[data-library]').value;if(key){this.doc=await shared('/'+key);this.review();}});
    bind('[data-kit]',async()=>{
      await editor.loadBrands();const brands=editor.brands||[];
      if(!brands.length)throw new Error('Create a brand kit in Image & GIF Studio first.');
      const panel=this.$('[data-review]');panel.innerHTML='<label>Brand kit<select data-kit-id>'+brands.map(b=>'<option value="'+esc(b.id)+'">'+esc(b.brand_name)+'</option>').join('')+'</select></label><button data-import-kit>Review brand kit rules</button>';
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
    this.run(async()=>{await this.refresh();const cap=await api('/editor/capabilities');this.$('[data-ai]').disabled=!cap.ai.available;this.$('[data-model]').textContent=cap.ai.reason;this.sync();});
  }
  async run(fn){this.$('[data-status]').textContent='Working…';try{await fn();this.$('[data-status]').textContent='Ready.';}catch(error){this.$('[data-status]').textContent=error.message;report(error);}}
  async ensureSaved(){if(!this.editor.projectId||this.editor.dirty)await this.editor.save();}
  sync(){this.$('[data-associated]').textContent=this.editor.project.guideline_id?'Applied guideline v'+this.editor.project.guideline_version+' · '+(this.editor.project.brand_rules?.brand_name||'Reviewed brand'):'No guideline applied. Upload or select a document to begin.';}
  async refresh(){const list=await shared('');const select=this.$('[data-library]');select.innerHTML='<option value="">Select existing guidelines</option>'+list.map(d=>'<option value="'+d.id+'">'+esc(d.rules.brand_name||d.filename)+' · v'+d.version+(d.confirmed?' · reviewed':' · needs review')+'</option>').join('');if(this.doc)select.value=this.doc.id;}
  review(){
    const doc=this.doc,panel=this.$('[data-review]'),assets=this.editor.studio.assets.filter(a=>a.kind==='image');
    const essential=new Set(['brand_name','primary_colors','secondary_colors','font_preferences','cta','language','logo_asset_id','logo_placement']);
    const field=(key,value)=>{
      let input;
      const options={language:['','en','ar'],logo_placement:['','top-right','top-left','bottom-right','bottom-left'],aspect_ratio:['','9:16','16:9','1:1','4:5']};
      if(key==='logo_asset_id')input='<select data-rule="'+key+'"><option value="">No reviewed logo</option>'+assets.map(a=>'<option value="'+a.id+'" '+(a.id===value?'selected':'')+'>'+esc(a.name)+'</option>').join('')+'</select>';
      else if(options[key])input='<select data-rule="'+key+'">'+options[key].map(x=>'<option '+(x===value?'selected':'')+'>'+esc(x)+'</option>').join('')+'</select>';
      else if(Array.isArray(value))input='<textarea data-rule="'+key+'" data-list>'+esc(value.join('\n'))+'</textarea>';
      else if(['logo_clear_space','caption_size','max_duration'].includes(key))input='<input data-rule="'+key+'" type="number" step="any" value="'+esc(value??'')+'">';
      else input='<input data-rule="'+key+'" value="'+esc(value??'')+'" maxlength="500">';
      return '<label>'+esc(key.replaceAll('_',' ')) + input+'</label>';
    };
    const entries=Object.entries(doc.rules);
    panel.innerHTML='<h3>Review extracted rules</h3><p>Only explicit document fields are extracted. Review missing/conflicting values before confirming.</p><details><summary>View source text & extraction evidence</summary><pre style="white-space:pre-wrap;max-height:260px;overflow:auto">'+esc(doc.source_text||doc.guidelines)+'</pre><pre style="white-space:pre-wrap">'+esc(JSON.stringify(doc.review,null,2))+'</pre></details><div class="vs-pair">'+entries.filter(([k])=>essential.has(k)).map(([k,v])=>field(k,v)).join('')+'</div><details><summary>Additional brand rules</summary><div class="vs-pair">'+entries.filter(([k])=>!essential.has(k)).map(([k,v])=>field(k,v)).join('')+'</div></details><div>'+doc.originals.map(o=>'<a class="vs-button" href="'+esc(o.url)+'">Download '+esc(o.name)+'</a>').join('')+'</div><button data-confirm class="primary">Confirm reviewed rules & apply to project</button>';
    panel.querySelector('[data-confirm]').onclick=()=>this.run(async()=>{
      const rules={};
      panel.querySelectorAll('[data-rule]').forEach(input=>{let value=input.value;if(input.hasAttribute('data-list'))value=value.split('\n').map(x=>x.trim()).filter(Boolean);else if(input.type==='number')value=value===''?null:Number(value);else if((input.dataset.rule==='logo_asset_id'||doc.rules[input.dataset.rule]===null)&&!value)value=null;rules[input.dataset.rule]=value;});
      this.doc=await shared('/'+doc.id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_version:doc.version,rules,confirmed:true})});
      await this.ensureSaved();const saved=await post('/projects/'+this.editor.projectId+'/guidelines',{guideline_id:doc.id});this.editor.open(saved);await this.refresh();this.review();this.sync();
    });
  }
  async plan(engine,repair_only=false){
    await this.ensureSaved();if(engine==='local_ai')await this.analyze(true);const instruction=this.$('[data-instruction]').value.trim()||'Apply the reviewed brand guidelines with professional, subtle styling.';
    this.pending=await post('/projects/'+this.editor.projectId+'/brand-edit/preview',{instruction,engine,repair_only});
    const pending=this.pending,root=this.$('[data-plan]');
    root.innerHTML='<h3>Proposed changes · '+(engine==='local_ai'?'Local AI':'Deterministic rules')+'</h3><ol>'+pending.plan.operations.map(op=>'<li>'+esc(op.reason)+' · '+esc(op.operation_type.replaceAll('_',' ').toLowerCase())+'</li>').join('')+'</ol><p>'+pending.plan.warnings.concat(pending.plan.unfulfilled_requests,pending.compliance.findings.filter(f=>f.state==='FAIL'||f.state==='WARNING').map(f=>f.state+': '+f.message)).map(esc).join('<br>')+'</p>'+(pending.conflicts.length?'<label><input type="checkbox" data-ack> '+esc(pending.conflicts.join(' '))+' Acknowledge this conflict.</label>':'')+'<div class="vs-row"><button data-preview-plan>Render proposed preview</button><button data-apply-plan class="primary">Apply changes</button><button data-reject-plan>Reject</button></div>';
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
