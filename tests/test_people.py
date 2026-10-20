import pytest
from conftest import API, fixture

pytestmark = pytest.mark.anyio

CATS = f"{API}/courses/categories/"
SITEMAP = "/sitemap/organization.xml"


async def test_categories_top_level(client, api):
    api[CATS] = fixture("categories.json")
    out = (await client.call_tool("mk_categories", {})).structured_content
    top = out["categories"][0]
    assert top["slug"] == "programming" and top["children"][0]["slug"] == "programming-languages"
    assert "children" not in top["children"][0] and top["children"][0]["children_count"] >= 1


async def test_categories_subtree_and_path(client, api):
    api[CATS] = fixture("categories.json")
    out = (await client.call_tool("mk_categories", {"slug": "programming", "depth": 2})).structured_content
    langs = out["children"][0]
    assert out["path"] == [] and langs["slug"] == "programming-languages"
    assert "python" in [c["slug"] for c in langs["children"]]
    out = (await client.call_tool("mk_categories", {"slug": "python"})).structured_content
    assert out["path"] == ["برنامه\u200cنویسی", "زبان\u200cهای برنامه\u200cنویسی"]


async def test_categories_query_and_unknown_slug(client, api):
    api[CATS] = fixture("categories.json")
    out = (await client.call_tool("mk_categories", {"query": "پایتون"})).structured_content
    assert out["categories"][0]["slug"] == "python" and out["categories"][0]["path"][0] == "برنامه\u200cنویسی"
    r = await client.call_tool("mk_categories", {"slug": "nope"})
    assert r.is_error and "No category" in r.content[0].text


async def test_categories_are_cached(client, api):
    api[CATS] = fixture("categories.json")
    await client.call_tool("mk_categories", {})
    await client.call_tool("mk_categories", {"slug": "python"})
    assert len(api.calls) == 1


async def test_teacher(client, api):
    api[f"{API}/accounts/teacher/jadi-mirmirani/"] = fixture("teacher.json")
    api[f"{API}/accounts/teacher/jadi-mirmirani/courses/"] = fixture("teacher_courses.json")
    out = (await client.call_tool("mk_teacher", {"teacher": "jadi-mirmirani", "limit": 2})).structured_content
    assert out["id"] == 252 and out["name"] == "جادی میرمیرانی" and out["students"] > 0
    assert "<p>" not in out["bio"] and len(out["courses"]) == 2 and out["courses"][0]["final_price"] > 0


async def test_teacher_rejects_path_tricks(client, api):
    for bad in ("..", "a/b", "a b"):
        r = await client.call_tool("mk_teacher", {"teacher": bad})
        assert r.is_error, bad
    assert not api.calls


async def test_organizations_from_sitemap(client, api):
    api[SITEMAP] = fixture("sitemap_organization.xml")
    out = (await client.call_tool("mk_organizations", {})).structured_content
    assert out["total"] == 3 and {"id": 133, "name": "udemy"} in out["organizations"]
    out = (await client.call_tool("mk_organizations", {"query": "دانشگاه تهران"})).structured_content
    assert out["organizations"] == [{"id": 3, "name": "دانشگاه تهران"}]


async def test_organization_profile(client, api):
    api[SITEMAP] = fixture("sitemap_organization.xml")
    api[f"{API}/organization/دانشگاه-تهران-org3/"] = fixture("organization.json")
    api[f"{API}/courses/categories/-/search/"] = fixture("free.json")
    out = (await client.call_tool("mk_organization", {"org_id": 3, "limit": 2})).structured_content
    assert out["id"] == 3 and out["name"] == "دانشگاه تهران" and out["course_count"] > 0
    assert api.calls[-1].url.params.get_list("organizations") == ["3"] and len(out["courses"]) == 3


async def test_organization_unknown_id(client, api):
    api[SITEMAP] = fixture("sitemap_organization.xml")
    r = await client.call_tool("mk_organization", {"org_id": 99999})
    assert r.is_error and "No publisher" in r.content[0].text
