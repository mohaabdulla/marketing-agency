/* Research-driven company introduction: website + web research -> proposal -> approval -> finished video. */
import {api,post,esc} from './video-api.js';
import {fillVoices,fitTimings,previewLine} from './video-narration.js';
import {frameFit,orientationFor,stockPanel} from './video-footage.js';
import {storageKey} from './public-session.js';

const key=()=>storageKey('lexnis.video.company-intro');
const IMAGE=(id,index)=>`/api/video/company-intro/${encodeURIComponent(id)}/images/${index}`;
const VIDEO=(id,index)=>`/api/video/company-intro/${encodeURIComponent(id)}/videos/${index}`;

export class CompanyIntro {
  constructor(wizard,host){
    this.wizard=wizard;this.studio=wizard.studio;this.host=host;this.proposal=null;
    host.innerHTML=`<h4>Introduce your company</h4>
      <p>Paste the company website. We read the site, search the web for public information, and propose a complete introduction video: who you are, what you do, who you help, why choose you, and how to get in touch. Nothing is rendered until you approve.</p>
      <label>Company website<input type="url" data-ci="company_url" maxlength="2000" placeholder="https://company.com" autocomplete="url"></label>
      <div class="vs-pair">
        <label>Video length<select data-ci="duration"><option value="15">15 seconds</option><option value="30" selected>30 seconds</option><option value="45">45 seconds</option><option value="60">60 seconds</option></select></label>
        <label>Format<select data-ci="platform_target"><option value="16:9">Website & YouTube · 16:9</option><option value="9:16">Reels / TikTok / Shorts · 9:16</option><option value="1:1">Feed · 1:1</option></select></label>
        <label>Tone<select data-ci="tone"><option value="professional">Professional</option><option value="warm">Warm</option><option value="energetic">Energetic</option></select></label>
        <label>Export quality<select data-ci="resolution"><option value="1080">1080p</option><option value="720">720p</option></select></label>
      </div>
      <label class="vbf-toggle"><input type="checkbox" data-ci="web_search" checked> Also search the web for public information about the company</label>
      <label class="vbf-toggle"><input type="checkbox" data-ci="website_images" checked> Use photos from the company website (only where the company owns or has licensed them)</label>
      <details><summary>Notes for the writer (optional)</summary><label>Anything the video must say or avoid<textarea data-ci="notes" maxlength="2000" placeholder="For example: mention our 24/7 support; do not mention pricing."></textarea></label></details>
      <p><small data-ci-brand-hint></small></p>
      <button type="button" class="primary" data-ci-research>Research company &amp; propose video</button>
      <progress data-ci-progress max="100" hidden aria-label="Company research progress"></progress>
      <p data-ci-status role="status" aria-live="polite"></p>
      <section data-ci-proposal class="vbf-ci-proposal" hidden>
        <h4>What we found</h4><dl data-ci-profile class="vbf-ci-profile"></dl>
        <div data-ci-warnings></div>
        <details data-ci-facts-box><summary>Facts used in the script and where they come from</summary><ul data-ci-facts></ul></details>
        <details><summary data-ci-sources-title>Sources</summary><ul data-ci-sources class="vbf-ci-sources"></ul></details>
        <div data-ci-questions-box hidden><h5>Questions for the client</h5><ul data-ci-questions></ul></div>
        <h4>Video proposal</h4>
        <label>What the video will show<textarea data-ci-treatment maxlength="2000"></textarea></label>
        <div data-ci-scenes class="vbf-scenes"></div>
        <p data-ci-total role="status"></p>
        <div class="vs-row"><button type="button" data-ci-fit>Fit scene lengths to the narration</button><span class="vbf-fit" data-ci-fit-status role="status" aria-live="polite"></span></div>
        <label>AI narrator (offline voice on this computer)<select data-ci-narrator><option value="">No narration (subtitles only)</option></select></label>
        <p class="vs-note" data-ci-narrator-note></p>
        <div class="vs-pair"><label>Licensed music track (optional)<select data-ci-music><option value="">No music</option></select></label>
          <label>Recorded voiceover (optional, replaces the AI narrator)<select data-ci-voiceover><option value="">No voiceover</option></select></label></div>
        <label class="vbf-toggle"><input type="checkbox" data-ci-subtitles checked> Burn the narration into the video as subtitles</label>
        <div class="vs-row"><button type="button" class="primary" data-ci-approve>Approve &amp; create video</button><button type="button" data-ci-again>Research again</button></div>
      </section>
      <section data-ci-result hidden><h4>Your company video</h4>
        <progress data-ci-render-progress max="100" value="0" aria-label="Video render progress"></progress><p data-ci-render-status role="status" aria-live="polite"></p>
        <div data-ci-preview class="vs-preview" hidden></div><div data-ci-quality></div><div data-ci-exports class="vs-row"></div></section>`;
    this.$=s=>host.querySelector(s);
    wizard.labelControls(host);
    this.$('[data-ci-research]').onclick=()=>this.research();
    this.$('[data-ci-again]').onclick=()=>this.research();
    this.$('[data-ci-approve]').onclick=()=>this.approve();
    this.$('[data-ci-narrator]').onchange=this.$('[data-ci-voiceover]').onchange=()=>{if(this.proposal)this.updateTotal();};
    this.$('[data-ci-fit]').onclick=()=>this.fitToNarration();
    this.$('[data-ci-treatment]').oninput=()=>{if(this.proposal){this.proposal.treatment=this.$('[data-ci-treatment]').value;this.persist();}};
    host.addEventListener('change',event=>{if(event.target.dataset.ci)this.persist();});
    wizard.root.querySelector('[data-field=brand_id]').addEventListener('change',()=>this.brandHint());
    this.restore();
  }
  status(text){this.$('[data-ci-status]').textContent=text;}
  brandHint(){
    const brand=this.wizard.root.querySelector('[data-field=brand_id]');
    this.$('[data-ci-brand-hint]').textContent=brand.value?`Colours, fonts and logo come from the “${brand.selectedOptions[0].text}” brand kit.`:'No brand kit selected: we will create one for this company from its website when you approve.';
  }
  fields(){
    const value=name=>this.$(`[data-ci="${name}"]`);
    const shared=this.wizard.root;
    return {company_url:value('company_url').value.trim(),duration:+value('duration').value,platform_target:value('platform_target').value,
      tone:value('tone').value,resolution:+value('resolution').value,web_search:value('web_search').checked,website_images:value('website_images').checked,
      notes:value('notes').value,brand_id:shared.querySelector('[data-field=brand_id]').value||null,
      language:shared.querySelector('[data-field=language]').value,target_audience:shared.querySelector('[data-field=target_audience]').value,
      guideline_id:shared.querySelector('[data-field=guideline_id]').value||null,
      pacing:shared.querySelector('[data-field=pacing]').value,transition:shared.querySelector('[data-field=transition]').value};
  }
  persist(){
    try{localStorage.setItem(key(),JSON.stringify({fields:this.fields(),proposal_id:this.proposal?.proposal_id||null,scenes:this.proposal?.scenes||null,
      treatment:this.proposal?.treatment||null,research_job:this.researchJob||null,render_job:this.renderJob||null,result:this.result||null}));}catch{}
  }
  async restore(){
    let saved=null;try{saved=JSON.parse(localStorage.getItem(key())||'null');}catch{}
    for(const [name,value] of Object.entries(saved?.fields||{})){
      const input=this.$(`[data-ci="${name}"]`);if(!input)continue;
      if(input.type==='checkbox')input.checked=!!value;else if(value!==null)input.value=value;
    }
    this.brandHint();
    try{
      if(saved?.proposal_id){
        const proposal=await api('/company-intro/'+saved.proposal_id);
        if(saved.scenes)proposal.scenes=saved.scenes;if(saved.treatment)proposal.treatment=saved.treatment;
        this.show(proposal);
      }
      if(saved?.result)this.showResult(saved.result);
    }catch{this.proposal=null;}
  }
  resume(job){if(job.kind==='company-research')this.watchResearch(job);else this.watchRender(job);}
  busy(value){
    this.working=value;
    this.host.querySelectorAll('input,select,textarea,button').forEach(el=>el.disabled=value);
    if(!value&&this.proposal)this.updateTotal();
  }
  async research(){
    if(this.working)return;
    const url=this.$('[data-ci="company_url"]');
    if(url.value.trim()&&!url.value.includes('://'))url.value='https://'+url.value.trim();
    if(!url.value.trim()){this.status('Enter the company website first.');url.focus();return;}
    if(!url.reportValidity())return;
    this.busy(true);this.status('Starting research…');
    try{this.watchResearch(await post('/company-intro/research',this.fields()));}
    catch(error){this.status(error.message);this.busy(false);}
  }
  watchResearch(job){
    this.researchJob=job.id;this.persist();this.busy(true);
    const bar=this.$('[data-ci-progress]');bar.hidden=false;bar.removeAttribute('value');
    this.studio.watch(job,proposal=>{
      this.researchJob=null;bar.hidden=true;this.busy(false);
      if(!proposal){this.status('Research was cancelled.');this.persist();return;}
      this.show(proposal);this.status('Proposal ready. Review the script, edit anything you like, then approve to create the video.');
      this.$('[data-ci-proposal]').scrollIntoView({behavior:'smooth',block:'start'});
    },status=>{
      if(status.progress?.percent!==undefined)bar.value=status.progress.percent;
      if(status.phase)this.status(status.phase+'…');
      if(['failed','cancelled'].includes(status.state)){this.researchJob=null;bar.hidden=true;this.busy(false);this.status(status.error||'Research was cancelled.');this.persist();}
    });
  }
  show(proposal){
    this.proposal=proposal;const ar=proposal.request.language==='ar',dir=ar?'rtl':'ltr';
    this.$('[data-ci-proposal]').hidden=false;this.loadVoices(proposal.request.language);
    const profile=proposal.profile,rows=[['Company',profile.company_name],['In one line',profile.one_line],['Who they are',profile.who_we_are],
      ['What they do',(profile.what_we_do||[]).join(' · ')],['Who they help',profile.who_we_help],['Why choose them',(profile.why_us||[]).join(' · ')]];
    const list=this.$('[data-ci-profile]');list.replaceChildren();
    for(const [term,value] of rows){if(!value)continue;const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=term;dd.textContent=value;dd.dir='auto';list.append(dt,dd);}
    const warnings=this.$('[data-ci-warnings]');warnings.replaceChildren();
    for(const text of proposal.warnings||[]){const note=document.createElement('p');note.className='vs-note';note.textContent=text;warnings.append(note);}
    const link=(url,text)=>{const a=document.createElement('a');a.href=url;a.textContent=text||url;a.target='_blank';a.rel='noopener noreferrer';return a;};
    const facts=this.$('[data-ci-facts]');facts.replaceChildren();
    for(const fact of proposal.facts||[]){const item=document.createElement('li');item.dir='auto';let host=fact.source_url;try{host=new URL(fact.source_url).hostname;}catch{}item.append(fact.claim+' — ',link(fact.source_url,host));facts.append(item);}
    this.$('[data-ci-facts-box]').hidden=!(proposal.facts||[]).length;
    const sources=this.$('[data-ci-sources]');sources.replaceChildren();
    for(const page of proposal.sources.website){const item=document.createElement('li');item.append(link(page.url,page.title||page.url),` · company website (${page.kind})`);sources.append(item);}
    for(const result of proposal.sources.search){const item=document.createElement('li');item.append(link(result.url,result.title||result.url),result.independent?' · third-party, verify before use':' · company-owned');if(result.snippet){const quote=document.createElement('small');quote.textContent=' '+result.snippet;item.append(quote);}sources.append(item);}
    this.$('[data-ci-sources-title]').textContent=`Sources (${proposal.sources.website.length} website pages, ${proposal.sources.search.length} search results)`;
    const questions=this.$('[data-ci-questions]');questions.replaceChildren();
    for(const question of proposal.questions||[]){const item=document.createElement('li');item.textContent=question;questions.append(item);}
    this.$('[data-ci-questions-box]').hidden=!(proposal.questions||[]).length;
    const treatment=this.$('[data-ci-treatment]');treatment.value=proposal.treatment;treatment.dir=dir;
    this.drawScenes();this.refreshAudio();this.persist();
  }
  drawScenes(){
    const proposal=this.proposal,host=this.$('[data-ci-scenes]'),dir=proposal.request.language==='ar'?'rtl':'ltr';host.replaceChildren();
    const videos=proposal.videos||[],ratio=proposal.request.platform_target||'16:9';
    proposal.scenes.forEach((scene,index)=>{
      const card=document.createElement('article');card.className='vbf-scene';
      const soft=entry=>entry.low_resolution?' · low resolution':'';
      const choices=[`<option value="">Brand motion graphics</option>`,
        videos.length?`<optgroup label="Company website videos">${videos.map(v=>`<option value="video:${v.index}">Website video ${v.index+1} · ${Math.round(v.duration)} s${soft(v)}</option>`).join('')}</optgroup>`:'',
        proposal.images.length?`<optgroup label="Company website photos">${proposal.images.map(i=>`<option value="image:${i.index}">Website photo ${i.index+1}${soft(i)}</option>`).join('')}</optgroup>`:'',
        `<option value="stock" data-stock-option hidden>Stock video</option>`].join('');
      card.innerHTML=`<h5>Scene ${index+1} · ${esc(scene.section)}</h5><div class="vbf-ci-visual"></div>
        <label>Visual<select data-scene-visual>${choices}</select></label>
        <details class="vbf-stock" data-stock></details>
        <label>On-screen headline<textarea data-scene-field="overlay_text" maxlength="180" dir="${dir}"></textarea></label>
        <label>Narration / subtitles<textarea data-scene-field="voiceover" maxlength="450" dir="${dir}"></textarea></label>
        <label>Visual direction<textarea data-scene-field="visual_prompt" maxlength="1000"></textarea></label>
        <label>Duration (seconds)<input data-scene-field="duration" type="number" min="2" max="30" step="any"></label>
        <div class="vs-row"><button type="button" data-scene-listen>Listen to narration</button><span class="vbf-fit" data-scene-fit role="status" aria-live="polite"></span></div>`;
      card.querySelector('[data-scene-listen]').onclick=()=>this.listen(scene,card);
      for(const field of ['overlay_text','voiceover','visual_prompt','duration'])card.querySelector(`[data-scene-field=${field}]`).value=scene[field];
      const visual=card.querySelector('.vbf-ci-visual'),select=card.querySelector('[data-scene-visual]'),stockOption=select.querySelector('[data-stock-option]');
      visual.style.aspectRatio=ratio.replace(':',' / ');
      const sync=()=>{
        stockOption.hidden=!scene.stock;
        if(scene.stock)stockOption.textContent=`Stock video · ${scene.stock.provider_label} · ${scene.stock.author||'unnamed creator'}`;
        select.value=scene.video!=null?`video:${scene.video}`:scene.image!=null?`image:${scene.image}`:scene.stock?'stock':'';
      };
      const paint=()=>{
        visual.replaceChildren();
        if(scene.video!=null){
          const video=document.createElement('video');video.src=VIDEO(proposal.proposal_id,scene.video);video.poster=VIDEO(proposal.proposal_id,scene.video)+'/poster';
          video.muted=true;video.loop=true;video.autoplay=true;video.playsInline=true;video.setAttribute('aria-label',`Website video ${scene.video+1} for scene ${index+1}`);visual.append(video);
        }else if(scene.stock){
          if(scene.stock.preview_url){const img=document.createElement('img');img.src=scene.stock.preview_url;img.alt=`${scene.stock.provider_label} clip by ${scene.stock.author||'an unnamed creator'}`;visual.append(img);}
          const badge=document.createElement('em');badge.textContent=`${scene.stock.provider_label} · ${scene.stock.author||'unnamed creator'} · ${scene.stock.duration} s`;visual.append(badge);
        }else if(scene.image!=null){
          const entry=proposal.images.find(i=>i.index===scene.image)||{};
          const img=document.createElement('img');img.src=IMAGE(proposal.proposal_id,scene.image);img.alt=`Website photo ${scene.image+1} for scene ${index+1}`;img.loading='lazy';
          // Shown the way the video will frame it: whole on a blurred fill rather than cropped or blown up.
          if(frameFit(entry.width,entry.height,ratio,proposal.request.resolution)==='contain'){img.style.objectFit='contain';visual.style.backgroundImage=`url("${img.src}")`;visual.classList.add('is-filled');}
          else{visual.style.backgroundImage='';visual.classList.remove('is-filled');}
          visual.append(img);
        }
        if(scene.image==null){visual.style.backgroundImage='';visual.classList.remove('is-filled');}
        const caption=document.createElement('span');caption.textContent=scene.overlay_text;caption.dir='auto';visual.append(caption);
      };
      sync();paint();
      select.onchange=()=>{
        const [kind,value]=select.value.split(':');
        scene.image=kind==='image'?+value:null;scene.video=kind==='video'?+value:null;
        if(kind!=='stock')scene.stock=null;
        sync();paint();this.persist();
      };
      stockPanel(card.querySelector('[data-stock]'),{query:scene.stock_query||'',orientation:orientationFor(ratio),minSeconds:()=>(+scene.duration||0)*.75,
        choose:item=>{scene.stock={provider:item.provider,id:item.id,provider_label:item.provider_label,author:item.author,preview_url:item.preview_url,duration:item.duration};
          scene.image=null;scene.video=null;sync();paint();this.persist();}});
      card.querySelectorAll('[data-scene-field]').forEach(input=>input.oninput=input.onchange=()=>{
        const field=input.dataset.sceneField;
        scene[field]=field==='duration'?+input.value:input.value;
        if(field==='overlay_text')paint();
        this.updateTotal();this.persist();
      });
      host.append(card);
    });
    this.wizard.labelControls(host);this.updateTotal();
  }
  updateTotal(){
    const total=this.proposal.scenes.reduce((sum,scene)=>sum+(+scene.duration||0),0);
    // ~15 characters per second is a natural narration pace; the narrator may speed up by at most 30%.
    const narrated=!!this.$('[data-ci-narrator]').value&&!this.$('[data-ci-voiceover]').value;
    const long=this.proposal.scenes.findIndex(scene=>scene.voiceover.length>Math.max(0,(+scene.duration||0)-.45)*(narrated?19:17));
    this.$('[data-ci-total]').textContent=`Total length: ${total.toFixed(1)} seconds.`+(total<6||total>60?' Adjust scene durations to a total between 6 and 60 seconds.':'')
      +(long>=0?` Scene ${long+1} has more narration than viewers can comfortably read in its duration; shorten it or give it more time.`:'');
    this.$('[data-ci-approve]').disabled=this.working||total<6||total>60;
  }
  async fitToNarration(){
    const voice=this.$('[data-ci-narrator]').value,out=this.$('[data-ci-fit-status]'),button=this.$('[data-ci-fit]');
    out.classList.remove('is-warning');
    if(!this.proposal)return;
    if(!voice||this.$('[data-ci-voiceover]').value){out.textContent='Choose an AI narrator (and no recorded voiceover) to time the scenes to it.';return;}
    button.disabled=true;out.textContent='Timing each line with the narrator…';
    try{
      const fitted=await fitTimings({voice,language:this.proposal.request.language,lines:this.proposal.scenes.map(scene=>scene.voiceover),
        durations:this.proposal.scenes.map(scene=>scene.duration)});
      this.proposal.scenes.forEach((scene,index)=>{scene.duration=fitted.durations[index];});
      this.drawScenes();this.persist();out.textContent=fitted.note;
    }catch(error){out.textContent=error.message;out.classList.add('is-warning');}
    finally{button.disabled=this.working;}
  }
  listen(scene,card){
    return previewLine({voice:this.$('[data-ci-narrator]').value,text:scene.voiceover,language:this.proposal.request.language,duration:scene.duration,
      output:card.querySelector('[data-scene-fit]'),button:card.querySelector('[data-scene-listen]'),
      missingVoice:'Choose an AI narrator above to hear this line.',isBusy:()=>this.working});
  }
  async loadVoices(language){
    const voices=await fillVoices(this.$('[data-ci-narrator]'),language,()=>'No narration (subtitles only)');
    const name=language==='ar'?'Arabic':'English';
    this.$('[data-ci-narrator-note]').textContent=voices.length?'The narrator reads each scene in time with its subtitles. Listen to the result before sending it to a client.'
      :`No ${name} narrator voice is installed on this computer, so the video will use subtitles only. Install a Piper ${name} voice (set PIPER_BIN and PIPER_VOICES) or attach a recorded voiceover.`;
  }
  refreshAudio(){
    const audio=this.studio.assets?.filter(asset=>asset.kind==='audio')||[];
    for(const [selector,empty] of [['[data-ci-music]','No music'],['[data-ci-voiceover]','No voiceover']]){
      const select=this.$(selector),value=select.value;select.replaceChildren(new Option(empty,''));
      for(const asset of audio)select.add(new Option(asset.name,asset.id));select.value=value;
    }
  }
  async approve(){
    if(this.working||!this.proposal)return;
    for(const field of this.$('[data-ci-proposal]').querySelectorAll('textarea,input'))if(!field.reportValidity())return;
    this.busy(true);this.status('Building the storyboard and starting the render…');
    try{
      const music=this.$('[data-ci-music]').value||null,voiceover=this.$('[data-ci-voiceover]').value||null;
      const response=await post(`/company-intro/${this.proposal.proposal_id}/approve`,{treatment:this.$('[data-ci-treatment]').value,
        scenes:this.proposal.scenes.map(({section,overlay_text,voiceover,visual_prompt,duration,motion,background_style,image,video,stock})=>({section,overlay_text,voiceover,
          visual_prompt,duration:+duration,motion,background_style,image:image??null,video:video??null,stock:stock?{provider:stock.provider,id:stock.id}:null})),
        burn_subtitles:this.$('[data-ci-subtitles]').checked,music_asset_id:music,voiceover_asset_id:voiceover,
        narrator_voice:voiceover?null:this.$('[data-ci-narrator]').value||null});
      this.status('Approved. Rendering your company video…');this.watchRender(response.job);
    }catch(error){this.status(error.message);this.busy(false);}
  }
  watchRender(job){
    this.renderJob=job.id;this.result=null;this.persist();this.busy(true);
    const section=this.$('[data-ci-result]'),bar=this.$('[data-ci-render-progress]');section.hidden=false;
    this.$('[data-ci-preview]').hidden=true;this.$('[data-ci-exports]').replaceChildren();
    this.studio.watch(job,result=>{this.renderJob=null;this.busy(false);this.showResult(result);this.status('Your company video is ready.');this.persist();},status=>{
      const p=status.progress;let percent=p?.percent;
      if(p?.total_scenes)percent=5+20*p.completed_scenes/p.total_scenes;
      if(p?.total_clips)percent=25+45*p.completed_clips/p.total_clips;
      if(percent!==undefined)bar.value=percent;
      this.$('[data-ci-render-status]').textContent=status.phase||status.state;
      if(['failed','cancelled'].includes(status.state)){this.renderJob=null;this.busy(false);this.$('[data-ci-render-status]').textContent=status.error||'Render cancelled.';this.persist();}
    });
  }
  showResult(result){
    this.result=result;const section=this.$('[data-ci-result]');section.hidden=false;
    this.$('[data-ci-render-progress]').value=100;
    this.$('[data-ci-render-status]').textContent=`Rendered ${result.width}×${result.height} at ${result.fps} fps, ${(+result.duration).toFixed(1)} seconds.`;
    const preview=this.$('[data-ci-preview]');preview.hidden=false;
    preview.innerHTML=`<video controls playsinline preload="metadata" src="${esc(result.video_url)}" aria-label="Company introduction video"></video>`;
    const quality=this.$('[data-ci-quality]');quality.replaceChildren();
    const lines=[...(result.quality?.warnings||[])];
    if(result.narration)lines.unshift(`Narrated by ${result.narration.voice}.`);
    if(result.captions?.cues)lines.push(`${result.captions.cues} subtitles timed to the ${result.narration?'narrator':'scenes'}, placed for ${result.captions.platform?.label||'the platform'}.`);
    if(result.quality)lines.push(result.quality.passed?'Automated checks passed. '+result.quality.notice:result.quality.notice);
    for(const text of result.advice||[])lines.push('Suggestion: '+text);
    for(const text of lines){const p=document.createElement('p');p.className='vs-note';p.textContent=text;quality.append(p);}
    this.$('[data-ci-exports]').innerHTML=`<a class="vs-button primary" href="${esc(result.mp4_url)}" download>Download MP4</a>`
      +(result.cover_download_url?`<a class="vs-button" href="${esc(result.cover_download_url)}" download>Download cover image</a>`:'')
      +`<a class="vs-button" href="${esc(result.bundle_zip_url)}" download>Download client kit (.ZIP) with script, subtitles &amp; sources</a>`;
  }
}
