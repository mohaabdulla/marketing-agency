import {storageKey} from './public-session.js';
import {context} from './app-context.js';
import {escapeHtml as escape} from './agency-api.js';
import {mountCampaignAssistant} from './campaign-assistant.js';
const requests=new WeakMap();
window.addEventListener('lexnis:agency-context',()=>{
  const root=document.getElementById('agency-command-center-workspace');
  if(root&&!root.hidden)mountCommandCenter(root);
});
/**
 * Campaign Command Center for LEXNIS Marketing Agency Operating System.
 * Connects briefs, concepts, copy, scripts, storyboards, production, approvals,
 * and distribution into an interactive, unified 15-stage agency lifecycle workspace.
 */

export async function mountCommandCenter(container) {
  if (!container) return;
  const version=(requests.get(container)||0)+1;requests.set(container,version);
  container.innerHTML = `
    <div class="ccc-loading" style="padding: 3rem; text-align: center; color: var(--color-text-secondary, #94a3b8);">
      <div class="spinner" style="display: inline-block; width: 28px; height: 28px; border: 3px solid rgba(16, 185, 129, 0.2); border-top-color: #10b981; border-radius: 50%; animation: spin 0.8s linear infinite;"></div>
      <p style="margin-top: 1rem; font-family: monospace;">Loading Campaign Command Center...</p>
    </div>
  `;

  // Fetch current client and campaign from app context / agency API
  const selected=context();
  let clientId = selected.client_id || '';
  let campaignId = selected.campaign_id || '';

  try {
    // If no client or campaign selected, fetch default or first client
    if (!clientId) {
      const clientsRes = await fetch('/api/agency/clients');
      if (clientsRes.ok) {
        const cdata = await clientsRes.json();
        if (cdata.items && cdata.items.length > 0) {
          clientId = cdata.items[0].id;
          localStorage.setItem(storageKey('lexnis.clientId'), clientId);
        }
      }
    }

    if (clientId && !campaignId) {
      const campRes = await fetch(`/api/agency/clients/${clientId}/records?kind=campaigns`);
      if (campRes.ok) {
        const campData = await campRes.json();
        if (campData.items && campData.items.length > 0) {
          campaignId = campData.items[0].id;
          localStorage.setItem(storageKey('lexnis.campaignId'), campaignId);
        }
      }
    }

    if (!clientId || !campaignId) {
      if(requests.get(container)!==version)return;
      container.innerHTML = `
        <div style="padding: 3rem; text-align: center; max-width: 600px; margin: 0 auto;">
          <h2 style="font-size: 1.5rem; color: #fff; margin-bottom: 0.75rem;">Campaign Command Center</h2>
          <p style="color: #94a3b8; margin-bottom: 1.5rem;">Select or create a client and campaign in the Strategy workspace to initialize the command center.</p>
          <button type="button" class="btn-primary" style="padding: 0.6rem 1.4rem; background: #10b981; color: #000; font-weight: 600; border-radius: 6px; border: none; cursor: pointer;" onclick="window.dispatchEvent(new CustomEvent('lexnis:workspace', {detail: {name: 'agency-campaigns'}}))">
            Go to Campaigns & Strategy
          </button>
        </div>
      `;
      return;
    }

    const res = await fetch(`/api/agency/clients/${clientId}/campaigns/${campaignId}/command-center`);
    if (!res.ok) {
      throw new Error(`Failed to load command center (${res.status})`);
    }
    const data = await res.json();
    if(requests.get(container)!==version)return;
    renderCommandCenter(container, data, clientId, campaignId);
  } catch (err) {
    if(requests.get(container)!==version)return;
    container.innerHTML = `
      <div style="padding: 2rem; color: #ef4444; background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 8px; margin: 1rem;">
        <h3 style="margin-top: 0;">Error Loading Campaign Command Center</h3>
        <p>${escape(err.message)}</p>
      </div>
    `;
  }
}

