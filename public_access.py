"""Opt-in guest workspaces. Identity comes only from a server-issued opaque cookie."""
import contextvars
import hashlib
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import unquote
from starlette.responses import JSONResponse, FileResponse

ROOT = Path(__file__).resolve().parent
_guest = contextvars.ContextVar('lexnis_guest', default=None)
_lock = threading.RLock()
COOKIE = 'lexnis_guest'
TTL = 7 * 86400


def enabled():
    return os.getenv('PUBLIC_TEST_MODE', 'false').lower() in {'true', '1', 'yes'}


def guest():
    return _guest.get()


def guest_root():
    return Path(os.getenv('PUBLIC_TEST_DATA_DIR', str(ROOT / 'output/public-test'))).resolve()


def folder(name):
    if not guest():
        raise ValueError('Guest workspace required')
    return guest_root() / guest() / name


class ScopedPath(os.PathLike):
    """Resolve storage at use time, including copied contexts in background workers."""
    def __init__(self, default, name):
        self.default, self.name = Path(default), name
    def path(self):
        return folder(self.name) if guest() else self.default
    def __fspath__(self):
        return str(self.path())
    def __str__(self):
        return str(self.path())
    def __truediv__(self, name):
        return self.path() / name
    def __getattr__(self, key):
        return getattr(self.path(), key)


def scoped(default, name):
    return ScopedPath(default, name)


def validate_visual(raw, filename):
    if not 0 < len(raw) <= 16*1024**2:
        raise ValueError('Visual uploads must be nonempty and at most 16 MB')
    if Path(filename).suffix.lower() == '.svg':
        import xml.etree.ElementTree as ET
        if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
            raise ValueError('SVG entities are not allowed')
        node = ET.fromstring(raw)
        if not node.tag.lower().endswith('svg'):
            raise ValueError('Invalid SVG signature')
        for element in node.iter():
            if element.tag.rsplit('}',1)[-1].lower() in {'script','foreignobject','iframe','object','embed'}:
                raise ValueError('Active SVG content is not allowed')
            for key, value in element.attrib.items():
                if key.lower().startswith('on') or (key.lower().endswith('href') and not value.startswith('#')):
                    raise ValueError('SVG event handlers and external references are not allowed')
            css = ' '.join(element.attrib.values()) + ' ' + (element.text or '')
            if '@import' in css.lower() or any(not v.strip(' "\'').startswith('#') for v in re.findall(r'url\(([^)]+)\)',css,re.I)):
                raise ValueError('External SVG resources are not allowed')
        return
    from PIL import Image
    import io
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.width*image.height > 64000000 or image.format not in {'JPEG','PNG','WEBP','GIF','BMP','TIFF'}:
                raise ValueError('Unsupported visual format or dimensions')
            expected={'.jpg':'JPEG','.jpeg':'JPEG','.png':'PNG','.webp':'WEBP','.gif':'GIF','.bmp':'BMP','.tif':'TIFF','.tiff':'TIFF'}
            if expected.get(Path(filename).suffix.lower()) != image.format:
                raise ValueError('Visual signature does not match its filename')
            image.verify()
    except Exception:
        raise ValueError('Upload a valid supported visual with at most 64 million pixels')


def public_asset(path):
    # Curated application branding only; user-generated static fixtures and brand JSON stay private.
    return path in {'/static/assets/brand_logo.png', '/static/assets/lexnis_logo.png'}


def media_path(url):
    from urllib.parse import urlsplit
    parsed = urlsplit(url)
    value = unquote(parsed.path)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or '\\' in value:
        raise ValueError('Use a managed workspace media URL')
    for prefix, name in [('/renders/', 'renders'), ('/uploads/', 'uploads'), ('/creative-renders/', 'creative_renders')]:
        if value.startswith(prefix):
            leaf = value[len(prefix):]
            if not leaf or '/' in leaf or '..' in leaf:
                break
            base = folder(name).resolve()
            path = (base / leaf).resolve()
            if path.parent == base and path.is_file():
                return path
    if public_asset(value):
        return ROOT / value.lstrip('/')
    raise ValueError('Media is not in this guest workspace')


