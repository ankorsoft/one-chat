"""Authentication and authorization middleware."""
import re
from typing import Optional, Callable
from fastapi import Request, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from backend.config import settings


class CSRFDoubleSubmitMiddleware(BaseHTTPMiddleware):
    """CSRF protection using Double-Submit Cookie pattern."""

    async def dispatch(self, request: Request, call_next):
        # Skip CSRF for safe methods
        if request.method in ["GET", "HEAD", "OPTIONS"]:
            return await call_next(request)

        # Get CSRF token from cookie and header
        csrf_cookie = request.cookies.get("csrf_token")
        csrf_header = request.headers.get("X-CSRF-Token")

        # Validate CSRF token for state-changing requests
        if not csrf_cookie or not csrf_header:
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"detail": "CSRF token missing"},
            )

        if not self._safe_compare(csrf_cookie, csrf_header):
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"detail": "CSRF token mismatch"},
            )

        return await call_next(request)

    @staticmethod
    def _safe_compare(a: str, b: str) -> bool:
        return a == b  # In production, use hmac.compare_digest


class WorkspaceAuthMiddleware(BaseHTTPMiddleware):
    """Validate workspace_id from JWT and set context."""

    def __init__(self, app, token_service):
        super().__init__(app)
        self.token_service = token_service

    async def dispatch(self, request: Request, call_next):
        # Skip auth for public endpoints
        if request.url.path in ["/health", "/ready", "/api/v1/auth/login", "/api/v1/auth/register"]:
            return await call_next(request)

        # Extract Bearer token
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Missing or invalid authorization header"},
            )

        token = auth_header.split(" ", 1)[1]

        try:
            payload = self.token_service.verify_access_token(token)
            request.state.user_id = payload["user_id"]
            request.state.workspace_id = payload["workspace_id"]
        except Exception as e:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": f"Invalid token: {str(e)}"},
            )

        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-channel rate limiting using TokenBucket."""

    def __init__(self, app, cache_service):
        super().__init__(app)
        self.cache = cache_service

    async def dispatch(self, request: Request, call_next):
        # Apply rate limit only to webhook endpoints
        if not request.url.path.startswith("/api/v1/webhooks/"):
            return await call_next(request)

        # Extract channel_account_id from path or headers
        channel_account_id = request.headers.get("X-Channel-Account-ID")
        if not channel_account_id:
            # Try to extract from path
            match = re.search(r"/webhooks/(\w+)/([^/]+)", request.url.path)
            if match:
                channel_account_id = match.group(2)

        if not channel_account_id:
            return await call_next(request)

        # Check rate limit
        key = f"rate_limit:{channel_account_id}"
        current = await self.cache.get(key)

        if current is None:
            await self.cache.set(key, "1", ttl=60)
            return await call_next(request)

        count = int(current)
        if count >= 100:  # 100 requests per minute default
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "Rate limit exceeded", "retry_after": 60},
                headers={"Retry-After": "60"},
            )

        await self.cache.set(key, str(count + 1), ttl=60)
        return await call_next(request)


def create_auth_middleware(token_service):
    """Factory for creating auth middleware with dependencies."""
    def factory(app):
        return WorkspaceAuthMiddleware(app, token_service)
    return factory


# Security helper for setting CSRF cookie
def set_csrf_cookie(response, csrf_token: str):
    response.set_cookie(
        key="csrf_token",
        value=csrf_token,
        httponly=False,  # Must be accessible by JS
        secure=settings.SECURE_COOKIES,
        samesite="lax",
        max_age=3600,
    )
    return response
