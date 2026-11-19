"""Reviewed delivery archives, portable media references and Unicode-safe script/storyboard PDFs."""
import io
import json
import zipfile
from pathlib import Path
from PIL import Image,ImageDraw,features
from video.production import file_hash
from video.assets import path_for
from video.storage import read,space


def _pdf(record,storyboard=False):
    from video.typography import font_for
    pages=[];page=None;draw=None;y=0
    font_name=record['governance']['brand']['font_family'];font=font_for(font_name,'sans',30,'regular',record['request']['language']=='ar')
    heading=font_for(font_name,'sans',42,'bold',record['request']['language']=='ar')
    def new_page():
        nonlocal page,draw,y
        page=Image.new('RGB',(1240,1754),'white');draw=ImageDraw.Draw(page);pages.append(page);y=70
        draw.text((70,y),'STORYBOARD' if storyboard else 'SCRIPT',font=heading,fill='#142332');y+=80
    def line(text):
        nonlocal y
        if y>1640:new_page()
        arabic=any('\u0600'<=c<='\u06ff' for c in text)
        direction=dict(direction='rtl',language='ar') if arabic and features.check_feature('raqm') else {}
        if arabic and not direction:
            import arabic_reshaper
            from bidi.algorithm import get_display
            text=get_display(arabic_reshaper.reshape(text))
        draw.text((1170,y) if arabic else (70,y),text,font=font,fill='#142332',anchor='ra' if arabic else None,**direction);y+=45
    def paragraph(text):
        import regex
        current=''
        for word in str(text).split():
            candidate=(current+' '+word).strip()
            if draw.textlength(candidate,font=font)<=1080:current=candidate;continue
            if current:line(current);current=''
            for cluster in regex.findall(r'\X',word):
                if current and draw.textlength(current+cluster,font=font)>1080:line(current);current=''
                current+=cluster
        if current:line(current)
    for shot in record['shots']:
        new_page();inputs=shot['input']
        paragraph(record['name']);paragraph(f'Shot {shot["sequence"]} — {shot["id"]}');paragraph(f'Duration: {inputs["duration"]:g} seconds')
        if storyboard and shot['approvals'].get('final'):
            candidate=next(c for c in shot['candidates'] if c['id']==shot['approvals']['final']['candidate_id'])
            thumb=path_for(candidate['asset_id']).with_suffix('.thumb.jpg')
            if thumb.is_file():
                picture=Image.open(thumb).convert('RGB');picture.thumbnail((1080,380));page.paste(picture,(70,y));y+=picture.height+30
        paragraph('Headline: '+inputs['overlay_text']);paragraph('Narration: '+inputs['voiceover'])
        if storyboard:
            for key in ('subject','framing','camera_angle','camera_motion','action','location','wardrobe','props','screen_direction','continuity_notes','visual_prompt'):
                if inputs.get(key):paragraph(key.replace('_',' ').title()+': '+str(inputs[key]))
    output=io.BytesIO();pages[0].save(output,format='PDF',save_all=True,append_images=pages[1:],resolution=150,
        title=record['name'],author=record['governance']['brand']['brand_name'])
    for page in pages:page.close()
    return output.getvalue()


def build_delivery(record,destination):
    render=record['render'];project=read('projects',render['project_id']);assets=set()
    for shot in record['shots']:
        for take in shot['candidates']:assets.add(take['asset_id'])
        assets.update(value for key,value in shot['input'].items() if key in ('reference_asset_id','source_asset_id') and value)
    for clip in project['clips']:
        if clip.get('asset_id'):assets.add(clip['asset_id'])
    size=sum(path_for(key).stat().st_size for key in assets)+path_for(render['asset_id']).stat().st_size
    size+=sum(path_for(value['asset_id']).stat().st_size for value in render.get('variants',{}).values())
    space(size+8*1024**2)
    manifest=dict(schema_version=1,production_id=record['id'],production_version=record['version'],
        governance_sha256=record['governance']['sha256'],timeline_sha256=render['timeline_sha256'],files={},assets={})
    from video.captions import CaptionSegment,to_srt,to_vtt
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as archive:
        def document(name,value):
            raw=value.encode('utf-8') if isinstance(value,str) else value
            archive.writestr(name,raw);manifest['files'][name]=dict(size=len(raw),sha256=__import__('hashlib').sha256(raw).hexdigest())
        def media(name,path):
            archive.write(path,name);manifest['files'][name]=dict(size=path.stat().st_size,sha256=file_hash(path))
        media(f'video/VIDEO_{record["id"]}_master_v{record["version"]}.mp4',path_for(render['asset_id']))
        for aspect,item in render.get('variants',{}).items():media(f'video/variants/{aspect.replace(":","x")}.mp4',path_for(item['asset_id']))
        for key in sorted(assets):
            source=path_for(key);name='media/'+key+source.suffix;media(name,source);manifest['assets'][key]=name
        document('script/script.txt','\n\n'.join(s['input']['voiceover'] for s in record['shots']))
        document('script/script.pdf',_pdf(record))
        document('storyboard/storyboard.pdf',_pdf(record,True))
        cues=[CaptionSegment(start=cue['start'],end=cue['end'],text=cue['text']) for track in project.get('caption_tracks',[]) for cue in track.get('segments',[])]
        cues.sort(key=lambda cue:cue.start)
        document('captions/subtitles.srt',to_srt(cues));document('captions/subtitles.vtt',to_vtt(cues))
        for name,value in [('project.json',project),('governance.json',record['governance']),('shots-and-takes.json',record['shots']),
                           ('review-history.json',record['events']),('quality.json',render),('release-review.json',record['release_review'])]:
            document('audit/'+name,json.dumps(value,ensure_ascii=False,indent=2))
        document('README.txt','Client video production kit\n\nMaster and variants: video/\nScripts and storyboard: script/ and storyboard/\n'
            'Captions: captions/\nPortable timeline and frozen brand rules: audit/\nSource media: media/ (IDs map to relative paths in manifest.json).\n'
            'PDF pages preserve Unicode typography as raster artwork; searchable source wording is also in script.txt.\n'
            'Font files are not redistributed; install the named licensed fonts before re-editing.\n'
            'AI native resolution and frame rate are recorded per take; a higher export resolution is not native model resolution.\n')
        archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip():raise ValueError('The delivery archive failed integrity validation.')
    return manifest
