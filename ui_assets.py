"""Version the local UI module graph so an ordinary reload cannot keep old imports."""
import hashlib
import re
from pathlib import Path
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

ROOT=Path(__file__).resolve().parent


class CampaignStaticFiles(StaticFiles):
    async def get_response(self,path,scope):
        parts=path.replace('\\','/').split('/')
        if len(parts)>1:
            base=Path(self.directory)
            if not re.fullmatch(r'[a-f0-9]{32}',parts[0]) or not (base/parts[0]/'_complete.json').is_file():
                raise HTTPException(404)
        return await super().get_response(path,scope)


def revision():
    digest=hashlib.sha256()
    for path in [ROOT/'index.html',*sorted((ROOT/'static/js').glob('*.js')),*sorted((ROOT/'static/css').glob('*.css'))]:
        digest.update(path.read_bytes())
    return digest.hexdigest()[:14]


def index_response(path):
    tag=revision();text=path.read_text(encoding='utf-8')
    text=re.sub(r'(/static/(?:js|css)/[^"?]+\.(?:js|css))(?:\?[^" ]*)?',lambda m:m[1]+'?v='+tag,text)
    text=text.replace('</head>','<script>window.lexnisUiVersion="'+tag+'";</script></head>')
    return Response(text,media_type='text/html',headers={'Cache-Control':'no-store','X-Studio-UI-Version':tag})


class StudioStaticFiles(StaticFiles):
    async def get_response(self,path,scope):
        relative=path.replace('\\','/').lstrip('/')
        if relative.startswith('js/') and relative.endswith('.js'):
            filename,stat=self.lookup_path(relative)
            if stat and Path(filename).is_file():
                tag=revision();text=Path(filename).read_text(encoding='utf-8')
                text=re.sub(r"(['\"])(\./[^'\"?]+\.js)(?:\?[^'\"]*)?\1",lambda m:m[1]+m[2]+'?v='+tag+m[1],text)
                return Response(text,media_type='text/javascript',headers={'Cache-Control':'no-store','X-Studio-UI-Version':tag})
        response=await super().get_response(path,scope)
        if path.endswith(('.css','.js')):response.headers['Cache-Control']='no-store'
        return response
