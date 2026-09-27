"""Regression tests for a real bug found via live testing against
https://www.theverge.com and https://developer.mozilla.org: a sitemap-
index entry that doesn't end in a recognized ".xml" suffix -- Google
News sitemaps conventionally live at a path like "/sitemaps/google_news"
with no extension at all, and many sites' regular sitemap children are
served gzip-compressed at ".xml.gz" -- was not recognized as "this is
itself a sitemap resource, not a content page", so it (and, in the
theverge.com case, its full sibling batch) fell through to being added
directly to the page-audit candidate pool. From there it was classified
`page_type="other"` (no real content) and still received EE-001 ("Poor
deep-page orientation context") purely because it has no H1/breadcrumb/
title -- a false positive, since it was never a content page at all.

`_is_sitemap_resource` (skills_impl/site_discovery/scripts/discovery.py)
is the shared fix: broadened to recognize ".xml", ".xml.gz", and a
"sitemap"/"sitemaps" path SEGMENT (never a substring of a longer
segment), reused both by the sitemap-index recursion heuristic and as a
defense-in-depth filter in `discover_pages`'s own `add()` -- so a
sitemap resource can never enter the candidate pool regardless of how it
was discovered (sitemap-index entry, homepage link, depth-2 link).

Fully offline; all network calls are monkeypatched.
"""
import skills_impl.site_discovery.scripts.discovery as discovery_mod
import skills_impl.site_discovery.scripts.robots as robots_mod
import skills_impl.audit_orchestrator.scripts.orchestrator as orch
from skills_impl.audit_orchestrator.scripts.config import AuditConfig
from skills_impl.site_discovery.scripts.discovery import _is_sitemap_resource


def _make_fake_safe_fetch(pages):
    def fake_safe_fetch(url, timeout=10, max_bytes=3_000_000, max_redirects=5):
        if url in pages:
            return {"ok": True, "url": url, "final_url": url, "status": 200,
                     "html": pages[url], "headers": {}, "truncated": False, "error": None}
        return {"ok": False, "url": url, "final_url": url, "status": 404,
                 "html": "", "headers": {}, "truncated": False, "error": "not found"}
    return fake_safe_fetch


ROBOTS_TXT = "User-agent: *\nSitemap: https://verge-like.example/sitemap.xml\n"

# The Verge's real-world shape: a top-level sitemap index whose children
# are a mix of ordinary ".xml" sitemaps and a Google-News-style,
# extension-less "/sitemaps/google_news" entry.
TOP_INDEX = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://verge-like.example/sitemaps/articles-1.xml</loc></sitemap>
<sitemap><loc>https://verge-like.example/sitemaps/google_news</loc></sitemap>
</sitemapindex>
"""

ARTICLES_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://verge-like.example/2026/1/1/article-one</loc></url>
<url><loc>https://verge-like.example/2026/1/2/article-two</loc></url>
</urlset>
"""

