"""Local, explainable copy and palette checks. No fabricated model confidence scores."""
import re
import unicodedata

PLACEHOLDER=re.compile(r'\[[^\]\n]{1,40}\]|\{\{[^}\n]{1,40}\}\}|lorem ipsum|\bTBD\b|\bTODO\b|\bXXX+\b|<[a-z_ ]{2,30}>',re.I)


def normalized(text):
    return ' '.join(unicodedata.normalize('NFC',text).casefold().split())


def similarity(first,second):
    try:
        from rapidfuzz.fuzz import ratio
        return ratio(first,second,processor=normalized)/100
    except ImportError:
        from difflib import SequenceMatcher
        return SequenceMatcher(None,normalized(first),normalized(second),autojunk=False).ratio()


def text_length(text,fmt):
    if fmt=='x_post':
        try:
            from twitter_text import parse_tweet
            parsed=parse_tweet(text).asdict()
            return dict(length=parsed['weightedLength'],valid=parsed['valid'],method='twitter-text weighted characters')
        except ImportError:
            return dict(length=len(text),valid=None,method='plain characters; install twitter-text-parser for X validation')
    return dict(length=len(text),valid=bool(text.strip()),method='Unicode characters')


def fit_x_text(text,limit=280):
    """Fit at grapheme boundaries so a family emoji is never split into different people."""
    if text_length(text,'x_post')['length']<=limit:return text
    import regex
    clusters=regex.findall(r'\X',text);low,high=0,len(clusters)
    while low<high:
        middle=(low+high+1)//2
        if text_length(''.join(clusters[:middle])+'…','x_post')['length']<=limit:low=middle
        else:high=middle-1
    candidate=''.join(clusters[:low]).rstrip()
    if ' ' in candidate:candidate=candidate.rsplit(' ',1)[0]
    while candidate and text_length(candidate+'…','x_post')['length']>limit:
        candidate=''.join(regex.findall(r'\X',candidate)[:-1])
    return candidate.rstrip(' ,;:')+'…'


def x_thread(text,limit=280):
    """Keep URLs and emoji intact while splitting prose into weighted-length posts."""
    import regex
    budget=limit-30;chunks=[]
    for paragraph in text.split('\n\n'):
        current=''
        for word in paragraph.split():
            pieces=[]
            if text_length(word,'x_post')['length']<=budget:pieces=[word]
            else:
                piece=''
                for cluster in regex.findall(r'\X',word):
                    if piece and text_length(piece+cluster,'x_post')['length']>budget:pieces.append(piece);piece=''
                    piece+=cluster
                if piece:pieces.append(piece)
            for piece in pieces:
                candidate=(current+' '+piece).strip()
                if current and text_length(candidate,'x_post')['length']>budget:chunks.append(current);current=piece
                else:current=candidate
        if current:chunks.append(current)
    return [f'{i+1}/{len(chunks)} {chunk}' for i,chunk in enumerate(chunks)]


def contrast(foreground,background):
    """WCAG relative luminance, measured for two solid colours, not a rendered-image audit.
    https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html
    """
    def luminance(color):
        if not re.fullmatch(r'#[0-9a-fA-F]{6}',color):raise ValueError('Use six-digit hex colours')
        rgb=[int(color[i:i+2],16)/255 for i in (1,3,5)]
        linear=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in rgb]
        return sum(v*w for v,w in zip(linear,(.2126,.7152,.0722)))
    a,b=sorted((luminance(foreground),luminance(background)))
    return (b+.05)/(a+.05)


