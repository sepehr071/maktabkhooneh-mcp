import json
from pathlib import Path

import httpx
import pytest
from mcp import Client

from maktabkhooneh_mcp import http
from maktabkhooneh_mcp.server import mcp

FIXTURES = Path(__file__).parent / "fixtures"
API = "/api/v1"


def fixture(name: str):
    """A recorded (trimmed) response: parsed JSON, or text for .xml."""
    text = (FIXTURES / name).read_text(encoding="utf-8")
    return text if name.endswith(".xml") else json.loads(text)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def fresh_http_client(monkeypatch):
    """The shared httpx client is bound to one event loop; each test gets a new loop."""
    monkeypatch.setattr(http, "RETRY_DELAY", 0)
    monkeypatch.setattr(http, "JITTER", (0, 0))
    http.set_transport(None)
    yield
    http.set_transport(None)


@pytest.fixture
def api():
    """Route table for a fake Maktabkhooneh API.

    Keys are decoded URL paths (api["/api/v1/courses/search/"]). Values: a dict/list (JSON), a str (XML/HTML) or a
    callable(request) -> httpx.Response. Unknown paths return 404 with a DRF body, like the site. Every request is
    appended to api.calls.
    """

    class Routes(dict):
        calls: list[httpx.Request]

        def params(self, i: int = -1) -> dict[str, str]:
            return dict(self.calls[i].url.params)

    routes = Routes()
    routes.calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        routes.calls.append(request)
        target = routes.get(request.url.path)
        if target is None:
            return httpx.Response(404, json={"detail": "Not found."})
        if isinstance(target, str):
            return httpx.Response(200, text=target)
        if callable(target):
            return target(request)
        return httpx.Response(200, json=target)

    http.set_transport(httpx.MockTransport(handler))
    return routes


@pytest.fixture
async def client():
    async with Client(mcp, raise_exceptions=True) as c:
        call_tool = c.call_tool

        async def parsed(*args, **kwargs):
            result = await call_tool(*args, **kwargs)
            if not result.is_error:  # tools return one compact JSON text block
                result.structured_content = json.loads(result.content[0].text)
            return result

        c.call_tool = parsed
        yield c
