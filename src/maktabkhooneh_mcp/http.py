"""Shared async HTTP client for Maktabkhooneh.

Maktabkhooneh (maktabkhooneh.org) is a Nuxt site over a public Django REST API at `/api/v1`. Every tool goes through
`api` (JSON) or `page` (sitemap XML). `_send` caps concurrency, retries timeouts, network errors, empty 200 bodies, 429
and 5xx (jittered backoff, Retry-After honoured; GET only), caps the body size, and turns HTTP failures into
`ToolError` messages the model can act on. No bot challenge was seen; a challenge page is reported, not solved.
"""

from __future__ import annotations

import asyncio
import os
import random
import re
import time
from typing import Any

import httpx
from httpx_curl_cffi import AsyncCurlTransport
from mcp.server.mcpserver.exceptions import ToolError

SITE = "https://maktabkhooneh.org"
API = f"{SITE}/api/v1"

HEADERS = {
    # User-Agent, sec-ch-ua and TLS come from the impersonated Chrome profile (see _get_client).
    "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
}
# The API is called by the Nuxt app on the same origin.
XHR_HEADERS = {
    "Accept": "application/json",
    "Referer": f"{SITE}/",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "priority": "u=1, i",
}
DOC_HEADERS = {
    "Accept": "application/xml,text/xml,text/html;q=0.9,*/*;q=0.8",
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "priority": "u=0, i",
}

MAX_CONCURRENCY = 2
JITTER = (0.15, 0.6)  # seconds before each uncached call
MAX_RETRIES = 2
MAX_RETRY_WAIT = 10  # cap for Retry-After and backoff, seconds
MAX_BYTES = 8_000_000  # the teacher sitemap is ~600 KB; a 100-card page ~140 KB
RETRY_DELAY = 0.5

_transport: httpx.AsyncBaseTransport | None = None
_client: httpx.AsyncClient | None = None
_limit: asyncio.Semaphore | None = None
_proxy_index = 0
_retired: set[asyncio.Task] = set()

# Only the slow-changing lists (category tree, sitemaps) are cached, for an hour; callers pass `ttl`.
CACHE_MAX = 16
_cache: dict[tuple[str, tuple], tuple[float, httpx.Response]] = {}


class _XhrTransport(AsyncCurlTransport):
    """The Chrome profile sends navigation-only headers; a None value makes curl drop them (API calls are XHR)."""

    def _create_request_params(self, req: httpx.Request) -> dict[str, Any]:
        p = super()._create_request_params(req)
        p["headers"] = [*p["headers"], (b"upgrade-insecure-requests", None), (b"sec-fetch-user", None)]
        return p