# The Google News sitemap itself: a real, valid, parseable XML sitemap,
# just served without a ".xml" extension -- must be fetched and parsed
# for its own article URLs, never itself added as a page candidate.
GOOGLE_NEWS_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://verge-like.example/2026/1/3/breaking-news-story</loc></url>
</urlset>
"""

HOMEPAGE = """<html><body>
<h1>Verge-like</h1>
<a href="/2026/1/1/article-one">Article One</a>
<a href="/blog/how-to-build-a-sitemap">How to Build a Sitemap</a>
<a href="/sitemaps/google_news">Sitemap</a>
</body></html>
"""

# A legitimate content page whose own slug happens to contain the word
# "sitemap" as part of a longer segment -- must NOT be filtered.
SITEMAP_ARTICLE_PAGE = """<html><body>
<h1>How to Build a Sitemap</h1>
<p>A guide to building XML sitemaps for your website, step by step.</p>
</body></html>
"""


def _base_pages():
    return {
        "https://verge-like.example/robots.txt": ROBOTS_TXT,
        "https://verge-like.example/sitemap.xml": TOP_INDEX,
        "https://verge-like.example/sitemaps/articles-1.xml": ARTICLES_SITEMAP,
        "https://verge-like.example/sitemaps/google_news": GOOGLE_NEWS_SITEMAP,
        "https://verge-like.example/": HOMEPAGE,
        "https://verge-like.example/blog/how-to-build-a-sitemap": SITEMAP_ARTICLE_PAGE,
    }


def _patch(monkeypatch, pages):
    fake = _make_fake_safe_fetch(pages)
    monkeypatch.setattr(robots_mod, "safe_fetch", fake)
    monkeypatch.setattr(discovery_mod, "safe_fetch", fake)


# --- Unit tests: _is_sitemap_resource ---------------------------------

def test_plain_xml_sitemap_is_a_sitemap_resource():
    assert _is_sitemap_resource("https://example.com/sitemap.xml") is True


def test_xml_gz_sitemap_is_a_sitemap_resource():
    assert _is_sitemap_resource("https://example.com/sitemaps/en-us/sitemap.xml.gz") is True


def test_extensionless_sitemaps_directory_entry_is_a_sitemap_resource():
    assert _is_sitemap_resource("https://www.theverge.com/sitemaps/google_news") is True


def test_query_string_does_not_defeat_xml_detection():
    assert _is_sitemap_resource("https://example.com/sitemap_products_1.xml?from=1&to=500") is True


def test_query_string_does_not_falsely_trigger_detection():
    assert _is_sitemap_resource("https://example.com/products/x200?ref=sitemap") is False


def test_ordinary_content_url_is_not_a_sitemap_resource():
    assert _is_sitemap_resource("https://example.com/blog/how-to-build-a-sitemap") is False
    assert _is_sitemap_resource("https://example.com/about") is False


def test_bare_sitemap_segment_is_a_sitemap_resource():
    assert _is_sitemap_resource("https://example.com/sitemap") is True


# --- A: sitemap.xml used for discovery, never audited -------------------

def test_top_level_sitemap_xml_never_in_candidate_urls(monkeypatch):
    _patch(monkeypatch, _base_pages())
    inventory = discovery_mod.discover_pages("https://verge-like.example/", max_pages=8)
    assert not any(u.endswith("sitemap.xml") for u in inventory["candidate_urls"])
    assert inventory["sitemap_found"] is True


# --- B: sitemap.xml.gz used for discovery, never audited -----------------

def test_xml_gz_child_sitemap_never_in_candidate_urls(monkeypatch):
    pages = dict(_base_pages())
    pages["https://verge-like.example/sitemap.xml"] = """<?xml version="1.0" encoding="UTF-8"?>
    <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <sitemap><loc>https://verge-like.example/sitemaps/en-us/sitemap.xml.gz</loc></sitemap>
    </sitemapindex>"""
    pages["https://verge-like.example/sitemaps/en-us/sitemap.xml.gz"] = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url><loc>https://verge-like.example/docs/guide-one</loc></url>
    </urlset>"""
    _patch(monkeypatch, pages)

    inventory = discovery_mod.discover_pages("https://verge-like.example/", max_pages=8)
    assert not any(u.endswith(".xml.gz") for u in inventory["candidate_urls"])
    assert any(u.endswith("/docs/guide-one") for u in inventory["candidate_urls"])


# --- C: /sitemaps/google_news is not audited as a normal page -----------

def test_google_news_style_sitemap_not_audited_but_its_articles_are(monkeypatch):
    _patch(monkeypatch, _base_pages())
    inventory = discovery_mod.discover_pages("https://verge-like.example/", max_pages=8)

    assert not any(u.endswith("/sitemaps/google_news") for u in inventory["candidate_urls"])
    # The real article discovered FROM WITHIN the google_news sitemap
    # must still surface as a candidate -- discovery still works.
    assert any(u.endswith("/breaking-news-story") for u in inventory["candidate_urls"])


# --- D: sitemap URLs with query strings still work (regression guard) ---

