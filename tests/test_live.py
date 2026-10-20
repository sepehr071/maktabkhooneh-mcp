"""One live test per tool against the real site (run with -m live). Assertions are loose: data changes daily."""

import json

import pytest

pytestmark = [pytest.mark.live, pytest.mark.anyio]


async def call(client, name, **args):
    result = await client.call_tool(name, args)
    assert not result.is_error, result.content[0].text
    return result.structured_content


async def test_search(client):
    out = await call(client, "mk_search", query="پایتون", limit=5)
    assert out["total"] > 50 and len(out["courses"]) == 5
    c = out["courses"][0]
    assert c["id"] and c["title"] and c["final_price"] >= 0 and c["url"].startswith("https://maktabkhooneh.org/")


async def test_browse_filters_narrow_results(client):
    everything = await call(client, "mk_browse", limit=1)
    out = await call(client, "mk_browse", category_slug="python", level="advanced", min_rating="4.0", limit=3)
    assert 0 < out["total"] < everything["total"] and out["courses"]


async def test_free_courses(client):
    out = await call(client, "mk_free_courses", limit=5)
    assert out["total"] > 100 and all(c["free"] for c in out["courses"])


async def test_cheapest(client):
    out = await call(client, "mk_cheapest", query="پایتون", limit=5)
    prices = [c["final_price"] for c in out["courses"]]
    assert out["scanned"] > 100 and prices == sorted(prices) and all(p > 0 for p in prices)


async def test_deals(client):
    out = await call(client, "mk_deals", min_discount=30, limit=5)
    assert out["scanned"] > 100
    assert all(c["discount_pct"] >= 30 and c["price"] > c["final_price"] for c in out["courses"])


async def test_course_curriculum_reviews(client):
    c = await call(client, "mk_course", course_id=1318)
    assert c["title"] and c["full"]["final_price"] > 0 and c["teachers"] and c["category"]
    cur = await call(client, "mk_curriculum", course_id=1318)
    assert len(cur["chapters"]) >= 3 and cur["chapters"][0]["units"]
    rev = await call(client, "mk_reviews", course_id=1318, limit=3)
    assert rev["ratings_count"] > 100 and len(rev["reviews"]) == 3 and sum(rev["stars"].values()) > 100


async def test_course_unknown(client):
    result = await client.call_tool("mk_course", {"course_id": 9999999})
    assert result.is_error and "404" in result.content[0].text


async def test_categories(client):
    top = await call(client, "mk_categories")
    assert len(top["categories"]) >= 8
    found = await call(client, "mk_categories", query="پایتون")
    assert any(c["slug"] == "python" for c in found["categories"])
    assert (await call(client, "mk_categories", slug="programming"))["children"]


async def test_teacher(client):
    out = await call(client, "mk_teacher", teacher="jadi-mirmirani", limit=3)
    assert out["name"] and out["students"] > 1000 and out["courses"]
    assert "جادی" in json.dumps(out, ensure_ascii=False)


async def test_organizations_and_organization(client):
    orgs = await call(client, "mk_organizations", query="دانشگاه تهران")
    assert orgs["organizations"] and orgs["organizations"][0]["id"] == 3
    out = await call(client, "mk_organization", org_id=3, limit=3)
    assert out["course_count"] > 10 and len(out["courses"]) == 3
    assert all(c["organization"]["id"] == 3 for c in out["courses"])
