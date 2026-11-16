"""Shared Image/GIF/Video brand documents: bounded parsers and evidence-only rules."""
import hashlib
import io
import json
import re
import time
import zipfile
import tempfile
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Annotated, Literal
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field
from public_access import scoped
from video_storage import uid, atomic, identifier

HOME = scoped(Path(__file__).resolve().parent / 'output/guidelines', 'guidelines')
Short = Annotated[str, Field(max_length=500)]
Items = Annotated[list[Short], Field(max_length=30)]
def normalize_color(value):
    """Store opaque RGB hex; accept explicit CSS names and short hex from operators."""
    from PIL import ImageColor
    if isinstance(value, str):
        value = value.strip()
        if re.fullmatch(r'#[0-9a-fA-F]{6}', value):
            return value
        if re.fullmatch(r'#[0-9a-fA-F]{3}', value):
            return '#' + ''.join(c * 2 for c in value[1:])
        named = ImageColor.colormap.get(value.casefold())
        if named:
            return named
    raise ValueError('Use a CSS color name such as blue or green, or a hex color such as #123ABC')


Color = Annotated[str, Field(pattern=r'^#[0-9a-fA-F]{6}$'), BeforeValidator(normalize_color)]
Colors = Annotated[list[Color], Field(max_length=12)]


class Rules(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    brand_name: str = Field('', max_length=150)
    primary_colors: Colors = []
    secondary_colors: Colors = []
    font_preferences: Items = []
    logo_asset_id: str | None = Field(None, pattern=r'^[a-f0-9]{32}$')
    logo_placement: Literal['', 'top-right', 'top-left', 'bottom-right', 'bottom-left'] = ''
    logo_clear_space: float | None = Field(None, ge=.02, le=.3)
    visual_style: Short = ''
    tone_of_voice: Short = ''
    animation_style: Short = ''
    transition_preferences: Items = []
    caption_color: Color | None = None
    caption_size: int | None = Field(None, ge=16, le=160)
    cta: Short = ''
    prohibited_elements: Items = []
    required_elements: Items = []
    required_disclosures: Items = []
    target_audience: Short = ''
    language: Literal['', 'en', 'ar'] = ''
    platform_preferences: Items = []
    aspect_ratio: Literal['', '9:16', '16:9', '1:1', '4:5'] = ''
    max_duration: float | None = Field(None, ge=1, le=300)


def extract(raw, filename):
    ext = Path(filename).suffix.lower()
    if not 0 < len(raw) <= 8 * 1024**2:
        raise ValueError('Guideline documents must be nonempty and no larger than 8 MB')
    if ext in {'.txt', '.md', '.markdown', '.json'}:
        text = raw.decode('utf-8-sig')
        if '\0' in text or sum(ord(c) < 32 and c not in '\r\n\t' for c in text):
            raise ValueError('Guideline text contains binary/control data')
        if ext == '.json':
            from agency.acquisition_schemas import strict_json
            value = strict_json(text)
            if not isinstance(value, dict):
                raise ValueError('A brand JSON guideline must contain an object')
    elif ext == '.pdf':
        if not raw.startswith(b'%PDF-'):
            raise ValueError('PDF signature does not match its extension')
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw), strict=True)
        if reader.is_encrypted or len(reader.pages) > 40:
            raise ValueError('Use an unencrypted guideline with at most 40 PDF pages')
        text = '\n'.join((p.extract_text() or '')[:30000] for p in reader.pages)
        if not text.strip():
            raise ValueError('This PDF has no extractable text; export a text PDF or supply a text guideline')
    elif ext == '.docx':
        if not raw.startswith(b'PK'):
            raise ValueError('DOCX signature does not match its extension')
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            entries = z.infolist()
            if len(entries) > 300 or sum(x.file_size for x in entries) > 10 * 1024**2:
                raise ValueError('DOCX archive exceeds its parsing budget')
            if any(x.flag_bits & 1 for x in entries) or 'word/document.xml' not in z.namelist():
                raise ValueError('Invalid or encrypted DOCX document')
            xml = z.read('word/document.xml')
            if b'<!DOCTYPE' in xml.upper() or b'<!ENTITY' in xml.upper():
                raise ValueError('DOCX XML entities are not supported')
            node = ET.fromstring(xml)
            text = '\n'.join(''.join(p.itertext()) for p in node.iter() if p.tag.endswith('}p'))
    else:
        raise ValueError('Supported documents: PDF, DOCX, TXT, Markdown and JSON')
    if not text.strip() or len(text) > 120000:
        raise ValueError('Guideline text must contain 1–120,000 characters')
    return text


