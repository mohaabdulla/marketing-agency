/**
 * Campaign Command Center for LEXNIS Marketing Agency Operating System.
 * Connects briefs, concepts, copy, scripts, storyboards, production, approvals,
 * and distribution into an interactive, unified 15-stage agency lifecycle workspace.
 */

export async function mountCommandCenter(container) {
  if (!container) return;
  container.innerHTML = `
    <div class="ccc-loading" style="padding: 3rem; text-align: center; color: var(--color-text-secondary, #94a3b8);">
      <div class="spinner" style="display: inline-block; width: 28px; height: 28px; border: 3px solid rgba(16, 185, 129, 0.2); border-top-color: #10b981; border-radius: 50%; animation: spin 0.8s linear infinite;"></div>
      <p style="margin-top: 1rem; font-family: monospace;">Loading Campaign Command Center...</p>
    </div>
  `;

  // Fetch current client and campaign from app context / agency API
  let clientId = localStorage.getItem('lexnis.clientId') || '';
  let campaignId = localStorage.getItem('lexnis.campaignId') || '';

  try {
    // If no client or campaign selected, fetch default or first client
    if (!clientId) {
      const clientsRes = await fetch('/api/agency/clients');
      if (clientsRes.ok) {
        const cdata = await clientsRes.json();
        if (cdata.items && cdata.items.length > 0) {
          clientId = cdata.items[0].id;
          localStorage.setItem('lexnis.clientId', clientId);
        }
      }
    }

    if (clientId && !campaignId) {
      const campRes = await fetch(`/api/agency/clients/${clientId}/records?kind=campaigns`);
      if (campRes.ok) {
        const campData = await campRes.json();
        if (campData.items && campData.items.length > 0) {
          campaignId = campData.items[0].id;
          localStorage.setItem('lexnis.campaignId', campaignId);
        }
      }
    }

    if (!clientId || !campaignId) {
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
    renderCommandCenter(container, data, clientId, campaignId);
  } catch (err) {
    container.innerHTML = `
      <div style="padding: 2rem; color: #ef4444; background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 8px; margin: 1rem;">
        <h3 style="margin-top: 0;">Error Loading Campaign Command Center</h3>
        <p>${err.message}</p>
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
              ${camp.client_name}
            </span>
            <span style="color: #64748b; font-size: 0.85rem;">Stage: <b style="color: #38bdf8;">${camp.current_stage}</b></span>
          </div>
          <h1 style="font-size: 1.75rem; font-weight: 800; color: #f8fafc; margin: 0 0 0.5rem 0;">${camp.name}</h1>
          <div style="display: flex; gap: 1.25rem; font-size: 0.85rem; color: #94a3b8; flex-wrap: wrap;">
            <span>🎯 <b>Objective:</b> ${camp.objective}</span>
            <span>💰 <b>Budget:</b> $${Number(camp.budget).toLocaleString()}</span>
            <span>📈 <b>Primary KPI:</b> ${camp.primary_kpi}</span>
            <span>🌐 <b>Languages:</b> ${(camp.languages || []).join(', ').toUpperCase()}</span>
          </div>
        </div>

        <!-- ACTIONS & READINESS -->
        <div style="display: flex; flex-direction: column; align-items: flex-end; gap: 0.75rem;">
          <div style="display: flex; align-items: center; gap: 0.75rem;">
            <span style="font-size: 0.85rem; color: #94a3b8;">Distribution Readiness:</span>
            <span style="font-size: 0.8rem; font-weight: 700; padding: 0.3rem 0.7rem; border-radius: 6px; ${readiness.status === 'READY' ? 'background: rgba(16, 185, 129, 0.2); color: #10b981; border: 1px solid #10b981;' : 'background: rgba(239, 68, 68, 0.2); color: #ef4444; border: 1px solid #ef4444;'}">
              ${readiness.status}
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

      <!-- STAGE PROGRESS RAIL -->
      <div style="background: #0f172a; border: 1px solid #1e293b; border-radius: 12px; padding: 1.25rem; margin-bottom: 1.5rem; overflow-x: auto;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem;">
          <h3 style="margin: 0; font-size: 0.95rem; font-weight: 700; color: #f1f5f9; text-transform: uppercase; letter-spacing: 0.05em;">Lifecycle Stage Progression (${camp.progress_percent}%)</h3>
          <div style="width: 250px; height: 8px; background: #1e293b; border-radius: 9999px; overflow: hidden;">
            <div style="width: ${camp.progress_percent}%; height: 100%; background: #10b981; transition: width 0.3s ease;"></div>
          </div>
        </div>
        <div style="display: flex; gap: 0.5rem; min-width: 900px;">
          ${stages.map((st, i) => `
            <div style="flex: 1; background: #1e293b; border: 1px solid ${st.stage === camp.current_stage ? '#38bdf8' : '#334155'}; border-radius: 8px; padding: 0.6rem; text-align: center; position: relative;">
              <div style="font-size: 0.7rem; color: #64748b; font-weight: 700; margin-bottom: 0.2rem;">0${st.order}</div>
              <div style="font-size: 0.75rem; font-weight: 700; color: ${st.stage === camp.current_stage ? '#38bdf8' : '#f8fafc'}; margin-bottom: 0.4rem;">${st.stage}</div>
              <span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: ${statusColors[st.status] || '#64748b'};" title="${st.status}"></span>
            </div>
          `).join('')}
        </div>
      </div>

      <!-- MAIN GRID: STRATEGY, PRODUCTION BOARD, RISKS -->
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 1.5rem;">
        <!-- STRATEGY SUMMARY CARD -->
        <div style="background: #0f172a; border: 1px solid #1e293b; border-radius: 12px; padding: 1.25rem;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; border-bottom: 1px solid #1e293b; padding-bottom: 0.5rem;">
            <h3 style="margin: 0; font-size: 1rem; font-weight: 700; color: #38bdf8;">Strategic Foundation</h3>
            <button type="button" style="background: none; border: none; color: #64748b; cursor: pointer; font-size: 0.8rem;" onclick="window.dispatchEvent(new CustomEvent('lexnis:workspace', {detail: {name: 'agency-strategy'}}))">Edit Strategy ↗</button>
          </div>
          <div style="display: flex; flex-direction: column; gap: 0.75rem; font-size: 0.85rem;">
            <div>
              <span style="color: #64748b; font-weight: 600;">Core Proposition:</span>
              <p style="margin: 0.2rem 0 0 0; color: #f8fafc; font-weight: 600;">${strat.proposition}</p>
            </div>
            <div>
              <span style="color: #64748b; font-weight: 600;">Problem Solved:</span>
              <p style="margin: 0.2rem 0 0 0; color: #cbd5e1;">${strat.problem}</p>
            </div>
            <div>
              <span style="color: #64748b; font-weight: 600;">Offer & Proof:</span>
              <p style="margin: 0.2rem 0 0 0; color: #cbd5e1;">${strat.offer} (${(strat.proof || []).join(', ')})</p>
            </div>
            <div>
              <span style="color: #64748b; font-weight: 600;">Primary Call to Action:</span>
              <p style="margin: 0.2rem 0 0 0; color: #10b981; font-weight: 700;">${strat.cta}</p>
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
            <span style="font-size: 0.8rem; color: #64748b;">Autonomous QA</span>
          </div>
          <div style="display: flex; flex-direction: column; gap: 0.75rem; max-height: 250px; overflow-y: auto;">
            ${risks.length === 0 ? `
              <div style="padding: 1.5rem; text-align: center; color: #10b981; background: rgba(16, 185, 129, 0.05); border-radius: 8px;">
                ✓ All legal rights, claim citations, and licensing gates cleared.
              </div>
            ` : risks.map(r => `
              <div style="background: rgba(239, 68, 68, 0.08); border-left: 3px solid ${r.severity === 'HIGH' ? '#ef4444' : '#f59e0b'}; padding: 0.6rem; border-radius: 0 6px 6px 0; font-size: 0.82rem;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 0.2rem;">
                  <b style="color: ${r.severity === 'HIGH' ? '#ef4444' : '#f59e0b'};">${r.code}</b>
                  <span style="color: #64748b; font-size: 0.75rem;">${r.stage}</span>
                </div>
                <div style="color: #cbd5e1; margin-bottom: 0.3rem;">${r.message}</div>
                <div style="color: #94a3b8; font-size: 0.78rem;"><b>Action:</b> ${r.remediation}</div>
              </div>
            `).join('')}
          </div>
        </div>
      </div>
    </div>
  `;

  // Attach event handlers
  const exportBtn = container.querySelector('#ccc-export-pkg-btn');
  if (exportBtn) {
    exportBtn.onclick = () => {
      window.location.href = `/api/agency/clients/${clientId}/campaigns/${campaignId}/export-package`;
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
        if (!advRes.ok) throw new Error('Stage advancement failed');
        await mountCommandCenter(container);
      } catch (e) {
        alert('Could not advance stage: ' + e.message);
      }
    };
  }
}

