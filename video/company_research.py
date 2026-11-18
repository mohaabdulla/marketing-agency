"""Open-source extraction and ranked, traceable evidence for company video planning.

Networking stays in agency.research (public IP validation and pinned DNS). Trafilatura
only parses bytes already fetched by that client; BM25 ranks quotes, not truth claims.
"""
import hashlib
import concurrent.futures
import importlib.util
import json
import os
import re
import threading
from urllib.parse import urljoin,urlsplit,urlunsplit,parse_qsl,urlencode
from bs4 import BeautifulSoup

VERSION=1
_SEARCH_POOL=concurrent.futures.ThreadPoolExecutor(max_workers=2,thread_name_prefix='company-search')
_SEARCH_SLOTS=threading.BoundedSemaphore(2)
TOPICS={
    'identity':('Who the company is','about founded mission purpose identity من نحن تأسست رؤيتنا رسالتنا'),
    'services':('Products and services','services solutions products software automation خدمات حلول منتجات تقنية'),
    'audience':('Customers and industries','customers industries sectors businesses clients جمهور عملاء قطاعات شركات'),
    'proof':('Evidence and outcomes','case study results certified certification project outcomes case-studies نتائج شهادات مشاريع إنجازات'),
    'contact':('Next step for viewers','contact consultation demo request email اتصل تواصل استشارة عرض')}
PROMPT_INSTRUCTION=re.compile(r'ignore (?:all |any |the )?(?:previous|prior|system) instructions|system prompt|reveal.*(?:secret|api.?key)|تجاهل.*التعليمات',re.I)


def evidence_text(text,limit=1200):
    return '\n'.join(line for line in str(text).splitlines() if not PROMPT_INSTRUCTION.search(line))[:limit]


def tokens(text):
    text=re.sub(r'[\u064b-\u065f\u0670]','',str(text).casefold())
    text=re.sub('[أإآ]','ا',text)
    return [word[2:] if word.startswith('ال') and len(word)>4 else word for word in re.findall(r'[\w-]{3,}',text)]


def rank_indices(query,texts):
    if not texts:return []
    corpus=[tokens(text) or ['_empty_'] for text in texts];query_tokens=tokens(query)
    try:
        from rank_bm25 import BM25Okapi
        scores=BM25Okapi(corpus).get_scores(query_tokens)
    except ImportError:scores=[0.]*len(texts)
    wanted=set(query_tokens)
    ranked=[(i,max(0,float(scores[i]))+len(wanted.intersection(words))) for i,words in enumerate(corpus)]
    return sorted(ranked,key=lambda item:(-item[1],item[0]))


def clean_url(url):
    p=urlsplit(url)
    if p.scheme not in {'http','https'} or not p.hostname or p.username or p.password:return None
    if re.search(r'login|logout|sign-in|sign-up|checkout|shopping-cart|/wp-admin|/search',p.path,re.I):return None
    pairs=parse_qsl(p.query,keep_blank_values=True)
    if any(key.lower() in {'q','s','search'} for key,_ in pairs):return None
    # Keep meaningful IDs on CMS websites; discard only known tracking parameters.
    pairs=[(key,value) for key,value in pairs if not key.lower().startswith('utm_') and key.lower() not in {'gclid','fbclid','msclkid'}]
    return urlunsplit((p.scheme,p.netloc.lower(),p.path or '/',urlencode(sorted(pairs)),''))


