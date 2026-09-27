"""Discovery tests, fully offline: `safe_fetch` is monkeypatched at each
call site so no real network access is required or used.
"""
import skills_impl.site_discovery.scripts.discovery as discovery_mod
import skills_impl.site_discovery.scripts.robots as robots_mod
from tests import fixtures as f

HOMEPAGE_WITH_LINKS = """
<html><body>
<a href="/pricing">Pricing</a>
<a href="/about">About</a>
<a href="https://external.example/other">External</a>
<a href="mailto:hi@acme.example">Email us</a>
</body></html>
"""

ROBOTS_TXT_WITH_SITEMAP_AND_DISALLOW = """
User-agent: *
Disallow: /admin
Sitemap: https://acme.example/sitemap.xml
"""

SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://acme.example/</loc></url>
<url><loc>https://acme.example/pricing</loc></url>
<url><loc>https://acme.example/admin</loc></url>
</urlset>
"""


def _make_fake_safe_fetch(pages):
    def fake_safe_fetch(url, timeout=10, max_bytes=3_000_000, max_redirects=5):
        if url in pages:
            return {"ok": True, "url": url, "final_url": url, "status": 200,
                     "html": pages[url], "headers": {}, "truncated": False, "error": None}
        return {"ok": False, "url": url, "final_url": url, "status": 404,
                 "html": "", "headers": {}, "truncated": False, "error": "not found"}
    return fake_safe_fetch


def test_discovery_uses_sitemap_and_respects_robots_disallow(monkeypatch):
    pages = {
        "https://acme.example/robots.txt": ROBOTS_TXT_WITH_SITEMAP_AND_DISALLOW,
        "https://acme.example/sitemap.xml": SITEMAP_XML,
        "https://acme.example/": HOMEPAGE_WITH_LINKS,
    }
    fake = _make_fake_safe_fetch(pages)
    monkeypatch.setattr(robots_mod, "safe_fetch", fake)
    monkeypatch.setattr(discovery_mod, "safe_fetch", fake)

    inventory = discovery_mod.discover_pages("https://acme.example/", max_pages=5)

    assert inventory["robots_found"] is True
    assert inventory["sitemap_found"] is True
    assert "https://acme.example/admin" in inventory["skipped_disallowed"]
    assert "https://acme.example/admin" not in inventory["candidate_urls"]
    assert "https://acme.example/" in inventory["candidate_urls"]


def test_discovery_falls_back_to_homepage_links_without_sitemap(monkeypatch):
    pages = {"https://acme.example/": HOMEPAGE_WITH_LINKS}
    fake = _make_fake_safe_fetch(pages)
    monkeypatch.setattr(robots_mod, "safe_fetch", fake)  # robots.txt -> 404 -> permissive
    monkeypatch.setattr(discovery_mod, "safe_fetch", fake)

    inventory = discovery_mod.discover_pages("https://acme.example/", max_pages=5)

    assert inventory["robots_found"] is False
    assert inventory["sitemap_found"] is False
    assert any(u.endswith("/pricing") for u in inventory["candidate_urls"])
    assert not any("external.example" in u for u in inventory["candidate_urls"])


def test_discovery_respects_max_pages_bound(monkeypatch):
    big_homepage = "<html><body>" + "".join(f'<a href="/page{i}">p{i}</a>' for i in range(50)) + "</body></html>"
    pages = {"https://acme.example/": big_homepage}
    fake = _make_fake_safe_fetch(pages)
    monkeypatch.setattr(robots_mod, "safe_fetch", fake)
    monkeypatch.setattr(discovery_mod, "safe_fetch", fake)

    inventory = discovery_mod.discover_pages("https://acme.example/", max_pages=5)
    assert len(inventory["candidate_urls"]) <= 5


def test_discovery_never_produces_a_duplicate_homepage_entry(monkeypatch):
    """Regression test: normalizing candidate URLs must never desync a
    root-path homepage from its own un-normalized base_url string --
    that previously produced both 'https://acme.example/' and
    'https://acme.example' as separate candidates for the same page."""
    pages = {"https://acme.example/": HOMEPAGE_WITH_LINKS}
    fake = _make_fake_safe_fetch(pages)
    monkeypatch.setattr(robots_mod, "safe_fetch", fake)
    monkeypatch.setattr(discovery_mod, "safe_fetch", fake)

    inventory = discovery_mod.discover_pages("https://acme.example/", max_pages=5)
    homepage_variants = [u for u in inventory["candidate_urls"] if u.rstrip('/') == "https://acme.example"]
    assert len(homepage_variants) == 1


def test_depth2_discovers_pages_only_reachable_through_an_intermediate_page(monkeypatch):
    """A page only linked from a depth-1 page (not from the homepage
    directly, and not in any sitemap) should still be found via the
    bounded depth-2 hop."""
    homepage = '<html><body><a href="/products">Products</a></body></html>'
    products_page = '<html><body><a href="/products/x200">RoboArm X200</a></body></html>'
    pages = {
        "https://acme.example/": homepage,
        "https://acme.example/products": products_page,
    }
    fake = _make_fake_safe_fetch(pages)
    monkeypatch.setattr(robots_mod, "safe_fetch", fake)
    monkeypatch.setattr(discovery_mod, "safe_fetch", fake)

    inventory = discovery_mod.discover_pages("https://acme.example/", max_pages=8)

    assert inventory["depth2_pages_explored"] >= 1
    assert any(u.endswith("/products/x200") for u in inventory["candidate_urls"])


def test_probes_common_sitemap_location_when_robots_declares_none(monkeypatch):
    homepage = '<html><body><a href="/about">About</a></body></html>'
    common_sitemap = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url><loc>https://acme.example/pricing</loc></url>
    </urlset>"""
    pages = {
        "https://acme.example/": homepage,
        "https://acme.example/sitemap.xml": common_sitemap,
    }
    fake = _make_fake_safe_fetch(pages)  # robots.txt -> 404 -> no declared sitemap
    monkeypatch.setattr(robots_mod, "safe_fetch", fake)
    monkeypatch.setattr(discovery_mod, "safe_fetch", fake)

    inventory = discovery_mod.discover_pages("https://acme.example/", max_pages=8)

    assert inventory["probed_common_sitemap"] is True
    assert inventory["sitemap_found"] is True
    assert any(u.endswith("/pricing") for u in inventory["candidate_urls"])


