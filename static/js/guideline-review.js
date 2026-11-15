import {escapeHtml as esc} from './agency-api.js';

// One review/correction view for the shared document model in every studio.
export function reviewGuideline(panel,doc,assets,onConfirm){
    const essential=new Set(['brand_name','primary_colors','secondary_colors','font_preferences','cta','language','logo_asset_id','logo_placement']);
    const field=(key,value)=>{
      let input;
      const options={language:['','en','ar'],logo_placement:['','top-right','top-left','bottom-right','bottom-left'],aspect_ratio:['','9:16','16:9','1:1','4:5']};
      if(key==='logo_asset_id')input='<select data-rule="'+key+'"><option value="">No reviewed logo</option>'+assets.map(a=>'<option value="'+a.id+'" '+(a.id===value?'selected':'')+'>'+esc(a.name)+'</option>').join('')+'</select>';
      else if(options[key])input='<select data-rule="'+key+'">'+options[key].map(x=>'<option '+(x===value?'selected':'')+'>'+esc(x)+'</option>').join('')+'</select>';
      else if(Array.isArray(value))input='<textarea data-rule="'+key+'" data-list>'+esc(value.join('\n'))+'</textarea>';
      else if(['logo_clear_space','caption_size','max_duration'].includes(key))input='<input data-rule="'+key+'" type="number" step="any" value="'+esc(value??'')+'">';
      else input='<input data-rule="'+key+'" value="'+esc(value??'')+'" maxlength="500">';
      return '<label>'+esc(key.replaceAll('_',' ')) + input+'</label>';
    };
    const entries=Object.entries(doc.rules);
    panel.innerHTML='<h3>Review extracted rules</h3><p>Only explicit document fields are extracted. Review missing/conflicting values before confirming.</p><details><summary>View source text & extraction evidence</summary><pre style="white-space:pre-wrap;max-height:260px;overflow:auto">'+esc(doc.source_text||doc.guidelines)+'</pre><pre style="white-space:pre-wrap">'+esc(JSON.stringify(doc.review,null,2))+'</pre></details><div class="vs-pair">'+entries.filter(([k])=>essential.has(k)).map(([k,v])=>field(k,v)).join('')+'</div><details><summary>Additional brand rules</summary><div class="vs-pair">'+entries.filter(([k])=>!essential.has(k)).map(([k,v])=>field(k,v)).join('')+'</div></details><div>'+doc.originals.map(o=>'<a class="vs-button" href="'+esc(o.url)+'">Download '+esc(o.name)+'</a>').join('')+'</div><button type="button" data-confirm class="primary">Confirm reviewed rules & apply</button>';
    panel.querySelector('[data-confirm]').onclick=()=>{
      const rules={};
      panel.querySelectorAll('[data-rule]').forEach(input=>{let value=input.value;if(input.hasAttribute('data-list'))value=value.split('\n').map(x=>x.trim()).filter(Boolean);else if(input.type==='number')value=value===''?null:Number(value);else if((input.dataset.rule==='logo_asset_id'||doc.rules[input.dataset.rule]===null)&&!value)value=null;rules[input.dataset.rule]=value;});
      onConfirm(rules);
    };
}
