// Content, assets, approvals, publishing export, analytics, reports and operations workspaces.
// Plugs into the schema-driven record pages in agency-workspaces.js; every action calls the API.
import {agencyApi as api, agencyPost as post, escapeHtml as e, human as titleCase} from './agency-api.js';
import {context, contextName} from './app-context.js';
import * as A from './agency-acquisition.js';
// States and enum values use hyphens ("checks-passed"); show them as words.
const human = key => titleCase(String(key).replaceAll('-', '_'));

export const GROUPS = {
  content: {title: 'Content Studio', description: 'Concepts, copy variants, scripts and storyboards, each tied to its campaign and brief.', types: ['concepts', 'copy', 'scripts', 'storyboards', 'shots','content-pillars','content-series']},
  assets: {title: 'Assets & Approvals', description: 'Registered files with checksums, versions, usage rights and version-specific approvals.', types: ['assets', 'licenses', 'approvals']},
  publishing: {title: 'Calendar & Publishing', description: 'Plan posts and export publication packages. Nothing is posted to an external platform from here.', types: ['calendar'], badge: 'LOCAL CORE · MANUAL POSTING'},
  analytics: {title: 'Analytics & Experiments', description: 'Metrics you enter or import, and experiments with computed results.', types: ['metrics', 'snapshots', 'experiments']},
  reports: {title: 'Reports & Learnings', description: 'Reports built from stored metrics, and learnings backed by evidence.', types: ['reports', 'learnings']},
  operations: {title: 'Operations', description: 'Tasks, scope, costs and internal pricing scenarios.', types: ['tasks', 'scope', 'costs', 'pricing']},
  ...A.GROUPS,
};
export const TITLES = {concepts: 'Creative concepts', copy: 'Copy variants', scripts: 'Scripts', storyboards: 'Storyboards', shots: 'Storyboard shots',
  assets: 'Assets', licenses: 'Usage rights', approvals: 'Approvals', calendar: 'Calendar entries', metrics: 'Metric definitions',
  snapshots: 'Metric values', experiments: 'Experiments', reports: 'Reports', learnings: 'Learnings', tasks: 'Tasks', scope: 'Scope items',
  costs: 'Costs', pricing: 'Pricing scenarios',...A.TITLES};
export const REFS = {brief_id: 'briefs', concept_id: 'concepts', script_id: 'scripts', storyboard_id: 'storyboards', image_asset_id: 'assets',
  video_asset_id: 'assets', asset_id: 'assets', asset_ids: 'assets', parent_asset_id: 'assets', license_id: 'licenses', copy_id: 'copy',
  metric_id: 'metrics', primary_metric_id: 'metrics', guardrail_metric_ids: 'metrics', metric_ids: 'metrics', experiment_ids: 'experiments',
  report_id: 'reports', depends_on_ids: 'tasks',...A.REFS};
export const FIELD_LABELS = {brief_id: 'Creative brief', concept_id: 'Creative concept', script_id: 'Script', storyboard_id: 'Storyboard',
  image_asset_id: 'Reference image (asset)', video_asset_id: 'Video clip (asset)', asset_id: 'Asset', asset_ids: 'Media assets',
  parent_asset_id: 'Derived from asset', license_id: 'Usage rights record', copy_id: 'Copy variant', metric_id: 'Metric',
  primary_metric_id: 'Primary metric', guardrail_metric_ids: 'Guardrail metrics', metric_ids: 'Metrics in this report',
  experiment_ids: 'Experiments', report_id: 'Report', depends_on_ids: 'Depends on tasks', generation_note: 'Generation provenance (as recorded by you)'};
export const HIDDEN = ['sha256', 'size', 'mime', 'stored_name', 'original_url', 'width', 'height', 'duration_seconds', 'asset_type','parent_asset_version'];
const APPROVABLE = new Set(['strategies', 'briefs', 'concepts', 'copy', 'scripts', 'storyboards', 'shots', 'assets', 'reports']);
const scoped = (client, path) => `/clients/${client}${path}`;
let specs;