def test_common_sitemap_probe_respects_robots_disallow(monkeypatch):
    """The common-location probe must never bypass a robots.txt rule --
    if /sitemap.xml itself is disallowed, it must not be fetched."""
    robots_txt = "User-agent: *\nDisallow: /sitemap.xml\n"
    homepage = '<html><body><a href="/about">About</a></body></html>'
    fetched_urls = []

    def fake(url, timeout=10, max_bytes=3_000_000, max_redirects=5):
        fetched_urls.append(url)
        pages = {"https://acme.example/robots.txt": robots_txt, "https://acme.example/": homepage}
        if url in pages:
            return {"ok": True, "url": url, "final_url": url, "status": 200,
                     "html": pages[url], "headers": {}, "truncated": False, "error": None}
        return {"ok": False, "url": url, "final_url": url, "status": 404,
                 "html": "", "headers": {}, "truncated": False, "error": "not found"}

    monkeypatch.setattr(robots_mod, "safe_fetch", fake)
    monkeypatch.setattr(discovery_mod, "safe_fetch", fake)

    discovery_mod.discover_pages("https://acme.example/", max_pages=8)
    assert "https://acme.example/sitemap.xml" not in fetched_urls


def test_sitemap_index_child_with_query_string_is_recognized_and_followed(monkeypatch):
    """Regression test for a real bug found via live testing: a
    sitemap-index child sitemap carrying a pagination query string
    (e.g. "sitemap_products_1.xml?from=1&to=500", a standard large-
    catalog/Shopify-style pattern) was misread as a final page URL
    instead of being recognized as another XML sitemap and recursed
    into -- meaning the actual product pages inside it were never
    discovered, and the raw sitemap filenames were fed into the audit
    as if they were content pages."""
    pages = {
        "https://shopdemo.example/robots.txt": f.ECOMMERCE_ROBOTS_TXT,
        "https://shopdemo.example/sitemap.xml": f.ECOMMERCE_SITEMAP_INDEX_XML,
        "https://shopdemo.example/sitemap_products_1.xml?from=1&to=500": f.ECOMMERCE_PRODUCTS_SITEMAP_XML,
        "https://shopdemo.example/sitemap_pages_1.xml": f.ECOMMERCE_PAGES_SITEMAP_XML,
        "https://shopdemo.example/": f.ECOMMERCE_HOMEPAGE_WITH_LEGAL_FOOTER,
    }
    fake = _make_fake_safe_fetch(pages)
    monkeypatch.setattr(robots_mod, "safe_fetch", fake)
    monkeypatch.setattr(discovery_mod, "safe_fetch", fake)

    inventory = discovery_mod.discover_pages("https://shopdemo.example/", max_pages=8)

    # The real product/page URLs from inside the query-stringed child
    # sitemap must be discovered...
    assert any(u.endswith("/products/trail-runner") for u in inventory["candidate_urls"])
    assert any(u.endswith("/products/wool-loafer") for u in inventory["candidate_urls"])
    assert any(u.endswith("/about") for u in inventory["candidate_urls"])
    # ...and the sitemap XML files themselves must never appear as
    # candidate "pages" to audit.
    assert not any(u.endswith(".xml") or ".xml?" in u for u in inventory["candidate_urls"])
    assert inventory["sitemap_url_count"] == 3


