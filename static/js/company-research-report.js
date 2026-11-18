/* Source evidence and coverage are review aids, never an automatic fact-verification claim. */
export function renderCompanyResearchReport(host,report){
  host.replaceChildren();if(!report)return;
  const details=document.createElement('details');details.className='vbf-message-help';
  const summary=document.createElement('summary');summary.textContent=`Research foundation · ${report.pages_read||0} pages · ${(report.evidence||[]).length} source excerpts`;
  details.append(summary);
  const notice=document.createElement('p');notice.textContent=report.notice;details.append(notice);
  const evidence=new Map((report.evidence||[]).map(item=>[item.id,item]));
  for(const topic of Object.values(report.topics||{})){
    const heading=document.createElement('h4');heading.textContent=topic.label;details.append(heading);
    if(!topic.evidence_ids.length){const missing=document.createElement('p');missing.textContent='Not found in the pages read. Add an approved company detail.';details.append(missing);}
    for(const id of topic.evidence_ids.slice(0,2)){
      const item=evidence.get(id);if(!item)continue;
      const quote=document.createElement('blockquote');quote.textContent=item.quote;quote.dir='auto';
      const link=document.createElement('a');link.href=item.source_url;link.textContent='Company source';link.target='_blank';link.rel='noopener noreferrer';
      quote.append(document.createElement('br'),link);details.append(quote);
    }
  }
  const media=report.media_candidates||[];
  const heading=document.createElement('h4');heading.textContent=`Visual discovery · ${media.length} non-decorative candidates`;details.append(heading);
  for(const candidate of media.slice(0,6)){
    const line=document.createElement('p'),link=document.createElement('a');link.href=candidate.source_page;link.textContent=candidate.description||'Uncaptioned website '+candidate.kind;
    link.target='_blank';link.rel='noopener noreferrer';line.append(link);details.append(line);
  }
  if(report.missing_information?.length){const gaps=document.createElement('p');gaps.textContent='Ask the client about: '+report.missing_information.join(', ')+'.';details.append(gaps);}
  host.append(details);
}