async function download(path, fallback) {
  const response = await fetch('/api/agency' + path);
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(typeof data.detail === 'string' ? data.detail : data.detail?.message || `Download failed (${response.status})`);
  }
  const name = /filename="?([^";]+)"?/.exec(response.headers.get('content-disposition') || '')?.[1] || fallback;
  const link = document.createElement('a');
  link.href = URL.createObjectURL(await response.blob());
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 4000);
  return name;
}

const number = value => typeof value === 'number' ? (Number.isInteger(value) ? value.toLocaleString() : value.toLocaleString(undefined, {maximumFractionDigits: 4})) : value;
function tree(value) {
  if (value === null || value === undefined) return '<span class="ag-muted">n/a</span>';
  if (Array.isArray(value)) return value.length ? '<ol class="ag-tree">' + value.map(x => `<li>${tree(x)}</li>`).join('') + '</ol>' : '<span class="ag-muted">none</span>';
  if (typeof value === 'object') return '<dl class="ag-tree">' + Object.entries(value).map(([k, v]) => `<dt>${e(human(k))}</dt><dd>${tree(v)}</dd>`).join('') + '</dl>';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  return e(number(value));
}

// ---------------------------------------------------------------- nested objects in forms
const deref = (page, field) => field?.$ref ? page.schema().$defs[field.$ref.split('/').pop()] : field;
function subInput(name, raw, value, page) {
  const field = deref(page, raw.anyOf?.find(x => x.type !== 'null') || raw);
  const label = `<span>${e(human(name))}</span>`;
  if (field.enum) return `<label>${label}<select data-sub="${name}">${field.enum.map(x => `<option value="${e(x)}" ${x === value ? 'selected' : ''}>${e(x ? human(x) : '—')}</option>`).join('')}</select></label>`;
  if (field.type === 'boolean') return `<label class="ag-check"><input type="checkbox" data-sub="${name}" ${value ? 'checked' : ''}> ${e(human(name))}</label>`;
  if (['number', 'integer'].includes(field.type)) return `<label>${label}<input type="number" step="${field.type === 'integer' ? 1 : 'any'}" data-sub="${name}" data-number="true" value="${e(value ?? '')}"></label>`;
  if ((field.maxLength || 0) > 300) return `<label class="ag-wide">${label}<textarea data-sub="${name}" maxlength="${field.maxLength}" dir="auto">${e(value ?? '')}</textarea></label>`;
  return `<label>${label}<input data-sub="${name}" maxlength="${field.maxLength || 250}" value="${e(value ?? '')}" dir="auto"></label>`;
}
function row(page, definition, values, removable) {
  return `<fieldset class="ag-nested-row" data-row><div class="ag-fields">${Object.entries(definition.properties).map(([name, raw]) => subInput(name, raw, values?.[name] ?? raw.default, page)).join('')}</div>${removable ? '<button type="button" data-remove-row>Remove</button>' : ''}</fieldset>`;
}

export function field(page, key, raw, resolved, value) {
  if (page.kind === 'copy' && key === 'format' && specs) {
    return `<select data-field="format">${Object.entries(specs.formats).map(([id, s]) => `<option value="${id}" ${id === value ? 'selected' : ''}>${e(s.label)} · ${s.limit_type === 'hard' ? 'limit' : 'recommended'} ${s.max_chars}</option>`).join('')}</select><small>${e(specs.notice)}</small>`;
  }
  if (resolved.type === 'array' && resolved.items?.$ref) {
    const definition = deref(page, resolved.items);
    return `<div data-nested="${key}" data-array="true">${(value || []).map(v => row(page, definition, v, true)).join('')}</div><button type="button" data-add-row="${key}">+ Add ${e(human(key).replace(/s$/, '').toLowerCase())}</button><small>Up to ${resolved.maxItems || 50}.</small>`;
  }
  const definition = deref(page, resolved);
  if (definition?.type === 'object' && definition.properties) {
    return `<div data-nested="${key}">${row(page, definition, value || {}, false)}</div><small>Leave every field empty if not applicable.</small>`;
  }
  return null;
}

