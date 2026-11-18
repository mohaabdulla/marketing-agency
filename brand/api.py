"""One guideline library used by Image/GIF and Video Studio: the /api/guidelines router."""
import re

from fastapi import APIRouter, File, UploadFile, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from brand import guidelines as g
from video.storage import LOCK, atomic

router = APIRouter(prefix='/api/guidelines', tags=['guidelines'])


def guard(fn, *args):
    try:
        return fn(*args)
    except FileNotFoundError:
        raise HTTPException(404, 'Guideline not found in this workspace')
    except ModuleNotFoundError as exc:
        raise HTTPException(503,'Missing guideline dependency '+str(exc.name)+'. Install requirements/brand-video.txt and restart.')
    except ValidationError as exc:
        raise HTTPException(422,exc.errors(include_input=False,include_context=False))
    except ValueError as exc:
        message=str(exc)
        if len(message)<400 and not re.search(r'[A-Za-z]:[\\/]',message):
            raise HTTPException(422,message)
        raise HTTPException(422,'Invalid guideline values; review the supported fields and limits')
    except Exception:
        raise HTTPException(422, 'Invalid guideline. Use a valid, unencrypted PDF, DOCX, UTF-8 text/Markdown or structured brand JSON within the documented limits.')


@router.get('')
def listing():
    g.HOME.mkdir(parents=True, exist_ok=True)
    return [g.public_view(g.get(p.stem)) for p in sorted(g.HOME.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True)]


@router.post('', status_code=201)
async def upload(file: UploadFile = File(...)):
    try:
        raw = await file.read(8 * 1024**2 + 1)
        return await run_in_threadpool(guard,g.upload_documents,[(file.filename or '',raw)])
    finally:
        await file.close()


@router.get('/{key}')
def get(key: str):
    return g.public_view(guard(g.get, key))


class Review(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: int = Field(ge=1)
    rules: g.Rules
    confirmed: bool = True


@router.put('/{key}')
def review(key: str, body: Review):
    with LOCK:
        value = guard(g.get, key)
        if value['version'] != body.expected_version:
            raise HTTPException(409, 'Guidelines changed; reload before confirming')
        if body.rules.logo_asset_id:
            from video.assets import path_for
            guard(path_for, body.rules.logo_asset_id)
        edited=body.rules.model_dump()
        changes={key:dict(before=value['rules'].get(key),after=item) for key,item in edited.items() if item!=value['rules'].get(key)}
        if changes:
            value['review'].setdefault('operator_changes',[]).append(dict(version=value['version']+1,fields=changes))
        value.update(version=value['version'] + 1, rules=edited, confirmed=body.confirmed)
        value['review']['operator_reviewed'] = body.confirmed
        value['review'].setdefault('original_extraction_conflicts',value['review'].get('conflicting_rules', []))
        value['review']['conflicting_rules'] = [] if body.confirmed else value['review']['conflicting_rules']
        atomic(g.HOME / (value['id'] + '.json'), value)
    return g.public_view(value)


@router.get('/{key}/original/{index}')
def original(key: str, index: int):
    value = guard(g.get, key)
    if not 0 <= index < len(value['originals']):
        raise HTTPException(404, 'Original document not found')
    doc = value['originals'][index]
    return FileResponse(g.HOME / doc['filename'], filename=doc['name'],
                        headers={'Content-Security-Policy': "default-src 'none'; sandbox", 'X-Content-Type-Options': 'nosniff'})


@router.post('/from-brand/{brand_id}', status_code=201)
def from_brand(brand_id: str):
    from brand.kits import get_brand
    import json
    kit = get_brand(brand_id)
    if not kit:
        raise HTTPException(404, 'Brand kit not found')
    rules = dict(brand_name=kit['brand_name'], primary_colors=[kit['primary_hex']], secondary_colors=[kit['accent_hex']])
    if kit.get('logo_path'):
        from video.assets import existing
        asset = guard(existing, kit['logo_path'])
        rules['logo_asset_id'] = asset['id']
    return guard(g.upload_documents, [('brand-kit.json', json.dumps(rules).encode())])