def test_nested_sitemap_index_without_query_strings_still_works(monkeypatch):
    """Non-regression: an ordinary (no query string) nested sitemap index
    must keep working exactly as before."""
    nested_index = """<?xml version="1.0" encoding="UTF-8"?>
    <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <sitemap><loc>https://acme.example/sitemap_products.xml</loc></sitemap>
    </sitemapindex>"""
    products_sitemap = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url><loc>https://acme.example/products/widget</loc></url>
    </urlset>"""
    pages = {
        "https://acme.example/robots.txt": ROBOTS_TXT_WITH_SITEMAP_AND_DISALLOW,
        "https://acme.example/sitemap.xml": nested_index,
        "https://acme.example/sitemap_products.xml": products_sitemap,
        "https://acme.example/": HOMEPAGE_WITH_LINKS,
    }
    fake = _make_fake_safe_fetch(pages)
    monkeypatch.setattr(robots_mod, "safe_fetch", fake)
    monkeypatch.setattr(discovery_mod, "safe_fetch", fake)

    inventory = discovery_mod.discover_pages("https://acme.example/", max_pages=8)
    assert any(u.endswith("/products/widget") for u in inventory["candidate_urls"])


def test_weak_internal_linking_requires_multiple_corroborating_signals(monkeypatch):
    """A site with a sitemap (even a thin one) must not be reported as
    having weak internal linking just because the homepage itself has
    few links -- sitemap absence, thin homepage links, AND thin depth-2
    yield must all line up."""
    pages = {
        "https://acme.example/robots.txt": ROBOTS_TXT_WITH_SITEMAP_AND_DISALLOW,
        "https://acme.example/sitemap.xml": SITEMAP_XML,
        "https://acme.example/": '<html><body><a href="/pricing">Pricing</a></body></html>',
    }
    fake = _make_fake_safe_fetch(pages)
    monkeypatch.setattr(robots_mod, "safe_fetch", fake)
    monkeypatch.setattr(discovery_mod, "safe_fetch", fake)

    inventory = discovery_mod.discover_pages("https://acme.example/", max_pages=8)
    assert inventory["weak_internal_linking"] is False


# --- Day 4: adversarial discovery patterns ------------------------------

BROKEN_SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://acme.example/pricing</loc>
</urlset>
"""  # missing closing </url> and </loc> -- malformed XML


def test_broken_sitemap_xml_does_not_crash_discovery(monkeypatch):
    """A malformed/truncated sitemap.xml (real-world occurrence: a CDN
    serving a partial response, a hand-edited sitemap with a typo) must
    degrade gracefully to 'no sitemap entries found', never raise."""
    pages = {
        "https://acme.example/robots.txt": ROBOTS_TXT_WITH_SITEMAP_AND_DISALLOW,
        "https://acme.example/sitemap.xml": BROKEN_SITEMAP_XML,
        "https://acme.example/": HOMEPAGE_WITH_LINKS,
    }
    fake = _make_fake_safe_fetch(pages)
    monkeypatch.setattr(robots_mod, "safe_fetch", fake)
    monkeypatch.setattr(discovery_mod, "safe_fetch", fake)

    inventory = discovery_mod.discover_pages("https://acme.example/", max_pages=5)
    assert inventory["sitemap_found"] is False
    assert inventory["sitemap_url_count"] == 0
    # Discovery should still fall back to homepage links rather than
    # coming back empty just because the sitemap was unusable.
    assert any(u.endswith("/pricing") for u in inventory["candidate_urls"])


CROSS_DOMAIN_SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://acme.example/pricing</loc></url>
<url><loc>https://cdn.thirdparty-assets.example/tracking-pixel.html</loc></url>
<url><loc>https://unrelated-partner.example/co-branded-page</loc></url>
</urlset>
"""


def test_irrelevant_cross_domain_sitemap_entries_are_filtered(monkeypatch):
    """A sitemap can legitimately list (or be polluted with) entries on
    a different domain entirely -- these must never consume this site's
    bounded page budget or appear as candidates."""
    pages = {
        "https://acme.example/robots.txt": ROBOTS_TXT_WITH_SITEMAP_AND_DISALLOW,
        "https://acme.example/sitemap.xml": CROSS_DOMAIN_SITEMAP_XML,
        "https://acme.example/": HOMEPAGE_WITH_LINKS,
    }
    fake = _make_fake_safe_fetch(pages)
    monkeypatch.setattr(robots_mod, "safe_fetch", fake)
    monkeypatch.setattr(discovery_mod, "safe_fetch", fake)

    inventory = discovery_mod.discover_pages("https://acme.example/", max_pages=8)
    assert not any("thirdparty-assets.example" in u for u in inventory["candidate_urls"])
    assert not any("unrelated-partner.example" in u for u in inventory["candidate_urls"])


def test_duplicate_urls_via_tracking_params_collapse_to_one_candidate():
    """The same page linked multiple times with different tracking query
    strings (utm_source, fbclid, session id, ...) must not consume
    multiple budget slots as if they were distinct pages."""
    normalized = [
        discovery_mod._normalize_url("https://acme.example/pricing?utm_source=newsletter"),
        discovery_mod._normalize_url("https://acme.example/pricing?utm_campaign=spring&fbclid=abc123"),
        discovery_mod._normalize_url("https://acme.example/pricing"),
    ]
    assert len(set(normalized)) == 1
