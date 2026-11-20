/* Campaign delivery presentation; generation and video editing remain separate workspaces. */
(() => {
  window.hydrateCampaignResult = async data => {
    if (!data || typeof data !== 'object') throw new Error('The server returned an empty campaign response. Generate the campaign again.');
    if (data.status !== 'success' || !data.assets || !data.campaign_id) return data;
    const response = await fetch('/api/campaign/' + encodeURIComponent(data.campaign_id) + '/deliverables');
    if (!response.ok) throw new Error('Unable to load the completed campaign kit (' + response.status + ').');
    const kit = await response.json().catch(() => null);
    if (!kit || typeof kit !== 'object') throw new Error('The completed campaign kit could not be read. Generate the campaign again.');
    return kit;
  };
  let sequence = 0;
  const element = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  window.renderCampaignDeliverables = (container, data, language = 'en', helpers = {}) => {
    const root = element('section', undefined, 'campaign-delivery');
    root.dataset.campaignDelivery = '';
    const id = 'campaign-delivery-' + (++sequence);
    const resolve = helpers.resolve || (url => url);
    const download = async (url, name) => {
      try { await helpers.download(resolve(url), name); }
      catch (error) { announce(error.message); }
    };
    const notice = element('p', '', 'campaign-delivery-status');
    notice.setAttribute('role', 'status');
    function announce(text) { notice.textContent = text; }
    async function copy(value) {
      try { await navigator.clipboard.writeText(value); announce('Copied to clipboard.'); }
      catch { announce('Clipboard unavailable. Select the text below to copy it.'); }
    }
    const header = element('header', undefined, 'campaign-delivery-header');
    const heading = element('div');
    heading.append(element('p', 'CAMPAIGN DELIVERY', 'campaign-delivery-eyebrow'), element('h3', 'Your complete campaign kit'));
    const languageLabel = element('label', 'Campaign language');
    const languageSelect = element('select');
    languageSelect.setAttribute('aria-label', 'Campaign delivery language');
    const available = ['en','ar'].filter(lang => data.agency_kits?.[lang] || data.copywriting_by_language?.[lang]);
    for (const lang of available.length ? available : [language]) {
      const option = element('option', lang === 'ar' ? 'العربية' : 'English'); option.value = lang; languageSelect.append(option);
    }
    languageSelect.value = available.includes(language) ? language : languageSelect.options[0].value;
    languageLabel.append(languageSelect); header.append(heading, languageLabel);
    const tabs = element('div', undefined, 'campaign-delivery-tabs');
    tabs.setAttribute('role','tablist'); tabs.setAttribute('aria-label','Campaign deliverables');
    const panels = {};
    const buttons = [];
    const titles = [['visuals','Visual Formats Grid'],['motion','Motion Preview'],['copy','Copywriting Hub'],['review','Campaign Review'],['design','Design Lab']];
    for (const [key,title] of titles) {
      const button = element('button',title); button.type='button'; button.id=id+'-tab-'+key;
      button.setAttribute('role','tab');button.setAttribute('aria-controls',id+'-'+key);button.dataset.deliveryTab=key;
      const panel = element('section');panel.id=id+'-'+key;panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby',button.id);
      panels[key]=panel;buttons.push(button);tabs.append(button);
      button.onclick=()=>activate(key);
      button.onkeydown=event=>{
        if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
        event.preventDefault();const index=buttons.indexOf(button);
        const next=event.key==='Home'?0:event.key==='End'?buttons.length-1:(index+(event.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length;
        buttons[next].click();buttons[next].focus();
      };
    }
    function activate(key) {
      for (const button of buttons) {const active=button.dataset.deliveryTab===key;button.setAttribute('aria-selected',String(active));button.tabIndex=active?0:-1;}
      for (const [name,panel] of Object.entries(panels)) {panel.hidden=name!==key;if(panel.hidden)panel.querySelectorAll('video').forEach(video=>video.pause());}
    }
    const master = element('button','Download Full Client Agency Kit (.ZIP)','campaign-delivery-master');master.type='button';master.dataset.masterKit='';
    master.onclick=()=>download(data.bundle_zip_url || currentKit().bundle_zip_url,'full-client-agency-kit');
    const currentKit=()=>{
      const prefix=languageSelect.value==='ar'?'arabic_':'';
      const kit={...data};
      for(const key of ['image_url','primary_image_url','companion_image_url','animation_url','animation_mp4_url','story_url','landscape_url']){
        kit[key]=data[prefix+key] || data[key];
      }
      return {...kit,...(data.agency_kits?.[languageSelect.value] || {})};
    };
    const buttonFor=(label,action)=>{const button=element('button',label);button.type='button';button.onclick=action;return button;};
    const swatch=hex=>{const chip=element('span',undefined,'design-swatch');if(/^#[0-9a-f]{6}$/i.test(hex||''))chip.style.background=hex;chip.title=hex||'';return chip;};
    const link=(text,href)=>{const anchor=element('a',text);if(/^https?:\/\//.test(href||'')){anchor.href=href;anchor.target='_blank';anchor.rel='noopener noreferrer';}return anchor;};
    /* Design Lab: the guideline version and the research-improved version of the same card, each graded from its
       pixels, with the research behind every change and the exact departures from the brand guideline. */
    function drawDesignLab(panel,lab,lang){
      if(!lab){panel.append(element('p','This kit has no Design Lab report. Generate a new kit to include it.'));return;}
      if(lab.status==='running'){
        // The review finishes after the kit is published; check back until its report is ready (up to ~4 minutes).
        panel.append(element('p','Design Lab is researching the market and grading this design… the kit above is ready to use meanwhile.','campaign-delivery-status'));
        if(data.campaign_id&&!root.dataset.designPolling){
          root.dataset.designPolling='1';let tries=0;
          const poll=async()=>{
            if(!root.isConnected)return;
            try{
              const response=await fetch('/api/campaign/'+encodeURIComponent(data.campaign_id)+'/deliverables');
              const kit=response.ok?await response.json():null;
              if(kit?.design_review&&kit.design_review.status!=='running'){data.design_review=kit.design_review;panels.design.replaceChildren();drawDesignLab(panels.design,data.design_review,languageSelect.value);return;}
            }catch{}
            if(++tries<48)setTimeout(poll,5000);
            else{panels.design.replaceChildren(element('p','The Design Lab is taking longer than expected. Reopen this campaign later to see it.','campaign-delivery-status'));}
          };
          setTimeout(poll,5000);
        }
        return;
      }
      if(lab.status!=='ready'){panel.append(element('p',lab.reason||'The design review is not available for this kit.','campaign-delivery-status'));return;}
      if(lab.language&&lab.language!==lang)panel.append(element('p',`The Design Lab compared the ${lab.language==='ar'?'Arabic':'English'} card.`,'campaign-delivery-status'));
      const compare=element('div',undefined,'campaign-format-grid design-compare');
      for(const [key,title,note] of [['guideline','Following the guideline','Same copy and layout, brand colours as specified.'],['improved','Research-improved','Same copy and layout with the changes below.']]){
        const version=lab[key];if(!version)continue;
        const card=element('article',undefined,'campaign-format-card');const image=element('img');image.src=resolve(version.image_url);image.alt=title;image.loading='lazy';
        const score=element('p',`Design score ${version.grade.score} / 100`,'design-score');
        card.append(element('h4',title),element('p',note),image,score,buttonFor('Download '+title,()=>download(version.image_url,'design-'+key)));compare.append(card);
      }
      const change=lab.change||0;
      panel.append(element('h4','Guideline vs research-improved'),
        element('p',change>0?`The improved version scores ${change} points higher.`:change<0?`The improved version scores ${-change} points lower; keep the guideline version.`:'Both versions score the same; the guideline version already meets the targets.'),compare);
      const table=element('table',undefined,'design-table');const head=element('tr');
      for(const label of ['Criterion','Guideline','Improved','Measured (improved)','Target','Source'])head.append(element('th',label));
      table.append(head);
      const improved=Object.fromEntries((lab.improved?.grade?.criteria||[]).map(item=>[item.id,item]));
      for(const item of lab.guideline?.grade?.criteria||[]){
        const row=element('tr');const better=improved[item.id];
        row.append(element('td',item.label),element('td',String(item.score)),element('td',better?String(better.score):'—'),element('td',better?.measured||item.measured),element('td',item.target));
        const cell=element('td');if(item.source?.url)cell.append(link(item.source.title,item.source.url));row.append(cell);
        row.title=item.why||'';table.append(row);
      }
      panel.append(element('h4','How each version scores'),table);
      const changes=lab.guideline_changes||[];
      panel.append(element('h4','Changes to the brand guideline'));
      if(!changes.length)panel.append(element('p','No colour departs from the guideline.'));
      for(const item of changes){
        const row=element('p',undefined,'design-change');
        row.append(element('span',item.role+': '),swatch(item.guideline),element('span',` ${item.guideline} → `),swatch(item.improved),
          element('span',` ${item.improved} · ΔE ${item.delta_e} · ${item.within_guideline?'barely visible change':'visible change, needs client approval'}`));
        panel.append(row);
      }
      const research=lab.research||{};
      panel.append(element('h4','Market and platform research'),
        element('p',`Industry: ${research.industry||'—'} · Platform: ${research.platform||'—'} · ${research.web_results||0} web results · analysed by ${research.engine||'—'}${research.cached?' (cached this month)':''}`));
      if(research.note)panel.append(element('p',research.note,'campaign-delivery-status'));
      const findings=element('ul');
      for(const finding of research.findings||[]){const item=element('li',finding.claim+' ');item.append(link(finding.title||'source',finding.url));findings.append(item);}
      panel.append(findings);
      const reasons=Object.entries(lab.reasons||{});
      if(reasons.length){const list=element('ul');for(const [move,reason] of reasons)list.append(element('li',`${move.replaceAll('_',' ')}: ${reason}`));panel.append(element('h4','Why each change'),list);}
      const motion=lab.motion||{};
      if(motion.delivered||motion.improved){
        panel.append(element('h4','Motion'));
        const describe=(name,item)=>element('p',`${name}: ${item.seconds}s loop, ${item.fps||'—'} fps, ${item.loops_forever?'loops forever':'does not loop'}, ${item.size_mb} MB, first frame ${item.still?.score??'—'}/100`);
        if(motion.delivered)panel.append(describe('Delivered GIF',motion.delivered));
        if(motion.improved){
          panel.append(describe('Research-improved GIF',motion.improved.grade));
          const gif=element('img');gif.src=resolve(motion.improved.gif_url);gif.alt='Research-improved looping GIF';gif.loading='lazy';gif.className='design-gif';
          panel.append(gif,buttonFor('Download improved GIF',()=>download(motion.improved.gif_url,'design-improved-loop')));
        }
      }
      panel.append(element('p',lab.notice||'','campaign-delivery-status'));
    }
    function draw() {
      const lang=languageSelect.value,kit=currentKit();
      const writing=data.copywriting_by_language?.[lang] || data.copywriting?.[lang] || kit.copywriting || data.copywriting;
      for(const panel of Object.values(panels))panel.replaceChildren();
      const grid=element('div',undefined,'campaign-format-grid');
      for(const [key,title,dimensions] of [['primary_image_url','Primary Feed','1080 × 1350'],['companion_image_url','Companion Slide','1080 × 1350'],['story_url','Story','1080 × 1920'],['landscape_url','Landscape Banner','1200 × 628']]){
        const url=kit[key] || (key==='primary_image_url'?kit.image_url:null);if(!url)continue;
        const card=element('article',undefined,'campaign-format-card');const image=element('img');image.src=resolve(url);image.alt=title+' · '+lang.toUpperCase();image.loading='lazy';
        card.append(element('h4',title),element('p',dimensions),image,buttonFor('Download '+title,()=>download(url,key)));grid.append(card);
      }
      panels.visuals.append(grid);
      if(kit.animation_mp4_url){
        const video=element('video');video.src=resolve(kit.animation_mp4_url);video.loop=true;video.muted=true;video.playsInline=true;video.controls=true;video.preload='metadata';video.setAttribute('aria-label','Campaign motion preview');
        panels.motion.append(video,buttonFor('Download MP4',()=>download(kit.animation_mp4_url,'campaign-motion')));
      }
      if(kit.animation_url){
        const details=element('details');details.append(element('summary','Preview looping GIF'));
        const gif=element('img');gif.src=resolve(kit.animation_url);gif.alt='Looping campaign GIF';gif.loading='lazy';details.append(gif);
        panels.motion.append(details,buttonFor('Download GIF',()=>download(kit.animation_url,'campaign-loop')));
      }
      panels.motion.append(element('p',data.motion?.fps?'Motion rendered at '+data.motion.fps+' fps. GIF playback depends on the viewer.':'Animated campaign artwork.'));
      if(writing){
        for(const [key,title] of [['linkedin_post','LinkedIn'],['instagram_caption','Instagram'],['x_post','X / Twitter']]){
          const card=element('article',undefined,'campaign-copy-card');
          const text=key==='x_post'&&writing.x_thread?.length?writing.x_thread.join('\n\n'):writing[key] || '';
          const content=element('pre',text);content.dir=lang==='ar'?'rtl':'ltr';content.lang=lang;
          card.append(element('h4',key==='x_post'?'X / Twitter Thread':title),buttonFor('Copy '+title,()=>copy(text)),content);panels.copy.append(card);
        }
        const pills=element('div',undefined,'campaign-hashtags');pills.setAttribute('aria-label','Click a hashtag to copy it');
        for(const tag of writing.hashtags || [])pills.append(buttonFor(tag,()=>copy(tag)));
        panels.copy.append(element('h4','Hashtag strategy'),pills,element('p',writing.hashtag_strategy?.guidance || 'Choose the tags most relevant to this post.'));
        if(writing.copy_source==='template')panels.copy.append(element('p','Template-based copy: review the wording against your approved brief before publishing.','campaign-delivery-status'));
      }
      const review=data.quality_review;
      if(review){
        const localized=review.copy?.[lang];
        panels.review.append(element('h4','Copy and delivery checks'),element('p',localized?.notice||'Review the final kit before publishing.'));
        for(const channel of localized?.channels||[])panels.review.append(element('p',`${channel.format}${channel.post?' · post '+channel.post:''}: ${channel.length} / ${channel.limit} (${channel.method})`));
        const issues=element('ul');for(const issue of localized?.issues||[])issues.append(element('li',issue.message));
        if(issues.childElementCount)panels.review.append(issues);else panels.review.append(element('p','No issues flagged by the copy checks.'));
        panels.review.append(element('h4','Brand palette contrast reference'),element('p',review.palette_notice));
        for(const pair of review.palette||[])panels.review.append(element('p',`${pair.foreground} on ${pair.background}: ${pair.ratio}:1 · ${pair.normal_text?'normal-text reference met':pair.large_text?'large-text reference met':'use another colour for readable text'}`));
        const label=element('label','Editable alt-text draft'),alt=element('textarea');alt.value=review.accessibility?.alt_text_draft||'';alt.rows=3;
        label.append(alt);panels.review.append(label,element('p',review.accessibility?.notice||''),buttonFor('Copy alt text',()=>copy(alt.value)));
        panels.review.append(element('h4','Client hand-off'));
        for(const step of review.handoff?.next_steps||[])panels.review.append(element('p',step));
      }else panels.review.append(element('p','This earlier kit has no campaign review report. Generate a new kit to include it.'));
      drawDesignLab(panels.design,data.design_review,lang);
      master.hidden=!(data.bundle_zip_url || kit.bundle_zip_url);
      announce('Showing '+(lang==='ar'?'Arabic':'English')+' deliverables.');
    }
    languageSelect.onchange=()=>{root.querySelectorAll('video').forEach(video=>video.pause());draw();};
    root.append(header,tabs,...Object.values(panels),master,notice);container.append(root);draw();activate('visuals');
  };
})();
