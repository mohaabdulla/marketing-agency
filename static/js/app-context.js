import {agencyApi,escapeHtml as e} from './agency-api.js';
const EMPTY = {client_id:'',project_id:'',campaign_id:'',language:'en'};
let state = {...EMPTY};
try {state={...EMPTY,...JSON.parse(localStorage.getItem('lexnis.agency.context')||'{}')};}catch{}
for(const key of ['client_id','project_id','campaign_id'])if(!/^[a-f0-9]{32}$/.test(state[key]||''))state[key]='';
if(!['en','ar','ar-BH'].includes(state.language))state.language='en';
let header, clients=[], projects=[], campaigns=[], revision=0;
export function context(){return {...state};}
export function contextName(){return clients.find(c=>c.id===state.client_id)?.name || 'No client selected';}
function persist(){try{localStorage.setItem('lexnis.agency.context',JSON.stringify(state));}catch{}}
function notify(){
  persist();
  if(window.agencyProductionContext&&(window.agencyProductionContext.client_id!==state.client_id||window.agencyProductionContext.campaign_id!==state.campaign_id))window.agencyProductionContext=null;
  window.dispatchEvent(new CustomEvent('lexnis:agency-context',{detail:context()}));
}
export async function setClient(key){state={...state,client_id:key,project_id:'',campaign_id:''};await refreshContext();notify();}
window.addEventListener('lexnis:agency-client-erased',event=>{
  document.querySelector('[data-privacy-result]')?.remove();
  const banner=document.createElement('div');banner.dataset.privacyResult='';banner.className='ag-status';banner.setAttribute('role','status');
  const message=document.createElement('p');message.textContent=event.detail.message||'Client erased. Review prior exported/downloaded copies separately.';
  const close=document.createElement('button');close.type='button';close.textContent='Dismiss';close.onclick=()=>banner.remove();banner.append(message,close);header?.after(banner);
  if(state.client_id===event.detail.client_id)setClient('').catch(showContextError);
});
export async function setCampaign(record){state={...state,client_id:record.client_id,project_id:record.project_id||'',campaign_id:record.id};await refreshContext();notify();}
export async function refreshContext(){
  const current=++revision;
  const result=await agencyApi('/clients?limit=100');
  if(current!==revision)return;
  clients=result.items;
  if(state.client_id&&!clients.some(c=>c.id===state.client_id)){
    try{const selected=await agencyApi('/clients/'+state.client_id);if(selected.status!=='archived')clients.push(selected);else state={...EMPTY,language:state.language};}
    catch(error){if(error.status===404)state={...EMPTY,language:state.language};else throw error;}
  }
  projects=[];campaigns=[];
  if(state.client_id){
    const prefix='/clients/'+state.client_id+'/records?summary=true&limit=100&kind=';
    const responses=await Promise.all([agencyApi(prefix+'projects'),agencyApi(prefix+'campaigns')]);
    if(current!==revision)return;
    [projects,campaigns]=responses.map(r=>r.items);
    for(const [key,kind,list] of [['project_id','projects',projects],['campaign_id','campaigns',campaigns]]){
      if(state[key]&&!list.some(r=>r.id===state[key])){
        try{const record=await agencyApi('/clients/'+state.client_id+'/record/'+state[key]);if(record.kind===kind&&!record.archived)list.push(record);else state[key]='';}
        catch(error){if(error.status===404)state[key]='';else throw error;}
      }
    }
    if(state.campaign_id){const campaign=campaigns.find(c=>c.id===state.campaign_id);if(campaign)state.project_id=campaign.project_id||'';}
  }else{state.project_id='';state.campaign_id='';}
  draw();persist();
}
function draw(){
  if(!header)return;
  const options=(items,selected,empty)=>`<option value="">${empty}</option>`+items.map(x=>`<option value="${x.id}" ${x.id===selected?'selected':''}>${e(x.name)}</option>`).join('');
  header.innerHTML=`<div class="agency-context-label">AGENCY CONTEXT <span>LOCAL CORE</span></div><label>Client<select id="agency-context-client">${options(clients,state.client_id,'Choose a client')}</select></label><label>Project<select id="agency-context-project" ${!state.client_id?'disabled':''}>${options(projects,state.project_id,'Client-wide')}</select></label><label>Campaign<select id="agency-context-campaign" ${!state.client_id?'disabled':''}>${options(campaigns.filter(c=>!state.project_id||c.project_id===state.project_id),state.campaign_id,'No campaign selected')}</select></label><label>Language / locale<select id="agency-context-language"><option value="en">English · International</option><option value="ar">Arabic · MSA</option><option value="ar-BH">Arabic · Bahrain/GCC review</option></select></label>`;
  header.querySelector('#agency-context-language').value=state.language;
  header.querySelector('#agency-context-client').onchange=event=>setClient(event.target.value).catch(showContextError);
  header.querySelector('#agency-context-project').onchange=event=>{state.project_id=event.target.value;state.campaign_id='';draw();notify();};
  header.querySelector('#agency-context-campaign').onchange=event=>{state.campaign_id=event.target.value;const campaign=campaigns.find(c=>c.id===state.campaign_id);if(campaign)state.project_id=campaign.project_id||'';draw();notify();};
  header.querySelector('#agency-context-language').onchange=event=>{state.language=event.target.value;notify();};
}
function showContextError(error){header.innerHTML=`<p role="alert">Agency context unavailable: ${e(error.message)}. Image and Video Studio remain available.</p>`;}
export async function mountContext(){
  if(header)return;
  header=document.createElement('header');header.className='agency-context';header.setAttribute('aria-label','Client, project, campaign and language');
  document.getElementById('image-workspace').before(header);
  try{await refreshContext();notify();}catch(error){showContextError(error);}
}