function renderCommandCenter(container, data, clientId, campaignId) {
  const camp = data.campaign || {};
  const strat = data.strategy_summary || {};
  const board = data.production_board || {};
  const readiness = data.readiness || {};
  const stages = data.stages || [];
  const risks = data.risks || [];

  const statusColors = {
    NOT_STARTED: '#64748b',
    IN_PROGRESS: '#3b82f6',
    BLOCKED: '#ef4444',
    AWAITING_APPROVAL: '#f59e0b',
    APPROVED: '#10b981',
    COMPLETE: '#10b981',
  };

  container.innerHTML = `
    <div class="ccc-workspace" style="padding: 1.5rem; max-width: 1400px; margin: 0 auto; color: #e2e8f0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
      <!-- HEADER -->
      <div style="background: #0f172a; border: 1px solid #1e293b; border-radius: 12px; padding: 1.5rem; margin-bottom: 1.5rem; display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 1rem;">
        <div>
          <div style="display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.5rem;">
            <span style="background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.3); font-size: 0.75rem; font-weight: 700; padding: 0.2rem 0.6rem; border-radius: 9999px; text-transform: uppercase;">
              ${escape(camp.client_name)}
            </span>
            <span style="color: #64748b; font-size: 0.85rem;">Stage: <b style="color: #38bdf8;">${escape(camp.current_stage)}</b></span>
          </div>
          <h1 style="font-size: 1.75rem; font-weight: 800; color: #f8fafc; margin: 0 0 0.5rem 0;">${escape(camp.name)}</h1>
          <div style="display: flex; gap: 1.25rem; font-size: 0.85rem; color: #94a3b8; flex-wrap: wrap;">
            <span>🎯 <b>Objective:</b> ${escape(camp.objective)}</span>
            <span>💰 <b>Budget:</b> ${escape(camp.currency||'BHD')} ${Number(camp.budget).toLocaleString()}</span>
            <span>📈 <b>Primary KPI:</b> ${escape(camp.primary_kpi)}</span>
            <span>🌐 <b>Languages:</b> ${escape((camp.languages || []).join(', ').toUpperCase())}</span>
          </div>
        </div>

        <!-- ACTIONS & READINESS -->
        <div style="display: flex; flex-direction: column; align-items: flex-end; gap: 0.75rem;">
          <div style="display: flex; align-items: center; gap: 0.75rem;">
            <span style="font-size: 0.85rem; color: #94a3b8;">Distribution Readiness:</span>
            <span style="font-size: 0.8rem; font-weight: 700; padding: 0.3rem 0.7rem; border-radius: 6px; ${readiness.status === 'READY' ? 'background: rgba(16, 185, 129, 0.2); color: #10b981; border: 1px solid #10b981;' : 'background: rgba(239, 68, 68, 0.2); color: #ef4444; border: 1px solid #ef4444;'}">
              ${escape(readiness.status)}
            </span>
          </div>
          <div style="display: flex; gap: 0.5rem;">
            <button id="ccc-export-pkg-btn" style="background: #1e293b; color: #f8fafc; border: 1px solid #334155; padding: 0.5rem 1rem; border-radius: 6px; font-weight: 600; cursor: pointer;">
              📦 Export Offline Package
            </button>
            <button id="ccc-advance-stage-btn" style="background: #10b981; color: #022c22; border: none; padding: 0.5rem 1.2rem; border-radius: 6px; font-weight: 700; cursor: pointer;">
              Advance Stage ➔
            </button>
          </div>
        </div>
      </div>

      <section class="ccc-generation" style="background:#0f172a;border:1px solid #334155;border-radius:12px;padding:1.5rem;margin-bottom:1.5rem;">
        <h2>Generate a complete campaign kit</h2>
        <p>Four visual formats, smooth GIF and MP4 loops, and English and Arabic copy in one client archive.</p>
        <label for="ccc-generation-brief">Campaign brief</label>
        <textarea id="ccc-generation-brief" rows="4" style="display:block;width:100%;box-sizing:border-box;margin:0.5rem 0;padding:0.75rem;background:#1e293b;color:#fff;border:1px solid #475569;border-radius:6px;">${escape([camp.name,camp.objective].filter(Boolean).join('. '))}</textarea>
        <label for="ccc-generation-direction">Visual direction (editable)</label><textarea id="ccc-generation-direction" rows="2" maxlength="1500" style="display:block;width:100%;box-sizing:border-box;margin:.5rem 0;background:#1e293b;color:#fff;"></textarea>
        <label for="ccc-generation-brand">Active brand kit</label>
        <select id="ccc-generation-brand" disabled style="padding:0.5rem;max-width:100%;"><option value="">Loading brands...</option></select>
        <div data-campaign-assistant></div>
        <button type="button" id="ccc-generate-kit" class="btn-primary" disabled>Generate full campaign kit</button>
        <button type="button" id="ccc-open-kit" ${data.generated_campaigns?.length ? '' : 'hidden'}>Open latest completed kit</button>
        <p id="ccc-generation-status" role="status" aria-live="polite"></p>
        <div id="ccc-generated-result"></div>
      </section>

      <!-- STAGE PROGRESS RAIL -->
      <div style="background: #0f172a; border: 1px solid #1e293b; border-radius: 12px; padding: 1.25rem; margin-bottom: 1.5rem; overflow-x: auto;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem;">
          <h3 style="margin: 0; font-size: 0.95rem; font-weight: 700; color: #f1f5f9; text-transform: uppercase; letter-spacing: 0.05em;">Lifecycle Stage Progression (${Math.min(100,Math.max(0,Number(camp.progress_percent)||0))}%)</h3>
          <div style="width: 250px; height: 8px; background: #1e293b; border-radius: 9999px; overflow: hidden;">
            <div style="width: ${Math.min(100,Math.max(0,Number(camp.progress_percent)||0))}%; height: 100%; background: #10b981; transition: width 0.3s ease;"></div>
          </div>
        </div>
        <div style="display: flex; gap: 0.5rem; min-width: 900px;">
          ${stages.map((st, i) => `
            <div style="flex: 1; background: #1e293b; border: 1px solid ${st.stage === camp.current_stage ? '#38bdf8' : '#334155'}; border-radius: 8px; padding: 0.6rem; text-align: center; position: relative;">
              <div style="font-size: 0.7rem; color: #64748b; font-weight: 700; margin-bottom: 0.2rem;">0${st.order}</div>
              <div style="font-size: 0.75rem; font-weight: 700; color: ${st.stage === camp.current_stage ? '#38bdf8' : '#f8fafc'}; margin-bottom: 0.4rem;">${escape(st.stage)}</div>
              <span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: ${statusColors[st.status] || '#64748b'};" title="${escape(st.status)}"></span>
            </div>
          `).join('')}
        </div>
      </div>

      <!-- MAIN GRID: STRATEGY, PRODUCTION BOARD, RISKS -->
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 360px), 1fr)); gap: 1.5rem;">
        <!-- STRATEGY SUMMARY CARD -->
        <div style="background: #0f172a; border: 1px solid #1e293b; border-radius: 12px; padding: 1.25rem;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; border-bottom: 1px solid #1e293b; padding-bottom: 0.5rem;">
            <h3 style="margin: 0; font-size: 1rem; font-weight: 700; color: #38bdf8;">Strategic Foundation</h3>
            <button type="button" style="background: none; border: none; color: #64748b; cursor: pointer; font-size: 0.8rem;" onclick="window.dispatchEvent(new CustomEvent('lexnis:workspace', {detail: {name: 'agency-strategy'}}))">Edit Strategy ↗</button>
          </div>
          <div style="display: flex; flex-direction: column; gap: 0.75rem; font-size: 0.85rem;">
            <div>
              <span style="color: #64748b; font-weight: 600;">Core Proposition:</span>
              <p style="margin: 0.2rem 0 0 0; color: #f8fafc; font-weight: 600;">${escape(strat.proposition)}</p>
            </div>
            <div>
              <span style="color: #64748b; font-weight: 600;">Problem Solved:</span>
              <p style="margin: 0.2rem 0 0 0; color: #cbd5e1;">${escape(strat.problem)}</p>
            </div>
            <div>
              <span style="color: #64748b; font-weight: 600;">Offer & Proof:</span>
              <p style="margin: 0.2rem 0 0 0; color: #cbd5e1;">${escape(strat.offer)} (${escape((strat.proof || []).join(', '))})</p>
            </div>
            <div>
              <span style="color: #64748b; font-weight: 600;">Primary Call to Action:</span>
              <p style="margin: 0.2rem 0 0 0; color: #10b981; font-weight: 700;">${escape(strat.cta)}</p>
            </div>
          </div>
        </div>

        <!-- PRODUCTION BOARD -->
        <div style="background: #0f172a; border: 1px solid #1e293b; border-radius: 12px; padding: 1.25rem;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; border-bottom: 1px solid #1e293b; padding-bottom: 0.5rem;">
            <h3 style="margin: 0; font-size: 1rem; font-weight: 700; color: #10b981;">Production Assets</h3>
            <span style="font-size: 0.8rem; color: #64748b;">${board.total_assets || 0} Total Assets</span>
          </div>
          <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 0.75rem; font-size: 0.85rem;">
            <div style="background: #1e293b; padding: 0.75rem; border-radius: 8px;">
              <span style="color: #94a3b8;">Copy Variants</span>
              <div style="font-size: 1.25rem; font-weight: 800; color: #f8fafc; margin-top: 0.2rem;">${board.copy_variants_count || 0}</div>
            </div>
            <div style="background: #1e293b; padding: 0.75rem; border-radius: 8px;">
              <span style="color: #94a3b8;">Images & Cards</span>
              <div style="font-size: 1.25rem; font-weight: 800; color: #f8fafc; margin-top: 0.2rem;">${board.images_count || 0}</div>
            </div>
            <div style="background: #1e293b; padding: 0.75rem; border-radius: 8px;">
              <span style="color: #94a3b8;">Video Clips</span>
              <div style="font-size: 1.25rem; font-weight: 800; color: #f8fafc; margin-top: 0.2rem;">${board.videos_count || 0}</div>
            </div>
            <div style="background: #1e293b; padding: 0.75rem; border-radius: 8px;">
              <span style="color: #94a3b8;">Voiceovers & Music</span>
              <div style="font-size: 1.25rem; font-weight: 800; color: #f8fafc; margin-top: 0.2rem;">${board.audio_count || 0}</div>
            </div>
          </div>
          <div style="display: flex; gap: 0.5rem; margin-top: 1rem;">
            <button type="button" style="flex: 1; background: #1e293b; border: 1px solid #334155; color: #e2e8f0; padding: 0.5rem; border-radius: 6px; font-size: 0.8rem; cursor: pointer;" onclick="window.dispatchEvent(new CustomEvent('lexnis:workspace', {detail: {name: 'image'}}))">Image Studio ↗</button>
            <button type="button" style="flex: 1; background: #1e293b; border: 1px solid #334155; color: #e2e8f0; padding: 0.5rem; border-radius: 6px; font-size: 0.8rem; cursor: pointer;" onclick="window.dispatchEvent(new CustomEvent('lexnis:workspace', {detail: {name: 'video'}}))">Video Studio ↗</button>
            <button type="button" style="flex: 1; background: #1e293b; border: 1px solid #334155; color: #e2e8f0; padding: 0.5rem; border-radius: 6px; font-size: 0.8rem; cursor: pointer;" onclick="window.dispatchEvent(new CustomEvent('lexnis:workspace', {detail: {name: 'agency-audio'}}))">Audio Studio ↗</button>
          </div>
        </div>

        <!-- RISK & COMPLIANCE PANEL -->
        <div style="background: #0f172a; border: 1px solid #1e293b; border-radius: 12px; padding: 1.25rem;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; border-bottom: 1px solid #1e293b; padding-bottom: 0.5rem;">
            <h3 style="margin: 0; font-size: 1rem; font-weight: 700; color: ${risks.length > 0 ? '#ef4444' : '#10b981'};">
              Risk & Rights Audit (${risks.length})
            </h3>
            <span style="font-size: 0.8rem; color: #64748b;">Automated checks</span>
          </div>
          <div style="display: flex; flex-direction: column; gap: 0.75rem; max-height: 250px; overflow-y: auto;">
            ${risks.length === 0 ? `
              <div style="padding: 1.5rem; text-align: center; color: #10b981; background: rgba(16, 185, 129, 0.05); border-radius: 8px;">
                No issues flagged by these checks. Final content and usage rights still need review.
              </div>
            ` : risks.map(r => `
              <div style="background: rgba(239, 68, 68, 0.08); border-left: 3px solid ${r.severity === 'HIGH' ? '#ef4444' : '#f59e0b'}; padding: 0.6rem; border-radius: 0 6px 6px 0; font-size: 0.82rem;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 0.2rem;">
                  <b style="color: ${r.severity === 'HIGH' ? '#ef4444' : '#f59e0b'};">${escape(r.code)}</b>
                  <span style="color: #64748b; font-size: 0.75rem;">${escape(r.stage)}</span>
                </div>
                <div style="color: #cbd5e1; margin-bottom: 0.3rem;">${escape(r.message)}</div>
                <div style="color: #94a3b8; font-size: 0.78rem;"><b>Action:</b> ${escape(r.remediation)}</div>
              </div>
            `).join('')}
          </div>
        </div>
      </div>
    </div>
  `;

  const generationVersion=requests.get(container);
  const current=()=>requests.get(container)===generationVersion;
  const generate=container.querySelector('#ccc-generate-kit');
  const brands=container.querySelector('#ccc-generation-brand');
  const notice=container.querySelector('#ccc-generation-status');
  const output=container.querySelector('#ccc-generated-result');
  const open=container.querySelector('#ccc-open-kit');
  let latest=data.generated_campaigns?.[0]?.campaign_id;
  let assistedGuidelines='';
  mountCampaignAssistant(container.querySelector('[data-campaign-assistant]'),{clientId,campaignId,brandSelect:brands,briefInput:container.querySelector('#ccc-generation-brief'),isCurrent:current,
    onApply:result=>{assistedGuidelines=result.guidelines;container.querySelector('#ccc-generation-direction').value=result.visual_direction;},onInvalidate:()=>{assistedGuidelines='';}});
  async function showKit(result) {
    const kit=await window.hydrateCampaignResult(result);
    if(!current())return;
    output.querySelectorAll('video').forEach(video=>video.pause());
    output.replaceChildren();
    window.renderCampaignDeliverables(output,kit,kit.language,{
      download:async(url,name)=>{
        const response=await fetch(url);
        if(!response.ok)throw new Error('Download failed ('+response.status+').');
        const link=document.createElement('a'),blob=URL.createObjectURL(await response.blob());
        const extension=new URL(url,location.href).pathname.match(/\.[a-z0-9]+$/i)?.[0]||'';
        link.href=blob;link.download=/\.[a-z0-9]+$/i.test(name)?name:name+extension;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(blob),4000);
      }
    });
  }
  fetch('/api/brands').then(async response=>{
    if(!response.ok)throw new Error('Unable to load brand kits.');
    const result=await response.json();if(!current())return;
    brands.replaceChildren(new Option('Campaign brand',''));
    for(const brand of result.brands||[])brands.add(new Option(brand.brand_name,brand.id));
    brands.disabled=false;generate.disabled=false;
  }).catch(error=>{if(current())notice.textContent=error.message;});
  open.onclick=async()=>{
    open.disabled=true;
    try {await showKit({status:'success',campaign_id:latest,assets:{}});}
    catch(error){if(current())notice.textContent=error.message;}
    finally{if(current())open.disabled=false;}
  };
  generate.onclick=async()=>{
    const brief=container.querySelector('#ccc-generation-brief').value.trim();
    if(!brief){notice.textContent='Enter a campaign brief.';return;}
    generate.disabled=true;open.disabled=true;brands.disabled=true;
    notice.textContent='Generating bilingual visuals, motion and copy. The complete kit will appear here when ready.';
    try {
      const response=await fetch(`/api/agency/clients/${clientId}/campaigns/${campaignId}/generate`,{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({prompt:brief,theme:container.querySelector('#ccc-generation-direction').value,guidelines:assistedGuidelines,brand_id:brands.value||null,brand:camp.client_name||camp.name,language:'both',use_search:false})
      });
      const result=await response.json();
      if(!response.ok)throw new Error(typeof result.detail==='string'?result.detail:JSON.stringify(result.detail||'Generation failed.'));
      if(!current())return;
      latest=result.campaign_id;open.hidden=false;
      await showKit(result);
      if(current())notice.textContent='Campaign kit ready. Download individual assets or the full client ZIP below.';
    }catch(error){if(current())notice.textContent=error.message;}
    finally{if(current()){generate.disabled=false;open.disabled=false;brands.disabled=false;}}
  };

  // Attach event handlers
  const exportBtn = container.querySelector('#ccc-export-pkg-btn');
  if (exportBtn) {
    exportBtn.onclick = async () => {
      exportBtn.disabled=true;
      let status=container.querySelector('[data-export-status]');if(!status){status=document.createElement('p');status.dataset.exportStatus='';status.setAttribute('role','status');exportBtn.after(status);}status.textContent='Preparing publication package...';
      try{
        const response=await fetch(`/api/agency/clients/${clientId}/campaigns/${campaignId}/export-package`,{method:'POST'});
        if(!response.ok){const error=await response.json().catch(()=>({}));throw new Error(typeof error.detail==='string'?error.detail:JSON.stringify(error.detail||'Export failed'));}
        const url=URL.createObjectURL(await response.blob()),link=document.createElement('a');link.href=url;link.download='campaign-publication-package.zip';document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),4000);status.textContent='Package downloaded. Nothing was published.';
      }catch(error){status.textContent=error.message;}finally{exportBtn.disabled=false;}
    };
  }

  const advanceBtn = container.querySelector('#ccc-advance-stage-btn');
  if (advanceBtn) {
    advanceBtn.onclick = async () => {
      const nextStages = {
        INTAKE: 'RESEARCH',
        RESEARCH: 'STRATEGY',
        STRATEGY: 'BRIEF',
        BRIEF: 'CONCEPT',
        CONCEPT: 'COPY',
        COPY: 'SCRIPT',
        SCRIPT: 'STORYBOARD',
        STORYBOARD: 'PRODUCTION',
        PRODUCTION: 'QA',
        QA: 'APPROVAL',
        APPROVAL: 'DISTRIBUTION',
        DISTRIBUTION: 'MEASUREMENT',
        MEASUREMENT: 'LEARNING',
        LEARNING: 'COMPLETE',
      };
      const nextStage = nextStages[camp.current_stage] || 'COMPLETE';
      try {
        const advRes = await fetch(`/api/agency/clients/${clientId}/campaigns/${campaignId}/advance`, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({target_stage: nextStage}),
        });
        if (!advRes.ok){const error=await advRes.json().catch(()=>({}));throw new Error(typeof error.detail==='string'?error.detail:JSON.stringify(error.detail||'Stage advancement failed'));}
        await mountCommandCenter(container);
      } catch (e) {
        alert('Could not advance stage: ' + e.message);
      }
    };
  }
}

