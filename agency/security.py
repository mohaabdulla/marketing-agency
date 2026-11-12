"""New client data is loopback-only until real multi-user authentication exists."""
import ipaddress
from urllib.parse import urlsplit
from fastapi import HTTPException, Request
from starlette.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


def allowed(scope):
    headers = dict(scope.get('headers',[]))
    peer = (scope.get('client') or ('',0))[0]
    testing = peer == 'testclient'
    try:
        local = ipaddress.ip_address(peer).is_loopback
    except ValueError:
        local = testing
    host = urlsplit('http://'+headers.get(b'host',b'').decode('latin-1')).hostname
    if not local or host not in {'localhost','127.0.0.1','::1',*({'testserver'} if testing else set())}:
        return False
    origin = headers.get(b'origin',b'').decode('latin-1')
    own = scope.get('scheme','http')+'://'+headers.get(b'host',b'').decode('latin-1')
    return (not origin or origin == own) and headers.get(b'sec-fetch-site') != b'cross-site'


def local_operator(request: Request):
    if not allowed(request.scope):
        raise HTTPException(403,'Agency data is available only to the local operator from this application origin')


class AgencyRequestLimits:
    def __init__(self,app):
        self.app=app

    async def __call__(self,scope,receive,send):
        if scope['type']!='http' or not scope.get('path','').startswith('/api/agency'):
            return await self.app(scope,receive,send)
        if not allowed(scope):
            return await JSONResponse({'detail':'Agency data is loopback-only; remote or cross-origin access is disabled'},403)(scope,receive,send)
        limit = 11*1024**2 if scope['path'].endswith('/research/import') else 2*1024**2
        headers=dict(scope.get('headers',[]))
        try:
            length=int(headers.get(b'content-length',b'0'))
        except ValueError:
            length=limit+1
        if length>limit:
            return await JSONResponse({'detail':'Agency request exceeds its size limit'},413)(scope,receive,send)
        received=0
        async def bounded():
            nonlocal received
            message=await receive()
            received+=len(message.get('body',b''))
            if received>limit:
                raise StarletteHTTPException(413,'Agency request exceeds its size limit')
            return message
        async def secured(message):
            if message['type']=='http.response.start':
                message.setdefault('headers',[]).extend([(b'cache-control',b'no-store'),(b'x-content-type-options',b'nosniff')])
            await send(message)
        return await self.app(scope,bounded,secured)
