"""Baseline HTTP security headers for every response (OWASP Secure Headers Project).

Headers a route already sets are kept: sandboxed previews and downloads send their own, stricter
Content-Security-Policy. The policy here deliberately does not restrict scripts or styles, because
the studio still uses inline scripts; it only blocks framing by other sites, plugins and <base>
hijacking, and switches off device features the studio never uses.
"""

HEADERS = (
    (b'x-content-type-options', b'nosniff'),
    # Links in review pages and kits must not leak tokenised URLs to other sites.
    (b'referrer-policy', b'same-origin'),
    # The studio frames its own previews, so same-origin framing stays allowed.
    (b'x-frame-options', b'SAMEORIGIN'),
    (b'content-security-policy', b"frame-ancestors 'self'; object-src 'none'; base-uri 'self'"),
    (b'permissions-policy', b'camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()'),
    (b'cross-origin-opener-policy', b'same-origin'),
)


class SecurityHeaders:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        https = scope.get('scheme') == 'https'

        async def wrapped(message):
            if message['type'] == 'http.response.start':
                headers = list(message.get('headers', []))
                present = {name.lower() for name, _ in headers}
                headers += [(name, value) for name, value in HEADERS if name not in present]
                if https and b'strict-transport-security' not in present:
                    headers.append((b'strict-transport-security', b'max-age=31536000; includeSubDomains'))
                message['headers'] = headers
            await send(message)

        return await self.app(scope, receive, wrapped)


class StudioRequestLimits:
    """Cap request bodies on studio routes; video and agency routes enforce their own, tighter limits."""

    def __init__(self, app):
        import os
        self.app = app
        self.limit = int(os.getenv('STUDIO_MAX_REQUEST_MB', '64')) * 1024**2

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        if scope['type'] != 'http' or not path.startswith('/api/') or path.startswith(('/api/video', '/api/agency')):
            return await self.app(scope, receive, send)
        from starlette.exceptions import HTTPException
        from starlette.responses import JSONResponse
        declared = dict(scope.get('headers', [])).get(b'content-length', b'0')
        if not declared.isdigit() or int(declared) > self.limit:
            return await JSONResponse({'detail': 'Request exceeds the upload size limit'}, 413)(scope, receive, send)
        received = 0

        async def bounded():
            nonlocal received
            message = await receive()
            received += len(message.get('body', b''))
            if received > self.limit:
                raise HTTPException(413, 'Request exceeds the upload size limit')
            return message

        return await self.app(scope, bounded, send)


def install_validation_handler(app):
    """Answer invalid requests with 422 and never echo the rejected input back.

    FastAPI's default handler serialises the raw request body into the error; a binary body cannot
    be serialised and turned every validation error into a 500, and a text body was reflected whole.
    """
    from fastapi.exceptions import RequestValidationError
    from starlette.responses import JSONResponse

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        detail = [dict(type=str(e.get('type', 'value_error')), loc=[x if isinstance(x, (int, str)) else str(x) for x in e.get('loc', ())],
                       msg=str(e.get('msg', 'Invalid value'))) for e in exc.errors()]
        return JSONResponse({'detail': detail}, 422)
