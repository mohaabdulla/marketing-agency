"""Concurrent campaign execution with private staging and atomic publication.

Only independent graph nodes run concurrently. CPU/GPU render work stays off the event
loop; in-flight workers are joined before any failed/cancelled staging area is removed.
"""
import asyncio
import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict

from public_access import _render_destination


class ChannelCopy(BaseModel):
    model_config=ConfigDict(extra='forbid')
    linkedin: str
    instagram: str
    x: str


class CampaignAssets(BaseModel):
    model_config=ConfigDict(extra='forbid')
    primary_image: str
    companion_image: str
    story_image: str
    landscape_banner: str
    animation_gif: str
    animation_mp4: str
    zip_bundle: str


class EnterpriseCampaignResult(BaseModel):
    model_config=ConfigDict(extra='forbid')
    status: Literal['success']='success'
    campaign_id: str
    assets: CampaignAssets
    copywriting: dict[Literal['en','ar'],ChannelCopy]


class RenderTransaction:
    def __init__(self,published_root):
        self.campaign_id=uuid.uuid4().hex
        self.published=Path(published_root).resolve()
        self.private=(self.published.parent/'.campaign-staging').resolve()
        self.private.mkdir(parents=True,exist_ok=True)
        self.stage=Path(tempfile.mkdtemp(prefix=self.campaign_id+'-',dir=self.private)).resolve()
        self.target=(self.published/self.campaign_id).resolve()
        self.committed=False

    def __enter__(self):
        self.token=_render_destination.set(self.stage)
        return self

    def commit(self):
        # Directory rename is one filesystem transaction, on the same volume.
        if self.stage.parent!=self.private or self.target.parent!=self.published or self.target.exists():
            raise ValueError('Invalid campaign publication target')
        self.published.mkdir(parents=True,exist_ok=True)
        (self.stage/'_complete.json').write_text(json.dumps(dict(campaign_id=self.campaign_id,status='success')),encoding='utf-8')
        os.replace(self.stage,self.target)
        self.committed=True

    def __exit__(self,*exc):
        _render_destination.reset(self.token)
        if not self.committed and self.stage.exists():
            resolved=self.stage.resolve()
            if resolved.parent!=self.private or not resolved.name.startswith(self.campaign_id+'-'):
                raise RuntimeError('Refusing cleanup outside this campaign staging directory')
            shutil.rmtree(resolved)


async def joined(*calls):
    """A failing node cannot leave another thread writing into a deleted transaction."""
    pending=asyncio.gather(*calls,return_exceptions=True)
    try:
        results=await asyncio.shield(pending)
    except asyncio.CancelledError:
        await pending
        raise
    for result in results:
        if isinstance(result,BaseException):raise result
    return results


async def offload(function,*args,**kwargs):
    return (await joined(asyncio.to_thread(function,*args,**kwargs)))[0]


def prepare_brand(request,resolve_path,stage):
    """Freeze one active kit and logo for every node, including during concurrent edits."""
    from brand_kits import get_brand,profile_for
    from fastapi import HTTPException
    from visual_engine import resolve_brand_theme
    from campaign_generator import extract_brand_name_from_prompt
    profile=dict(request.brand_profile or {})
    if request.brand_profile_json:
        try:parsed=json.loads(request.brand_profile_json)
        except ValueError as exc:raise HTTPException(422,'Brand profile must be valid JSON') from exc
        if not isinstance(parsed,dict):raise HTTPException(422,'Brand profile must be an object')
        profile.update(parsed)
    brand=request.brand or profile.get('brand_name') or extract_brand_name_from_prompt(request.prompt) or 'Brand'
    logo=request.logo_path or request.logo_url
    if request.brand_id:
        kit=get_brand(request.brand_id)
        if not kit:raise HTTPException(404,'Brand kit not found')
        profile.update(profile_for(kit));brand=kit['brand_name'];logo=kit.get('logo_path') or None
        profile['locked_by_guidelines']=True
    frozen_logo=None
    logo_hash=None
    if logo:
        source=resolve_path(logo)
        if not source:raise HTTPException(400,'Select an existing logo from this workspace')
        source=Path(source)
        frozen_logo=stage/('brand-logo'+source.suffix.lower())
        shutil.copyfile(source,frozen_logo)
        logo_hash=hashlib.sha256(frozen_logo.read_bytes()).hexdigest()
    theme=resolve_brand_theme(brand_profile=profile,uploaded_logo_path=str(frozen_logo) if frozen_logo else None,
                              brand_name=brand,post_type=request.post_type or 'general')
    frozen=request.model_copy(update=dict(brand_id=None,brand=brand,brand_profile=profile,brand_profile_json=None,
        logo_path=str(frozen_logo) if frozen_logo else None,logo_url=None,generate_companion=False,output_format='portrait',language='both'))
    snapshot=dict(id=request.brand_id,brand_name=brand,profile=profile,logo_sha256=logo_hash)
    return frozen,theme,snapshot


