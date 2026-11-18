"""Licensed stock footage for storyboard scenes (Pexels and Pixabay video libraries).

Opt-in: searching needs the person's own free API key, set as PEXELS_API_KEY and/or PIXABAY_API_KEY.
Only the search words are sent to the provider (taken from a scene's visual direction and editable);
nothing else about the client leaves this computer. Results are cached for 24 hours, as Pixabay asks
of API users, and previews are fetched by this server so the browser never contacts the provider.

Both libraries license their videos for free commercial use. Their API guidelines ask apps to show
where results come from and to credit the creator, so every chosen clip carries a credit into the
client kit. GIF libraries are deliberately not offered: GIPHY requires a separate agreement for
commercial use and Tenor's terms forbid it, and GIFs (256 colours, low frame rates) look poor in HD video.
"""
import hashlib
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests

from video.storage import DATA, atomic

PROVIDERS = {
    'pexels': dict(label='Pexels', key='PEXELS_API_KEY', signup='https://www.pexels.com/api/',
                   licence='Pexels License: free for commercial use; credit the creator and Pexels where possible.'),
    'pixabay': dict(label='Pixabay', key='PIXABAY_API_KEY', signup='https://pixabay.com/api/docs/',
                    licence='Pixabay Content License: free for commercial use; show where the clip comes from.'),
}
GIF_NOTE = ('GIF libraries are not used: GIPHY needs a separate commercial agreement and Tenor forbids commercial use; '
            'GIFs also look poor in HD video. Stock video and the company\'s own footage are used instead.')
CACHE_SECONDS = 24 * 3600
TIMEOUT = 20
MAX_PREVIEW = 3 * 1024**2
MAX_DOWNLOAD = 250 * 1024**2
STOP = set('a an and the of for to in on with at by from into over under our your their its this that these those is are be '
           'as or clean clear brand branded shot shots scene video footage professional modern simple subtle generous negative '
           'space text logo website address composition readable captions no invented claims imagery photo still close up '
           'wide medium camera slow gentle soft calm light lighting style tone frame framing screens purposeful products services '
           'use used hands equipment showing work itself palette subject safe end card warm energetic people who what why we us '
           'company companies help helps offer offers provide provides across every each more most'.split())


def folder():
    path = DATA / 'stock'
    (path / 'previews').mkdir(parents=True, exist_ok=True)
    (path / 'items').mkdir(parents=True, exist_ok=True)
    return path


def configured():
    return [name for name, spec in PROVIDERS.items() if os.getenv(spec['key'], '').strip()]


def status():
    return dict(providers=[dict(id=name, label=spec['label'], configured=bool(os.getenv(spec['key'], '').strip()),
                                signup=spec['signup'], licence=spec['licence'], setting=spec['key']) for name, spec in PROVIDERS.items()],
                gifs=GIF_NOTE)


def keywords(text, limit=5, exclude=''):
    """Extract short local YAKE keyphrases; omit layout language and the company's own name."""
    skip = STOP | {word.lower() for word in re.findall(r'[A-Za-z][A-Za-z-]+', exclude or '')}
    # YAKE extracts local keyphrases without model weights, API calls or client-data uploads.
    # Keep the existing provider-query filtering so colours and layout instructions do not dominate.
    cleaned=re.sub(r'#[0-9a-fA-F]{6}\b',' ',text or '')
    cleaned=re.split(r'\b(?:Brand palette|typography|composition with clear space)\s*:',cleaned,flags=re.I)[0]
    phrases=[]
    try:
        from yake import KeywordExtractor
        language='ar' if re.search(r'[\u0600-\u06ff]',cleaned) else 'en'
        phrases=[phrase for phrase,score in KeywordExtractor(lan=language,n=2,top=8,dedup_lim=.8).extract_keywords(cleaned[:2000])]
    except ImportError:pass
    words = []
    for word in re.findall(r'[^\W\d_][\w-]{2,}', ' '.join(phrases),re.UNICODE):
        lowered=word.lower()
        if lowered not in skip and lowered not in words:words.append(lowered)
    for word in re.findall(r'[^\W\d_][\w-]{2,}',cleaned,re.UNICODE):
        lowered = word.lower()
        if lowered not in skip and lowered not in words:
            words.append(lowered)
    return ' '.join(words[:limit])


def orientation_of(width, height):
    if not width or not height:
        return 'landscape'
    ratio = width / height
    return 'landscape' if ratio > 1.15 else 'portrait' if ratio < .87 else 'square'


def _check(response, provider):
    label = PROVIDERS[provider]['label']
    if response.status_code in (401, 403):
        raise ValueError(f'{label} rejected the API key; check {PROVIDERS[provider]["key"]}')
    if response.status_code == 429:
        raise ValueError(f'{label} is limiting searches right now; wait a minute and try again')
    if response.status_code >= 400:
        raise ValueError(f'{label} search failed (HTTP {response.status_code})')
    try:
        return response.json()
    except ValueError:
        raise ValueError(f'{label} returned an unreadable response')


