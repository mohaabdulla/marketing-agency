"""Run a reviewable edit through the local marketing app, for any supplied video."""
import argparse
import hashlib
import json
import time
from pathlib import Path
import requests


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--brand',default='')
    parser.add_argument('--language',default='en',choices=['en','ar','auto'])
    parser.add_argument('--instruction',default='Add readable captions, tighten pauses, add subtle zoom-ins and remove recording remarks at the end. Keep the original quality.')
    args=parser.parse_args();base='http://127.0.0.1:8000';session=requests.Session()
    for _ in range(90):
        try:
            response=session.get(base+'/api/video/editor/capabilities',timeout=3)
            if response.ok and response.json().get('quick_edit'):break
        except requests.RequestException:pass
        time.sleep(.5)
    else:raise RuntimeError('Start the current marketing app on port 8000')
    def call(path,body=None,files=None):
        r=session.post(base+'/api/video'+path,json=body,files=files,timeout=30);r.raise_for_status();return r.json()
    original_hash=hashlib.sha256(args.source.read_bytes()).hexdigest()
    with args.source.open('rb') as stream:asset=call('/upload',files={'file':(args.source.name,stream,'video/mp4')})
    rules={};logo=None
    if args.brand:
        brands=session.get(base+'/api/brands',timeout=10).json();brands=brands.get('brands',brands) if isinstance(brands,dict) else brands
        brand=next(b for b in brands if b['id']==args.brand)
        rules=dict(brand_name=brand['brand_name'],primary_colors=[brand['primary_hex']],secondary_colors=[brand['accent_hex']],font_preferences=['Arial'],language=args.language if args.language!='auto' else 'en')
        if brand.get('logo_path'):
            response=session.get(base+brand['logo_path'],timeout=15);response.raise_for_status()
            logo=call('/upload',files={'file':(Path(brand['logo_path']).name,response.content,'image/png')})
            rules.update(logo_asset_id=logo['id'],logo_placement='top-right')
    project=call('/projects',dict(name='Review '+args.output.name,brand_id=args.brand or None,brand_rules=rules or None,
        editing_brief=dict(logo_asset_id=logo['id'] if logo else None,instruction=args.instruction),
        creative_context=dict(objective='Social video edit',platform='Instagram / TikTok',language=args.language if args.language!='auto' else 'en'),
        clips=[dict(asset_id=asset['id'],duration=asset['duration'])]))
    job=call('/projects/'+project['id']+'/quick-edit',dict(asset_id=asset['id'],instruction=args.instruction,language=args.language))
    print('Project',project['id'],'job',job['id'],flush=True);last=None
    for _ in range(1800):
        r=session.get(base+'/api/video/jobs/'+job['id'],timeout=15);r.raise_for_status();state=r.json();status=(state['state'],state.get('phase'))
        if status!=last:print(status,flush=True);last=status
        if state['state'] in {'completed','failed','cancelled'}:break
        time.sleep(1)
    if state['state']!='completed':raise RuntimeError(state)
    result=state['result'];response=session.get(base+'/api/video/download/'+result['id'],timeout=60);response.raise_for_status()
    args.output.mkdir(parents=True,exist_ok=True);(args.output/'edited.mp4').write_bytes(response.content)
    (args.output/'result.json').write_text(json.dumps(dict(source_sha256=original_hash,source_asset=asset,source_project_id=project['id'],result=result),indent=2),encoding='utf-8')
    assert hashlib.sha256(args.source.read_bytes()).hexdigest()==original_hash
    print('Saved',args.output/'edited.mp4',json.dumps(result['edit_report']),flush=True)


if __name__=='__main__':main()