def enrich_page(url,raw):
    """Clean main text, structured company data, and descriptive media metadata."""
    soup=BeautifulSoup(raw,'html.parser');structured=[]
    for script in soup.find_all('script',type='application/ld+json')[:12]:
        if len(script.get_text())>150000:continue
        try:pending=[json.loads(script.get_text())]
        except (ValueError,TypeError):continue
        count=0
        while pending and count<80:
            item=pending.pop();count+=1
            if isinstance(item,list):pending.extend(item[:30]);continue
            if not isinstance(item,dict):continue
            pending.extend(item.get('@graph',[])[:30] if isinstance(item.get('@graph'),list) else [])
            kind=item.get('@type','');kinds=kind if isinstance(kind,list) else [kind]
            if not any(isinstance(name,str) and name in {'Organization','LocalBusiness','Corporation','Product','Service'} for name in kinds):continue
            value={key:' '.join(item[key].split())[:900] for key in ('name','description','slogan','industry','serviceType') if isinstance(item.get(key),str)}
            if value:structured.append(dict(type=kinds,**value))
    media=[]
    for tag in soup.find_all(['img','video'])[:100]:
        source=tag.get('src') or tag.get('data-src')
        if not source and tag.name=='video':
            child=tag.find('source');source=child.get('src') if child else None
        if not source and tag.get('srcset'):source=tag['srcset'].split(',')[-1].strip().split(' ')[0]
        if not source:continue
        absolute=urljoin(url,source)
        if urlsplit(absolute).scheme not in {'http','https'}:continue
        figure=tag.find_parent('figure');caption=figure.find('figcaption') if figure else None
        description=' '.join(filter(None,[tag.get('alt',''),tag.get('title',''),caption.get_text(' ',strip=True) if caption else '']))[:500]
        decorative=bool(re.search(r'logo|icon|sprite|avatar|badge|pixel|tracking|\.svg',absolute+' '+description,re.I))
        media.append(dict(url=absolute,kind='video' if tag.name=='video' else 'image',description=description,
                          source_page=url,decorative=decorative,rights='Client ownership or permission must be confirmed'))
    try:
        import trafilatura
        text=trafilatura.extract(raw,url=url,include_comments=False,include_tables=True,deduplicate=True,favor_precision=True) or ''
        engine='trafilatura'
    except ImportError:text='';engine='beautifulsoup-fallback'
    for tag in soup(['script','style','nav','footer','header','noscript','form','svg','iframe']):tag.decompose()
    if len(text.strip())<60:text=soup.get_text('\n',strip=True);engine+='-landing-fallback'
    paragraphs=[]
    for line in re.split(r'\n+',text):
        line=' '.join(line.split())
        if len(line)>=20 and line not in paragraphs:paragraphs.append(line[:900])
    return dict(text=text[:16000],paragraphs=paragraphs[:60],structured_data=structured[:12],media_candidates=media[:50],extraction_engine=engine)


def crawl_pages(start,read_page,kinds,max_pages=6,job=None):
    """Follow relevant company pages to depth two, with deterministic prioritization."""
    home=read_page(start);pages=[dict(home,kind='home')];seen={clean_url(home['url'])};frontier=[];attempted=0
    host=(urlsplit(home['url']).hostname or '').lower().removeprefix('www.')
    def enqueue(page,depth):
        for target,label in page.get('links',[])[:200]:
            target=clean_url(target)
            if not target or (urlsplit(target).hostname or '').lower().removeprefix('www.')!=host or target in seen:continue
            for priority,(kind,pattern) in enumerate(kinds):
                if re.search(pattern,urlsplit(target).path+' '+label,re.I):frontier.append((priority,depth,target,kind));break
    enqueue(home,1)
    while frontier and len(pages)<max_pages and attempted<max_pages*2:
        if job and job.cancelled():break
        covered={page['kind'] for page in pages}
        frontier.sort(key=lambda item:(item[3] in covered,item[0],item[1],item[2]))
        _,depth,target,kind=frontier.pop(0)
        if target in seen:continue
        seen.add(target);attempted+=1
        try:
            page=read_page(target)
            final=clean_url(page['url'])
            if final in {clean_url(p['url']) for p in pages}:continue
            digest=page.get('sha256')
            if digest and digest in {p.get('sha256') for p in pages}:continue
            pages.append(dict(page,kind=kind))
            if depth<2:enqueue(page,depth+1)
        except Exception:continue
    return pages