def _pexels(query, orientation, per_page):
    key = os.environ['PEXELS_API_KEY'].strip()
    params = dict(query=query, orientation=orientation, size='medium', per_page=per_page)
    # The documented path is /v1/videos/search; older integrations used /videos/search.
    for url in ('https://api.pexels.com/v1/videos/search', 'https://api.pexels.com/videos/search'):
        response = requests.get(url, params=params, headers={'Authorization': key}, timeout=TIMEOUT)
        if response.status_code != 404:
            break
    data = _check(response, 'pexels')
    results = []
    for video in data.get('videos') or []:
        files = [dict(url=f['link'], width=int(f.get('width') or 0), height=int(f.get('height') or 0), quality=f.get('quality') or '')
                 for f in video.get('video_files') or [] if f.get('link') and 'mp4' in (f.get('file_type') or 'video/mp4')]
        if not files:
            continue
        user = video.get('user') or {}
        results.append(dict(provider='pexels', id=str(video['id']), page_url=video.get('url') or '', preview=video.get('image') or '',
                            duration=float(video.get('duration') or 0), width=int(video.get('width') or 0), height=int(video.get('height') or 0),
                            description=(video.get('url') or '').rstrip('/').rsplit('/',1)[-1].replace('-',' '),
                            author=user.get('name') or '', author_url=user.get('url') or '', files=files))
    return results


def _pixabay(query, orientation, per_page):
    key = os.environ['PIXABAY_API_KEY'].strip()
    response = requests.get('https://pixabay.com/api/videos/', timeout=TIMEOUT,
                            params=dict(key=key, q=query[:100], safesearch='true', per_page=max(3, min(200, per_page * 3))))
    data = _check(response, 'pixabay')
    results = []
    for hit in data.get('hits') or []:
        files = [dict(url=v['url'], width=int(v.get('width') or 0), height=int(v.get('height') or 0), quality=size, thumbnail=v.get('thumbnail') or '')
                 for size, v in (hit.get('videos') or {}).items() if isinstance(v, dict) and v.get('url')]
        if not files:
            continue
        biggest = max(files, key=lambda f: f['width'] * f['height'])
        if orientation_of(biggest['width'], biggest['height']) != orientation:
            continue  # Pixabay has no orientation filter
        user = hit.get('user') or ''
        results.append(dict(provider='pixabay', id=str(hit['id']), page_url=hit.get('pageURL') or '',
                            preview=next((f['thumbnail'] for f in sorted(files, key=lambda f: f['width']) if f['thumbnail']), ''),
                            duration=float(hit.get('duration') or 0), width=biggest['width'], height=biggest['height'], author=user,
                            description=str(hit.get('tags') or '')[:500],
                            author_url=f'https://pixabay.com/users/{user}-{hit.get("user_id", "")}/' if user else '', files=files))
    return results[:per_page]


SEARCH = dict(pexels=_pexels, pixabay=_pixabay)


def _get(url, limit):
    """Download from a provider URL over HTTPS, following at most five redirects, each to a public address."""
    from agency.research import target
    for _ in range(6):
        if urlsplit(url).scheme != 'https':
            raise ValueError('Stock media must be downloaded over HTTPS')
        target(url, public_page=True)
        response = requests.get(url, stream=True, timeout=TIMEOUT, allow_redirects=False)
        if response.is_redirect:
            url = urljoin(url, response.headers.get('Location', ''))
            response.close()
            continue
        if response.status_code != 200:
            response.close()
            raise ValueError(f'The stock media download failed (HTTP {response.status_code})')
        size, parts = 0, []
        for chunk in response.iter_content(1024 * 1024):
            size += len(chunk)
            if size > limit:
                response.close()
                raise ValueError('The stock clip is larger than allowed')
            parts.append(chunk)
        return b''.join(parts), response.headers.get('Content-Type', '')
    raise ValueError('Too many redirects while downloading stock media')


def _item_path(provider, item_id):
    if provider not in PROVIDERS or not re.fullmatch(r'[0-9]{1,20}', str(item_id)):
        raise ValueError('Unknown stock clip')
    return folder() / 'items' / f'{provider}-{item_id}.json'


def preview_path(provider, item_id):
    _item_path(provider, item_id)
    path = folder() / 'previews' / f'{provider}-{item_id}.jpg'
    if not path.is_file():
        raise FileNotFoundError('Preview not found')
    return path


def _store_preview(item):
    path = folder() / 'previews' / f'{item["provider"]}-{item["id"]}.jpg'
    if path.is_file() or not item.get('preview'):
        return path.is_file()
    try:
        from PIL import Image
        import io
        raw, _ = _get(item['preview'], MAX_PREVIEW)
        with Image.open(io.BytesIO(raw)) as image:
            image = image.convert('RGB')
            image.thumbnail((480, 480))
            image.save(path, 'JPEG', quality=85)
        return True
    except Exception:
        return False