export function collect(page, data) {
  for (const box of page.$('[data-editor]').querySelectorAll('[data-nested]')) {
    const rows = [...box.querySelectorAll('[data-row]')].map(fieldset => {
      const out = {};
      for (const input of fieldset.querySelectorAll('[data-sub]')) {
        let value = input.type === 'checkbox' ? input.checked : input.value;
        if (input.dataset.number) value = value === '' ? null : Number(value);
        out[input.dataset.sub] = value;
      }
      return out;
    });
    if (box.dataset.array) data[box.dataset.nested] = rows;
    else data[box.dataset.nested] = Object.values(rows[0] || {}).some(v => v !== '' && v !== null && v !== false) ? rows[0] : null;
  }
}

// ---------------------------------------------------------------- per-kind editor replacements
export async function customEdit(page, item) {
  if (!specs) specs = await api('/channel-specs');
  if (page.kind === 'approvals') { if (item) await approvalView(page, item); else page.$('[data-editor]').innerHTML = '<div class="ag-empty">Approvals are requested from the record being reviewed (a copy variant, asset, brief, script…). Open it and choose “Request approval”.</div>'; return true; }
  if (page.kind === 'assets' && !item) { registerForm(page); return true; }
  return false;
}

function registerForm(page, prefill = {}) {
  const editor = page.$('[data-editor]');
  editor.innerHTML = `<h2>Register an asset</h2><p><small>${e(contextName())}. The file is copied into the agency asset store with a SHA-256 checksum, so later approvals refer to exactly this file.</small></p>
    <form data-register><div class="ag-fields">
    <label class="ag-wide">Name<input name="name" maxlength="160" value="${e(prefill.name || '')}" placeholder="Launch hero · English"></label>
    <label class="ag-wide">Application media URL<input name="media_url" maxlength="500" value="${e(prefill.media_url || '')}" placeholder="/renders/example.jpg"><small>A generated or uploaded file from Image &amp; GIF Studio (/renders/…, /uploads/…, /static/assets/…). Use “Register in Assets” under a generated image to fill this in.</small></label>
    <label class="ag-wide">…or Video Studio asset ID<input name="video_asset_id" maxlength="32" pattern="[a-f0-9]{32}" placeholder="32-character ID shown in Video Studio assets"></label>
    <label>Origin<select name="origin">${['generated', 'owned', 'client-provided', 'stock', 'creative-commons', 'unknown'].map(x => `<option ${x === (prefill.origin || 'unknown') ? 'selected' : ''} value="${x}">${human(x)}</option>`).join('')}</select></label>
    <label>Language<select name="language"><option value="">Not language-specific</option><option value="en">English</option><option value="ar">Arabic</option><option value="ar-BH">Arabic · Bahrain/GCC</option></select></label>
    </div><button class="primary" type="submit">Register asset</button></form>`;
  editor.querySelector('form').onsubmit = async event => {
    event.preventDefault();
    const form = new FormData(event.target), ctx = context();
    try {
      const saved = await post(scoped(page.client, '/assets/register'), {name: form.get('name'), media_url: form.get('media_url').trim(), video_asset_id: form.get('video_asset_id').trim(),
        origin: form.get('origin'), language: form.get('language'), campaign_id: ctx.campaign_id || null, project_id: ctx.campaign_id ? null : ctx.project_id || null});
      page.options = {};
      await page.load();
      await page.edit(saved);
      page.status('Registered · checksum ' + saved.data.sha256.slice(0, 12) + '… · add usage rights before publishing.');
    } catch (error) { page.status(error.message, true); }
  };
}
window.addEventListener('lexnis:agency-asset', event => { pendingAsset = event.detail; });
let pendingAsset = null;
export function activated(page) {
  if (page.name === 'assets' && pendingAsset && page.client) {
    const prefill = pendingAsset; pendingAsset = null;
    page.selectKind('assets').then(() => registerForm(page, prefill));
  }
}

