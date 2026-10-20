<!-- mcp-name: io.github.sepehr071/maktabkhooneh-mcp -->

# maktabkhooneh-mcp: Maktabkhooneh MCP server for AI agents

**Unofficial, read-only MCP server that lets your AI agent search Maktabkhooneh (مکتب&zwnj;خونه), the Iranian online course platform: compare prices and discounts, find free courses, read curricula and reviews, look up teachers and universities.**

Covers about 5,700 Persian video courses on [maktabkhooneh.org](https://maktabkhooneh.org), prices in Toman. No API key,
no account. Works with Claude, Cursor and Copilot.

[Quick start](#quick-start) · [Tools](#tools) · [FAQ](#faq) · [فارسی](#فارسی)

---

## For AI agents

- **What:** Unofficial MCP server for Maktabkhooneh (مکتب&zwnj;خونه, maktabkhooneh.org), an Iranian online course platform. Queries in Persian work best; prices in Toman.
- **Install:** `claude mcp add maktabkhooneh -- uvx maktabkhooneh-mcp` (stdio, needs [uv](https://docs.astral.sh/uv/getting-started/installation/) and Python 3.10+).
- **Auth:** none. Optional `MAKTABKHOONEH_MCP_PROXY` sets an HTTP proxy (or a comma-separated list) for every request.
- **Access:** read-only. It cannot log in, enrol, buy or review.
- **Tools:** 12, all prefixed `mkh_`. Start with `mkh_search`, `mkh_browse`, `mkh_cheapest`, `mkh_course`, `mkh_free_courses`.
- **Typical sequence:** `mkh_search` (or `mkh_categories` -> `mkh_browse`) -> `mkh_course` -> `mkh_curriculum` or `mkh_reviews`.
- **Use when:** the user wants to find an Iranian online course, compare price, level, hours and rating, find free or discounted courses, or look up a teacher or a university's courses.
- **Do not use when:** the user wants to enrol, pay, watch lessons or needs their own account data.
- **Output:** compact JSON. Prices in Toman (`final_price` is what you pay, 0 = free), rating 0-5, numeric course ids to pass between tools, paging with `next_page`.
- **Machine-readable:** [server.json](https://github.com/sepehr071/maktabkhooneh-mcp/blob/main/server.json), and the catalog of all Iranian MCP servers [awesome-iran-mcp](https://github.com/sepehr071/awesome-iran-mcp).

## Quick start

You need [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
claude mcp add maktabkhooneh -- uvx maktabkhooneh-mcp
```

Any other MCP client (Claude Desktop, Cursor, VS Code): run `uvx maktabkhooneh-mcp` as a stdio server (or
`pip install maktabkhooneh-mcp` and run `maktabkhooneh-mcp`), e.g.

```json
{
  "mcpServers": {
    "maktabkhooneh": { "command": "uvx", "args": ["maktabkhooneh-mcp"] }
  }
}
```

Then ask, for example:

- "The cheapest Python courses on Maktabkhooneh with a certificate, and which has the best rating?"
- "Free advanced programming courses from University of Tehran."
- "What is in course 1318 and what do learners say about it?"
- <span dir="rtl">بهترین دوره&zwnj;های رایگان زبان انگلیسی کدامند؟</span>

## How it works

`maktabkhooneh-mcp` runs locally and calls the same public JSON API the maktabkhooneh.org website uses
(`/api/v1/courses/...`, `/api/v1/accounts/teacher/...`, `/api/v1/organization/...`); the publisher list is read from
the site's sitemap. No hosted server in between. API map and quirks: `../maktabkhooneh/`.

## Tools

All 12 tools are annotated `readOnlyHint: true` and return compact structured JSON.

**Find courses**

| Tool | What it does |
|---|---|
| `mkh_search` | Text search (Persian or English) with price, discount, hours, rating, students, teachers; sort relevance / popular / new; first 300 matches |
| `mkh_browse` | A category or all ~5,700 courses with the site's filters: paid / free, level, hours, minimum rating, publisher, feature (certificate, exam and project, Persian subtitle or dubbing); sort popular / new / rate |
| `mkh_free_courses` | Free courses (~740), optionally per category, level and rating |
| `mkh_cheapest` | Cheapest paid courses for a topic or category, with a price ceiling (scans the first 300 results) |
| `mkh_deals` | Biggest current discounts, with a minimum percent and price ceiling |
| `mkh_categories` | The category tree (~680 nodes): top-level groups, one subtree, or title search; gives the slugs for the tools above |

**One course**

| Tool | What it does |
|---|---|
| `mkh_course` | Full / content-only / upgrade prices, discount end, level, hours, teachers, publisher, category, prerequisites, features, description, FAQ |
| `mkh_curriculum` | Chapters and lessons with type and duration |
| `mkh_reviews` | Learner reviews (stars, text, date, instructor reply) and the star histogram; reviewer names are left out |

**People**

| Tool | What it does |
|---|---|
| `mkh_teacher` | A teacher's profile (bio, students, rating, links) and courses |
| `mkh_organizations` | Publishers (~180 universities and companies) with their ids; name search |
| `mkh_organization` | A publisher's totals and its most popular courses |

## Good to know

- **Prices are in Toman** (the site shows the same numbers with «تومان»; its JSON-LD labels them IRR, which is wrong). `final_price` is what you pay, `price` the list price (shown only when discounted), `discount_pct` a whole percent, `free` true for 0.
- **The site cannot sort or filter by price.** `mkh_cheapest` and `mkh_deals` scan the first 300 results (3 requests of 100) and sort here; `scanned` of `total` tells how complete the answer is. Use `mkh_browse` filters to narrow the pool first.
- **`mkh_search` reaches only the first 300 matches** and the site ignores filters there; filter with `mkh_browse` instead (it has no text query).
- **`full`, `content_only`, `upgrade` in `mkh_course`:** the whole course (lessons, projects, certificate), lessons only, and the price to upgrade from lessons-only to full.
- **`hours`** is a number, or `"H:MM"` for courses under two hours.
- **`kind`:** `PLUS` paid, `MAKTAB` free, `HAMAYESH` events.
- Discounts are time limited (a site-wide sale ran 14-22 Oct 2026); `mkh_course` gives `discount_ends`.
- Persian queries match best.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `MAKTABKHOONEH_MCP_PROXY` | unset | HTTP proxy for every request, e.g. `http://user:pass@host:port` (system proxy variables are ignored). A comma-separated list is used one at a time: the next proxy takes over when one is blocked or fails to connect. |

## FAQ

**Is there a Maktabkhooneh API or MCP server for AI agents?**
Yes: this unofficial MCP server wraps the public JSON API the maktabkhooneh.org website itself uses, so Claude, Cursor
or Copilot can search courses and read prices, curricula and reviews.

**Is it official, safe and free?**
It is unofficial, open source (MIT) and free. It is read-only, needs no account or API key, and runs on your machine
with no hosted server in between.

**Can it enrol me or play a lesson?**
No. It only reads public catalog data. Enrolment, payment and lessons happen on maktabkhooneh.org.

<a id="فارسی"></a>

## فارسی: سرور MCP مکتب&zwnj;خونه

<div dir="rtl">

**maktabkhooneh-mcp** یک سرور MCP غیررسمی برای مکتب&zwnj;خونه است که به دستیار هوش مصنوعی شما (Claude، Cursor، Copilot و ...)
اجازه می&zwnj;دهد در میان حدود ۵٬۷۰۰ دوره آموزشی فارسی جستجو کند، قیمت و تخفیف&zwnj;ها را مقایسه کند، دوره&zwnj;های رایگان
را پیدا کند و سرفصل و نظر دانشجویان را بخواند.

- فقط خواندنی است و حساب کاربری یا کلید API نمی&zwnj;خواهد.
- همه قیمت&zwnj;ها به تومان است.

بپرسید: «ارزان&zwnj;ترین دوره&zwnj;های پایتون با گواهی&zwnj;نامه کدامند؟»

</div>

## Related servers

- [Fidibo MCP server](https://github.com/sepehr071/fidibo-mcp) for Persian ebooks and audiobooks
- [Taaghche MCP server](https://github.com/sepehr071/taaghche-mcp) for Persian ebooks and audiobooks
- All Iranian MCP servers: [awesome-iran-mcp](https://github.com/sepehr071/awesome-iran-mcp)

## Development

```bash
export HTTPS_PROXY=http://127.0.0.1:10898 HTTP_PROXY=http://127.0.0.1:10898   # uv downloads only
uv sync
uv run ruff check . && uv run ruff format --check .
uv run python -m pytest -q            # offline, on recorded fixtures
uv run python -m pytest -m live -q    # real API
```

If this saves you clicks, a star helps others find it.

## License

MIT
