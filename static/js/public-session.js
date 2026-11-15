// Bootstrap from the server-issued cookie; a localStorage value never proves ownership.
try{
  const response=await fetch('/api/session',{credentials:'same-origin'});
  if(response.ok){
    const session=await response.json();window.publicTestMode=!!session.public_test_mode;
    if(session.public_test_mode){
      window.lexnisGuestWorkspace=session.workspace;
      const notice=document.createElement('div');notice.className='ag-status';notice.id='public-testing-notice';notice.setAttribute('role','status');
      notice.textContent='Public Testing Mode — All Creative Features Available';document.body.prepend(notice);
    }
  }
}catch{/* Existing local mode remains usable if the session endpoint is unavailable. */}

export const storageKey = key => window.lexnisGuestWorkspace ? key+'.guest.'+window.lexnisGuestWorkspace : key;

async function checkStudioUpdate(){
  if(!window.lexnisUiVersion||document.getElementById('studio-update-notice'))return;
  try{const response=await fetch('/api/ui-version',{cache:'no-store'});if(!response.ok)return;const data=await response.json();if(data.version!==window.lexnisUiVersion){const notice=document.createElement('div');notice.id='studio-update-notice';notice.className='studio-update-notice';notice.setAttribute('role','status');notice.textContent='Studio updated. Reload to use the latest editor.';const button=document.createElement('button');button.textContent='Reload studio';button.onclick=()=>location.reload();notice.append(button);document.body.append(notice);}}catch{}
}
setInterval(checkStudioUpdate,30000);window.addEventListener('focus',checkStudioUpdate);
