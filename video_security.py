"""Reject oversized or cross-origin video requests before multipart parsing/spooling."""
import os
import threading
from urllib.parse import urlsplit
from starlette.responses import JSONResponse
from starlette.exceptions import HTTPException
from video_storage import MAX_UPLOAD


class VideoRequestLimits:
    def __init__(self, app):
        self.app = app
        self.upload_slots = threading.BoundedSemaphore(3)

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or not scope.get('path', '').startswith('/api/video/'):
            return await self.app(scope, receive, send)
        headers = dict(scope.get('headers', []))
        origin = headers.get(b'origin', b'').decode('latin-1')
        own_origin = scope.get('scheme', 'http') + '://' + headers.get(b'host', b'').decode('latin-1')
        allowed = [x.strip() for x in os.getenv('VIDEO_ALLOWED_ORIGINS','').split(',') if x.strip()]
        if origin and origin != own_origin and origin not in allowed:
            return await JSONResponse({'detail':'Video requests must originate from this application'},403)(scope,receive,send)
        uploading = scope['path'] == '/api/video/upload' and scope['method'] == 'POST'
        limit = MAX_UPLOAD + 1024**2 if uploading else 2*1024**2
        try:
            length = int(headers.get(b'content-length', b'0'))
        except ValueError:
            length = limit+1
        if length > limit:
            return await JSONResponse({'detail':'Request exceeds video upload limit'},413)(scope,receive,send)
        slot = self.upload_slots.acquire(blocking=False) if uploading else True
        if not slot:
            return await JSONResponse({'detail':'Too many simultaneous uploads; retry shortly'},429)(scope,receive,send)
        received = 0
        async def bounded_receive():
            nonlocal received
            message = await receive()
            received += len(message.get('body', b''))
            if received > limit:
                raise HTTPException(413, 'Request exceeds video upload limit')
            return message
        try:
            await self.app(scope, bounded_receive, send)
        finally:
            if uploading:
                self.upload_slots.release()