def primary_sources(request,theme,stage,base_renderer,resolve_path):
    from campaign_generator import render_enterprise_fallback
    from visual_engine import model_setup
    data={}
    try:
        # An absent cloud token must not bypass an installed local-image worker.
        model=request.image_model or 'flux'
        configured=model_setup(model).get('configured')
        if model=='flux':configured=bool(os.getenv('POLLINATIONS_API_KEY'))
        if not request.uploaded_image_url and not request.uploaded_image_urls and not configured:
            raise RuntimeError('Use the local renderer when provider credentials are absent')
        data=base_renderer(request)
        paths={lang:resolve_path(data.get(('arabic_' if lang=='ar' else '')+'image_url','')) for lang in ('en','ar')}
        if not all(paths.values()):raise RuntimeError('Image provider did not finish both primary canvases')
        for language,path in paths.items():
            target=stage/f'primary-{language}.jpg'
            if Path(path).resolve()!=target:shutil.copyfile(path,target)
            layers=Path(path).with_suffix('.welcome_layers')
            if layers.is_dir() and layers!=target.with_suffix('.welcome_layers'):
                shutil.copytree(layers,target.with_suffix('.welcome_layers'))
            paths[language]=str(target)
        return paths,data,'campaign-renderer'
    except Exception as error:
        from fastapi import HTTPException
        if isinstance(error,HTTPException) and error.status_code<500 and error.status_code not in {408,429}:raise
        paths,source=render_enterprise_fallback(request.model_dump(),theme,stage)
        return paths,data,source


def motion(path,request,theme,language):
    from campaign_generator import generate_social_gif
    base='primary' if 'welcome' in (request.post_type or '') else 'companion'
    return generate_social_gif(request.prompt,request.post_type or 'general',str(path),base_image=str(path.parent/f'{base}-{language}.jpg'),
                               brand_theme=theme,language=language,motion_fps=30)


def validate_motion(paths):
    from PIL import Image
    from video_ffmpeg import probe
    for language,items in paths.items():
        meta=probe(items['animation_mp4_url'])
        if (meta['width'],meta['height'])!=(1080,1350) or abs(meta['fps']-30)>.01 or meta['video_codec']!='h264':
            raise ValueError(f'Incorrect motion delivery for {language}')
        with Image.open(items['animation_url']) as image:
            if not getattr(image,'is_animated',False) or image.info.get('loop')!=0:
                raise ValueError(f'Incorrect GIF loop for {language}')