ALIASES = {
    'brand': 'brand_name', 'brand name': 'brand_name', 'primary colors': 'primary_colors',
    'primary color': 'primary_colors', 'secondary colors': 'secondary_colors', 'secondary color': 'secondary_colors',
    'fonts': 'font_preferences', 'font': 'font_preferences', 'typography': 'font_preferences',
    'visual style': 'visual_style', 'tone': 'tone_of_voice', 'tone of voice': 'tone_of_voice',
    'animation': 'animation_style', 'animation style': 'animation_style', 'transitions': 'transition_preferences',
    'cta': 'cta', 'call to action': 'cta', 'prohibited elements': 'prohibited_elements',
    'required elements': 'required_elements', 'required disclosure': 'required_disclosures',
    'disclosure': 'required_disclosures', 'language': 'language', 'audience': 'target_audience',
    'aspect ratio': 'aspect_ratio', 'max duration': 'max_duration', 'logo placement': 'logo_placement',
    'caption size': 'caption_size', 'caption color': 'caption_color'
}


def parse(text):
    data, evidence, conflicts = {}, {}, []
    unmapped=[]
    if text.lstrip().startswith('{'):
        from agency.acquisition_schemas import strict_json
        value = strict_json(text)
        data = value.get('rules', value)
        data = {k:v for k,v in data.items() if k in Rules.model_fields}
        if 'brand_colors' in value and isinstance(value['brand_colors'],dict):
            primary = value['brand_colors'].get('primary')
            secondary = value['brand_colors'].get('accent')
            if primary: data.setdefault('primary_colors',[primary])
            if secondary: data.setdefault('secondary_colors',[secondary])
        for old, new in [('cta_rules','cta'),('caption_style','caption_color')]:
            if isinstance(value.get(old),dict):
                item = value[old].get('text' if old=='cta_rules' else 'color')
                if item: data.setdefault(new,item)
        if isinstance(value.get('caption_style'),dict) and value['caption_style'].get('font_size'):
            data.setdefault('caption_size',value['caption_style']['font_size'])
        if isinstance(value.get('logo_rules'),dict):
            logo=value['logo_rules']
            for old,new in [('placement','logo_placement'),('asset_id','logo_asset_id'),('clear_space','logo_clear_space')]:
                if old in logo: data.setdefault(new,logo[old])
        unmapped=[key for key in value if key not in Rules.model_fields and key not in {'rules','brand_colors','caption_style','cta_rules','logo_rules'}]
        # Strict schema deliberately refuses unsupported keys rather than fabricating interpretations.
        result = Rules.model_validate(data)
        evidence = {k: 'Explicit JSON field' for k in data}
    else:
        for line in text.splitlines():
            if ':' not in line:
                continue
            label, value = line.split(':', 1)
            field = ALIASES.get(label.strip(' #*-\t').casefold())
            value = value.strip().strip('*')
            if not field or not value:
                continue
            if field in {'primary_colors', 'secondary_colors'}:
                try:
                    parsed = [normalize_color(x.strip()) for x in re.split(r'[;,|]', value)]
                except ValueError:
                    parsed = re.findall(r'#[0-9A-Fa-f]{6}\b', value)
                if not parsed:
                    continue
            elif field in {'font_preferences', 'transition_preferences', 'prohibited_elements', 'required_elements', 'required_disclosures'}:
                parsed = [x.strip() for x in re.split(r'[;,|]', value) if x.strip()]
            elif field in {'caption_size', 'max_duration'}:
                number = re.search(r'\d+(?:\.\d+)?', value)
                if not number:
                    continue
                parsed = float(number[0]) if field == 'max_duration' else int(float(number[0]))
            elif field == 'language':
                parsed = 'ar' if value.lower() in {'ar', 'arabic', 'العربية'} else 'en' if value.lower() in {'en', 'english'} else ''
            else:
                parsed = value
            if field in data and data[field] != parsed:
                conflicts.append(dict(field=field, values=[data[field], parsed], message='Conflicting explicit values; review required'))
                continue
            data[field], evidence[field] = parsed, line[:800]
        result = Rules.model_validate(data)
    rules = result.model_dump()
    missing = [k for k in ('brand_name', 'primary_colors', 'font_preferences', 'logo_asset_id', 'cta', 'language') if not rules[k]]
    return rules, dict(explicit_requirements=evidence, preferences=['Visual style, tone, fonts and transitions remain preferences unless specified as required.'],
                       inferred_suggestions=[], missing_information=missing, conflicting_rules=conflicts,
                       unmapped_json_fields=unmapped,
                       extraction_method='Bounded document parsing and labelled fields; unlabelled prose is retained for review, never promoted to invented facts.')


def get(key):
    path = HOME / (identifier(key) + '.json')
    if not path.is_file():
        raise FileNotFoundError('Guideline not found')
    return json.loads(path.read_text(encoding='utf-8'))


