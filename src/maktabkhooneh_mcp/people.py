"""Categories, teachers and publishers (universities, companies) of Maktabkhooneh."""

from __future__ import annotations

import asyncio
import re
from typing import Annotated, Any

from pydantic import Field

from . import courses
from .http import ApiError, api, page
from .registry import tool

DAY = 3600  # cache of the category tree and the publisher sitemap, seconds
ORG_LOC = re.compile(r"<loc>https://maktabkhooneh\.org/organization/([^<]+?)-org(\d+)/</loc>")


def _nodes(tree: list[dict[str, Any]], path: tuple[str, ...] = ()) -> list[tuple[dict[str, Any], tuple[str, ...]]]:
    """Every category node with the titles above it."""
    out = []
    for n in tree:
        out.append((n, path))
        out += _nodes(n.get("children") or [], (*path, n["title"]))
    return out


def _view(n: dict[str, Any], depth: int) -> dict[str, Any]:
    kids = n.get("children") or []
    out: dict[str, Any] = {"slug": n["slug"], "title": n["title"]}
    if kids and depth > 0:
        out["children"] = [_view(k, depth - 1) for k in kids if k.get("public_show", True)]
    elif kids:
        out["children_count"] = len(kids)
    return out


@tool("Course categories")
async def mk_categories(
    slug: Annotated[
        str | None,
        Field(
            pattern=r"^[a-z0-9][a-z0-9-]{0,80}$",
            description="Show this category and what is below it, e.g. 'programming'.",
        ),
    ] = None,
    query: Annotated[
        str | None, Field(min_length=2, max_length=60, description="Find categories by title, e.g. 'پایتون' or 'زبان'.")
    ] = None,
    depth: Annotated[
        int,
        Field(
            ge=1, le=3, description="Levels of sub-categories to show below slug (default 1; top level when no slug)."
        ),
    ] = 1,
) -> dict[str, Any]:
    """Category tree (about 680 nodes in 11 top-level groups): slugs for mk_browse, mk_free_courses, mk_cheapest, mk_deals.

    No arguments = the 11 top-level groups with their sub-categories. slug = one subtree. query = title search with path.
    """
    tree = await api("/courses/categories/", ttl=DAY)
    nodes = _nodes(tree)
    if query:
        hits = [{"slug": n["slug"], "title": n["title"], "path": list(p)} for n, p in nodes if query in n["title"]]
        return {"matches": len(hits), "categories": hits[:30]}
    if slug:
        for n, p in nodes:
            if n["slug"] == slug:
                return {"path": list(p), **_view(n, depth)}
        raise ApiError(f"No category with slug '{slug}'. Use mk_categories(query=...) to find it.", 404)
    return {"categories": [_view(n, depth) for n in tree if n.get("public_show", True)]}


@tool("Teacher profile")
async def mk_teacher(
    teacher: Annotated[
        str,
        Field(
            pattern=r"^[^\s/?#.][^\s/?#]{0,79}$",
            description="Teacher slug from a course (teachers[].slug), e.g. 'jadi-mirmirani'.",
        ),
    ],
    limit: Annotated[int, Field(ge=1, le=30, description="Courses to list.")] = 10,
) -> dict[str, Any]:
    """A teacher's profile (bio, students, rating, teaching hours, links) and their courses with prices.

    Next: mk_course for one of the courses.
    """
    t, cs = await _both(f"/accounts/teacher/{teacher}/", f"/accounts/teacher/{teacher}/courses/")
    social = {k: v for k, v in (t.get("social_media") or {}).items() if v}
    return {
        "id": t.get("teacher_id"),
        "slug": t.get("slug"),
        "name": t.get("full_name"),
        "headline": t.get("headline"),
        "bio": courses._text(t.get("description"), 800),
        "students": t.get("student_count"),
        "course_count": t.get("course_count"),
        "teaching_hours": t.get("teaching_hours"),
        "rating": t.get("rating_avg") or None,
        "ratings_count": t.get("rating_count") or None,
        "links": social or None,
        "courses": [courses.card(c) for c in cs[:limit]],
    }


async def _both(a: str, b: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    return await asyncio.gather(api(a), api(b))


async def _orgs() -> list[dict[str, Any]]:
    """Publishers from the sitemap: [{id, slug, name}] (the site has no list endpoint)."""
    xml = await page("/sitemap/organization.xml", ttl=DAY)
    return [{"id": int(i), "slug": f"{s}-org{i}", "name": s.replace("-", " ")} for s, i in ORG_LOC.findall(xml)]


@tool("Publishers")
async def mk_organizations(
    query: Annotated[
        str | None, Field(max_length=60, description="Part of the name, Persian or English, e.g. 'دانشگاه' or 'udemy'.")
    ] = None,
    limit: Annotated[int, Field(ge=1, le=100, description="Publishers to list.")] = 30,
) -> dict[str, Any]:
    """Course publishers (universities, companies, Maktabkhooneh itself, about 180) with the id used as a filter.

    Names come from the site map, so word separators are approximate. Next: mk_organization, or pass the id as
    organization_ids to mk_browse.
    """
    orgs = await _orgs()
    q = (query or "").lower().replace(" ", "-")
    hits = [o for o in orgs if q in o["slug"].lower()]
    return {"total": len(hits), "organizations": [{"id": o["id"], "name": o["name"]} for o in hits[:limit]]}


@tool("Publisher profile")
async def mk_organization(
    org_id: Annotated[int, Field(ge=1, le=100_000, description="Publisher id from mk_organizations, e.g. 2 or 3.")],
    limit: Annotated[int, Field(ge=1, le=30, description="Courses to list (most popular first).")] = 10,
) -> dict[str, Any]:
    """A publisher's totals (courses, students, rating) and its most popular courses.

    Next: mk_course, or mk_browse with organization_ids for filters and paging.
    """
    org = next((o for o in await _orgs() if o["id"] == org_id), None)
    if not org:
        raise ApiError(f"No publisher with id {org_id}. Use mk_organizations to list them.", 404)
    info = await api(f"/organization/{org['slug']}/")
    cs = await courses._browse("-", {"sorting": "popular", "organizations": [org_id]}, 1, limit)
    desc = info.get("description")
    return {
        "id": org_id,
        "name": info.get("name") or org["name"],
        "course_count": info.get("course_count"),
        "students": info.get("student_count"),
        "rating": info.get("rating_avg") or None,
        "ratings_count": info.get("rating_count") or None,
        "description": None if desc in (None, "", "no") else courses._text(desc, 600),
        "courses": cs["courses"],
    }
