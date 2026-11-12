import {mountStudio, refreshStatus} from './video-studio.js';
const icon = paths => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;
// Lucide Image, Clapperboard, Settings2 and PanelLeft paths (ISC license).
const icons = [icon('<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-5-5L5 21"/>'),
  icon('<path d="M4 11h16v10H4zM4 11 2 5l17-4 2 6ZM6 4l4 5m3-7 4 5"/>'),
  icon('<path d="M20 7h-9M14 17H4M4 7h3m13 10h-3"/><circle cx="9" cy="7" r="2"/><circle cx="16" cy="17" r="2"/>')];
const rail = document.createElement('nav'); rail.className = 'studio-rail'; rail.setAttribute('aria-label', 'Workspaces'); rail.id = 'studio-navigation';
rail.innerHTML = `<div class="studio-brand"><b>L</b><span class="rail-label">LEXNIS</span></div>${['Image & GIF Studio','Video Studio','System Status'].map((name,i)=>`<button type="button" data-workspace="${['image','video','settings'][i]}" title="${name}">${icons[i]}<span class="rail-label">${name}</span></button>`).join('')}<button type="button" class="rail-bottom" id="rail-collapse" title="Collapse navigation" aria-label="Collapse navigation">${icon('<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18m7-13-3 4 3 4"/>')}<span class="rail-label">Collapse sidebar</span></button>`;
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
  if(!['image','video','settings'].includes(name))name='image';
  for(const key of ['image','video','settings'])document.getElementById(`${key}-workspace`).hidden = key !== name;
  rail.querySelectorAll('[data-workspace]').forEach(b=>{if(b.dataset.workspace===name)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
  remember('lexnis.workspace',name);drawer(false);
  if(name==='video')await mountStudio();if(name==='settings')await refreshStatus();
  if(name!=='image')document.getElementById('image-workspace').querySelectorAll('video,audio').forEach(x=>x.pause());
  if(name!=='video')document.getElementById('video-workspace').querySelectorAll('video,audio').forEach(x=>x.pause());
  if(focus){const heading=document.getElementById(`${name}-workspace`).querySelector('h1');if(heading){heading.tabIndex=-1;heading.focus({preventScroll:true});}}
}
rail.querySelectorAll('[data-workspace]').forEach(b=>b.onclick=()=>switchWorkspace(b.dataset.workspace));
window.addEventListener('lexnis:video',async event=>{await switchWorkspace('video');window.dispatchEvent(new CustomEvent('lexnis:video-import',{detail:event.detail}));});
switchWorkspace(recalled('lexnis.workspace') || 'image',false);
// Attach only to generated carousel output; never alter uploaded originals or old handlers.
function bridge() {
  const scope=document.getElementById('carousel-preview');if(!scope)return;
  scope.querySelectorAll('img,video').forEach(img=>{const raw=img.getAttribute('src');if(!raw)return;let parsed;try{parsed=new URL(raw,location.href);}catch{return;}const local=['localhost','127.0.0.1','[::1]'];if(parsed.origin!==location.origin&&!(local.includes(parsed.hostname)&&local.includes(location.hostname)))return;const source=parsed.pathname;if(!source.startsWith('/renders/')&&!source.startsWith('/static/assets/'))return;if(img.parentElement.querySelector('.image-video-actions'))return;
    const actions=document.createElement('div');actions.className='image-video-actions';
    for(const [label,mode] of [['Send to Video','editor'],['Animate Image','image-animation'],['Use as starting frame','image-to-video']]){const button=document.createElement('button');button.type='button';button.textContent=label;button.onclick=()=>window.dispatchEvent(new CustomEvent('lexnis:video',{detail:{source_url:source,mode}}));actions.append(button);}img.parentElement.append(actions);
  });
}
new MutationObserver(bridge).observe(document.getElementById('image-workspace'),{childList:true,subtree:true});bridge();