async function approvalView(page, item) {
  const d = item.data, editor = page.$('[data-editor]'), open = ['review-requested', 'changes-requested'].includes(d.state);
  let target = null;
  try { target = await api(scoped(page.client, '/record/' + d.target_id)); } catch { /* archived or removed targets still show their frozen details */ }
  const stale = target && target.version !== d.target_version;
  const preview = d.target_kind === 'assets' ? `<p><a class="ag-button" target="_blank" rel="noopener" href="/api/agency/clients/${page.client}/assets/${d.target_id}/file?version=${d.target_version}">Open reviewed file · v${d.target_version}</a></p>` : '';
  editor.innerHTML = `<h2>Approval · ${e(d.target_name)}</h2>
    <p><span class="ag-state" data-state="${e(d.state)}">${e(human(d.state))}</span> ${e(TITLES[d.target_kind] || d.target_kind)} · reviewed version <strong>v${d.target_version}</strong>${d.target_sha256 ? ` · SHA-256 ${e(d.target_sha256.slice(0, 16))}…` : ''}</p>
    <p><small>Reviewer: ${e(d.reviewer)}${d.due_date ? ' · due ' + e(d.due_date) : ''}${d.decided_at ? ' · decided ' + e(new Date(d.decided_at).toLocaleString()) : ''}</small></p>
    ${d.request_note ? `<p dir="auto">${e(d.request_note)}</p>` : ''}${preview}
    ${stale ? `<div class="ag-note">The record is now at v${target.version}. This request covers v${d.target_version} only; request approval of the current version from the record.</div>` : ''}
    <h3>Review history</h3><div class="ag-list">${d.comments.length ? d.comments.map(c => `<div class="ag-item"><small>${e(c.author)} · ${e(new Date(c.at).toLocaleString())}${c.timecode_seconds !== null && c.timecode_seconds !== undefined ? ' · at ' + c.timecode_seconds + 's' : ''}${c.decision ? ' · <strong>' + e(human(c.decision)) + '</strong>' : ''}</small><p dir="auto">${e(c.text) || '<span class="ag-muted">No comment</span>'}</p></div>`).join('') : '<div class="ag-empty">No comments yet.</div>'}</div>
    ${open && !stale ? `<form data-review style="margin-top:16px"><div class="ag-fields"><label>Your name<input name="reviewer" required maxlength="250" value="${e(d.reviewer)}"></label><label>Timecode (seconds, optional)<input name="timecode" type="number" min="0" step="any"></label><label class="ag-wide">Comment<textarea name="text" maxlength="6000" dir="auto"></textarea></label></div><div class="ag-row"><button type="button" data-act="comment">Add comment</button><button type="button" class="primary" data-act="approved">Approve this version</button><button type="button" data-act="changes-requested">Request changes</button><button type="button" data-act="rejected">Reject</button></div><p><small>Approval applies to exactly v${d.target_version}. Any later edit needs a new review.</small></p></form>` : ''}`;
  editor.querySelectorAll('[data-act]').forEach(button => button.onclick = async () => {
    const form = new FormData(editor.querySelector('[data-review]')), act = button.dataset.act;
    try {
      let saved;
      if (act === 'comment') saved = await post(scoped(page.client, `/approvals/${item.id}/comments`), {expected_version: item.version, author: form.get('reviewer'), text: form.get('text'), timecode_seconds: form.get('timecode') === '' ? null : Number(form.get('timecode'))});
      else {
        const result = await post(scoped(page.client, `/approvals/${item.id}/decision`), {expected_version: item.version, decision: act, reviewer: form.get('reviewer'), text: form.get('text')});
        saved = result.approval;
        if (result.workflow.tasks_created.length) page.status(`Approved. Workflow rule opened ${result.workflow.tasks_created.length} production task(s) in Operations.`);
      }
      await page.load();
      await page.edit(saved);
    } catch (error) { page.status(error.message, true); }
  });
}

