import {esc} from './video-api.js';
import {storageKey} from './public-session.js';
import {reviewGuideline,guidelineError} from './guideline-review.js';

async function request(path='',options={}){
  const response=await fetch('/api/guidelines'+path,options);
  const data=await response.json();
  if(!response.ok)throw new Error(guidelineError(data.detail));
  return data;
}

// A generator selection belongs to its draft, never to an editor project.
export class GenerationGuidelines{
  constructor(host,assets){
    this.assets=assets;this.selection=null;this.doc=null;
    host.innerHTML='<section id="vg-brand-guidelines"><h2>Generation brand guidelines</h2><p>Select and review the brand rules for this generation.</p><div class="vs-row"><button type="button" data-upload>Upload guidelines</button><select data-library aria-label="Generation guidelines"><option value="">Choose a guideline</option></select><button type="button" data-refresh>Refresh</button><button type="button" data-view>Review selected guideline</button><button type="button" data-remove>Clear generation guidelines</button></div><input type="file" data-file accept=".pdf,.docx,.txt,.md,.markdown,.json" hidden><div data-review></div><p data-associated></p><p data-status role="status"></p></section>';
    this.root=host.firstElementChild;this.$=s=>this.root.querySelector(s);
    this.$('[data-upload]').onclick=()=>this.$('[data-file]').click();
    this.$('[data-file]').onchange=()=>this.run(async()=>{
      const file=this.$('[data-file]').files[0];if(!file)return;
      const body=new FormData();body.append('file',file);
      this.doc=await request('',{method:'POST',body});this.review();await this.refresh();
      this.$('[data-file]').value='';
    });
    this.$('[data-library]').onchange=()=>this.run(()=>this.view());
    this.$('[data-view]').onclick=()=>this.run(()=>this.view());
    this.$('[data-refresh]').onclick=()=>this.run(()=>this.refresh());
    this.$('[data-remove]').onclick=()=>{this.doc=null;this.select(null);this.$('[data-review]').innerHTML='';this.$('[data-library]').value='';};
    this.ready=this.run(async()=>{
      await this.refresh();
      let id;try{id=localStorage.getItem(storageKey('lexnis.video.generation-guideline'));}catch{}
      if(id){const doc=await request('/'+id);if(doc.confirmed){this.doc=doc;this.select(doc);this.$('[data-library]').value=id;}}
    });
    this.sync();
  }
  async run(fn){this.$('[data-status]').textContent='Working...';try{await fn();this.$('[data-status]').textContent='Ready.';}catch(error){this.$('[data-status]').textContent=error.message;}}
  select(doc){
    this.selection=doc?{guideline_id:doc.id,guideline_version:doc.version}:null;
    try{const key=storageKey('lexnis.video.generation-guideline');if(doc)localStorage.setItem(key,doc.id);else localStorage.removeItem(key);}catch{}
    this.sync();
  }
  sync(){this.$('[data-associated]').textContent=this.selection?'Selected for generation: '+(this.doc.rules.brand_name||'Reviewed brand')+' (v'+this.selection.guideline_version+')':'No guideline selected for generation.';}
  async refresh(){
    const list=await request(),select=this.$('[data-library]'),id=this.doc?.id||this.selection?.guideline_id||select.value;
    select.innerHTML='<option value="">Choose a guideline</option>'+list.map(doc=>'<option value="'+doc.id+'">'+esc(doc.rules.brand_name||doc.filename)+' - v'+doc.version+'</option>').join('');select.value=id||'';
  }
  async view(){
    const id=this.$('[data-library]').value;if(!id)throw new Error('Choose a guideline first');
    this.doc=await request('/'+id);this.review();
    this.$('[data-status]').textContent='Review and confirm to use these rules for generation.';
  }
  review(){
    const doc=this.doc;
    reviewGuideline(this.$('[data-review]'),doc,this.assets().filter(asset=>asset.kind==='image'),rules=>this.run(async()=>{
      this.doc=await request('/'+doc.id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_version:doc.version,rules,confirmed:true})});
      this.select(this.doc);await this.refresh();this.review();
    }));
  }
}
