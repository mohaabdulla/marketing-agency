import {renderCompanyResearchReport} from './company-research-report.js';

// Assistance stays editable and applies only to the visible generation brief.
export function mountCampaignAssistant(host,{clientId,campaignId,brandSelect,briefInput,isCurrent,onApply=()=>{},onInvalidate=()=>{}}){
  host.innerHTML=`<details><summary>Help me plan this campaign</summary>
    <p>Use the saved campaign context and optional company website to suggest a brief, visual concepts, and a content plan.</p>
    <label>Company website for campaign research<input data-company-site type="url" placeholder="https://company.com" maxlength="2000" style="display:block;width:100%;box-sizing:border-box"></label>
    <label>Campaign company guidelines<select data-campaign-guideline><option value="">No guideline selected</option></select></label>
    <label>Campaign planning notes<textarea data-planning-notes maxlength="2000" rows="2" style="display:block;width:100%;box-sizing:border-box"></textarea></label>
    <label>Suggested brief language<select data-assistant-language><option value="en">English</option><option value="ar">Arabic</option></select></label>
    <div><button type="button" data-campaign-assist="draft">Suggest campaign brief</button><button type="button" data-campaign-assist="enhance">AI enhance campaign brief</button></div>
    <p data-campaign-assist-status role="status"></p>
    <section data-campaign-suggestion hidden><label>Editable campaign suggestion<textarea data-proposed-brief maxlength="6000" rows="6" style="display:block;width:100%;box-sizing:border-box"></textarea></label>
      <button type="button" data-use-campaign-suggestion>Use suggested campaign brief</button>
      <div data-campaign-planning-result></div><div data-campaign-source-report></div>
    </section></details>`;
  const $=selector=>host.querySelector(selector),status=$('[data-campaign-assist-status]');let busy=false,researchId=null,sourceIdentity=null,suggestionIdentity=null,latest=null;
  const sources=()=>({brand_id:brandSelect.value,company_url:$('[data-company-site]').value.trim(),guideline_id:$('[data-campaign-guideline]').value||null,
    notes:$('[data-planning-notes]').value,language:$('[data-assistant-language]').value});
  const invalidate=()=>{researchId=null;sourceIdentity=null;suggestionIdentity=null;latest=null;onInvalidate();$('[data-campaign-suggestion]').hidden=true;};
  host.querySelectorAll('input,select,[data-planning-notes]').forEach(el=>el.addEventListener('input',invalidate));brandSelect.addEventListener('change',invalidate);
  fetch('/api/guidelines').then(async response=>{
    if(!response.ok)return;const docs=await response.json();if(!isCurrent())return;
    for(const doc of docs)$('[data-campaign-guideline]').add(new Option(doc.filename||'Company guideline',doc.id));
  }).catch(()=>{status.textContent='Guidelines could not be loaded. You can still use saved campaign context.';});
  for(const button of host.querySelectorAll('[data-campaign-assist]'))button.onclick=async()=>{
    if(busy)return;
    const site=$('[data-company-site]');if(site.value.trim()&&!site.value.includes('://'))site.value='https://'+site.value.trim();
    if(!site.reportValidity())return;
    const source=sources(),identity=JSON.stringify(source),original=briefInput.value;
    if((source.company_url||source.guideline_id)&&!source.brand_id){status.textContent='Choose the active brand kit before company research.';return;}
    busy=true;host.querySelectorAll('[data-campaign-assist]').forEach(el=>el.disabled=true);status.textContent='Preparing an editable campaign plan…';
    try{
      const response=await fetch(`/api/agency/clients/${clientId}/campaigns/${campaignId}/assist`,{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({...source,current_brief:original,action:button.dataset.campaignAssist,research_context_id:sourceIdentity===identity?researchId:null})});
      const result=await response.json();if(!response.ok)throw new Error(typeof result.detail==='string'?result.detail:'The campaign suggestion could not be prepared.');
      if(!isCurrent())return;
      if(JSON.stringify(sources())!==identity||briefInput.value!==original){status.textContent='Campaign inputs changed. Request a fresh suggestion.';return;}
      researchId=result.research_context_id;sourceIdentity=identity;suggestionIdentity=identity;
      latest=result;
      $('[data-proposed-brief]').value=result.brief;$('[data-proposed-brief]').dir=source.language==='ar'?'rtl':'ltr';$('[data-campaign-suggestion]').hidden=false;
      const output=$('[data-campaign-planning-result]');output.replaceChildren();
      const add=(tag,text)=>{const node=document.createElement(tag);node.textContent=text;output.append(node);};
      add('h4','Visual concepts');for(const text of result.creative_directions)add('p',text);
      add('h4','Content sequence');for(const item of result.content_plan)add('p',`${item.sequence}. ${item.stage}: ${item.purpose}`);
      add('h4','Measurement plan');add('p','Primary KPI: '+(result.measurement_plan.primary_kpi||'Choose with the client')+'. Add an approved baseline, target, and reporting source.');
      for(const question of result.questions)add('p',question);
      for(const warning of result.warnings)add('p',warning);
      drawSourceReport(result.research_report);
      status.textContent=(result.ai_used?'AI-assisted suggestion. ':'Structured suggestion; no AI inference. ')+result.notice;
    }catch(error){if(isCurrent())status.textContent=error.message;}
    finally{busy=false;host.querySelectorAll('[data-campaign-assist]').forEach(el=>el.disabled=false);}
  };
  function drawSourceReport(report){renderCompanyResearchReport($('[data-campaign-source-report]'),report);}
  $('[data-use-campaign-suggestion]').onclick=()=>{
    if(!isCurrent()||suggestionIdentity!==JSON.stringify(sources()))return;
    briefInput.value=$('[data-proposed-brief]').value;briefInput.dispatchEvent(new Event('input',{bubbles:true}));
    onApply({guidelines:latest?.generation_context?.guidelines||'',visual_direction:latest?.creative_directions?.[0]||''});
    status.textContent='Applied to the generation brief. Edit it as needed, then generate the campaign kit.';
  };
}
