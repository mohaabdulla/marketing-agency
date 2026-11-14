import {mountStudio, refreshStatus} from './video-studio.js';
import {mountContext} from './app-context.js';
import {mountAgency,mountAgencySystem} from './agency-workspaces.js';
import {mountCommandCenter} from './campaign-command-center.js';
const icon = paths => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;
// Lucide Image, Clapperboard, Settings2 and PanelLeft paths (ISC license).
const icons = [icon('<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-5-5L5 21"/>'),
  icon('<path d="M4 11h16v10H4zM4 11 2 5l17-4 2 6ZM6 4l4 5m3-7 4 5"/>'),
  icon('<path d="M20 7h-9M14 17H4M4 7h3m13 10h-3"/><circle cx="9" cy="7" r="2"/><circle cx="16" cy="17" r="2"/>')];
const rail = document.createElement('nav'); rail.className = 'studio-rail'; rail.setAttribute('aria-label', 'Workspaces'); rail.id = 'studio-navigation';
const agencyIcons=[
  icon('<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>'),
  icon('<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2m20 0v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/><circle cx="9" cy="7" r="4"/>'),
  icon('<circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>'),
  icon('<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>'),
  icon('<path d="M20 20H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2Z"/>')
];
// Lucide PenLine, Library, CalendarDays, ChartLine, FileText and ListChecks paths (ISC license).
const productionIcons=[
  icon('<path d="M12 20h9"/><path d="M16.4 3.6a2 2 0 0 1 2.8 2.8L7 18.6 3 20l1.4-4Z"/>'),
  icon('<path d="m16 6 4 14M12 6v14M8 8v12M4 4v16"/>'),
  icon('<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18M8 14h.01M12 14h.01M16 14h.01M8 18h.01M12 18h.01"/>'),
  icon('<path d="M3 3v18h18"/><path d="m7 15 4-5 4 3 5-7"/>'),
  icon('<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6M8 13h8M8 17h6"/>'),
  icon('<path d="m3 7 2 2 4-4M3 17l2 2 4-4M13 6h8M13 12h8M13 18h8"/>')
];
const destinations=[['agency-dashboard','Dashboard',agencyIcons[0]],['agency-command-center','Campaign Command Center',agencyIcons[4]],['agency-clients','Clients & Brands',agencyIcons[1]],['agency-research','Research',agencyIcons[2]],['agency-strategy','Strategy',agencyIcons[3]],['agency-campaigns','Campaigns',agencyIcons[4]],['agency-content','Content Studio',productionIcons[0]],['image','Image & GIF Studio',icons[0]],['video','Video Studio',icons[1]],['agency-audio','Audio & Subtitles',icons[1]],['agency-assets','Assets & Approvals',productionIcons[1]],['agency-publishing','Calendar & Publishing',productionIcons[2]],['agency-analytics','Analytics & Experiments',productionIcons[3]],['agency-reports','Reports & Learnings',productionIcons[4]],['agency-web','SEO & Landing Pages',agencyIcons[2]],['agency-crm','Email & CRM',agencyIcons[1]],['agency-paid','Paid Media Planning',productionIcons[3]],['agency-creators','Creators & UGC',agencyIcons[1]],['agency-operations','Operations',productionIcons[5]],['agency-privacy','Privacy & Retention',icons[2]],['settings','System Status',icons[2]]];
const workspaceKeys=destinations.map(x=>x[0]);
rail.innerHTML = `<div class="studio-brand"><b>L</b><span class="rail-label">LEXNIS</span></div>${destinations.map(([key,label,svg])=>`<button type="button" data-workspace="${key}" title="${label}">${svg}<span class="rail-label">${label}</span></button>`).join('')}<button type="button" class="rail-bottom" id="rail-collapse" title="Collapse navigation" aria-label="Collapse navigation">${icon('<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18m7-13-3 4 3 4"/>')}<span class="rail-label">Collapse sidebar</span></button>`;
const mobile = document.createElement('button'); mobile.className = 'studio-mobile-toggle'; mobile.type = 'button'; mobile.textContent = '☰ Workspaces'; mobile.setAttribute('aria-controls',rail.id); mobile.setAttribute('aria-expanded','false');
const backdrop = document.createElement('div'); backdrop.className = 'studio-backdrop';
document.body.prepend(backdrop,rail,mobile);
const remember = (key, value) => { try {localStorage.setItem(key,value);} catch {} };
const recalled = key => {try{return localStorage.getItem(key);}catch{return null;}};
document.body.classList.toggle('rail-collapsed', recalled('lexnis.railCollapsed') === 'true');
let returnFocus;
function drawer(open) {rail.inert=matchMedia('(max-width:640px)').matches&&!open;rail.classList.toggle('drawer-open',open);backdrop.classList.toggle('open',open);mobile.setAttribute('aria-expanded',String(open));if(open){returnFocus=document.activeElement;rail.querySelector('button').focus();}else if(returnFocus){returnFocus.focus();returnFocus=null;}}
drawer(false);window.addEventListener('resize',()=>{rail.inert=matchMedia('(max-width:640px)').matches&&!rail.classList.contains('drawer-open');});
mobile.onclick = () => drawer(!rail.classList.contains('drawer-open')); backdrop.onclick = () => drawer(false);
rail.addEventListener('keydown', event => {if(event.key === 'Escape'){drawer(false);return;}if(event.key==='Tab'&&rail.classList.contains('drawer-open')){const buttons=[...rail.querySelectorAll('button')];if(event.shiftKey&&document.activeElement===buttons[0]){buttons.at(-1).focus();event.preventDefault();}else if(!event.shiftKey&&document.activeElement===buttons.at(-1)){buttons[0].focus();event.preventDefault();}}});
document.getElementById('rail-collapse').onclick = () => {if(matchMedia('(max-width:640px)').matches){drawer(false);return;}document.body.classList.toggle('rail-collapsed');remember('lexnis.railCollapsed',document.body.classList.contains('rail-collapsed'));};
export async function switchWorkspace(name, focus = true) {
  if(!workspaceKeys.includes(name))name='image';
  for(const key of workspaceKeys)document.getElementById(`${key}-workspace`).hidden = key !== name;
  rail.querySelectorAll('[data-workspace]').forEach(b=>{if(b.dataset.workspace===name)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
  remember('lexnis.workspace',name);drawer(false);
  if(name==='video')await mountStudio();if(name==='settings'){await refreshStatus();await mountAgencySystem(document.getElementById('settings-workspace'));}
  if(name==='agency-command-center'){try{await mountCommandCenter(document.getElementById('agency-command-center-workspace'));}catch(error){document.getElementById('agency-command-center-workspace').textContent='Command Center error: '+error.message;}}
  else if(name.startsWith('agency-')){try{await mountAgency(name.slice(7),document.getElementById(`${name}-workspace`));}catch(error){document.getElementById(`${name}-workspace`).textContent='Agency workspace unavailable: '+error.message;}}
  if(name!=='image')document.getElementById('image-workspace').querySelectorAll('video,audio').forEach(x=>x.pause());
  if(name!=='video')document.getElementById('video-workspace').querySelectorAll('video,audio').forEach(x=>x.pause());
  if(focus){const heading=document.getElementById(`${name}-workspace`).querySelector('h1');if(heading){heading.tabIndex=-1;heading.focus({preventScroll:true});}}
}
rail.querySelectorAll('[data-workspace]').forEach(b=>b.onclick=()=>switchWorkspace(b.dataset.workspace));
window.addEventListener('lexnis:workspace',event=>switchWorkspace(event.detail.name));
mountContext();
window.addEventListener('lexnis:video',async event=>{await switchWorkspace('video');window.dispatchEvent(new CustomEvent('lexnis:video-import',{detail:event.detail}));});
switchWorkspace(recalled('lexnis.workspace') || 'image',false);
// Attach only to generated carousel output; never alter uploaded originals or old handlers.
function bridge() {
  const scope=document.getElementById('carousel-preview');if(!scope)return;
  scope.querySelectorAll('img,video').forEach(img=>{const raw=img.getAttribute('src');if(!raw)return;let parsed;try{parsed=new URL(raw,location.href);}catch{return;}const local=['localhost','127.0.0.1','[::1]'];if(parsed.origin!==location.origin&&!(local.includes(parsed.hostname)&&local.includes(location.hostname)))return;const source=parsed.pathname;if(!source.startsWith('/renders/')&&!source.startsWith('/static/assets/'))return;if(img.parentElement.querySelector('.image-video-actions'))return;
    const actions=document.createElement('div');actions.className='image-video-actions';
    for(const [label,mode] of [['Send to Video','editor'],['Animate Image','image-animation'],['Use as starting frame','image-to-video']]){const button=document.createElement('button');button.type='button';button.textContent=label;button.onclick=()=>window.dispatchEvent(new CustomEvent('lexnis:video',{detail:{source_url:source,mode}}));actions.append(button);}
    // Hand the generated file to the agency asset library; nothing is registered until the operator confirms there.
    const register=document.createElement('button');register.type='button';register.textContent='Register in Assets';register.onclick=()=>{window.dispatchEvent(new CustomEvent('lexnis:agency-asset',{detail:{media_url:source,origin:'generated'}}));switchWorkspace('agency-assets');};actions.append(register);
    img.parentElement.append(actions);
  });
}
new MutationObserver(bridge).observe(document.getElementById('image-workspace'),{childList:true,subtree:true});bridge();
