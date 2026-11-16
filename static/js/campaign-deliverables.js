/* Campaign delivery presentation; generation and video editing remain separate workspaces. */
(() => {
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
    const titles = [['visuals','Visual Formats Grid'],['motion','Motion Preview'],['copy','Copywriting Hub']];
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
      master.hidden=!(data.bundle_zip_url || kit.bundle_zip_url);
      announce('Showing '+(lang==='ar'?'Arabic':'English')+' deliverables.');
    }
    languageSelect.onchange=()=>{root.querySelectorAll('video').forEach(video=>video.pause());draw();};
    root.append(header,tabs,...Object.values(panels),master,notice);container.append(root);draw();activate('visuals');
  };
})();