def review_copy(copy,language,brief='',rules=None):
    from .production import channel_specs
    specs=channel_specs()['formats'];rules=rules or {};issues=[];channels=[]
    texts=[('linkedin_post',copy.get('linkedin_post','')),('instagram_caption',copy.get('instagram_caption',''))]
    texts += [('x_post',text) for text in copy.get('x_thread') or [copy.get('x_post','')]]
    known_numbers=set(re.findall(r'\d+(?:[.,]\d+)?',brief))
    for i,(fmt,text) in enumerate(texts):
        measured=text_length(text,fmt);limit=specs[fmt]['max_chars'];index=i-1 if fmt=='x_post' else None
        entry=dict(format=fmt,post=index,**measured,limit=limit);channels.append(entry)
        def flag(code,message):issues.append(dict(code=code,format=fmt,post=index,message=message))
        if not text.strip():flag('empty','Add the missing channel copy.')
        if measured['length']>limit:flag('length',f'{fmt}: {measured["length"]} counted characters exceeds {limit}.')
        if measured['valid'] is False and text.strip():flag('invalid-text',f'{fmt}: the text parser rejected this post; check length and control characters.')
        if fmt=='x_post' and measured['valid'] is None:flag('counter-unavailable','Install twitter-text-parser before relying on X character validation.')
        if PLACEHOLDER.search(text):flag('placeholder',f'{fmt}: replace unfinished placeholders.')
        if language=='ar' and not re.search(r'[\u0600-\u06ff]',text):flag('localization',f'{fmt}: native Arabic copy is missing.')
        for term in rules.get('prohibited_terms') or []:
            if normalized(term) and normalized(term) in normalized(text):flag('brand-term',f'{fmt}: contains prohibited wording: {term}')
        for term in rules.get('mandatory_terms') or []:
            if normalized(term) and normalized(term) not in normalized(text):flag('mandatory-term',f'{fmt}: check the required wording: {term}')
        # A review hint, not a claim-verification verdict; product IDs and dates can also contain digits.
        numeric_text=text
        prefix=f'{index}/{len(copy.get("x_thread") or [copy.get("x_post","")])} '
        if fmt=='x_post' and numeric_text.startswith(prefix):numeric_text=numeric_text[len(prefix):]
        numeric_text=re.sub(r'https?://\S+|(?<!\w)[#@]\w+','',numeric_text)
        numbers=set(re.findall(r'\d+(?:[.,]\d+)?',numeric_text))-known_numbers
        if numbers:flag('new-number',f'{fmt}: numeric details absent from the supplied brief need confirmation: '+', '.join(sorted(numbers)[:8]))
        tags=re.findall(r'(?<!\w)#\w+',text)
        if specs[fmt].get('max_hashtags') is not None and len(tags)>specs[fmt]['max_hashtags']:
            flag('hashtags',f'{fmt}: {len(tags)} hashtags; the configured maximum or recommendation is {specs[fmt]["max_hashtags"]}.')
    for i,(fmt,text) in enumerate(texts):
        for other_fmt,other in texts[:i]:
            if fmt!=other_fmt and min(len(text),len(other))>60 and similarity(text,other)>=.9:
                issues.append(dict(code='channel-duplication',format=fmt,message=f'{fmt} and {other_fmt} are nearly identical; tailor their opening and structure to each platform.'))
    return dict(language=language,status='review-required' if issues else 'checks-passed',issues=issues,channels=channels,
        copy_source=copy.get('copy_source','unknown'),notice='Automated editorial checks; source accuracy, cultural fit and final wording need review.')


def review_campaign(copies,request,theme):
    evidence='\n'.join([request.get('prompt',''),*(request.get('key_points') or []),*(request.get('key_points_ar') or [])])
    profile=request.get('brand_profile') or {}
    rules={key:profile.get(key,[]) for key in ('mandatory_terms','prohibited_terms')}
    reviews={language:review_copy(copy,language,evidence,rules) for language,copy in copies.items()}
    primary=theme.primary_hex;accent=theme.secondary_hex
    colors=[dict(foreground=c,background=primary,ratio=round(contrast(c,primary),2),normal_text=contrast(c,primary)>=4.5,large_text=contrast(c,primary)>=3) for c in (accent,'#ffffff','#000000')]
    return dict(version=1,status='review-required' if any(r['issues'] for r in reviews.values()) else 'checks-passed',copy=reviews,
        palette=colors,palette_notice='Solid-colour reference ratios only. This does not measure text over photos or certify the finished artwork.',
        accessibility=dict(alt_text_draft=f'{theme.brand_name}: campaign artwork about {request.get("prompt","")[:180]}',
            notice='Context-based draft. Edit it to describe the actual final visual and any essential on-image text.'),
        handoff=dict(reviewed_by='',approved_at='',next_steps=['Review English and Arabic copy against the brief.','Check every final canvas and motion loop.','Confirm media usage rights.','Add final alt text and record client approval.']),
        tools=['RapidFuzz','twitter-text-parser','WCAG solid-colour contrast calculation'])