class ApiError(ToolError):
    """A failed upstream call. `status` is the HTTP status, or None for network errors."""

    def __init__(self, message: str, status: int | None = None, retry_after: float | None = None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Swap the transport (tests use httpx.MockTransport). Drops the current client and the cache."""
    global _transport, _client, _limit, _proxy_index
    _transport, _client, _limit, _proxy_index = transport, None, None, 0
    _cache.clear()


async def _same_site(r: httpx.Response) -> None:
    """Refuse a redirect off maktabkhooneh.org."""
    if r.has_redirect_location:
        host = r.url.join(r.headers["location"]).host
        if host != "maktabkhooneh.org" and not host.endswith(".maktabkhooneh.org"):
            raise ApiError("maktabkhooneh.org redirected to another host; refused.")


def _proxies() -> list[str]:
    """MAKTABKHOONEH_MCP_PROXY: one proxy URL, or a comma-separated list used one at a time."""
    return [p.strip() for p in os.environ.get("MAKTABKHOONEH_MCP_PROXY", "").split(",") if p.strip()]


# A bare HTML 403 is often a plain error page; only a known bot-check marker counts as a challenge.
_CHALLENGE = re.compile(r"just a moment|captcha|challenge|arvan|attention required|enable javascript", re.I)


def _is_challenge(r: httpx.Response) -> bool:
    """A bot-check page: 403/429/503 with an HTML body that carries a known challenge marker."""
    return (
        r.status_code in (403, 429, 503)
        and "html" in r.headers.get("content-type", "") + r.text[:20].lower()
        and bool(_CHALLENGE.search(r.text[:5000]))
    )


def _next_proxy(client: httpx.AsyncClient) -> None:
    """Sticky pool: move to the next proxy after a block or connect error; the next call rebuilds the client.

    Only the client that failed may rotate: a slower request that failed on an old client must not skip a good proxy.
    The old client is closed late because other requests may still be using it.
    """
    global _client, _limit, _proxy_index
    if len(_proxies()) < 2 or client is not _client:
        return
    _client, _limit, _proxy_index = None, None, _proxy_index + 1
    t = asyncio.create_task(_close_later(client))
    _retired.add(t)
    t.add_done_callback(_retired.discard)


async def _close_later(client: httpx.AsyncClient) -> None:
    await asyncio.sleep(30)  # longer than the 30 s request timeout
    await client.aclose()


def _get_client() -> tuple[httpx.AsyncClient, asyncio.Semaphore]:
    global _client, _limit
    if _client is None:
        # Maktabkhooneh answers direct connections fine; a proxy is only used when the user opts in with
        # MAKTABKHOONEH_MCP_PROXY. curl_cffi presents Chrome's TLS/HTTP2 fingerprint and default headers.
        # The proxy goes to the transport (a client-level proxy would be ignored once a transport is given).
        proxies = _proxies()
        _client = httpx.AsyncClient(
            transport=_transport
            or _XhrTransport(
                impersonate="chrome",
                default_headers=True,
                proxy=proxies[_proxy_index % len(proxies)] if proxies else None,
                max_connections=2 * MAX_CONCURRENCY,
            ),
            headers=HEADERS,
            timeout=httpx.Timeout(30, connect=10),
            limits=httpx.Limits(max_connections=2 * MAX_CONCURRENCY),
            follow_redirects=True,
            event_hooks={"response": [_same_site]},
            trust_env=False,
        )
        _limit = asyncio.Semaphore(MAX_CONCURRENCY)
    assert _limit is not None
    return _client, _limit


async def api(path: str, params: dict[str, Any] | None = None, *, ttl: int = 0) -> Any:
    """GET a JSON path under /api/v1 and return the parsed JSON. A 301 with a JSON body (wrong course slug) is returned."""
    r = await _send(
        f"{API}{path}", params={k: v for k, v in (params or {}).items() if v is not None}, ttl=ttl, headers=XHR_HEADERS
    )
    try:
        return r.json()
    except ValueError as e:
        raise ApiError(f"maktabkhooneh.org returned a non-JSON response for {path} (HTTP {r.status_code}).") from e


async def page(path: str, *, ttl: int = 0) -> str:
    """GET a site path (the sitemaps) and return the text."""
    return (await _send(f"{SITE}{path}", ttl=ttl, headers=DOC_HEADERS)).text


async def _send(url: str, *, ttl: int, **kwargs: Any) -> httpx.Response:
    params = kwargs.get("params") or {}
    key = (url, tuple(sorted((k, str(v)) for k, v in params.items())))
    hit = _cache.get(key) if ttl else None
    if hit and time.monotonic() - hit[0] < ttl:
        return hit[1]
    r = await _fetch(url, **kwargs)
    if ttl:
        if len(_cache) >= CACHE_MAX:
            _cache.pop(next(iter(_cache)))
        _cache[key] = (time.monotonic(), r)
    return r


async def _get(client: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
    """GET with the body read in chunks and capped at MAX_BYTES."""
    async with client.stream("GET", url, **kwargs) as r:
        if int(r.headers.get("content-length") or 0) > MAX_BYTES:
            raise ApiError("maktabkhooneh.org sent a reply that is too large.", 413)
        body = bytearray()
        async for chunk in r.aiter_bytes():
            body += chunk
            if len(body) > MAX_BYTES:
                raise ApiError("maktabkhooneh.org sent a reply that is too large.", 413)
        headers = [(k, v) for k, v in r.headers.items() if k.lower() not in ("content-encoding", "content-length")]
        return httpx.Response(r.status_code, headers=headers, content=bytes(body), request=r.request)


async def _once(client: httpx.AsyncClient, limit: asyncio.Semaphore, url: str, **kwargs: Any) -> httpx.Response:
    """One jittered request; timeouts and network errors become ApiError (status None)."""
    try:
        async with limit:
            await asyncio.sleep(random.uniform(*JITTER))
            return await _get(client, url, **kwargs)
    except httpx.TimeoutException as e:
        raise ApiError("maktabkhooneh.org did not answer in time. Try again in a moment.") from e
    except httpx.TooManyRedirects as e:
        _next_proxy(client)
        raise ApiError("maktabkhooneh.org kept redirecting. Try again in a moment.") from e
    except httpx.TransportError as e:
        if isinstance(e, httpx.ConnectError | httpx.ProxyError):
            _next_proxy(client)
        raise ApiError(
            f"Could not reach maktabkhooneh.org ({type(e).__name__}). Check the internet connection, "
            "or set MAKTABKHOONEH_MCP_PROXY."
        ) from e


def _retry_after(r: httpx.Response) -> float | None:
    """Seconds from a numeric Retry-After on a 429/503, else None (HTTP-date form is ignored)."""
    v = r.headers.get("retry-after", "")
    return float(v) if r.status_code in (429, 503) and v.replace(".", "", 1).isdigit() else None


async def _fetch(url: str, **kwargs: Any) -> httpx.Response:
    """GET with up to MAX_RETRIES retries (jittered backoff, or Retry-After) on timeout, network error, empty 200,
    429 and 5xx. Other 4xx (403 too) are never retried."""
    for attempt in range(MAX_RETRIES + 1):
        wait = RETRY_DELAY * 2**attempt * random.uniform(1, 1.5)
        client, limit = _get_client()
        try:
            r = await _once(client, limit, url, **kwargs)
        except ApiError as e:
            if attempt == MAX_RETRIES or e.status is not None:
                raise
        else:
            if _is_challenge(r):
                _next_proxy(client)
                raise ApiError(
                    "maktabkhooneh.org served a bot-check page. Try again later, or set MAKTABKHOONEH_MCP_PROXY.",
                    r.status_code,
                )
            if not ((r.status_code == 200 and not r.content) or r.status_code == 429 or r.status_code >= 500):
                break
            if attempt == MAX_RETRIES:
                break
            wait = _retry_after(r) or wait
        await asyncio.sleep(min(wait, MAX_RETRY_WAIT))
    if r.status_code >= 400:
        detail = ""
        try:
            body = r.json()
            if isinstance(body, dict):  # DRF: {"detail": "..."} or {"<param>": ["..."]}
                detail = str(body.get("detail") or body)[:300]
        except ValueError:
            pass
        raise ApiError(_status_message(r.status_code) + (f" Site says: {detail}" if detail else ""), r.status_code)
    return r


def _status_message(code: int) -> str:
    if code == 400:
        return "maktabkhooneh.org rejected the parameters (HTTP 400)."
    if code in (401, 403):
        return f"maktabkhooneh.org refused the request (HTTP {code}); this server is read-only and has no login."
    if code == 404:
        return "Not found on maktabkhooneh.org (HTTP 404). Check the id or slug."
    if code == 429:
        return "maktabkhooneh.org is rate limiting requests (HTTP 429). Wait a minute before retrying."
    if code >= 500:
        return f"maktabkhooneh.org had a server error (HTTP {code}). Try again later."
    return f"maktabkhooneh.org rejected the request (HTTP {code})."