async def execute_campaign(request,*,origin,published_root,base_renderer,resolve_path,agency_context=None):
    from campaign_generator import generate_enterprise_copy,generate_companion_image,render_omnichannel_variants
    from agency_suite import bundle_enterprise_campaign
    if not request.prompt.strip():raise ValueError('A campaign brief is required')
    with RenderTransaction(published_root) as tx:
        frozen,theme,snapshot=await offload(prepare_brand,request,resolve_path,tx.stage)
        source,en,ar=await joined(
            asyncio.to_thread(primary_sources,frozen,theme,tx.stage,base_renderer,resolve_path),
            asyncio.to_thread(generate_enterprise_copy,frozen.model_dump(),theme,'en'),
            asyncio.to_thread(generate_enterprise_copy,frozen.model_dump(),theme,'ar'))
        primary,base,provenance=source
        copies={'en':en,'ar':ar}
        render_slots=asyncio.Semaphore(2)
        async def render(function,*args,**kwargs):
            async with render_slots:return await offload(function,*args,**kwargs)
        async def language_assets(language):
            localized={**frozen.model_dump(), 'topic':frozen.prompt,'language':language,'use_local_sdxl':False,
                       'copy_pack':copies['en'],'copy_pack_ar':copies['ar'],'role_title':frozen.person_name or '',
                       'tagline':theme.tagline_ar or theme.tagline if language=='ar' else theme.tagline}
            companion=await render(generate_companion_image,localized,theme,str(tx.stage/f'companion-{language}.jpg'))
            localized['companion_image_path']=companion
            formats,gif=await joined(
                render(render_omnichannel_variants,primary[language],localized,theme),
                render(motion,tx.stage/f'motion-{language}.gif',frozen,theme,language))
            return dict(image_url=primary[language],companion_image_url=companion,story_url=formats['story_path'],
                        landscape_url=formats['landscape_path'],animation_url=gif,animation_mp4_url=str(Path(gif).with_suffix('.mp4')))
        en_assets,ar_assets=await joined(language_assets('en'),language_assets('ar'))
        paths={'en':en_assets,'ar':ar_assets}
        await offload(validate_motion,paths)
        selected='ar' if request.language=='ar' else 'en'
        archive=tx.stage/'client-agency-kit.zip'
        await offload(bundle_enterprise_campaign,paths,copies,archive,selected=selected,brand=theme.brand_name)
        def url(path):return origin.rstrip('/')+'/renders/'+tx.campaign_id+'/'+Path(path).name
        fields={'primary_image':'image_url','companion_image':'companion_image_url','story_image':'story_url',
                'landscape_banner':'landscape_url','animation_gif':'animation_url','animation_mp4':'animation_mp4_url'}
        assets={key:url(paths[selected][value]) for key,value in fields.items()};assets['zip_bundle']=url(archive)
        result=EnterpriseCampaignResult(campaign_id=tx.campaign_id,assets=CampaignAssets(**assets),copywriting={
            lang:ChannelCopy(linkedin=copy['linkedin_post'],instagram=copy['instagram_caption'],x='\n\n'.join(copy['x_thread'])) for lang,copy in copies.items()})
        kits={lang:{**{key:url(path) for key,path in items.items()},'primary_image_url':url(items['image_url']),
                    'bundle_zip_url':url(archive),'copywriting':copies[lang]} for lang,items in paths.items()}
        presentation={key:value for key,value in base.items() if not key.endswith('_path') and key not in {'raw_response','agency_kits'}}
        # Keep the existing image studio usable when no cloud response supplied metadata.
        writing=copies[selected]
        defaults=dict(hook=writing['hook'],caption=writing['instagram_caption'],instagram_caption=writing['instagram_caption'],
            cta=writing['cta'],hashtags=' '.join(writing['hashtags']),highlights=frozen.key_points_ar if selected=='ar' else frozen.key_points,
            visual_prompt=frozen.prompt,image_headline=writing['hook'],seed=frozen.seed or 42,output_format='portrait',
            post_type=frozen.post_type,image_status='ready',watermark_free=True,warnings=[])
        for key,value in defaults.items():presentation.setdefault(key,value)
        presentation.update({'arabic_'+key:value for key,value in kits['ar'].items()})
        presentation.update(kits[selected],schema_version=1,status='success',campaign_id=tx.campaign_id,assets=assets,
            language=selected,brand=theme.brand_name,brand_dna=snapshot['profile'],brand_snapshot=snapshot,
            copywriting={**copies[selected],**copies},copywriting_by_language=copies,agency_kits=kits,
            carousel_urls=[kits['en'][key] for key in ('image_url','companion_image_url','animation_url')],
            arabic_carousel_urls=[kits['ar'][key] for key in ('image_url','companion_image_url','animation_url')],
            arabic_image_url=kits['ar']['image_url'],arabic_companion_image_url=kits['ar']['companion_image_url'],
            motion=dict(fps=30,kind='rendered-card-animation',native_frames=True),
            execution=dict(created_at=datetime.now(timezone.utc).isoformat(),visual_source=provenance,agency_context=agency_context or {}))
        # Published metadata contains URLs and brand rules, never private staging filenames.
        def clean(value):
            if isinstance(value,dict):return {key:clean(item) for key,item in value.items() if not key.endswith('_path')}
            if isinstance(value,list):return [clean(item) for item in value]
            if isinstance(value,str) and str(tx.stage) in value:return ''
            if isinstance(value,str) and value.startswith('/renders/') and (tx.stage/Path(value).name).is_file():return url(tx.stage/Path(value).name)
            return value
        (tx.stage/'_presentation.json').write_text(json.dumps(clean(presentation),ensure_ascii=False),encoding='utf-8')
        (tx.stage/'_result.json').write_text(result.model_dump_json(),encoding='utf-8')
        tx.commit()
        return result


def presentation_for(published_root,campaign_id):
    if not re.fullmatch(r'[a-f0-9]{32}',campaign_id):raise FileNotFoundError('Campaign not found')
    folder=Path(published_root)/campaign_id
    if not (folder/'_complete.json').is_file():raise FileNotFoundError('Campaign not found')
    return json.loads((folder/'_presentation.json').read_text(encoding='utf-8'))


def completed_runs(published_root,client_id,campaign_id):
    results=[]
    for folder in Path(published_root).glob('*'):
        if not folder.is_dir() or not re.fullmatch(r'[a-f0-9]{32}',folder.name):continue
        try:
            data=presentation_for(published_root,folder.name)
            context=data['execution']['agency_context']
            if context==dict(client_id=client_id,campaign_id=campaign_id):
                results.append(dict(campaign_id=folder.name,created_at=data['execution']['created_at'],assets=data['assets']))
        except (OSError,ValueError,KeyError):continue
    return sorted(results,key=lambda item:item['created_at'],reverse=True)
