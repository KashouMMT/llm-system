"""
CSRF protection: a browser-request gate that runs before the router.

Three checks, applied to every state-changing request (anything that is
not GET/HEAD/OPTIONS/TRACE):

1. Origin / Referer must be in `CSRF_TRUSTED_ORIGINS`. The browser sets
   these and page JavaScript cannot forge them, so this alone stops a
   cross-site page from driving the API — including login CSRF, which no
   token scheme can cover because there is no session yet.
2. The body's Content-Type may not be one a cross-site `<form>` can send
   (`application/x-www-form-urlencoded`, `multipart/form-data`,
   `text/plain`). Requiring JSON closes form-based CSRF on endpoints that
   take a body.
3. A signed double-submit token: the `csrf_token` cookie and the
   `X-CSRF-Token` header must be equal, and the token's HMAC must verify
   against the caller's session cookie. Equality defeats the classic
   cross-site attacker (they cannot read the cookie to set the header);
   binding the signature to the session token defeats a cookie planted
   from a sibling subdomain (they cannot sign for a session they do not
   hold).

The gate is a pure-ASGI middleware, not a `BaseHTTPMiddleware`: it either
answers a rejected request itself or hands a passing one straight to the
app, and never wraps the response stream — which is what keeps it clear
of the SSE endpoint.
"""

import base64
import hashlib
import hmac
import secrets
from urllib.parse import urlsplit

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config.settings import (
    COOKIE_SAMESITE,
    COOKIE_SECURE,
    CSRF_SECRET,
    CSRF_TRUSTED_ORIGINS,
    SESSION_COOKIE_NAME,
    SESSION_TTL_HOURS,
)
from app.utils.logger import logger

CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "x-csrf-token"

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

# A cross-site <form> can only submit one of these encodings.
_FORM_CONTENT_TYPES = frozenset(
    {
        "application/x-www-form-urlencoded",
        "multipart/form-data",
        "text/plain",
    }
)

# Skipped for the token check only — these run before a session, and so
# before a CSRF cookie, exists. Check 1 still covers them.
_TOKEN_EXEMPT_PATHS = frozenset({"/auth/login", "/auth/register"})

_TRUSTED_ORIGINS = frozenset(CSRF_TRUSTED_ORIGINS)

_CSRF_COOKIE_MAX_AGE = SESSION_TTL_HOURS * 3600

if CSRF_SECRET:
    _SECRET = CSRF_SECRET.encode()
else:
    _SECRET = secrets.token_urlsafe(32).encode()
    logger.warning(
        "CSRF_SECRET is not set — generated an ephemeral key. Every CSRF "
        "cookie stops validating after a restart; set CSRF_SECRET in the "
        "environment for a stable deployment.",
    )


def _sign(nonce: str, session_token: str) -> str:
    digest = hmac.new(
        _SECRET,
        f"{nonce}.{session_token}".encode(),
        hashlib.sha256,
    ).digest()

    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def issue_csrf_token(session_token: str) -> str:
    """
    Build a signed double-submit token: `<nonce>.<hmac(nonce, session)>`.

    `session_token` is the raw value of the session cookie. Binding the
    signature to it is what makes a planted cookie useless.
    """
    nonce = secrets.token_urlsafe(32)

    return f"{nonce}.{_sign(nonce, session_token)}"


def _token_matches_session(token: str, session_token: str) -> bool:
    nonce, _, signature = token.partition(".")

    if not nonce or not signature:
        return False

    return hmac.compare_digest(signature, _sign(nonce, session_token))


def set_csrf_cookie(response: Response, session_token: str) -> None:
    """Issue a fresh CSRF cookie bound to `session_token`."""
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=issue_csrf_token(session_token),
        max_age=_CSRF_COOKIE_MAX_AGE,
        # Not HttpOnly on purpose: the SPA reads it to echo it back in the
        # X-CSRF-Token header.
        httponly=False,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path="/",
    )


def clear_csrf_cookie(response: Response) -> None:
    response.delete_cookie(
        key=CSRF_COOKIE_NAME,
        path="/",
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
    )


def _origin_allowed(request: Request) -> bool:
    origin = request.headers.get("origin")

    if origin is not None:
        return origin.rstrip("/") in _TRUSTED_ORIGINS

    # No Origin header (some same-origin requests, older clients): fall
    # back to Referer, compared by scheme + host + port.
    referer = request.headers.get("referer")

    if not referer:
        return False

    parts = urlsplit(referer)

    if not parts.scheme or not parts.netloc:
        return False

    return f"{parts.scheme}://{parts.netloc}" in _TRUSTED_ORIGINS


def _rejection_reason(request: Request) -> str | None:
    """Return why the request fails CSRF, or None if it passes."""
    if request.method in _SAFE_METHODS:
        return None

    if not _origin_allowed(request):
        return "Origin or Referer check failed."

    base_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()

    if base_type in _FORM_CONTENT_TYPES:
        return "Unsupported Content-Type for a state-changing request."

    if request.url.path in _TOKEN_EXEMPT_PATHS:
        return None

    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    header_token = request.headers.get(CSRF_HEADER_NAME)

    if not cookie_token or not header_token:
        return "Missing CSRF token."

    if not hmac.compare_digest(cookie_token, header_token):
        return "CSRF token mismatch."

    if not _token_matches_session(
        cookie_token,
        request.cookies.get(SESSION_COOKIE_NAME, ""),
    ):
        return "Invalid CSRF token."

    return None


class CSRFMiddleware:
    """
    Pure-ASGI CSRF gate. Add it *before* the CORS middleware in
    `create_api` so CORS ends up outermost and a rejected request still
    carries the headers a browser needs to read the 403.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        reason = _rejection_reason(request)

        if reason is None:
            await self.app(scope, receive, send)
            return

        logger.info(
            "CSRF rejected | method=%s path=%s reason=%s",
            request.method,
            request.url.path,
            reason,
        )

        response = JSONResponse({"detail": reason}, status_code=403)
        await response(scope, receive, send)
