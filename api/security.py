"""Bound public request sizes and per-process traffic; database limits guard SMS."""
from collections import OrderedDict, deque
from threading import Lock
from time import monotonic

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class RequestProtection(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.windows = OrderedDict()
        self.lock = Lock()

    async def dispatch(self, request, call_next):
        ip = request.client.host if request.client else "unknown"
        now = monotonic()
        with self.lock:
            bucket = self.windows.setdefault(ip, deque())
            while bucket and now - bucket[0] >= 60:
                bucket.popleft()
            self.windows.move_to_end(ip)
            if len(bucket) >= 120:
                return JSONResponse({"detail": "Too many requests."}, 429, headers={"Retry-After": "60"})
            bucket.append(now)
            while len(self.windows) > 10000:
                self.windows.popitem(last=False)
        if request.method in ("POST", "PUT", "PATCH"):
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > 65536:
                    return JSONResponse({"detail": "Request body exceeds 64 KiB."}, 413)
                chunks.append(chunk)
            request._body = b"".join(chunks)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Allow worker-based MapLibre and the current CDN fonts/scripts, while
        # preventing third-party frames from embedding operator pages.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline' https://unpkg.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://unpkg.com https://fonts.googleapis.com https://cdn.jsdelivr.net; "
            "font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob: https:; "
            "connect-src 'self' http://localhost:8000 https://*.cartocdn.com https://*.supabase.co https://floodsight-starter.onrender.com; "
            "worker-src 'self' blob:; frame-src 'self' https://floodsight-starter.onrender.com; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'self'"
        )
        return response
