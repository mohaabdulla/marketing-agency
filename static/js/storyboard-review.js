// Render server-owned editorial checks without interpreting any model text as markup.
export function drawStoryboardReview(host,report){
  host.replaceChildren();if(!report)return;
  const heading=document.createElement('h4');heading.textContent='Storyboard readiness';host.append(heading);
  for(const scene of report.scenes||[]){
    const line=document.createElement('p');line.textContent=`Scene ${scene.scene} · ${scene.beat.replaceAll('-',' ')} · ${scene.words} words · about ${scene.estimated_narration_seconds.toFixed(1)}s of speech / ${scene.duration}s available`;
    host.append(line);
  }
  const list=document.createElement('ul');
  for(const issue of report.issues||[]){const item=document.createElement('li');item.textContent=issue.message;list.append(item);}
  if(list.childElementCount)host.append(list);
  const note=document.createElement('p');note.textContent=report.notice;host.append(note);
}

// The writing review from video.script_writer: score, what the editor fixed, what is left, alternative openings.
// `useHook(hook)` is called when the person picks an alternative opening.
export function drawScriptReview(host,report,useHook){
  host.replaceChildren();if(!report)return;
  const add=(tag,text,parent=host)=>{const node=document.createElement(tag);node.textContent=text;parent.append(node);return node;};
  add('h4',`Script review · ${report.score}/100`);
  const editor=report.editor;
  add('p',editor?.used?(editor.accepted?`Revised once by the script editor (${editor.engine}); score ${report.score_before} → ${report.score}.`:editor.reason||'The editor revision was not better, so the draft was kept.')
    :'Checked against the script rules'+(editor?.reason?` (no editor model: ${editor.reason})`:'')+'.');
  if(report.fixed?.length){const list=add('ul','');add('li','Fixed: '+report.fixed.join(' '),list);}
  const open=(report.issues||[]).filter(issue=>issue.severity!=='suggestion'),hints=(report.issues||[]).filter(issue=>issue.severity==='suggestion');
  if(open.length){const list=add('ul','');for(const issue of open)add('li',issue.message,list);}
  if(hints.length){const list=add('ul','');list.className='vbf-script-hints';for(const issue of hints)add('li','Tip: '+issue.message,list);}
  if(report.hooks?.length&&useHook){
    add('p','Other openings for scene 1:');
    const row=document.createElement('div');row.className='vs-row';host.append(row);
    for(const hook of report.hooks){
      const button=add('button',`${hook.overlay_text} — ${hook.voiceover}`,row);button.type='button';button.className='vbf-hook';
      button.onclick=()=>useHook(hook);
    }
  }
  if(report.proofreading==='off')add('p','Grammar proofreading is off (set LANGUAGETOOL_URL to a LanguageTool server to enable it).').className='vs-note';
}
