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
    this.root.innerHTML='<ol class="ve-steps" aria-label="Editing steps"><li>Source</li><li>Brand guidelines</li><li>Brief</li><li>AI assistant</li><li>Settings</li><li>Preview</li><li>QA</li><li>Export</li></ol><section class="vs-card" data-step="source"><h2>1. Source video</h2><button type="button" data-quick-upload>Upload video</button><input type="file" data-quick-file accept=".mp4,.mov,.webm,.gif" hidden><label>Source video<select data-quick-source><option value="">Upload or choose a video</option></select></label><p data-quick-source-info></p><p><small>The original file is never changed. Every edit is a new timeline revision you can undo.</small></p></section><section class="vs-card" data-step="brand"><h2>2. Brand guidelines &amp; logo</h2><p>Upload or choose the same reviewed guidelines used for Image &amp; GIF. Their rules steer titles, captions, logo and compliance checks.</p><div data-quick-guidelines></div><h3>Logo</h3><div data-quick-logo></div></section><section class="vs-card" data-step="brief"><h2>3. Goal &amp; creative brief</h2><div data-quick-details></div><div data-quick-instruction></div></section><section class="vs-card" data-step="assistant"><h2>4. AI prompt assistant</h2><p>Turn a short request into an editable brief before anything is edited.</p><div data-quick-assist-slot></div></section><section class="vs-card" data-step="settings"><h2>5. Edit settings</h2><div class="vs-row ve-quick-options"><label><input type="checkbox" data-quick-captions checked> Captions</label><label><input type="checkbox" data-quick-pauses checked> Tighten pauses</label><label><input type="checkbox" data-quick-zooms checked> Punch-ins at cuts and new thoughts</label><label><input type="checkbox" data-quick-tail checked> Trim recording ending</label></div><div class="vs-pair"><label>Speech language<select data-quick-language><option value="en">English</option><option value="ar">Arabic</option><option value="auto">Detect automatically</option></select></label><label>Framing<select data-quick-aspect><option value="source">Keep original / use preset</option><option value="9:16">Vertical reel · 9:16</option><option value="16:9">Landscape · 16:9</option><option value="1:1">Square</option><option value="4:5">Portrait · 4:5</option></select></label><label>Delivery preset<select data-quick-delivery></select></label><label>Largest punch-in<select data-quick-punch><option value="1.03">Very subtle · 3%</option><option value="1.06" selected>Subtle · 6%</option><option value="1.1">Noticeable · 10%</option></select></label></div><p data-quick-preset-note><small></small></p><button type="button" class="primary" data-quick-run>Create edited video</button><p role="status" data-quick-status></p></section><section class="vs-card" data-step="preview"><h2>6. Before / after</h2><div class="vs-row"><button type="button" data-quick-original disabled>Original</button><button type="button" data-quick-edited disabled>Edited</button></div><p data-quick-preview-label></p><div class="vs-preview" data-quick-preview><p>Your edited video appears here after processing.</p></div><div data-quick-report></div></section><section class="vs-card" data-step="qa"><h2>7. Brand &amp; technical QA</h2><div data-quick-qa><p>After rendering, the exported file itself is measured and checked here.</p></div></section><section class="vs-card" data-step="export"><h2>8. Export</h2><a class="vs-button primary" data-quick-download hidden>Download edited MP4</a><p data-quick-export-note>Download the MP4 from here and compare it before sending it through a messaging app, which re-compresses video.</p></section>';
    this.bar.after(this.root);this.$=selector=>this.root.querySelector(selector);
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
    this.loadPresets();
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
  sourceAsset(){return this.editor.studio.assets.find(asset=>asset.id===this.sourceId&&asset.kind==='video');}
  refreshSources(){
    const videos=this.editor.studio.assets.filter(asset=>asset.kind==='video'),select=this.$('[data-quick-source]');
    if(!videos.some(asset=>asset.id===this.sourceId))this.sourceId=this.editor.project.clips.map(clip=>clip.asset_id).find(id=>videos.some(asset=>asset.id===id))||videos[0]?.id||'';
    select.innerHTML='<option value="">Upload or choose a video</option>'+videos.map(asset=>'<option value="'+asset.id+'">'+esc(asset.name)+'</option>').join('');select.value=this.sourceId;
    const asset=this.sourceAsset();this.$('[data-quick-source-info]').textContent=asset?`${asset.width} × ${asset.height} · ${asset.duration.toFixed(2)}s · ${asset.fps.toFixed(2)} fps · original quality`:'No video selected yet.';
    this.$('[data-quick-original]').disabled=!asset;
    if(this.result&&this.result.source_asset_id!==this.sourceId){this.result=null;this.$('[data-quick-download]').hidden=true;this.$('[data-quick-edited]').disabled=true;this.$('[data-quick-preview]').innerHTML='<p>Create an edit for the selected source.</p>';this.$('[data-quick-report]').innerHTML='';this.$('[data-quick-qa]').innerHTML='<p>After rendering, the exported file itself is measured and checked here.</p>';}
    if(!this.result){try{const saved=JSON.parse(localStorage.getItem(storageKey('lexnis.video.quick-result'))||'null'),result=this.editor.studio.assets.find(a=>a.id===saved?.id&&a.source_asset_id===this.sourceId);if(result?.edit_report)this.showResult(result);}catch{}}
  }
  sync(){if(this.projectId!==this.editor.projectId){this.projectId=this.editor.projectId;this.sourceId=this.editor.project.clips.map(c=>c.asset_id).find(id=>this.editor.studio.assets.some(a=>a.id===id&&a.kind==='video'))||this.sourceId;}this.refreshSources();this.$('[data-quick-language]').value=this.editor.project.creative_context?.language?.startsWith('ar')?'ar':'en';}
  status(message){this.$('[data-quick-status]').textContent=message;}
  showVideo(url,label){if(!url)return;const preview=this.$('[data-quick-preview]'),asset=this.result?.url===url?this.result:this.sourceAsset();preview.innerHTML='<video controls preload="metadata" '+(asset?.thumbnail_url?'poster="'+esc(asset.thumbnail_url)+'" ':'')+'src="'+esc(url)+'"></video>';if(asset?.width&&asset?.height){preview.style.aspectRatio=asset.width+'/'+asset.height;preview.style.maxWidth=asset.height>asset.width?Math.round(600*asset.width/asset.height)+'px':'100%';preview.style.margin='12px auto';}this.$('[data-quick-preview-label]').textContent=label;}
  showResult(result){
    this.result=result;this.showVideo(result.url,'Edited result · this is the rendered file');
    this.$('[data-quick-edited]').disabled=false;const link=this.$('[data-quick-download]');link.href='/api/video/download/'+result.id;link.hidden=false;link.download='edited.mp4';
    const report=result.edit_report,time=t=>Number(t).toFixed(2)+'s';
    const decisions=(report.decisions||[]).map(d=>'<tr><td>'+esc(d.type.replace('_',' '))+'</td><td>'+time(d.start)+' → '+time(d.end)+'</td><td>'+esc(d.reason)+'<br><small>'+esc(d.evidence)+'</small></td><td>'+Math.round(d.confidence*100)+'%</td><td>'+esc(d.effect)+'</td></tr>').join('');
    this.$('[data-quick-report]').innerHTML='<h3>What changed</h3><p>'+report.source_duration.toFixed(2)+'s original → '+report.edited_duration.toFixed(2)+'s edited · '+(report.duration_removed??Math.max(0,report.source_duration-report.edited_duration)).toFixed(2)+'s removed by '+report.cuts.length+' cut(s) · '+report.caption_count+' caption cues · '+report.zoom_segments+' framing change(s).</p>'
      +(report.caption_count?'<p>Speech captions are a draft. Review names and wording.</p>':report.captions_requested?'<p role="alert"><strong>Captions were requested but not created.</strong> '+esc(report.caption_diagnostic||'See the notes below.')+'</p>':'<p>Captions are disabled.</p>')
      +(report.uncertain_words.length?'<p>Check these recognized words: '+report.uncertain_words.map(esc).join(', ')+'</p>':'')
      +(decisions?'<div class="ve-table"><table><thead><tr><th>Decision</th><th>When</th><th>Why · evidence</th><th>Confidence</th><th>Effect</th></tr></thead><tbody>'+decisions+'</tbody></table></div>':'')
      +'<details><summary>Notes and limits</summary>'+report.warnings.map(w=>'<p>'+esc(w)+'</p>').join('')+'</details>';
    const qa=result.qa_report,box=this.$('[data-quick-qa]');
    if(qa){const show=v=>v===null||v===undefined?'':typeof v==='object'?JSON.stringify(v):String(v);
      box.innerHTML='<p><span class="ve-qa" data-status="'+qa.overall+'">'+qa.overall+'</span> '+qa.counts.PASS+' passed · '+qa.counts.WARNING+' warnings · '+qa.counts.FAIL+' failed · '+qa.counts.NOT_CHECKED+' not checked · preset: '+esc(qa.preset.label)+'</p>'
        +(qa.true_peak_safety_pass?.applied?'<p><small>'+esc(qa.true_peak_safety_pass.reason)+'</small></p>':'')
        +'<div class="ve-table"><table><thead><tr><th>Result</th><th>Check</th><th>Measured</th><th>Expected</th></tr></thead><tbody>'+qa.checks.map(c=>'<tr><td><span class="ve-qa" data-status="'+c.status+'">'+c.status.replace('_',' ')+'</span></td><td>'+esc(c.label)+(c.detail?'<br><small>'+esc(c.detail)+'</small>':'')+'</td><td>'+esc(show(c.measured))+'</td><td>'+esc(show(c.expected))+'</td></tr>').join('')+'</tbody></table></div><p><small>'+esc(qa.scope)+'</small></p>';}
    else box.innerHTML='<p>No measurement report is attached to this result.</p>';
    try{localStorage.setItem(storageKey('lexnis.video.quick-result'),JSON.stringify({id:result.id}));}catch{}
  }
  async run(){
    const button=this.$('[data-quick-run]');if(button.disabled)return;button.disabled=true;
    try{
      const asset=this.sourceAsset();if(!asset)throw new Error('Upload or select a source video first.');
      const instruction=this.brand.$('[data-instruction]').value.trim()||'Add readable captions, tighten pauses and use subtle zooms.';
      this.brand.brief().instruction=instruction;await this.brand.ensureSaved();
      const job=await post('/projects/'+this.editor.projectId+'/quick-edit',{asset_id:asset.id,instruction,
        captions:this.$('[data-quick-captions]').checked,tighten_pauses:this.$('[data-quick-pauses]').checked,
        subtle_zooms:this.$('[data-quick-zooms]').checked,trim_recording_tail:this.$('[data-quick-tail]').checked,
        language:this.$('[data-quick-language]').value,aspect:this.$('[data-quick-aspect]').value,
        delivery:this.$('[data-quick-delivery]').value||'web-youtube',max_punch_in:Number(this.$('[data-quick-punch]').value)});
      this.editor.studio.watch(job);const started=Date.now();
      while(true){
        const state=await api('/jobs/'+job.id);this.status(state.phase||state.state);
        if(state.state==='completed'){this.result=state.result;break;}
        if(['failed','cancelled'].includes(state.state))throw new Error(state.error||'Edit cancelled.');
        if(Date.now()-started>1800000)throw new Error('The edit is still processing. Check the production queue.');
        await new Promise(resolve=>setTimeout(resolve,700));
      }
      this.showResult(this.result);
      if(this.result.project_id)this.editor.open(await api('/projects/'+this.result.project_id));
      this.status('Edited video ready. Watch it here, compare with Original, or download the MP4.');
    }catch(error){this.status(error.message);}finally{button.disabled=false;}
  }
}