def _session(token, create=False):
    root = guest_root()
    root.mkdir(parents=True, exist_ok=True)
    if token and re.fullmatch(r'[a-f0-9]{64}', token):
        key = hashlib.sha256(token.encode()).hexdigest()[:32]
        path = root / key / 'session.json'
        try:
            if json.loads(path.read_text())['expires'] > time.time():
                return key, token
        except (OSError, ValueError, KeyError):
            pass
    if not create:
        return None, None
    with _lock:
        if sum(1 for _ in root.glob('*/session.json')) >= int(os.getenv('PUBLIC_TEST_MAX_SESSIONS', '1000')):
            raise ValueError('Testing session capacity reached; contact the operator')
        token = secrets.token_hex(32)
        key = hashlib.sha256(token.encode()).hexdigest()[:32]
        home = root / key
        for name in ('renders', 'uploads', 'guidelines', 'creative_projects', 'creative_assets', 'creative_renders',
                     'video/assets', 'video/projects', 'video/jobs', 'video/work', 'video/revisions', 'video/analysis'):
            (home / name).mkdir(parents=True, exist_ok=True)
        (home / 'brands.json').write_text('[]')
        (home / 'session.json').write_text(json.dumps(dict(expires=time.time() + TTL)))
        return key, token


def _clean(value):
    """Redact filesystem paths in legacy JSON responses without changing their response shape."""
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, str):
        home = str(folder('')).rstrip('\\/')
        # Managed media paths become URLs. Unmanaged absolute paths are not exposed.
        for name, prefix in [('renders', '/renders/'), ('uploads', '/uploads/'), ('creative_renders', '/creative-renders/')]:
            for base in (str(folder(name)), str(folder(name)).replace('\\', '/')):
                if value.startswith(base + os.sep) or value.startswith(base + '/'):
                    return prefix + Path(value).name
        if home in value or home.replace('\\', '/') in value or re.search(r'[A-Za-z]:[\\/]', value):
            return 'Managed workspace asset'
        if value.startswith('/') and not value.startswith(('/api/','/uploads/','/renders/','/static/','/creative-renders/')):
            return 'Managed workspace asset'
    return value


def validate_payload(value, key=''):
    if isinstance(value, list):
        if len(value) > 2000:
            raise ValueError('Too many items in request')
        return [validate_payload(v, key) for v in value]
    if isinstance(value, dict):
        if 'canvas' in value and isinstance(value['canvas'], dict):
            canvas = value['canvas']
            if any(float(canvas.get(k, default)) > maximum for k, default, maximum in
                   [('width', 1080, 1920), ('height', 1080, 1920), ('fps', 30, 60), ('duration', 5, 30)]):
                raise ValueError('Creative canvas exceeds public rendering limits')
        return {k: validate_payload(v, k) for k, v in value.items()}
    if isinstance(value, str) and value:
        if key.endswith('_id') and not re.fullmatch(r'[A-Za-z0-9_-]{1,160}',value):
            raise ValueError('Invalid object identifier')
        if key.endswith('_path') or key in {'logo_url', 'image_url', 'uploaded_image_url', 'uploaded_image_urls', 'source_url'}:
            path = media_path(value)
            return value
    return value


def bytes_used(directory):
    size=0
    for path in directory.rglob('*'):
        try:
            if path.is_file():
                size+=path.stat().st_size
        except OSError:
            pass
    return size