// ---------------------------------------------------------------- actions under an open record
export async function actions(page, item) {
  A.actions(page,item);
  const area = page.$('[data-actions]'), client = page.client, kind = page.kind;
  if (!item || !area) return;
  const add = html => area.insertAdjacentHTML('beforeend', html);
  const fail = error => page.status(error.message, true);
  const result = html => { let box = area.querySelector('[data-result]'); if (!box) { add('<div data-result class="ag-note" style="width:100%"></div>'); box = area.querySelector('[data-result]'); } box.innerHTML = html; };

  if (item.computed) add(`<details open class="ag-computed" style="width:100%"><summary>Calculated from the saved values (read-only)</summary>${tree(item.computed)}</details>`);
  if (kind === 'assets') {
    const d = item.data, file = `/api/agency/clients/${client}/assets/${item.id}/file`;
    add(`<div style="width:100%" class="ag-note"><strong>${e(human(d.asset_type))}</strong> · ${(d.size / 1024).toFixed(1)} KB${d.width ? ` · ${d.width}×${d.height}` : ''}${d.duration_seconds ? ` · ${d.duration_seconds}s` : ''} · ${e(d.mime)}<br><small>SHA-256 ${e(d.sha256)}</small>${d.mime.startsWith('image/') ? `<br><img class="ag-preview" src="${file}?version=${item.version}" alt="${e(item.name)}">` : ''}</div>
      <a class="ag-button" href="${file}?download=true">Download current file</a><input data-new-file placeholder="/renders/new-version.jpg" aria-label="Media URL of the new file version" style="max-width:260px"><button data-add-version>Add new file version</button>`);
    area.querySelector('[data-add-version]').onclick = async () => {
      try { const saved = await post(scoped(client, `/assets/${item.id}/version`), {expected_version: item.version, media_url: area.querySelector('[data-new-file]').value.trim()}); await page.load(); await page.edit(saved); page.status('New file version saved · earlier versions and their approvals are retained.'); } catch (error) { fail(error); }
    };
  }
  if (kind === 'copy') {
    add('<button data-copy-checks>Run copy checks</button>');
    area.querySelector('[data-copy-checks]').onclick = async () => {
      try {
        const d = page.collect().data;
        const r = await post(scoped(client, `/campaigns/${item.campaign_id}/copy-checks`), {format: d.format, text: d.text, headline: d.headline, cta: d.cta, hashtags: d.hashtags, language: d.language, claim_ids: d.claim_ids, exclude_id: item.id});
        result(`<strong>${e(human(r.export_state))}</strong> · ${r.characters} / ${r.limit} characters (${e(r.format)}, ${r.limit_type === 'hard' ? 'limit' : 'recommended'})${r.flags.length ? '<ul>' + r.flags.map(f => `<li><strong>${f.severity === 'block' ? 'Must fix' : 'Review'}:</strong> ${e(f.message)}</li>`).join('') + '</ul>' : '<p>No configured flags found.</p>'}<small>${e(r.scope)}</small>`);
      } catch (error) { fail(error); }
    };
  }
  if (kind === 'scripts') {
    add('<button data-make-board>Create storyboard from this script</button>');
    area.querySelector('[data-make-board]').onclick = async () => {
      try { const made = await post(scoped(client, `/scripts/${item.id}/storyboard`)); page.options = {}; await page.selectKind('storyboards'); await page.edit(made.storyboard); page.status(`Storyboard created with ${made.shots.length} shot(s), one per scene. Add prompts or reference images to each shot.`); } catch (error) { fail(error); }
    };
  }
  if (kind === 'storyboards') {
    add('<button data-shot-list>Shot list &amp; timing</button><button data-video-project>Create Video Studio project</button><button data-board-export>Export storyboard (.zip)</button>');
    area.querySelector('[data-shot-list]').onclick = async () => {
      try {
        const r = await api(scoped(client, `/storyboards/${item.id}/shots`));
        const total = r.total_seconds || 1;
        result(`<strong>${r.shots.length} shots · ${r.total_seconds}s</strong><div class="ag-strip">${r.shots.map(s => `<span style="flex:${s.data.duration_seconds / total}" title="${e(s.name)} · ${s.data.duration_seconds}s">${s.data.sequence}</span>`).join('')}</div><div class="ag-table-wrap"><table class="ag-table"><thead><tr><th>#</th><th>Seconds</th><th>Picture</th><th>Voiceover / text</th><th>Media</th></tr></thead><tbody>${r.shots.map(s => `<tr><td>${s.data.sequence}</td><td>${s.data.duration_seconds}</td><td dir="auto">${e(s.data.description)}</td><td dir="auto">${e(s.data.voiceover || s.data.on_screen_text)}</td><td>${s.data.video_asset_id ? 'Video' : s.data.image_asset_id ? 'Image' : 'None yet'}</td></tr>`).join('')}</tbody></table></div><small>Edit shots under the “Storyboard shots” tab.</small>`);
      } catch (error) { fail(error); }
    };
    area.querySelector('[data-video-project]').onclick = async () => {
      try { const r = await post(scoped(client, `/storyboards/${item.id}/video-project`)); result(`<strong>Video project created:</strong> ${e(r.name)} · ${r.shots} shots · ${r.duration_seconds}s${r.slates ? ` · ${r.slates} plain slate(s) for shots without a picture` : ''}.<br><small>${e(r.note)}</small><br><button data-open-video>Open Video Studio</button>`); area.querySelector('[data-open-video]').onclick = () => window.dispatchEvent(new CustomEvent('lexnis:workspace', {detail: {name: 'video'}})); } catch (error) { fail(error); }
    };
    area.querySelector('[data-board-export]').onclick = () => download(scoped(client, `/storyboards/${item.id}/export`), 'storyboard.zip').then(name => page.status('Downloaded ' + name)).catch(fail);
    add('<button data-captions="srt">Captions from voiceover (.srt)</button><button data-captions="vtt">Captions (.vtt)</button>');
    area.querySelectorAll('[data-captions]').forEach(button => button.onclick = () => download(scoped(client, `/storyboards/${item.id}/captions?format=${button.dataset.captions}`), 'captions.' + button.dataset.captions).then(name => page.status('Downloaded ' + name + ' · timing follows the planned shot durations, not recorded audio. Re-time against the final edit.')).catch(fail));
  }
  if (kind === 'calendar') {
    add('<button data-package-draft>Export draft package</button><button class="primary" data-package-final>Export final publication package</button>');
    area.querySelector('[data-package-draft]').onclick = () => download(scoped(client, `/calendar/${item.id}/package?draft=true`), 'publication-package-DRAFT.zip').then(name => page.status('Downloaded ' + name + ' · open issues are listed in posting-checklist.txt')).catch(fail);
    area.querySelector('[data-package-final]').onclick = async () => { try { const name = await download(scoped(client, `/calendar/${item.id}/package?draft=false`), 'publication-package.zip'); await page.load(); page.status('Downloaded ' + name + ' · a person still posts it; record the post link here afterwards.'); } catch (error) { fail(error); } };
  }
  if (kind === 'reports') {
    add('<button class="primary" data-render-report>Render report (.zip: HTML, CSV, JSON)</button>');
    area.querySelector('[data-render-report]').onclick = () => download(scoped(client, `/reports/${item.id}/render`), 'report.zip').then(name => page.status('Downloaded ' + name + ' · FACT sections come only from stored metric values.')).catch(fail);
  }
  if (APPROVABLE.has(kind) && !item.archived) {
    let state = 'not-approved';
    try { state = (await api(scoped(client, `/record/${item.id}/approval-state`))).state; } catch { /* shown as not approved */ }
    if (page.opened?.id !== item.id) return;
    add(`<div class="ag-note" style="width:100%"><span class="ag-state" data-state="${e(state)}">v${item.version} · ${e(human(state))}</span><div class="ag-row" style="margin-top:8px"><input data-reviewer placeholder="Reviewer name" aria-label="Reviewer name" maxlength="250" style="max-width:220px"><button data-request-approval>Request approval of v${item.version}</button></div><small>Save your edits first: approval covers exactly the saved version.</small></div>`);
    area.querySelector('[data-request-approval]').onclick = async () => {
      try { const reviewer = area.querySelector('[data-reviewer]').value.trim(); if (!reviewer) throw new Error('Enter the reviewer’s name'); await post(scoped(client, '/approvals'), {target_id: item.id, reviewer}); page.status('Review requested for v' + item.version + '. Decide it under Assets & Approvals → Approvals.'); await page.edit(item); } catch (error) { fail(error); }
    };
  }
}

