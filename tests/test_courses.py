import httpx
import pytest
from conftest import API, fixture

pytestmark = pytest.mark.anyio

SEARCH = f"{API}/courses/search/"
BROWSE = f"{API}/courses/categories/python/search/"
ALL = f"{API}/courses/categories/-/search/"


def first_page_only(name):
    """The fixture for page 1, an empty page after it (the scan tools ask for pages 2 and 3 too)."""
    data = fixture(name)

    def handler(request):
        if request.url.params.get("page", "1") == "1":
            return httpx.Response(200, json=data)
        return httpx.Response(200, json={**data, "courses": {**data["courses"], "results": []}})

    return handler


async def test_search_maps_cards(client, api):
    api[SEARCH] = fixture("search.json")
    out = (await client.call_tool("mk_search", {"query": "پایتون", "limit": 4})).structured_content
    assert api.params() == {"q": "پایتون", "sorting": "relevance", "page": "1", "limit": "4"}
    assert out["total"] == 300 and out["next_page"] == 2 and len(out["courses"]) == 4
    c = out["courses"][0]
    assert c["id"] == 10465 and c["final_price"] == 1299500 and c["price"] == 2599000 and c["discount_pct"] == 50
    assert c["free"] is False and c["kind"] == "PLUS" and c["organization"]["id"] == 2
    assert c["teachers"][0]["slug"] == "jadi-mirmirani" and c["url"].endswith("/course/x-mk10465/")
    assert "image_url" not in c


async def test_browse_sends_site_filter_keys(client, api):
    api[BROWSE] = fixture("browse.json")
    out = (
        await client.call_tool(
            "mk_browse",
            {
                "category_slug": "python",
                "type": "paid",
                "level": "advanced",
                "duration": "5-10h",
                "min_rating": "4.0",
                "organization_ids": [2, 3],
                "feature": "certificate",
                "sorting": "rate",
            },
        )
    ).structured_content
    q = api.calls[-1].url.params
    assert q["types"] == "PLUS" and q["levels"] == "ADVANCED" and q["duration"] == "5-10h" and q["rating"] == "mid"
    assert q.get_list("organizations") == ["2", "3"] and q["features"] == "5" and q["sorting"] == "rate"
    assert out["total"] == 183


async def test_browse_omits_unset_filters(client, api):
    api[ALL] = fixture("browse.json")
    await client.call_tool("mk_browse", {})
    assert set(api.params()) == {"sorting", "page", "limit"}


async def test_free_courses(client, api):
    api[ALL] = fixture("free.json")
    out = (await client.call_tool("mk_free_courses", {})).structured_content
    assert api.params()["types"] == "MAKTAB"
    assert all(c["free"] and c["final_price"] == 0 and "price" not in c for c in out["courses"])


async def test_cheapest_sorts_and_filters_client_side(client, api):
    api[SEARCH] = first_page_only("search.json")  # 300 total: the scan asks for 3 pages
    out = (
        await client.call_tool("mk_cheapest", {"query": "پایتون", "max_price": 1500000, "limit": 2})
    ).structured_content
    prices = [c["final_price"] for c in out["courses"]]
    assert prices == sorted(prices) and prices[0] == 899400 and max(prices) <= 1500000
    assert out["total"] == 300 and out["scanned"] == 4
    assert len(api.calls) == 3 and api.params(0)["limit"] == "100"


async def test_cheapest_skips_free_unless_asked(client, api):
    api[ALL] = first_page_only("free.json")
    out = (await client.call_tool("mk_cheapest", {})).structured_content
    assert out["matches"] == 0 and api.params(0)["types"] == "PLUS"
    out = (await client.call_tool("mk_cheapest", {"include_free": True})).structured_content
    assert out["courses"][0]["final_price"] == 0


async def test_deals_picks_biggest_discount_first(client, api):
    api[BROWSE] = first_page_only("browse.json")
    out = (await client.call_tool("mk_deals", {"category_slug": "python", "min_discount": 40})).structured_content
    assert [c["discount_pct"] for c in out["courses"]] == [60, 50] and out["matches"] == 2


async def test_course_detail(client, api):
    api[f"{API}/courses/x-mk1318/"] = fixture("detail_301.json")
    api[f"{API}/courses/یادگیری-ماشین-پایتون-mk1318/"] = fixture("detail.json")
    out = (await client.call_tool("mk_course", {"course_id": 1318})).structured_content
    assert out["id"] == 1318 and out["level"] == "مقدماتی" and out["certificate"] is True
    assert out["full"] == {"price": 4999000, "final_price": 1999600}
    assert out["content_only"]["final_price"] == 1599600
    assert out["upgrade"] == {"final_price": 999000}  # no list price when it equals the final price
    assert out["discount_pct"] == 60 and out["discount_ends"].startswith("2026-10-22")
    assert out["category"] == ["برنامه\u200cنویسی", "زبان\u200cهای برنامه\u200cنویسی", "پایتون"]
    assert out["teachers"][0]["slug"] == "jadi-mirmirani" and out["publisher"]["id"] == 2
    assert out["faq"][0]["q"] and "<" not in out["description"]
    assert len(api.calls) == 2


async def test_course_unknown_id(client, api):
    result = await client.call_tool("mk_course", {"course_id": 999999})
    assert result.is_error and "HTTP 404" in result.content[0].text


async def test_curriculum_strips_duration_quote(client, api):
    api[f"{API}/courses/x-mk1318/chapters/"] = fixture("chapters.json")
    out = (await client.call_tool("mk_curriculum", {"course_id": 1318})).structured_content
    ch = out["chapters"][0]
    assert ch["lessons"] == len(ch["units"]) and ch["units"][0]["duration"] == "06:30"
    assert ch["units"][0]["type"] == "lecture" and "truncated" not in out


async def test_curriculum_truncates(client, api):
    unit = {"title": "t", "type": "lecture", "effort_time_in_minutes": '"01:00'}
    api[f"{API}/courses/x-mk5/chapters/"] = {
        "chapters": [{"title": f"c{i}", "total_effort_time": "01:00", "units": [unit] * 120} for i in range(2)]
    }
    out = (await client.call_tool("mk_curriculum", {"course_id": 5})).structured_content
    assert sum(len(c["units"]) for c in out["chapters"]) == 200 and out["truncated"] is True
    assert out["chapters"][1]["lessons"] == 120


async def test_reviews_without_reviewer_names(client, api):
    api[f"{API}/courses/x-mk1318/reviews/"] = fixture("reviews.json")
    api[f"{API}/courses/x-mk1318/reviews-summary/"] = fixture("reviews_summary.json")
    r = await client.call_tool("mk_reviews", {"course_id": 1318, "limit": 4})
    out = r.structured_content
    assert out["ratings_count"] == 3030 and out["stars"]["5"] == 2309 and out["next_offset"] == 4
    assert len(out["reviews"]) == 4 and out["reviews"][0]["stars"] and out["reviews"][0]["date"]
    assert "کاربر نمونه" not in r.content[0].text and "full_name" not in r.content[0].text