class PublicTestingMiddleware:
    def __init__(self, app):
        self.app = app
        self.render_slots = threading.BoundedSemaphore(2)
        self.recovered=set()

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        if not enabled():
            import ipaddress
            from urllib.parse import urlsplit
            peer=(scope.get('client') or ('',0))[0]
            headers=dict(scope.get('headers',[]))
            try:
                local=ipaddress.ip_address(peer).is_loopback
            except ValueError:
                local=peer=='testclient'
            host=urlsplit('http://'+headers.get(b'host',b'').decode('latin-1')).hostname
            if not local or host not in {'localhost','127.0.0.1','::1',*({'testserver'} if peer=='testclient' else set())}:
                return await JSONResponse({'detail':'Local operator mode is loopback-only. Enable PUBLIC_TEST_MODE for isolated anonymous testing.'},403)(scope,receive,send)
            return await self.app(scope, receive, send)
        from http.cookies import SimpleCookie
        headers = dict(scope.get('headers', []))
        path, method = scope['path'], scope['method']
        if '\\' in path or ':' in path or any(part in {'.','..'} for part in path.split('/')):
            return await JSONResponse({'detail':'Invalid path'},400)(scope,receive,send)
        own = scope.get('scheme', 'http') + '://' + headers.get(b'host', b'').decode('latin-1')
        origin = headers.get(b'origin', b'').decode('latin-1')
        landing = method == 'GET' and path == '/' and headers.get(b'sec-fetch-mode') == b'navigate'
        if (origin and origin != own) or (headers.get(b'sec-fetch-site') == b'cross-site' and not landing):
            return await JSONResponse({'detail': 'Use this application origin'}, 403)(scope, receive, send)
        cookie = SimpleCookie()
        try:
            cookie.load(headers.get(b'cookie', b'').decode('latin-1'))
        except Exception:
            pass
        try:
            key, token = _session(cookie[COOKIE].value if COOKIE in cookie else None,
                                  create=method == 'GET' and path in {'/', '/api/session'})
        except ValueError as exc:
            return await JSONResponse({'detail': str(exc)}, 503)(scope, receive, send)
        if not key:
            if path.startswith('/static/') and not path.startswith('/static/assets/'):
                return await self.app(scope, receive, send)
            return await JSONResponse({'detail': 'Open the application to initialize your private guest session'}, 401)(scope, receive, send)
        reset = _guest.set(key)
        acquired = False
        try:
            if key not in self.recovered:
                with _lock:
                    if key not in self.recovered:
                        from video_jobs import jobs
                        from video_storage import atomic
                        with jobs.lock:
                            for item in folder('video/jobs').glob('*.json'):
                                data=json.loads(item.read_text())
                                if data.get('state') not in {'completed','failed','cancelled'} and data['id'] not in jobs.active:
                                    data.update(state='failed',error='Server restarted; submit this job again')
                                    atomic(item,data)
                        self.recovered.add(key)
            if path == '/api/session':
                response = JSONResponse(dict(public_test_mode=True, guest=True, workspace=key,
                                             csrf='same-origin + SameSite cookie', expires_in=TTL))
                response.set_cookie(COOKIE, token, httponly=True, secure=scope.get('scheme') == 'https', samesite='lax', max_age=TTL, path='/')
                response.headers['Cache-Control'] = 'no-store'
                return await response(scope, receive, send)
            if path.startswith(('/api/admin', '/api/system/', '/api/agency/system/', '/api/agency/connectors', '/docs', '/openapi', '/redoc')):
                return await JSONResponse({'detail': 'Operator-only capability'}, 403)(scope, receive, send)
            if path.startswith('/test_assets/') or (path.startswith('/static/assets/') and not public_asset(path)):
                return await JSONResponse({'detail': 'Asset not found'}, 404)(scope, receive, send)
            if path.startswith(('/renders/', '/uploads/', '/creative-renders/')):
                try:
                    asset = media_path(path)
                except ValueError:
                    return await JSONResponse({'detail': 'Asset not found'}, 404)(scope, receive, send)
                return await FileResponse(asset, headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
                                                         'Content-Security-Policy': "default-src 'none'; sandbox"})(scope, receive, send)
            if method not in {'GET', 'HEAD', 'OPTIONS'}:
                used = bytes_used(folder(''))
                total = bytes_used(guest_root())
                if used > 2 * 1024**3 or total > int(os.getenv('PUBLIC_TEST_DISK_QUOTA_GB', '8')) * 1024**3:
                    return await JSONResponse({'detail': 'Testing storage capacity reached; remove unused media or contact the operator'}, 507)(scope, receive, send)
                content_type = headers.get(b'content-type', b'')
                limit = 2 * 1024**2 if b'application/json' in content_type else (17 * 1024**2 if path in {
                    '/api/upload-guidelines','/api/guidelines','/api/analyze-brand','/api/upload-visual','/api/upload-logo'} else 257 * 1024**2)
                raw = bytearray()
                if b'application/json' in content_type:
                    while True:
                        message = await receive()
                        raw.extend(message.get('body', b''))
                        if len(raw) > limit:
                            return await JSONResponse({'detail': 'Request too large'}, 413)(scope, receive, send)
                        if not message.get('more_body'):
                            break
                    try:
                        raw = json.dumps(validate_payload(json.loads(raw)), allow_nan=False).encode() if raw else b''
                    except (ValueError, TypeError, RecursionError):
                        return await JSONResponse({'detail': 'Invalid request or inaccessible media reference'}, 400)(scope, receive, send)
                    original_receive = receive
                    async def json_receive():
                        nonlocal raw
                        if raw is not None:
                            data, raw = raw, None
                            return dict(type='http.request', body=data, more_body=False)
                        return await original_receive()
                    receive = json_receive
                else:
                    original_receive = receive
                    received = 0
                    async def upload_receive():
                        nonlocal received
                        from starlette.exceptions import HTTPException
                        message = await original_receive()
                        received += len(message.get('body', b''))
                        if received > limit:
                            raise HTTPException(413, 'Upload exceeds public safety limit')
                        return message
                    receive = upload_receive
                if path.startswith(('/api/generate', '/api/campaign/generate', '/api/template', '/api/creative/render', '/api/render',
                                    '/api/guidelines', '/api/upload-guidelines', '/api/analyze-brand')) or path.endswith('/documents/upload'):
                    import asyncio
                    deadline = time.monotonic() + 60
                    while not self.render_slots.acquire(blocking=False):
                        if time.monotonic() > deadline:
                            return await JSONResponse({'detail': 'Render queue is busy; retry shortly'}, 503)(scope, receive, send)
                        await asyncio.sleep(.1)
                    acquired = True
            start = None
            chunks = []
            async def protected(message):
                nonlocal start
                if message['type'] == 'http.response.start':
                    start = message
                    start['headers'] = [(k, v) for k, v in start.get('headers', []) if k.lower() not in {b'cache-control'}]
                    start['headers'] += [(b'cache-control', b'private, no-store'), (b'x-content-type-options', b'nosniff')]
                    if path == '/':
                        start['headers'].append((b'set-cookie', f'{COOKIE}={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age={TTL}{"; Secure" if scope.get("scheme") == "https" else ""}'.encode()))
                    if not any(k == b'content-type' and b'application/json' in v for k, v in start['headers']):
                        await send(start)
                        start = None
                elif start is not None and message['type'] == 'http.response.body':
                    chunks.append(message.get('body', b''))
                    if not message.get('more_body'):
                        raw = b''.join(chunks)
                        try:
                            raw = json.dumps(_clean(json.loads(raw)), ensure_ascii=False, allow_nan=False).encode()
                        except (ValueError, UnicodeDecodeError):
                            raw = b'{"detail":"Invalid server response"}'
                        start['headers'] = [(k, v) for k, v in start['headers'] if k != b'content-length'] + [(b'content-length', str(len(raw)).encode())]
                        await send(start)
                        await send(dict(type='http.response.body', body=raw))
                else:
                    await send(message)
            await self.app(scope, receive, protected)
        finally:
            if acquired:
                self.render_slots.release()
            _guest.reset(reset)