def test_sitemap_index_child_with_query_string_still_recognized(monkeypatch):
    pages = {
        "https://shopdemo-sm.example/robots.txt": "User-agent: *\nSitemap: https://shopdemo-sm.example/sitemap.xml\n",
        "https://shopdemo-sm.example/sitemap.xml": """<?xml version="1.0" encoding="UTF-8"?>
        <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        <sitemap><loc>https://shopdemo-sm.example/sitemap_products_1.xml?from=1&amp;to=500</loc></sitemap>
        </sitemapindex>""",
        "https://shopdemo-sm.example/sitemap_products_1.xml?from=1&to=500": """<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        <url><loc>https://shopdemo-sm.example/products/widget</loc></url>
        </urlset>""",
        "https://shopdemo-sm.example/": "<html><body><h1>Shop</h1></body></html>",
    }
    _patch(monkeypatch, pages)
    inventory = discovery_mod.discover_pages("https://shopdemo-sm.example/", max_pages=8)
    assert any(u.endswith("/products/widget") for u in inventory["candidate_urls"])
    assert not any(".xml" in u for u in inventory["candidate_urls"])


# --- E: sitemap-index containing child sitemap URLs still works ----------

def test_sitemap_index_with_mixed_children_still_recurses_correctly(monkeypatch):
    _patch(monkeypatch, _base_pages())
    inventory = discovery_mod.discover_pages("https://verge-like.example/", max_pages=8)
    assert any(u.endswith("/article-one") for u in inventory["candidate_urls"])
    assert any(u.endswith("/article-two") for u in inventory["candidate_urls"])
    assert any(u.endswith("/breaking-news-story") for u in inventory["candidate_urls"])


# --- F: legitimate content URLs containing "sitemap" are NOT filtered ---

def test_content_page_with_sitemap_in_slug_is_still_discovered(monkeypatch):
    _patch(monkeypatch, _base_pages())
    inventory = discovery_mod.discover_pages("https://verge-like.example/", max_pages=8)
    assert any(u.endswith("/blog/how-to-build-a-sitemap") for u in inventory["candidate_urls"])


# --- G: EE-001 cannot be emitted for a sitemap resource ------------------

def test_ee001_never_points_at_a_sitemap_resource_end_to_end(monkeypatch):
    """Full orchestrator pipeline: even though the homepage links
    directly to '/sitemaps/google_news' (a real, common footer-link
    pattern), it must never enter the audit queue, and therefore no
    finding of any kind -- especially not EE-001 -- can ever reference
    it."""
    monkeypatch.setattr(orch, "is_safe_url", lambda url: (True, None, "safe"))
    monkeypatch.setattr(orch, "PLAYWRIGHT_AVAILABLE", False)
    fake = _make_fake_safe_fetch(_base_pages())
    monkeypatch.setattr(orch, "safe_fetch", fake)
    monkeypatch.setattr(discovery_mod, "safe_fetch", fake)
    monkeypatch.setattr(robots_mod, "safe_fetch", fake)

    report = orch.run_audit("https://verge-like.example/", config=AuditConfig(max_pages=8, total_audit_timeout=30))

    audited_urls = set(report["metadata"]["page_classifications"].keys())
    assert not any("sitemap" in u.lower() for u in audited_urls if "google_news" in u or u.endswith(".xml"))
    assert "https://verge-like.example/sitemaps/google_news" not in audited_urls
    for finding in report["findings"]:
        url = finding.get("evidence", {}).get("url", "")
        assert "/sitemaps/google_news" not in url
        if finding["id"] == "EE-001":
            assert "sitemap" not in url.lower()


# --- H: existing discovery behavior remains intact (spot checks) --------

def test_homepage_links_and_depth2_still_discovered_normally(monkeypatch):
    _patch(monkeypatch, _base_pages())
    inventory = discovery_mod.discover_pages("https://verge-like.example/", max_pages=8)
    assert inventory["homepage_fetch_ok"] is True
    assert inventory["homepage_link_count"] >= 1