def upload_documents(documents):
    HOME.mkdir(parents=True, exist_ok=True)
    if not 1 <= len(documents) <= 8 or sum(len(raw) for name, raw in documents) > 16 * 1024**2:
        raise ValueError('Upload at most eight guidelines and 16 MB in total')
    texts = [bounded_extract(raw, name) for name, raw in documents]
    combined = '\n\n'.join(texts)
    if len(texts) == 1:
        rules, review = parse(combined)
    else:
        rules, review = Rules().model_dump(), dict(explicit_requirements={}, preferences=[],inferred_suggestions=[],
            missing_information=[],conflicting_rules=[], extraction_method='Each original parsed separately; explicit fields merged for operator review.')
        for text in texts:
            parsed, evidence = parse(text)
            for key, value in parsed.items():
                if value not in (None,'',[]):
                    if rules[key] not in (None,'',[]) and rules[key] != value:
                        review['conflicting_rules'].append(dict(field=key,values=[rules[key],value]))
                    else:
                        rules[key] = value
            review['explicit_requirements'].update(evidence['explicit_requirements'])
        review['missing_information']=[key for key,value in rules.items() if value in (None,'',[])]
    key = uid()
    originals = []
    for name, raw in documents:
        leaf = key + '-' + uid() + Path(name).suffix.lower()
        (HOME / leaf).write_bytes(raw)
        originals.append(dict(name=Path(name.replace('\\', '/')).name[:160], filename=leaf,
                              sha256=hashlib.sha256(raw).hexdigest(), size=len(raw)))
    value = dict(id=key, version=1, created=time.time(), rules=rules, review=review, text=combined,
                 originals=originals, file_texts=texts, confirmed=False)
    atomic(HOME / (key + '.json'), value)
    return public_view(value)


def bounded_extract(raw,name):
    if Path(name).suffix.lower()!='.pdf':
        return extract(raw,name)
    if not 0<len(raw)<=8*1024**2 or not raw.startswith(b'%PDF-'):
        raise ValueError('Invalid PDF size or signature')
    import importlib.util
    if importlib.util.find_spec('pypdf') is None:
        raise ModuleNotFoundError('PDF parsing requires pypdf',name='pypdf')
    import psutil
    work=HOME/'work'
    work.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='pdf-',dir=work) as directory:
        source=Path(directory)/'input.pdf'
        destination=Path(directory)/'text.txt'
        source.write_bytes(raw)
        process=subprocess.Popen([sys.executable,str(Path(__file__).with_name('brand_guideline_worker.py')),str(source),str(destination)],
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,shell=False,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        start=time.monotonic()
        try:
            while process.poll() is None:
                if time.monotonic()-start>25:
                    raise ValueError('PDF parsing exceeded 25 seconds')
                try:
                    if psutil.Process(process.pid).memory_info().rss>384*1024**2:
                        raise ValueError('PDF parsing exceeded its memory budget')
                except psutil.NoSuchProcess:
                    pass
                time.sleep(.05)
            if process.returncode or not destination.is_file() or destination.stat().st_size>512000:
                error=destination.with_suffix('.error')
                if error.is_file() and error.stat().st_size<1000:
                    raise ValueError(error.read_text(encoding='utf-8'))
                raise ValueError('PDF parsing failed; export a text PDF or TXT guideline')
            return destination.read_text(encoding='utf-8')
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)


def public_view(value):
    rules = value['rules']
    # Compatibility adapter for the existing Image & GIF Studio upload response.
    colors = rules['primary_colors']
    profile = dict(source='uploaded_guidelines', locked_by_guidelines=True, brand_name=rules['brand_name'],
                   brand_colors={k: v for k, v in zip(('primary', 'accent'), colors)}, guideline_summary=value['text'][:6000],
                   cta=rules['cta'], font_preferences=rules['font_preferences'])
    return dict(status='success', id=value['id'], guideline_id=value['id'], version=value['version'],
                confirmed=value['confirmed'], rules=rules, review=value['review'],
                filename=', '.join(o['name'] for o in value['originals']),
                files=[dict(filename=o['name'],size=o['size'],is_image=False,
                            guidelines=value.get('file_texts',[value['text']])[i] if i<len(value.get('file_texts',[value['text']])) else '',
                            word_count=len(value.get('file_texts',[value['text']])[i].split()) if i<len(value.get('file_texts',[value['text']])) else 0)
                       for i,o in enumerate(value['originals'])],
                file_count=len(value['originals']), guidelines=(json.dumps(rules,ensure_ascii=False,indent=2) if value['confirmed'] else value['text'][:120000]),
                source_text=value['text'][:120000], preview=value['text'][:350],
                word_count=len(value['text'].split()), char_count=len(value['text']), brand_dna=profile,
                originals=[dict(name=o['name'], sha256=o['sha256'], size=o['size'],
                                url=f'/api/guidelines/{value["id"]}/original/{i}') for i, o in enumerate(value['originals'])])
