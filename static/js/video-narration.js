// Offline AI narrator controls shared by the storyboard wizard and the company-introduction flow.
import {api,post} from './video-api.js';

let player=null;

/** Fill a <select> with the narrator voices installed for `language`, keeping the current choice
 *  when it is still offered. `emptyLabel(count)` names the "no narration" option. Returns the voices. */
export async function fillVoices(select,language,emptyLabel){
  const previous=select.value;let voices=[];
  try{voices=(await api('/voices?language='+encodeURIComponent(language))).voices||[];}catch{}
  select.replaceChildren(...voices.map(voice=>new Option(voice.name,voice.id)),new Option(emptyLabel(voices.length),''));
  select.value=voices.some(voice=>voice.id===previous)?previous:voices[0]?.id||'';
  return voices;
}

/** Scene lengths that follow how long each line takes to say, keeping the same total. */
export function fitTimings({voice,language,lines,durations}){
  return post('/voices/fit',{voice_id:voice,language,lines,durations:durations.map(Number)});
}

/** Record one narration line, play it, and say whether it fits its scene. `isBusy()` decides whether
 *  the button stays disabled afterwards (the surrounding form may be working). */
export async function previewLine({voice,text,language,duration,output,button,missingVoice,isBusy}){
  output.classList.remove('is-warning');
  if(!voice){output.textContent=missingVoice;return;}
  button.disabled=true;output.textContent='Recording the line…';
  try{
    const heard=await post('/voices/preview',{voice_id:voice,text,language,duration:+duration||null});
    player?.pause();player=new Audio(heard.audio);player.play().catch(()=>{});
    output.textContent=`${heard.spoken_seconds.toFixed(1)} s when spoken. ${heard.message||''}`;
    output.classList.toggle('is-warning',heard.fits===false);
  }catch(error){output.textContent=error.message;output.classList.add('is-warning');}
  finally{button.disabled=isBusy();}
}