// ---------------------------------------------------------------- extra tools above the list
export function extras(page) {
  A.extras(page);
  const extra = page.$('[data-extra]'), client = page.client, editor = page.$('[data-editor]');
  const fail = error => page.status(error.message, true);
  if (page.kind === 'concepts') {
    extra.innerHTML = '<button data-matrix style="margin-top:12px">Build a concept matrix</button>';
    extra.querySelector('[data-matrix]').onclick = () => {
      const ctx = context();
      if (!ctx.campaign_id) { page.status('Choose a campaign in Agency Context first.', true); return; }
      const axes = [['hook_type', 'Hook types (authority, curiosity, problem, benefit, story, social-proof, offer, question)'], ['benefit', 'Benefits'], ['pain_point', 'Pain points'], ['awareness_stage', 'Awareness stages (unaware, problem-aware, solution-aware, product-aware, most-aware)'], ['appeal', 'Appeal (emotional, rational)'], ['visual_territory', 'Visual territories'], ['offer', 'Offers'], ['cta', 'Calls to action'], ['channel', 'Channels']];
      editor.innerHTML = `<h2>Concept matrix</h2><p>Enter the options you want to test, one per line. Every combination becomes a proposed concept (24 at most). Nothing is invented: rationale and copy stay yours to write.</p><form data-matrix-form><div class="ag-fields">${axes.map(([key, label]) => `<label>${e(label)}<textarea data-axis="${key}" dir="auto"></textarea></label>`).join('')}</div><button class="primary" type="submit">Create proposed concepts</button></form>`;
      editor.querySelector('form').onsubmit = async event => {
        event.preventDefault();
        const body = {axes: {}};
        editor.querySelectorAll('[data-axis]').forEach(t => { const lines = t.value.split('\n').map(x => x.trim()).filter(Boolean); if (lines.length) body.axes[t.dataset.axis] = lines; });
        try { const r = await post(scoped(client, `/campaigns/${ctx.campaign_id}/concept-matrix`), body); await page.load(); editor.innerHTML = `<div class="ag-empty">${r.combinations} proposed concepts created from ${r.axes.map(human).join(' × ')}. Open each to approve or reject it before producing assets.</div>`; } catch (error) { fail(error); }
      };
    };
  }
  if (page.kind === 'snapshots') {
    extra.innerHTML = '<label class="ag-note">Import metric values · UTF-8 CSV with columns date, metric, value (optional: channel, variant)<input type="file" data-metrics-csv accept=".csv"></label>';
    extra.querySelector('[data-metrics-csv]').onchange = async event => {
      const file = event.target.files[0]; if (!file) return;
      try { const form = new FormData(); form.append('file', file); const ctx = context(); const r = await api(scoped(client, '/analytics/import' + (ctx.campaign_id ? '?campaign_id=' + ctx.campaign_id : '')), {method: 'POST', body: form}); await page.load(); page.status(`Imported ${r.imported} values for ${r.metrics.join(', ')}. All rows are saved together or not at all.`); } catch (error) { fail(error); } finally { event.target.value = ''; }
    };
  }
  if (page.kind === 'metrics') {
    extra.innerHTML = '<button data-kpi style="margin-top:12px">View KPI summary</button>';
    extra.querySelector('[data-kpi]').onclick = async () => {
      try {
        const ctx = context(), r = await api(scoped(client, '/analytics/summary' + (ctx.campaign_id ? '?campaign_id=' + ctx.campaign_id : '')));
        const spark = series => { if (series.length < 2) return ''; const v = series.map(p => p.value), lo = Math.min(...v), span = (Math.max(...v) - lo) || 1; return `<svg viewBox="0 0 120 30" class="ag-spark" role="img" aria-label="Trend"><polyline fill="none" stroke="currentColor" stroke-width="1.5" points="${v.map((x, i) => `${4 + i * 112 / (v.length - 1)},${26 - (x - lo) * 22 / span}`).join(' ')}"/></svg>`; };
        editor.innerHTML = `<h2>KPI summary</h2><p><small>${ctx.campaign_id ? 'Selected campaign' : 'All campaigns for ' + e(contextName())}. ${e(r.attribution)}</small></p>${r.metrics.length ? '<div class="ag-table-wrap"><table class="ag-table"><thead><tr><th>Metric</th><th>Values</th><th>First</th><th>Latest</th><th>Change</th><th>Period</th><th>Trend</th></tr></thead><tbody>' + r.metrics.map(m => `<tr><td>${e(m.name)}<br><small>${e(m.aggregation)} · ${e(m.source)}</small></td><td>${m.observations}</td><td>${m.first ? number(m.first.value) + '<br><small>' + m.first.date + '</small>' : '—'}</td><td>${m.last ? number(m.last.value) + '<br><small>' + m.last.date + '</small>' : '—'}</td><td>${m.change === null ? '—' : (m.change > 0 ? '+' : '') + number(m.change) + (m.change_percent === null ? '' : ` (${m.change_percent.toFixed(1)}%)`)}</td><td>${m.overall === null ? '—' : number(m.overall)} ${e(m.unit)}</td><td>${spark(m.series)}</td></tr>`).join('') + '</tbody></table></div>' : '<div class="ag-empty">No metric definitions yet. Create one, then add or import values.</div>'}`;
      } catch (error) { fail(error); }
    };
  }
  if (page.kind === 'calendar') {
    extra.innerHTML = '<button data-schedule style="margin-top:12px">View schedule</button>';
    extra.querySelector('[data-schedule]').onclick = async () => {
      try {
        const ctx = context(), r = await api(scoped(client, '/schedule' + (ctx.campaign_id ? '?campaign_id=' + ctx.campaign_id : '')));
        const weeks = new Map();
        for (const item of r.items) { const d = new Date(item.data.scheduled_date + 'T00:00:00'); d.setDate(d.getDate() - ((d.getDay() + 6) % 7)); const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; /* local date: toISOString would shift the day in UTC+ zones */ if (!weeks.has(key)) weeks.set(key, []); weeks.get(key).push(item); }
        editor.innerHTML = `<h2>Schedule</h2><p><small>${e(r.note)}</small></p>${weeks.size ? [...weeks].map(([week, items]) => `<h3>Week of ${week}</h3><div class="ag-table-wrap"><table class="ag-table"><thead><tr><th>Date</th><th>Time</th><th>Channel</th><th>Entry</th><th>Status</th></tr></thead><tbody>${items.map(i => `<tr><td>${e(i.data.scheduled_date)}</td><td>${e(i.data.scheduled_time)} <small>${e(i.data.timezone)}</small></td><td>${e(i.data.channel)}</td><td>${e(i.name)}</td><td>${e(human(i.data.publish_status))}</td></tr>`).join('')}</tbody></table></div>`).join('') : '<div class="ag-empty">No calendar entries yet.</div>'}`;
      } catch (error) { fail(error); }
    };
  }
}

