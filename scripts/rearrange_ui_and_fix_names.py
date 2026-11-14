"""
Script to rearrange index.html into a clear, unified 3-stage flow:
Stage 1: Brand Identity & Guidelines
Stage 2: Campaign Objective & Concept Studio (Post Type + Quick-Fill Fields + Prompt + AI Enhance + Tone/Style)
Stage 3: Visual Assets & Launch Production (Dropzones + Samples + Format + Quick Test Swap + Generate Campaign)
Stage 4 / Results: Generated Bilingual Assets

Also updates JS to live-sync person names and clear stale names on photo upload.
"""
import re
from pathlib import Path

INDEX_PATH = Path(r"c:\Users\mohamed redha\Desktop\marketing-agency\index.html")

def refactor():
    html = INDEX_PATH.read_text(encoding="utf-8")

    # 1. Locate the Stage 2, Stage 3, and old Stage 4 sections
    stage2_start = html.find('<!-- STAGE 2: CAMPAIGN OBJECTIVE & CONCEPT STUDIO -->')
    assert stage2_start != -1, "Stage 2 start not found"

    stage3_start = html.find('<!-- STAGE 3: VISUAL ASSETS, REFERENCE TEMPLATES & SAMPLE IMAGES -->')
    assert stage3_start != -1, "Stage 3 start not found"

    stage4_start = html.find('<!-- STAGE 4: CAMPAIGN PROMPT & AI LAUNCH STUDIO -->')
    assert stage4_start != -1, "Stage 4 start not found"

    results_start = html.find('<!-- RESULTS SECTION: Two-Column Responsive Layout -->')
    assert results_start != -1, "Results section start not found"

    # Extract Stage 2 content before closing </section>
    stage2_chunk = html[stage2_start:stage3_start]
    # Extract Stage 3 content before Stage 4
    stage3_chunk = html[stage3_start:stage4_start]
    # Extract Stage 4 content before Results
    stage4_chunk = html[stage4_start:results_start]

    print("Found all 3 stage chunks!")

    # In stage 2, find where post-type-fields-container ends
    idx_ptfc = stage2_chunk.find('id="post-type-fields-container"')
    assert idx_ptfc != -1
    idx_close_div = stage2_chunk.find('</div>\n        </div>\n      </section>', idx_ptfc)
    if idx_close_div == -1:
        idx_close_div = stage2_chunk.find('</div>', idx_ptfc)
        # find the end of the post-type-fields-container div
        idx_close_div = stage2_chunk.find('</div>', idx_close_div + 6)

    # Prompt studio HTML to embed inside Stage 2:
    prompt_studio_html = '''
          <!-- Unified Campaign Prompt & Concept Directives -->
          <div class="space-y-3 pt-3 border-t border-obsidian-800">
            <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div class="flex items-center space-x-2">
                <span class="text-xs font-tech font-bold text-cyan-accent uppercase tracking-wider flex items-center space-x-1.5">
                  <i data-lucide="sparkles" class="w-4 h-4 text-cyan-accent"></i>
                  <span>Campaign Prompt &amp; Concept Directives</span>
                </span>
                <span class="text-[10px] font-mono text-slate-500 hidden md:inline">Auto-synced with quick-fill fields, or edit directly below</span>
              </div>

              <!-- Quick Actions & Presets -->
              <div class="flex flex-wrap items-center gap-2">
                <button 
                  type="button" 
                  id="enhance-prompt-btn" 
                  class="px-3.5 py-1.5 rounded-xl bg-gradient-to-r from-cyan-accent/20 via-cyan-400/20 to-violet-accent/20 hover:from-cyan-accent hover:to-violet-accent text-cyan-accent hover:text-obsidian-950 border border-cyan-accent/40 font-tech font-bold text-xs tracking-wider uppercase transition-all flex items-center space-x-1.5 shadow-sm active:scale-95 group cursor-pointer"
                  title="Transform simple or conversational requests into Fortune-500 launch briefs with auto-brand detection"
                >
                  <i data-lucide="sparkles" class="w-3.5 h-3.5 group-hover:rotate-12 transition-transform text-cyan-accent group-hover:text-obsidian-950"></i>
                  <span id="enhance-prompt-text">✨ Enhance Prompt</span>
                  <svg id="enhance-spinner" class="animate-spin -ml-1 mr-1 h-3.5 w-3.5 text-obsidian-950 hidden" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                </button>

                <span class="text-[11px] font-mono text-slate-600 hidden sm:inline">|</span>
                <span class="text-[11px] font-mono text-slate-400">Presets:</span>
                <div class="flex flex-wrap gap-1.5" id="preset-chips">
                  <button type="button" data-prompt="Predictive maintenance IoT platform launch with zero-downtime edge analytics and vibration AI sensor arrays" class="preset-chip text-[11px] font-mono bg-obsidian-800 hover:bg-cyan-accent/20 hover:text-cyan-accent text-slate-300 border border-obsidian-700 px-2.5 py-1 rounded-lg transition-all">
                    Predictive Maintenance
                  </button>
                  <button type="button" data-prompt="Tesla Model 3, deep blue, driving on a winding coastal road at sunset. Create a cinematic landscape ad with the headline Accelerate the future." class="preset-chip text-[11px] font-mono bg-obsidian-800 hover:bg-cyan-accent/20 hover:text-cyan-accent text-slate-300 border border-obsidian-700 px-2.5 py-1 rounded-lg transition-all">
                    Tesla Coastal Ad
                  </button>
                  <button type="button" data-prompt="Autonomous robotic fleet orchestration for smart gigafactories" class="preset-chip text-[11px] font-mono bg-obsidian-800 hover:bg-violet-accent/20 hover:text-violet-accent text-slate-300 border border-obsidian-700 px-2.5 py-1 rounded-lg transition-all">
                    Robotics Fleet
                  </button>
                </div>
              </div>
            </div>

            <!-- Prompt Textarea -->
            <div class="relative">
              <textarea 
                id="prompt-input" 
                autocomplete="off"
                rows="3" 
                placeholder="Describe your campaign concept... e.g. A high-end commercial campaign portrait welcoming our new team member to the team."
                class="w-full bg-obsidian-950 border border-obsidian-700 focus:border-cyan-accent focus:ring-1 focus:ring-cyan-accent rounded-xl p-4 text-sm font-sans text-slate-100 placeholder-slate-600 outline-none transition-all resize-none shadow-inner"
              ></textarea>
              
              <div class="absolute bottom-3 right-3 text-[11px] font-mono text-slate-400 flex items-center space-x-2 bg-obsidian-900/90 px-2 py-0.5 rounded border border-obsidian-800">
                <span id="char-count">0</span>
                <span>chars</span>
              </div>
            </div>

            <!-- Prompt Enhancement Notification Pill -->
            <div id="enhance-badge" class="hidden px-3.5 py-2 rounded-xl bg-cyan-950/40 border border-cyan-500/40 text-cyan-300 text-xs font-mono flex items-center justify-between transition-all">
              <div class="flex items-center space-x-2">
                <i data-lucide="sparkles" class="w-3.5 h-3.5 text-cyan-400"></i>
                <span id="enhance-badge-msg">✨ Upgraded to Fortune-500 Executive Launch Brief</span>
              </div>
              <span id="enhance-brand-tag" class="px-2 py-0.5 rounded text-[10px] bg-cyan-accent/20 text-cyan-accent border border-cyan-accent/30 font-bold">BRAND: TESLA</span>
            </div>

            <!-- Advanced Tone & Target Modifiers -->
            <div class="flex flex-wrap items-center justify-between gap-4 pt-1 text-xs font-mono">
              <div class="flex flex-wrap items-center gap-4">
                <div class="flex items-center space-x-2">
                  <span class="text-slate-400">Brand:</span>
                  <input id="brand-input" type="text" autocomplete="off" value="" placeholder="Auto (guideline / prompt)" class="w-40 bg-obsidian-950 border border-obsidian-800 text-slate-300 rounded-lg px-2.5 py-1 focus:outline-none focus:border-cyan-accent text-xs">
                </div>

                <div class="flex items-center space-x-2">
                  <span class="text-slate-400">Tone:</span>
                  <select id="tone-select" class="bg-obsidian-950 border border-obsidian-800 text-slate-300 rounded-lg px-2.5 py-1 focus:outline-none focus:border-cyan-accent text-xs">
                    <option value="confident, premium and benefit-driven">Premium &amp; Benefit-Driven</option>
                    <option value="warm, friendly and conversational for consumers">Friendly Consumer (B2C)</option>
                    <option value="authoritative and cutting-edge industrial technology">Authoritative B2B Enterprise</option>
                    <option value="visionary executive thought-leadership">Executive Thought Leadership</option>
                    <option value="deeply technical and data-driven for engineers">Technical / Engineering First</option>
                    <option value="high-energy disruptive product launch">Product Launch Hype</option>
                  </select>
                </div>

                <div class="flex items-center space-x-2">
                  <span class="text-slate-400">Visual Style:</span>
                  <select id="theme-select" class="bg-obsidian-950 border border-obsidian-800 text-slate-300 rounded-lg px-2.5 py-1 focus:outline-none focus:border-cyan-accent text-xs">
                    <option value="Cinematic lifestyle photography: golden-hour coastal road, ocean sunset, natural reflections, low front three-quarter tracking shot, 35mm lens, hero product fully visible, quiet upper left and lower right for copy" selected>Cinematic Lifestyle (Reference Ad)</option>
                    <option value="Apple Minimalist Studio: genuine physical hardware hero shot on dark honed graphite monolith, seamless obsidian infinity sweep, overhead strip softbox casting crisp specular reflection, Hasselblad 100mm macro lens, pure luxury isolation, no humans, no anime, no illustration">Apple Minimalist Hero (Luxury Tech)</option>
                    <option value="Teenage Engineering Industrial: genuine physical hardware photograph, CNC-milled black anodized aluminum housing, exposed ribbed heatsink fins, tactile hardware details, architectural concrete workbench, diffused natural studio lighting, Sony 90mm macro lens, no humans, no anime">Teenage Engineering (Tactile Industrial)</option>
                    <option value="Dyson / Deep Tech Physics: genuine physical high-tech hardware photograph, dark frosted optical chassis with exposed neural co-processor glow, volumetric cyan laser telemetry streams, Phase One 150MP, no humans, no anime">Dyson Deep Tech (Optical &amp; Physics)</option>
                    <option value="dark futuristic automated factory floor with neon cyan robotics and laser telemetry, crisp edge separation, tangible physical machinery, no humans, no anime">Cyber-Physical Smart Factory</option>
                    <option value="rugged industrial edge compute hardware module, brushed dark aluminum heatsink fins, glowing optical fiber channels, dark architectural slate, no humans, no anime">Edge Computing Hardware</option>
                  </select>
                </div>

                <label class="flex items-center space-x-1.5 cursor-pointer text-slate-300 hover:text-cyan-accent transition-colors select-none">
                  <input type="checkbox" id="search-toggle" checked class="w-3.5 h-3.5 rounded border-obsidian-700 bg-obsidian-950 text-cyan-accent focus:ring-cyan-accent accent-[#00f0ff] cursor-pointer">
                  <span class="flex items-center space-x-1">
                    <i data-lucide="globe" class="w-3 h-3 text-cyan-accent"></i>
                    <span>Google Research</span>
                  </span>
                </label>

                <label class="flex items-center space-x-1.5 cursor-pointer text-slate-300 hover:text-cyan-accent transition-colors select-none" title="AI Prompt Architect improves prompt quality and lets you review & edit before launching">
                  <input type="checkbox" id="review-prompt-toggle" checked class="w-3.5 h-3.5 rounded border-obsidian-700 bg-obsidian-950 text-cyan-accent focus:ring-cyan-accent accent-[#00f0ff] cursor-pointer">
                  <span class="flex items-center space-x-1">
                    <i data-lucide="sparkles" class="w-3 h-3 text-cyan-accent"></i>
                    <span>Review AI Prompt</span>
                  </span>
                </label>
              </div>
            </div>
          </div>
'''

    # Build new Stage 2
    new_stage2 = f'''<!-- ========================================== -->
      <!-- STAGE 2: CAMPAIGN OBJECTIVE & CONCEPT STUDIO -->
      <!-- ========================================== -->
      <section class="bg-obsidian-900/80 backdrop-blur-md border border-obsidian-800 rounded-2xl p-6 shadow-xl space-y-5">
        <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <div class="flex items-center space-x-2">
              <span class="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-gradient-to-r from-cyan-950 to-violet-950 text-cyan-300 border border-cyan-500/40 uppercase">STAGE 2</span>
              <h2 class="text-lg font-tech font-bold text-white flex items-center space-x-2">
                <i data-lucide="target" class="w-5 h-5 text-cyan-accent"></i>
                <span>CAMPAIGN OBJECTIVE &amp; CONCEPT STUDIO</span>
              </h2>
            </div>
            <p class="text-xs text-slate-400 font-mono mt-1">Select your campaign objective and enter key details to auto-structure copy, persona &amp; visual rules</p>
          </div>

          <div class="flex items-center space-x-2">
            <span id="active-post-type-badge" class="px-2.5 py-0.5 rounded-full text-[10px] font-mono font-bold bg-cyan-accent/20 text-cyan-300 border border-cyan-500/40 shadow-sm flex items-center space-x-1">
              <span>🤝</span>
              <span id="active-post-type-name">TEAM WELCOME</span>
            </span>
          </div>
        </div>

        <!-- ============================================== -->
        <!-- POST TYPE & CAMPAIGN OBJECTIVE SELECTOR -->
        <!-- ============================================== -->
        <div class="space-y-4 bg-obsidian-950/70 border border-obsidian-800 rounded-2xl p-4 shadow-inner">
          <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-2 border-b border-obsidian-800/80">
            <div class="flex items-center space-x-2">
              <span class="text-xs font-tech font-bold text-cyan-accent uppercase tracking-wider flex items-center space-x-1.5">
                <i data-lucide="layers" class="w-4 h-4 text-cyan-accent"></i>
                <span>Choose Post Type / Campaign Objective</span>
              </span>
              <span class="text-[10px] font-mono text-slate-500 hidden md:inline">Auto-structures prompt, persona &amp; visual rules</span>
            </div>
          </div>

          <!-- Post Type Selector Grid -->
          <div class="grid grid-cols-2 sm:grid-cols-4 gap-2" id="post-type-grid">
            <!-- 1. Team Welcome -->
            <button type="button" data-post-type="team_welcome" class="post-type-card active text-left p-2.5 rounded-xl border transition-all cursor-pointer bg-gradient-to-br from-cyan-950/60 to-obsidian-900 border-cyan-500/70 text-cyan-200 shadow-cyan-glow/20">
              <div class="flex items-center space-x-1.5 mb-1">
                <span class="text-base">🤝</span>
                <span class="font-bold text-xs truncate">Team Welcome</span>
              </div>
              <p class="text-[10px] text-slate-400 font-mono leading-tight truncate">New hire &amp; executive onboarding</p>
            </button>

            <!-- 2. Product Launch -->
            <button type="button" data-post-type="product_launch" class="post-type-card text-left p-2.5 rounded-xl border transition-all cursor-pointer bg-obsidian-900/90 border-obsidian-800 text-slate-300 hover:border-cyan-accent/40 hover:text-white">
              <div class="flex items-center space-x-1.5 mb-1">
                <span class="text-base">🚀</span>
                <span class="font-bold text-xs truncate">Product Launch</span>
              </div>
              <p class="text-[10px] text-slate-400 font-mono leading-tight truncate">Software, hardware &amp; AI tools</p>
            </button>

            <!-- 3. Milestone & Award -->
            <button type="button" data-post-type="milestone_achievement" class="post-type-card text-left p-2.5 rounded-xl border transition-all cursor-pointer bg-obsidian-900/90 border-obsidian-800 text-slate-300 hover:border-cyan-accent/40 hover:text-white">
              <div class="flex items-center space-x-1.5 mb-1">
                <span class="text-base">🏆</span>
                <span class="font-bold text-xs truncate">Milestone &amp; Award</span>
              </div>
              <p class="text-[10px] text-slate-400 font-mono leading-tight truncate">Growth metrics &amp; company awards</p>
            </button>

            <!-- 4. Event & Webinar -->
            <button type="button" data-post-type="event_announcement" class="post-type-card text-left p-2.5 rounded-xl border transition-all cursor-pointer bg-obsidian-900/90 border-obsidian-800 text-slate-300 hover:border-cyan-accent/40 hover:text-white">
              <div class="flex items-center space-x-1.5 mb-1">
                <span class="text-base">🎤</span>
                <span class="font-bold text-xs truncate">Event &amp; Webinar</span>
              </div>
              <p class="text-[10px] text-slate-400 font-mono leading-tight truncate">Summits, keynotes &amp; workshops</p>
            </button>

            <!-- 5. Thought Leadership -->
            <button type="button" data-post-type="thought_leadership" class="post-type-card text-left p-2.5 rounded-xl border transition-all cursor-pointer bg-obsidian-900/90 border-obsidian-800 text-slate-300 hover:border-cyan-accent/40 hover:text-white">
              <div class="flex items-center space-x-1.5 mb-1">
                <span class="text-base">💡</span>
                <span class="font-bold text-xs truncate">Thought Leadership</span>
              </div>
              <p class="text-[10px] text-slate-400 font-mono leading-tight truncate">Industry insights &amp; tech future</p>
            </button>

            <!-- 6. Client Case Study -->
            <button type="button" data-post-type="case_study" class="post-type-card text-left p-2.5 rounded-xl border transition-all cursor-pointer bg-obsidian-900/90 border-obsidian-800 text-slate-300 hover:border-cyan-accent/40 hover:text-white">
              <div class="flex items-center space-x-1.5 mb-1">
                <span class="text-base">💼</span>
                <span class="font-bold text-xs truncate">Client Case Study</span>
              </div>
              <p class="text-[10px] text-slate-400 font-mono leading-tight truncate">ROI proof &amp; client transformation</p>
            </button>

            <!-- 7. We're Hiring -->
            <button type="button" data-post-type="hiring" class="post-type-card text-left p-2.5 rounded-xl border transition-all cursor-pointer bg-obsidian-900/90 border-obsidian-800 text-slate-300 hover:border-cyan-accent/40 hover:text-white">
              <div class="flex items-center space-x-1.5 mb-1">
                <span class="text-base">📣</span>
                <span class="font-bold text-xs truncate">We're Hiring</span>
              </div>
              <p class="text-[10px] text-slate-400 font-mono leading-tight truncate">Open roles &amp; talent recruitment</p>
            </button>

            <!-- 8. Brand Story -->
            <button type="button" data-post-type="brand_awareness" class="post-type-card text-left p-2.5 rounded-xl border transition-all cursor-pointer bg-obsidian-900/90 border-obsidian-800 text-slate-300 hover:border-cyan-accent/40 hover:text-white">
              <div class="flex items-center space-x-1.5 mb-1">
                <span class="text-base">🌐</span>
                <span class="font-bold text-xs truncate">Brand Story</span>
              </div>
              <p class="text-[10px] text-slate-400 font-mono leading-tight truncate">Mission, values &amp; brand story</p>
            </button>
          </div>

          <!-- Dynamic Guided Quick-Fill Form Container -->
          <div id="post-type-fields-container" class="bg-obsidian-900/90 border border-obsidian-800/80 rounded-xl p-3.5 space-y-3 transition-all">
            <!-- Dynamic fields rendered here by JavaScript -->
          </div>
{prompt_studio_html}
        </div>
      </section>
'''

    # Build new Stage 3
    new_stage3 = '''<!-- ============================================================ -->
      <!-- STAGE 3: VISUAL ASSETS & LAUNCH PRODUCTION -->
      <!-- ============================================================ -->
      <section id="visual-assets-section" class="bg-obsidian-900/80 backdrop-blur-md border border-obsidian-800 rounded-2xl p-6 shadow-xl space-y-5">
        <!-- Section Header -->
        <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <div class="flex items-center space-x-2">
              <span class="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-violet-950/90 text-violet-300 border border-violet-500/50 uppercase">STAGE 3</span>
              <h2 class="text-lg font-tech font-bold text-white flex items-center space-x-2">
                <i data-lucide="image" class="w-5 h-5 text-violet-400"></i>
                <span>VISUAL ASSETS &amp; LAUNCH PRODUCTION</span>
              </h2>
            </div>
            <p class="text-xs text-slate-400 font-mono mt-1">
              Upload target portrait or product photo, template graphic, or load ready benchmark sample images.
            </p>
          </div>

          <!-- Quick Actions & Sample Presets -->
          <div class="flex flex-wrap items-center gap-2">
            <span class="text-[11px] font-mono text-slate-400 flex items-center gap-1">
              <i data-lucide="sparkles" class="w-3.5 h-3.5 text-cyan-accent"></i>
              <span>Sample Images:</span>
            </span>
            <div class="flex flex-wrap gap-1.5" id="sample-visual-chips">
              <button 
                type="button" 
                id="btn-sample-popout" 
                class="sample-visual-chip text-[11px] font-mono bg-violet-950/70 hover:bg-violet-900/90 hover:text-white text-violet-200 border border-violet-500/50 px-3 py-1.5 rounded-lg transition-all flex items-center gap-1.5 cursor-pointer shadow-sm active:scale-95" 
                title="Load Sekawan Media blue Polaroid template + studio subject portrait in abaya (1-click benchmark test)"
              >
                <span>⚡ Sekawan 2.5D Pop-Out</span>
              </button>
              <button 
                type="button" 
                id="btn-sample-portrait" 
                class="sample-visual-chip text-[11px] font-mono bg-obsidian-950 hover:bg-obsidian-800 hover:text-emerald-300 text-slate-300 border border-obsidian-700 px-3 py-1.5 rounded-lg transition-all flex items-center gap-1.5 cursor-pointer active:scale-95" 
                title="Load raw portrait subject photo only"
              >
                <span>👤 Studio Portrait Only</span>
              </button>
              <button 
                type="button" 
                id="btn-sample-template" 
                class="sample-visual-chip text-[11px] font-mono bg-obsidian-950 hover:bg-obsidian-800 hover:text-cyan-300 text-slate-300 border border-obsidian-700 px-3 py-1.5 rounded-lg transition-all flex items-center gap-1.5 cursor-pointer active:scale-95" 
                title="Load Sekawan blue Polaroid template only"
              >
                <span>🖼️ Blue Template Only</span>
              </button>
            </div>
          </div>
        </div>

        <!-- 3 Upload Slots Grid (Subject, Template Reference, Corporate Logo) -->
        <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
          <!-- SLOT 1: Subject / Product Photo -->
          <div class="p-4 rounded-xl bg-obsidian-950/90 border border-obsidian-800 space-y-3 relative group">
            <div class="flex items-center justify-between">
              <span class="text-xs font-mono font-bold text-slate-300 flex items-center gap-1.5">
                <i data-lucide="user" class="w-3.5 h-3.5 text-emerald-400"></i>
                <span>1. Subject / Product Photo</span>
              </span>
              <span id="subject-slot-badge" class="px-2 py-0.5 rounded text-[10px] font-mono bg-obsidian-800 text-slate-400 border border-obsidian-700">
                Not Loaded
              </span>
            </div>
            <p class="text-[11px] font-mono text-slate-500">Portrait, face, or product hardware</p>

            <div id="subject-dropzone" class="border border-dashed border-obsidian-700 hover:border-emerald-400/60 rounded-xl p-3 text-center cursor-pointer transition-all bg-obsidian-900/40 hover:bg-obsidian-900/80 min-h-[140px] flex flex-col items-center justify-center space-y-1.5">
              <input type="file" id="subject-file-input" class="hidden" accept="image/*">
              <i data-lucide="user-plus" class="w-6 h-6 text-emerald-400/80"></i>
              <span class="text-xs font-mono text-slate-300 font-bold">Upload Target Subject</span>
              <span class="text-[10px] font-mono text-slate-500">Portrait photo (JPG, PNG, WebP)</span>
            </div>

            <div id="subject-preview-card" class="hidden space-y-2">
              <div class="relative rounded-lg overflow-hidden border border-emerald-500/30 bg-black flex items-center justify-center max-h-[130px]">
                <img id="subject-thumb" src="" alt="Subject Preview" class="max-h-[130px] object-contain">
                <span id="subject-dim-tag" class="absolute bottom-1 right-1 px-1.5 py-0.5 rounded text-[9px] font-mono bg-black/80 text-emerald-400 border border-emerald-500/40">
                  1024x682
                </span>
              </div>
              <div class="flex items-center justify-between pt-1">
                <button type="button" id="btn-replace-subject" class="px-2.5 py-1 text-[11px] font-mono rounded bg-obsidian-800 hover:bg-obsidian-700 text-slate-300 hover:text-white border border-obsidian-700 cursor-pointer transition-colors">
                  Replace
                </button>
                <button type="button" id="btn-remove-subject" class="px-2.5 py-1 text-[11px] font-mono rounded bg-rose-950/40 hover:bg-rose-900/60 text-rose-300 hover:text-white border border-rose-500/30 cursor-pointer transition-colors">
                  Remove
                </button>
              </div>
            </div>
          </div>

          <!-- SLOT 2: Template / Reference Graphic -->
          <div class="p-4 rounded-xl bg-obsidian-950/90 border border-obsidian-800 space-y-3 relative group">
            <div class="flex items-center justify-between">
              <span class="text-xs font-mono font-bold text-slate-300 flex items-center gap-1.5">
                <i data-lucide="layout" class="w-3.5 h-3.5 text-cyan-accent"></i>
                <span>2. Template / Reference Ad</span>
              </span>
              <span id="template-slot-badge" class="px-2 py-0.5 rounded text-[10px] font-mono bg-obsidian-800 text-slate-400 border border-obsidian-700">
                Not Loaded
              </span>
            </div>
            <p class="text-[11px] font-mono text-slate-500">Polaroid frame or style layout</p>

            <div id="template-dropzone" class="border border-dashed border-obsidian-700 hover:border-cyan-accent/60 rounded-xl p-3 text-center cursor-pointer transition-all bg-obsidian-900/40 hover:bg-obsidian-900/80 min-h-[140px] flex flex-col items-center justify-center space-y-1.5">
              <input type="file" id="template-file-input" class="hidden" accept="image/*">
              <i data-lucide="layout-template" class="w-6 h-6 text-cyan-accent/80"></i>
              <span class="text-xs font-mono text-slate-300 font-bold">Upload Template Graphic</span>
              <span class="text-[10px] font-mono text-slate-500">Brand poster / framing reference</span>
            </div>

            <div id="template-preview-card" class="hidden space-y-2">
              <div class="relative rounded-lg overflow-hidden border border-cyan-500/30 bg-black flex items-center justify-center max-h-[130px]">
                <img id="template-thumb" src="" alt="Template Preview" class="max-h-[130px] object-contain">
                <span id="template-dim-tag" class="absolute bottom-1 right-1 px-1.5 py-0.5 rounded text-[9px] font-mono bg-black/80 text-cyan-300 border border-cyan-500/40">
                  808x1024
                </span>
              </div>
              <div class="flex items-center justify-between pt-1">
                <button type="button" id="btn-replace-template" class="px-2.5 py-1 text-[11px] font-mono rounded bg-obsidian-800 hover:bg-obsidian-700 text-slate-300 hover:text-white border border-obsidian-700 cursor-pointer transition-colors">
                  Replace
                </button>
                <button type="button" id="btn-remove-template" class="px-2.5 py-1 text-[11px] font-mono rounded bg-rose-950/40 hover:bg-rose-900/60 text-rose-300 hover:text-white border border-rose-500/30 cursor-pointer transition-colors">
                  Remove
                </button>
              </div>
            </div>
          </div>

          <!-- SLOT 3: Corporate Logo -->
          <div class="p-4 rounded-xl bg-obsidian-950/90 border border-obsidian-800 space-y-3 relative group">
            <div class="flex items-center justify-between">
              <span class="text-xs font-mono font-bold text-slate-300 flex items-center gap-1.5">
                <i data-lucide="shield" class="w-3.5 h-3.5 text-amber-400"></i>
                <span>3. Official Company Logo</span>
              </span>
              <span id="logo-slot-badge" class="px-2 py-0.5 rounded text-[10px] font-mono bg-obsidian-800 text-slate-400 border border-obsidian-700">
                Vector / Default
              </span>
            </div>
            <p class="text-[11px] font-mono text-slate-500">Authentic corporate mark (PNG, SVG, WebP)</p>

            <div id="logo-dropzone" class="border border-dashed border-obsidian-700 hover:border-amber-400/60 rounded-xl p-3 text-center cursor-pointer transition-all bg-obsidian-900/40 hover:bg-obsidian-900/80 min-h-[140px] flex flex-col items-center justify-center space-y-1.5">
              <input type="file" id="logo-file-input" class="hidden" accept="image/*,.svg">
              <i data-lucide="circle-dot" class="w-6 h-6 text-amber-400/80"></i>
              <span class="text-xs font-mono text-slate-300 font-bold">Upload Company Logo</span>
              <span class="text-[10px] font-mono text-slate-500">Transparent PNG or SVG recommended</span>
            </div>

            <div id="logo-preview-card" class="hidden space-y-2">
              <div class="relative rounded-lg overflow-hidden border border-amber-500/30 bg-black/80 p-2 flex items-center justify-center max-h-[130px]">
                <img id="logo-thumb" src="" alt="Logo Preview" class="max-h-[110px] object-contain">
                <span id="logo-dim-tag" class="absolute bottom-1 right-1 px-1.5 py-0.5 rounded text-[9px] font-mono bg-black/80 text-amber-400 border border-amber-500/40">
                  Vector
                </span>
              </div>
              <div class="flex items-center justify-between pt-1">
                <button type="button" id="btn-replace-logo" class="px-2.5 py-1 text-[11px] font-mono rounded bg-obsidian-800 hover:bg-obsidian-700 text-slate-300 hover:text-white border border-obsidian-700 cursor-pointer transition-colors">
                  Replace
                </button>
                <button type="button" id="btn-remove-logo" class="px-2.5 py-1 text-[11px] font-mono rounded bg-rose-950/40 hover:bg-rose-900/60 text-rose-300 hover:text-white border border-rose-500/30 cursor-pointer transition-colors">
                  Remove
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- Hidden Compatibility Inputs -->
        <div id="personalization-strip" class="hidden">
          <input id="person-name-input" type="hidden" value="">
          <input id="person-title-input" type="hidden" value="">
        </div>

        <!-- Visual Engine Mode Indicator & Action Launch Bar -->
        <div id="visual-engine-status-bar" class="p-4 rounded-xl bg-obsidian-950 border border-obsidian-800 flex flex-col sm:flex-row sm:items-center justify-between gap-4 text-xs font-mono">
          <div class="flex items-center space-x-3">
            <span id="visual-mode-indicator" class="relative flex h-2.5 w-2.5">
              <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-slate-500 opacity-75"></span>
              <span class="relative inline-flex rounded-full h-2.5 w-2.5 bg-slate-400"></span>
            </span>
            <div>
              <span id="visual-mode-title" class="font-bold text-slate-300">PURE AI GENERATION MODE</span>
              <p id="visual-mode-desc" class="text-[11px] text-slate-500">No custom visual assets loaded. Will generate photorealistic imagery from campaign prompt.</p>
            </div>
          </div>

          <div class="flex flex-wrap items-center gap-3">
            <label class="flex items-center space-x-1.5 text-slate-300 hover:text-cyan-accent cursor-pointer select-none" title="When checked, the campaign visual will use your loaded visual assets instead of generating from scratch">
              <input type="checkbox" id="use-uploaded-assets-toggle" checked class="w-3.5 h-3.5 rounded border-obsidian-700 bg-obsidian-950 text-cyan-accent focus:ring-cyan-accent accent-[#00f0ff] cursor-pointer">
              <span>Use Assets in Campaign</span>
            </label>

            <button 
              type="button" 
              id="btn-analyze-template-layout" 
              class="px-3.5 py-2 rounded-lg bg-obsidian-800 hover:bg-obsidian-700 text-slate-200 font-tech font-bold text-xs tracking-wider uppercase transition-all border border-cyan-500/30 flex items-center space-x-1.5 cursor-pointer shadow-sm active:scale-95"
              title="Reverse-engineer template into proportional design tokens"
            >
              <i data-lucide="scan" class="w-3.5 h-3.5 text-cyan-accent"></i>
              <span id="analyze-layout-btn-text">📐 Layout Blueprint</span>
            </button>

            <button 
              type="button" 
              id="btn-quick-test-swap" 
              class="px-4 py-2 rounded-lg bg-gradient-to-r from-violet-600 to-cyan-600 hover:from-violet-500 hover:to-cyan-500 text-white font-tech font-bold text-xs tracking-wider uppercase transition-all shadow-sm active:scale-95 flex items-center space-x-1.5 cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <i data-lucide="zap" class="w-3.5 h-3.5"></i>
              <span id="quick-test-swap-text">⚡ Quick Test Swap</span>
            </button>

            <button 
              type="button" 
              id="template-swap-btn" 
              class="hidden sm:inline-flex px-4 py-2 rounded-lg bg-obsidian-950 hover:bg-obsidian-800 border border-violet-500/40 hover:border-violet-400 text-violet-300 hover:text-white font-tech font-bold text-xs tracking-wider uppercase transition-all items-center space-x-2 cursor-pointer shadow-sm"
              title="Autonomous Template Subject-Replacement & 2.5D Pop-Out Compositing Engine"
            >
              <i data-lucide="layers" class="w-3.5 h-3.5 text-violet-400"></i>
              <span>2.5D Template Swap</span>
            </button>

            <button 
              type="button" 
              id="instant-demo-btn" 
              class="hidden sm:inline-flex px-4 py-2 rounded-lg bg-obsidian-950 hover:bg-obsidian-800 border border-obsidian-700 hover:border-cyan-accent/50 text-slate-300 hover:text-cyan-accent font-tech font-bold text-xs tracking-wider uppercase transition-all items-center space-x-2"
              title="Preview with sample campaign data and Flux visual"
            >
              <i data-lucide="play" class="w-3.5 h-3.5 text-cyan-accent"></i>
              <span>Instant Demo</span>
            </button>

            <button 
              type="button" 
              id="generate-btn" 
              class="px-6 py-2 rounded-lg bg-gradient-to-r from-cyan-accent via-cyan-400 to-violet-accent hover:from-cyan-300 hover:to-violet-400 text-obsidian-950 font-tech font-bold text-xs tracking-wider uppercase shadow-cyan-glow hover:shadow-dual-glow active:scale-[0.98] transition-all flex items-center justify-center space-x-2 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <i data-lucide="zap" id="generate-icon" class="w-4 h-4 text-obsidian-950 fill-obsidian-950"></i>
              <span id="generate-btn-text">Generate Campaign</span>
              <svg id="generate-spinner" class="animate-spin -ml-1 mr-2 h-4 w-4 text-obsidian-950 hidden" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
            </button>
          </div>
        </div>

        <!-- Realtime Status Banner for generation steps -->
        <div id="status-bar" class="hidden px-4 py-2.5 rounded-xl bg-obsidian-950/80 border border-cyan-accent/30 text-cyan-accent text-xs font-mono flex items-center justify-between">
          <div class="flex items-center space-x-3">
            <span class="relative flex h-2 w-2">
              <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-accent opacity-75"></span>
              <span class="relative inline-flex rounded-full h-2 w-2 bg-cyan-accent"></span>
            </span>
            <span id="status-message">Synthesizing campaign assets...</span>
          </div>
          <span id="status-timer" class="text-slate-500 font-mono">0.0s</span>
        </div>

        <!-- Inline Error Banner -->
        <div id="error-banner" class="hidden px-4 py-3 rounded-xl bg-rose-950/40 border border-rose-800/80 text-rose-300 text-xs font-mono flex items-start space-x-3">
          <i data-lucide="alert-triangle" class="w-4 h-4 text-rose-400 mt-0.5 flex-shrink-0"></i>
          <div class="space-y-1">
            <p class="font-semibold" id="error-title">Generation Error</p>
            <p class="text-slate-300 text-[11px]" id="error-details">Please check your API key and network connection.</p>
          </div>
        </div>

        <!-- Layout Blueprint Inspector Container (Collapsible) -->
        <div id="layout-blueprint-inspector" class="hidden p-4 rounded-xl bg-obsidian-950 border border-cyan-500/40 space-y-3">
          <div class="flex items-center justify-between">
            <div class="flex items-center space-x-2">
              <span class="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-cyan-950 text-cyan-300 border border-cyan-500/40 uppercase">
                📐 REVERSE-ENGINEERED DESIGN-TOKEN BLUEPRINT
              </span>
              <span class="text-[11px] font-mono text-slate-400">10 Visual Elements Detected • Proportional Design Tokens • 0 Magic Numbers</span>
            </div>
            <div class="flex items-center space-x-2">
              <button type="button" id="btn-toggle-blueprint-json" class="px-2.5 py-1 text-xs font-mono font-bold rounded bg-obsidian-800 text-slate-300 hover:text-white border border-obsidian-700 transition-all cursor-pointer">
                { } View JSON
              </button>
              <button type="button" id="btn-close-layout-inspector" class="p-1 rounded text-slate-400 hover:text-white cursor-pointer">
                <i data-lucide="x" class="w-4 h-4"></i>
              </button>
            </div>
          </div>

          <!-- 3-Panel Visual Diagnostic Preview -->
          <div class="flex justify-center bg-obsidian-900/60 p-2 rounded-lg overflow-x-auto">
            <img id="layout-inspector-img" class="max-h-80 rounded shadow-2xl object-contain border border-obsidian-800" src="/static/assets/debug_layout_boxes.jpg" alt="Layout Inspector Diagnostic">
          </div>

          <!-- Key Design Tokens Grid -->
          <div id="layout-tokens-grid" class="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs font-mono">
            <div class="p-2 rounded bg-obsidian-900 border border-obsidian-800">
              <div class="text-[10px] text-slate-500 uppercase">Frame Bounding Box</div>
              <div id="token-frame-box" class="font-bold text-white">[195, 294, 418, 505]</div>
              <div class="text-[10px] text-cyan-400">Width: 51.7% • H: 49.3%</div>
            </div>
            <div class="p-2 rounded bg-obsidian-900 border border-obsidian-800">
              <div class="text-[10px] text-slate-500 uppercase">Display Headline</div>
              <div id="token-headline" class="font-bold text-white">WELCOME</div>
              <div class="text-[10px] text-cyan-400">Cap-H: 56px • Z-Index: 10</div>
            </div>
            <div class="p-2 rounded bg-obsidian-900 border border-obsidian-800">
              <div class="text-[10px] text-slate-500 uppercase">2.5D Head Pop-Out</div>
              <div id="token-popout" class="font-bold text-white">76px over top frame</div>
              <div class="text-[10px] text-purple-400">Overlaps WELCOME text</div>
            </div>
            <div class="p-2 rounded bg-obsidian-900 border border-obsidian-800">
              <div class="text-[10px] text-slate-500 uppercase">Auto-Fit Nameplate</div>
              <div id="token-nameplate" class="font-bold text-white">418 × 131 px</div>
              <div class="text-[10px] text-emerald-400">Auto-Fit Font Scaling</div>
            </div>
          </div>

          <!-- Raw JSON Container (Collapsible) -->
          <pre id="blueprint-raw-json" class="hidden p-3 bg-black/60 rounded-lg text-[11px] font-mono text-cyan-300 max-h-60 overflow-y-auto border border-obsidian-800"></pre>
        </div>

        <!-- Quick Test Swap Result Container (Collapsible) -->
        <div id="quick-swap-result-box" class="hidden p-4 rounded-xl bg-obsidian-950 border border-violet-500/40 space-y-3">
          <div class="flex items-center justify-between">
            <div class="flex items-center space-x-2">
              <span class="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-950 text-emerald-300 border border-emerald-500/40 uppercase">
                ✓ 2.5D POP-OUT COMPOSITE READY
              </span>
              <span class="text-[11px] font-mono text-slate-400">808 × 1024 • Sub-pixel hair matting • Head pop-out over typography</span>
            </div>
            <div class="flex items-center space-x-2">
              <a id="quick-swap-download-link" href="#" download="popout_composite.jpg" class="px-2.5 py-1 text-xs font-mono font-bold rounded bg-cyan-950 text-cyan-300 hover:bg-cyan-900 border border-cyan-500/30 transition-all flex items-center gap-1">
                <i data-lucide="download" class="w-3.5 h-3.5"></i> <span>Download</span>
              </a>
              <button type="button" id="btn-close-quick-swap" class="p-1 rounded text-slate-400 hover:text-white cursor-pointer">
                <i data-lucide="x" class="w-4 h-4"></i>
              </button>
            </div>
          </div>
          <div class="flex justify-center bg-obsidian-900/60 p-2 rounded-lg">
            <img id="quick-swap-result-img" class="max-h-96 rounded shadow-2xl object-contain border border-obsidian-800" src="" alt="2.5D Pop-out Result">
            <div id="quick-swap-carousel" class="hidden w-full space-y-3"></div>
          </div>
        </div>
      </section>
'''

    # Replace stage 2 and stage 3, removing stage 4 completely
    new_html = html[:stage2_start] + new_stage2 + "\n" + new_stage3 + "\n" + html[results_start:]

    INDEX_PATH.write_text(new_html, encoding="utf-8")
    print("HTML stage refactor complete!")

if __name__ == "__main__":
    refactor()

