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
