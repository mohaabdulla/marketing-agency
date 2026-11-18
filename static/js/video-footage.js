// Motion footage for storyboard scenes: licensed stock video search (Pexels / Pixabay) with credits.
import {api,post} from './video-api.js';

let cachedStatus=null;
/** Which stock libraries are configured on this computer (cached for the page). */
export async function stockStatus(){
  if(!cachedStatus)cachedStatus=api('/stock/status').catch(()=>({providers:[],gifs:''}));
  return cachedStatus;
}

/** Orientation that matches an aspect ratio such as "16:9". */
export function orientationFor(ratio){return ratio==='9:16'?'portrait':ratio==='1:1'?'square':'landscape';}

/** How the renderer frames a picture (mirrors video.sequence.frame_fit): the whole picture on a blurred
 *  fill when filling the frame would crop away more than a third of it or enlarge it more than 1.6x. */
export function frameFit(width,height,ratio,frameShort=1080){
  if(!width||!height)return 'cover';
  const [a,b]=ratio.split(':').map(Number),frame=a/b,image=width/height;
  const frameW=frame>=1?frameShort*frame:frameShort,frameH=frame>=1?frameShort:frameShort/frame;
  return Math.min(image/frame,frame/image)<.64||Math.max(frameW/width,frameH/height)>1.6?'contain':'cover';
}

/** Fill a <details> panel with a search box and a result grid; `choose(item)` receives the picked clip. */
export async function stockPanel(panel,{query,orientation,minSeconds,choose}){
  const status=await stockStatus(),ready=(status.providers||[]).filter(p=>p.configured);
  panel.replaceChildren();
  const summary=document.createElement('summary');summary.textContent='Find stock video';panel.append(summary);
  if(!ready.length){
    const note=document.createElement('p');note.className='vs-note';
    note.textContent='Search licensed stock video by adding a free API key on this computer: '
      +(status.providers||[]).map(p=>`${p.label} (${p.setting})`).join(' or ')+', then restart the server. '+(status.gifs||'');
    panel.append(note);return;
  }
  const row=document.createElement('div');row.className='vs-row';
  const input=document.createElement('input');input.type='search';input.maxLength=100;input.value=query||'';input.setAttribute('aria-label','Stock video search words');
  const button=document.createElement('button');button.type='button';button.textContent='Search '+ready.map(p=>p.label).join(' + ');
  row.append(input,button);
  const state=document.createElement('p');state.className='vbf-fit';state.setAttribute('role','status');
  const grid=document.createElement('div');grid.className='vbf-stock-grid';
  const licence=document.createElement('p');licence.className='vs-note';licence.textContent=ready.map(p=>p.licence).join(' ');
  panel.append(row,state,grid,licence);
  const run=async()=>{
    button.disabled=true;state.textContent='Searching…';grid.replaceChildren();
    try{
      const seconds=typeof minSeconds==='function'?minSeconds():minSeconds;
      const found=await post('/stock/search',{query:input.value,orientation,min_seconds:Math.max(0,+seconds||0)});
      state.textContent=found.results.length?`${found.results.length} clips long enough for this scene. Only the search words were sent.`:'No clips long enough for this scene; try other words.';
      for(const item of found.results){
        const card=document.createElement('button');card.type='button';card.className='vbf-stock-item';
        card.setAttribute('aria-label',`Use ${item.provider_label} clip by ${item.author||'unknown creator'}, ${item.duration} seconds`);
        if(item.preview_url){const img=document.createElement('img');img.src=item.preview_url;img.alt='';img.loading='lazy';card.append(img);}
        const meta=document.createElement('span');meta.textContent=`${item.duration} s · ${item.author||'Unknown'} · ${item.provider_label}`;card.append(meta);
        card.onclick=()=>{choose(item);state.textContent=`Chosen: ${item.provider_label} clip by ${item.author||'an unnamed creator'}. It is credited in the client kit.`;};
        grid.append(card);
      }
    }catch(error){state.textContent=error.message;}
    finally{button.disabled=false;}
  };
  button.onclick=run;input.onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();run();}};
}