// Add / remove rows of nested lists (script scenes, experiment variants).
export function bind(page) {
  const editor = page.$('[data-editor]');
  const wire = box => box.querySelectorAll('[data-remove-row]').forEach(b => b.onclick = () => { b.closest('[data-row]').remove(); page.persistDraft(); });
  editor.querySelectorAll('[data-nested]').forEach(wire);
  editor.querySelectorAll('[data-add-row]').forEach(button => button.onclick = () => {
    const key = button.dataset.addRow, box = editor.querySelector(`[data-nested="${key}"]`);
    const definition = deref(page, page.resolve(page.schema().properties[key]).items);
    box.insertAdjacentHTML('beforeend', row(page, definition, {}, true));
    wire(box);
    page.persistDraft();
  });
}

export async function dashboard(root, ctx) {
  const slot = root.querySelector('[data-overview]');
  if (!slot || !ctx.client_id) return;
  try {
    const o = await api(scoped(ctx.client_id, '/overview'));
    const cards = [['Awaiting approval', o.awaiting_approval, 'agency-assets'], ['Changes requested', o.changes_requested, 'agency-assets'], ['Upcoming content', o.upcoming_content, 'agency-publishing'],
      ['Open tasks', o.open_tasks + (o.overdue_tasks ? ` · ${o.overdue_tasks} overdue` : ''), 'agency-operations'], ['Running experiments', o.running_experiments, 'agency-analytics'],
      ['Assets without rights', `${o.assets_without_rights} of ${o.registered_assets}`, 'agency-assets'], ['Failed jobs', o.failed_jobs, 'agency-research']];
    slot.innerHTML = `<h2 style="margin-top:22px">${e(contextName())} · work in progress</h2><div class="ag-metrics">${cards.map(([label, value, go]) => `<button class="ag-panel ag-metric" data-go="${go}"><small>${label}</small><strong>${e(value)}</strong></button>`).join('')}</div><small>Counts of saved records only. No engagement or revenue figure is shown unless you record it under Analytics.</small>`;
    slot.querySelectorAll('[data-go]').forEach(b => b.onclick = () => window.dispatchEvent(new CustomEvent('lexnis:workspace', {detail: {name: b.dataset.go}})));
  } catch { slot.textContent = ''; }
}