def build_dossier(pages,notes='',guideline=None):
    chunks=[];seen=set();excluded=0
    for page in pages:
        values=[page.get('description',''),*page.get('paragraphs',[]),*page.get('headings',[])]
        for record in page.get('structured_data',[]):
            values.extend(record.get(key,'') for key in ('description','slogan','industry','serviceType'))
        for text in values:
            text=' '.join(str(text).split())[:900]
            if PROMPT_INSTRUCTION.search(text):excluded+=1;continue
            fingerprint=text.casefold()
            if len(text)<12 or fingerprint in seen:continue
            seen.add(fingerprint)
            chunks.append(dict(id='e-'+hashlib.sha256((page['url']+'|'+text).encode()).hexdigest()[:12],
                quote=text,source_url=page['url'],page_kind=page.get('kind','company'),basis='company-stated'))
    chunks=chunks[:180]
    topics={};missing=[]
    for key,(label,query) in TOPICS.items():
        relevant=[chunks[i] for i,score in rank_indices(query,[c['quote'] for c in chunks]) if score>0][:3]
        topics[key]=dict(label=label,evidence_ids=[c['id'] for c in relevant])
        if not relevant:missing.append(label)
    media=[item for page in pages for item in page.get('media_candidates',[]) if not item.get('decorative')]
    unique={item['url']:item for item in media}
    return dict(version=VERSION,tools=dict(extraction=sorted({p.get('extraction_engine','beautifulsoup') for p in pages}),ranking='rank-bm25' if importlib.util.find_spec('rank_bm25') else 'lexical-fallback'),
        source_manifest=[{key:p.get(key) for key in ('url','kind','fetched_at','sha256')} for p in pages],
        pages_read=len(pages),evidence=chunks[:180],topics=topics,missing_information=missing,
        media_candidates=list(unique.values())[:60],guideline=dict(id=guideline.get('id'),version=guideline.get('version')) if guideline else None,
        notes_available=bool(notes.strip()),excluded_instruction_like_passages=excluded,
        notice='Website statements are company claims, not independent verification. Visual relevance is based on captions and page context, not image recognition.')


def supporting_quote(claim,url,dossier):
    stop={'the','and','for','our','that','with','from','are','was','were','has','have','its','this','their','they','a','an'}
    wanted=set(tokens(claim))-stop
    if not wanted:return None
    for item in dossier.get('evidence',[]):
        if item['source_url']!=url:continue
        quote=item['quote'];available=set(tokens(quote))-stop
        if len(wanted&available)/len(wanted)<.65:continue
        if not set(re.findall(r'\d+(?:[.,]\d+)?',claim)).issubset(set(re.findall(r'\d+(?:[.,]\d+)?',quote))):continue
        negatives=r'\b(?:not|never|without|no)\b|غير|ليست|لا '
        if bool(re.search(negatives,quote,re.I))!=bool(re.search(negatives,claim,re.I)):continue
        return quote
    return None


def relevant_evidence(dossier,query,limit=8):
    chunks=dossier.get('evidence',[])
    return [chunks[i] for i,score in rank_indices(query,[c['quote'] for c in chunks]) if score>0][:limit]


def media_match(candidates,query):
    labels=[item.get('description','')+' '+item.get('source_page','')+' '+item.get('url',item.get('source_url','')) for item in candidates]
    return rank_indices(query,labels)


def searxng_search(query,limit=6):
    """Optional administrator-configured self-hosted API; no random public instances."""
    endpoint=os.getenv('SEARXNG_URL','').strip().rstrip('/')
    if not endpoint:return None
    parsed=urlsplit(endpoint)
    if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Invalid SearXNG endpoint configuration')
    from agency.local_text import session,bounded_json
    with session() as client:
        with client.get(endpoint+'/search',params=dict(q=query,format='json',safesearch=1),timeout=(3,12),stream=True,allow_redirects=False) as response:
            data=bounded_json(response,512*1024)
    return [dict(url=item['url'],title=str(item.get('title',''))[:160],description=str(item.get('content',''))[:500])
            for item in data.get('results',[])[:limit] if isinstance(item,dict) and clean_url(str(item.get('url','')))]


def search_results(query,legacy,limit=6):
    try:
        result=searxng_search(query,limit)
        if result is not None:return result
    except Exception:pass
    if not _SEARCH_SLOTS.acquire(blocking=False):return []
    future=_SEARCH_POOL.submit(legacy,query,limit)
    future.add_done_callback(lambda done:_SEARCH_SLOTS.release())
    try:return future.result(timeout=20)
    except Exception:future.cancel();return []


def capabilities():
    return dict(extraction=dict(tool='Trafilatura',installed=bool(importlib.util.find_spec('trafilatura'))),
        ranking=dict(tool='rank-bm25',installed=bool(importlib.util.find_spec('rank_bm25'))),
        web_search=dict(tool='SearXNG',configured=bool(os.getenv('SEARXNG_URL'))),
        local_ai=dict(configured=bool(os.getenv('LOCAL_TEXT_URL')),runtime='existing local OpenAI-compatible text adapter'),
        network='Public website fetching with validated redirects and pinned DNS')