def public(item):
    return dict(provider=item['provider'], provider_label=PROVIDERS[item['provider']]['label'], id=item['id'],
                duration=round(item['duration'], 1), width=item['width'], height=item['height'], author=item['author'],
                page_url=item['page_url'],description=item.get('description',''),
                selection_notes=item.get('selection_notes',[]),
                preview_url=f'/api/video/stock/{item["provider"]}/{item["id"]}/preview')


def rank_results(items,query,orientation,min_seconds=0):
    """Combine actual BM25 caption relevance with measurable format fit, without image-AI claims."""
    from video.company_research import rank_indices
    unique={(item['provider'],item['id']):item for item in items}
    items=[item for item in unique.values() if item.get('duration',0)>=min_seconds]
    texts=[item.get('description','')+' '+item.get('page_url','').replace('-',' ') for item in items]
    relevance=dict(rank_indices(query,texts));ranked=[]
    for i,item in enumerate(items):
        same=orientation_of(item.get('width'),item.get('height'))==orientation
        hd=min(item.get('width',0),item.get('height',0))>=720
        notes=[]
        if relevance.get(i,0)>0:notes.append('Search words match provider metadata')
        if same:notes.append('Matches the selected orientation')
        if hd:notes.append('At least 720 pixels on the short side')
        score=relevance.get(i,0)+(1 if same else 0)+(.25 if hd else 0)
        ranked.append((score,{**item,'selection_notes':notes}))
    return [item for _,item in sorted(ranked,key=lambda row:-row[0])]


def search(query, orientation='landscape', min_seconds=0, provider=None, per_page=8):
    """Search the configured libraries; returns clips at least ``min_seconds`` long in the requested orientation."""
    query = re.sub(r'\s+', ' ', query or '').strip()[:100]
    if not query:
        raise ValueError('Describe the footage in a few words')
    if orientation not in ('landscape', 'portrait', 'square'):
        raise ValueError('Unknown orientation')
    names = [provider] if provider else configured()
    if provider and provider not in PROVIDERS:
        raise ValueError('Unknown stock library')
    if not names or any(not os.getenv(PROVIDERS[name]['key'], '').strip() for name in names):
        raise ValueError('Add a free Pexels or Pixabay API key (PEXELS_API_KEY or PIXABAY_API_KEY) to search stock video')
    found = []
    for name in names:
        cache = folder() / f'{name}-{hashlib.sha256(f"{query}|{orientation}|{per_page}".encode()).hexdigest()[:24]}.json'
        try:
            cached = json.loads(cache.read_text(encoding='utf-8')) if cache.is_file() else None
        except (OSError, ValueError):
            cached = None
        if cached and time.time() - cached['at'] < CACHE_SECONDS:
            items = cached['items']
        else:
            items = SEARCH[name](query, orientation, per_page)
            atomic(cache, dict(at=time.time(), query=query, orientation=orientation, items=items))
        for item in items:
            atomic(_item_path(item['provider'], item['id']), item)
        found += [item for item in items if item['duration'] >= min_seconds]
    found=rank_results(found,query,orientation,min_seconds)
    return [dict(public(item), preview_url=public(item)['preview_url'] if _store_preview(item) else None) for item in found]


def credit(item):
    label = PROVIDERS[item['provider']]['label']
    return dict(provider=item['provider'], library=label, id=item['id'], author=item['author'], author_url=item['author_url'],
                page_url=item['page_url'], licence=PROVIDERS[item['provider']]['licence'],
                text=f'Video by {item["author"] or "an unnamed creator"} on {label}' + (f' ({item["page_url"]})' if item['page_url'] else ''))


def download(provider, item_id, width, height, work):
    """The chosen clip, in the smallest rendition that covers the output frame (at most 4K), plus its credit."""
    path = _item_path(provider, item_id)
    if not path.is_file():
        raise ValueError('Search for this clip again; its details have expired')
    item = json.loads(path.read_text(encoding='utf-8'))
    files = sorted((f for f in item['files'] if max(f['width'], f['height']) <= 3840), key=lambda f: f['width'] * f['height'])
    if not files:
        raise ValueError('This clip has no downloadable MP4 rendition')
    short = min(width, height)
    choice = next((f for f in files if min(f['width'], f['height']) >= short), files[-1])
    raw, mime = _get(choice['url'], MAX_DOWNLOAD)
    if mime and not mime.lower().startswith(('video/', 'application/octet-stream', 'binary/octet-stream')):
        raise ValueError('The stock library returned something other than a video')
    out = Path(work) / f'stock-{provider}-{item_id}.mp4'
    out.write_bytes(raw)
    return out, dict(credit(item), rendition=dict(width=choice['width'], height=choice['height'], quality=choice['quality']))
