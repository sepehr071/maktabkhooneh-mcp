import re
from pathlib import Path

import httpx
import pytest
from conftest import API, fixture

from maktabkhooneh_mcp import http

pytestmark = pytest.mark.anyio

SEARCH = f"{API}/courses/search/"
ARGS = {"query": "پایتون"}


async def test_all_tools_are_read_only(client):
    tools = (await client.list_tools()).tools
    assert len(tools) == 12
    for t in tools:
        assert t.name.startswith("mk_"), t.name
        assert t.annotations.read_only_hint is True and t.annotations.destructive_hint is False, t.name
        assert t.description and t.title, t.name


async def test_readme_tool_tables_match_the_server(client):
    readme = (Path(__file__).parent.parent / "README.md").read_text(encoding="utf-8")
    listed = re.findall(r"^\| `(mk_\w+)` \|", readme, re.M)
    assert sorted(listed) == sorted(t.name for t in (await client.list_tools()).tools)


async def test_output_is_compact_json_without_nulls(client, api):
    api[SEARCH] = fixture("search.json")
    r = await client.call_tool("mk_search", ARGS)
    text = r.content[0].text
    assert len(r.content) == 1 and "null" not in text.replace('"next_page":null', "") and "\n" not in text


async def test_dropped_connection_is_retried_once(client, api):
    attempts = []

    def flaky(request):
        attempts.append(request)
        if len(attempts) == 1:
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.", request=request)
        return httpx.Response(200, json=fixture("search.json"))

    api[SEARCH] = flaky
    result = await client.call_tool("mk_search", ARGS)
    assert not result.is_error and len(attempts) == 2


async def test_empty_200_body_is_retried_once(client, api):
    replies = iter([httpx.Response(200), httpx.Response(200, json=fixture("search.json"))])
    api[SEARCH] = lambda r: next(replies)
    out = (await client.call_tool("mk_search", ARGS)).structured_content
    assert out["total"] == 300 and len(api.calls) == 2


async def test_network_error_after_retry(client, api):
    def down(request):
        raise httpx.ConnectError("[SSL: UNEXPECTED_EOF_WHILE_READING]", request=request)

    api[SEARCH] = down
    result = await client.call_tool("mk_search", ARGS)
    assert result.is_error and "Could not reach maktabkhooneh.org (ConnectError)" in result.content[0].text
    assert len(api.calls) == 3  # retried twice


async def test_timeout_is_retried_twice(client, api):
    def slow(request):
        raise httpx.ReadTimeout("timed out", request=request)

    api[SEARCH] = slow
    result = await client.call_tool("mk_search", ARGS)
    assert result.is_error and "did not answer in time" in result.content[0].text and len(api.calls) == 3


@pytest.mark.parametrize(
    ("status", "text"),
    [(404, "HTTP 404"), (429, "rate limiting"), (500, "server error (HTTP 500)"), (403, "no login"), (401, "no login")],
)
async def test_http_errors_are_actionable(client, api, status, text):
    api[SEARCH] = lambda r: httpx.Response(status)
    result = await client.call_tool("mk_search", ARGS)
    assert result.is_error and text in result.content[0].text


async def test_drf_error_detail_is_shown(client, api):
    api[SEARCH] = lambda r: httpx.Response(400, json={"sorting": ['"rate" is not a valid choice.']})
    result = await client.call_tool("mk_search", ARGS)
    assert result.is_error and "not a valid choice" in result.content[0].text


async def test_retry_after_is_honoured(client, api, monkeypatch):
    waits = []

    async def fake_sleep(s):
        waits.append(s)

    monkeypatch.setattr(http.asyncio, "sleep", fake_sleep)
    replies = iter(
        [httpx.Response(429, headers={"retry-after": "3"}), httpx.Response(200, json=fixture("search.json"))]
    )
    api[SEARCH] = lambda r: next(replies)
    assert not (await client.call_tool("mk_search", ARGS)).is_error
    assert 3 in waits


async def test_bot_check_page_is_reported(client, api):
    api[SEARCH] = lambda r: httpx.Response(
        403, html="<html>Just a moment...</html>", headers={"content-type": "text/html"}
    )
    result = await client.call_tool("mk_search", ARGS)
    assert result.is_error and "bot-check" in result.content[0].text


async def test_redirect_off_site_is_refused(client, api):
    api[SEARCH] = lambda r: httpx.Response(302, headers={"location": "https://evil.example/x"})
    result = await client.call_tool("mk_search", ARGS)
    assert result.is_error and "another host" in result.content[0].text


def test_proxy_list_parsing(monkeypatch):
    monkeypatch.setenv("MAKTABKHOONEH_MCP_PROXY", " http://a:1 , ,http://b:2")
    assert http._proxies() == ["http://a:1", "http://b:2"]
    monkeypatch.delenv("MAKTABKHOONEH_MCP_PROXY")
    assert http._proxies() == []
