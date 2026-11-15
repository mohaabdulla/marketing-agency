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
    this.root.innerHTML='<section class="vs-card"><h2>1. Your video & logo</h2><div class="flow-fields"><div><button type="button" data-quick-upload>Upload video</button><input type="file" data-quick-file accept=".mp4,.mov,.webm,.gif" hidden><label>Source video<select data-quick-source><option value="">Upload or choose a video</option></select></label><p data-quick-source-info></p><p><small>Logos are kept separate from the video. This edits the selected source, not repeated copies on an old timeline.</small></p></div><div data-quick-logo></div></div></section><section class="vs-card"><h2>2. What should change?</h2><div data-quick-instruction></div><div class="vs-row ve-quick-options"><label><input type="checkbox" data-quick-captions checked> Captions</label><label><input type="checkbox" data-quick-pauses checked> Tighten pauses</label><label><input type="checkbox" data-quick-zooms checked> Subtle zooms</label><label><input type="checkbox" data-quick-tail checked> Trim recording ending</label></div><div class="vs-pair"><label>Speech language<select data-quick-language><option value="en">English</option><option value="ar">Arabic</option><option value="auto">Detect automatically</option></select></label><label>Framing<select data-quick-aspect><option value="source">Keep original portrait / landscape</option><option value="9:16">Vertical reel · 9:16</option><option value="16:9">Landscape · 16:9</option><option value="1:1">Square</option><option value="4:5">Portrait · 4:5</option></select></label></div><details data-quick-assistant><summary>Improve my request (optional)</summary><div data-quick-assist-slot></div></details><details><summary>Brand, purpose & name (optional)</summary><div data-quick-details></div></details><button type="button" class="primary" data-quick-run>Create edited video</button><p role="status" data-quick-status></p></section><section class="vs-card"><h2>3. Edited preview</h2><div class="vs-row"><button type="button" data-quick-original disabled>Original</button><button type="button" data-quick-edited disabled>Edited</button><a class="vs-button primary" data-quick-download hidden>Download edited MP4</a></div><p data-quick-preview-label></p><div class="vs-preview" data-quick-preview><p>Your edited video appears here after processing.</p></div><div data-quick-report></div></section>';
    this.bar.after(this.root);this.$=selector=>this.root.querySelector(selector);
    this.slots=[{node:brand.logoPanel,slot:this.$('[data-quick-logo]')},{node:instruction,slot:this.$('[data-quick-instruction]')},
      {node:brand.assistant.root,slot:this.$('[data-quick-assist-slot]')},
      ...[purpose,brand.guidelineControls,brand.personPanel,goal].map(node=>({node,slot:this.$('[data-quick-details]')}))];
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
  sourceAsset(){return this.editor.studio.assets.find(asset=>asset.id===this.sourceId&&asset.kind==='video');}
  refreshSources(){
    const videos=this.editor.studio.assets.filter(asset=>asset.kind==='video'),select=this.$('[data-quick-source]');
    if(!videos.some(asset=>asset.id===this.sourceId))this.sourceId=this.editor.project.clips.map(clip=>clip.asset_id).find(id=>videos.some(asset=>asset.id===id))||videos[0]?.id||'';
    select.innerHTML='<option value="">Upload or choose a video</option>'+videos.map(asset=>'<option value="'+asset.id+'">'+esc(asset.name)+'</option>').join('');select.value=this.sourceId;
    const asset=this.sourceAsset();this.$('[data-quick-source-info]').textContent=asset?`${asset.width} × ${asset.height} · ${asset.duration.toFixed(2)}s · ${asset.fps.toFixed(2)} fps · original quality`:'No video selected yet.';
    this.$('[data-quick-original]').disabled=!asset;
    if(this.result&&this.result.source_asset_id!==this.sourceId){this.result=null;this.$('[data-quick-download]').hidden=true;this.$('[data-quick-edited]').disabled=true;this.$('[data-quick-preview]').innerHTML='<p>Create an edit for the selected source.</p>';this.$('[data-quick-report]').innerHTML='';}
    if(!this.result){try{const saved=JSON.parse(localStorage.getItem(storageKey('lexnis.video.quick-result'))||'null'),result=this.editor.studio.assets.find(a=>a.id===saved?.id&&a.source_asset_id===this.sourceId);if(result?.edit_report)this.showResult(result);}catch{}}
  }
  sync(){if(this.projectId!==this.editor.projectId){this.projectId=this.editor.projectId;this.sourceId=this.editor.project.clips.map(c=>c.asset_id).find(id=>this.editor.studio.assets.some(a=>a.id===id&&a.kind==='video'))||this.sourceId;}this.refreshSources();this.$('[data-quick-language]').value=this.editor.project.creative_context?.language?.startsWith('ar')?'ar':'en';}
  status(message){this.$('[data-quick-status]').textContent=message;}
  showVideo(url,label){if(!url)return;const preview=this.$('[data-quick-preview]'),asset=this.result?.url===url?this.result:this.sourceAsset();preview.innerHTML='<video controls preload="metadata" '+(asset?.thumbnail_url?'poster="'+esc(asset.thumbnail_url)+'" ':'')+'src="'+esc(url)+'"></video>';if(asset?.width&&asset?.height){preview.style.aspectRatio=asset.width+'/'+asset.height;preview.style.maxWidth=asset.height>asset.width?Math.round(600*asset.width/asset.height)+'px':'100%';preview.style.margin='12px auto';}this.$('[data-quick-preview-label]').textContent=label;}
  showResult(result){
    this.result=result;this.showVideo(result.url,'Edited result · this is the rendered file');
    this.$('[data-quick-edited]').disabled=false;const link=this.$('[data-quick-download]');link.href='/api/video/download/'+result.id;link.hidden=false;link.download='edited.mp4';
    const report=result.edit_report;
    this.$('[data-quick-report]').innerHTML='<p>'+report.source_duration.toFixed(2)+'s original → '+report.edited_duration.toFixed(2)+'s edited · '+report.cuts.length+' cleanup cuts · '+report.caption_count+' caption cues · '+report.zoom_segments+' zoom shots.</p>'+(report.caption_count?'<p>Speech captions are a draft. Review names and wording.</p>':report.captions_requested?'<p>No captions were created. See edit details for the speech setup limitation.</p>':'<p>Captions are disabled.</p>')+(report.uncertain_words.length?'<p>Check these recognized words: '+report.uncertain_words.map(esc).join(', ')+'</p>':'')+'<details><summary>Edit details</summary>'+report.warnings.map(w=>'<p>'+esc(w)+'</p>').join('')+'</details>';
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
        language:this.$('[data-quick-language]').value,aspect:this.$('[data-quick-aspect]').value});
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
