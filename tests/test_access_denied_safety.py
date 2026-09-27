"""Regression tests for a real false-positive class found live against
https://www.cnn.com/: a page's RAW HTTP fetch succeeded with genuine,
substantial article content, but the SEPARATE Playwright render step got
a bot-management access-denied interstitial instead (rendered title/body
literally "Access to this page has been denied"). Treating that
interstitial as "the rendered page" corrupted two checks:

- TP-001 compared the real raw article against the four-word block page
  and reported "substantive content requires JavaScript rendering" --
  backwards, since the raw response already had the real content and it
  was the RENDER step that failed to reach it.
- EE-001 analyzed the block page's own (missing) H1/breadcrumb/title
  context as if it were the actual deep page's orientation.

`_is_access_denied_page` (skills_impl/audit_orchestrator/scripts/orchestrator.py)
is the fix: a page is only ever treated as access-denied when its OWN
title or H1 exactly matches a curated, well-known block-page phrase
("access denied", "you have been blocked", "pardon our interruption",
"attention required", "403 forbidden", ...) AND its overall body text is
short -- a genuine interstitial is minimal; an article that merely
discusses "denied"/"blocked"/"access" as a topic, or even one unusually
titled "Forbidden", still has substantial body content, which the length
guard rules out. Detected access-denial is never used as "rendered
content": the affected page falls back to its (still genuinely usable)
raw HTML exactly like a render failure, is excluded from TP-001's raw-
vs-rendered comparison entirely, and is recorded as an `access_denied`
diagnostic -- never a website finding.
"""
import skills_impl.audit_orchestrator.scripts.orchestrator as orch
import skills_impl.site_discovery.scripts.discovery as discovery_mod
import skills_impl.site_discovery.scripts.robots as robots_mod
from skills_impl.audit_orchestrator.scripts.config import AuditConfig
from tests import fixtures as f

BASE = "https://news-like.example"
DEEP_PATH = "/underscored/deals/real-article"

REAL_ARTICLE_RAW = """
<html><head><title>Today is your last day to buy a widget before prices increase</title></head>
<body>
<h1>Today is your last day to buy a widget before prices increase</h1>
<p>Buy now for $49.99. Add to cart today. In stock and ready to ship before the price increase.</p>
<p>Industry analysts say the shift reflects rising component costs across the supply chain.</p>
</body></html>
"""

ACCESS_DENIED_RENDERED = """
<html><head><title>Access to this page has been denied</title></head>
<body><h1>Access to this page has been denied</h1></body></html>
"""

HOMEPAGE_HTML = f"""<html><body><h1>News Site</h1><a href="{DEEP_PATH}">Real Article</a></body></html>"""


def _fake_fetch_for(pages):
    def fake(url, timeout=10, max_bytes=3_000_000, max_redirects=5):
        if url in pages:
            return {"ok": True, "url": url, "final_url": url, "status": 200,
                     "html": pages[url], "headers": {}, "truncated": False, "error": None}
        return {"ok": False, "url": url, "final_url": url, "status": 404,
                 "html": "", "headers": {}, "truncated": False, "error": "not found"}
    return fake


def _patch_network(monkeypatch, pages, render_map):
    fake = _fake_fetch_for(pages)
    monkeypatch.setattr(orch, "is_safe_url", lambda url: (True, None, "safe"))
    monkeypatch.setattr(orch, "safe_fetch", fake)
    monkeypatch.setattr(discovery_mod, "safe_fetch", fake)
    monkeypatch.setattr(robots_mod, "safe_fetch", fake)
    monkeypatch.setattr(orch, "PLAYWRIGHT_AVAILABLE", True)
    monkeypatch.setattr(orch, "_render_page", lambda url, timeout_ms: (render_map.get(url, ""), None))


# --- Unit tests: _is_access_denied_page -----------------------------------

def test_exact_access_denied_title_with_short_body_detected():
    assert orch._is_access_denied_page(ACCESS_DENIED_RENDERED) is True


def test_real_article_never_classified_as_access_denied():
    assert orch._is_access_denied_page(REAL_ARTICLE_RAW) is False


def test_various_known_block_page_phrases_detected():
    for title in (
        "Access Denied",
        "You have been blocked",
        "Sorry, you have been blocked",
        "Request Blocked",
        "This request has been blocked",
        "You don't have permission to access this page",
        "Pardon Our Interruption",
        "Attention Required",
        "403 Forbidden",
    ):
        html = f"<html><head><title>{title}</title></head><body><h1>{title}</h1></body></html>"
        assert orch._is_access_denied_page(html) is True, f"expected block-page phrase {title!r} to be detected"


def test_article_incidentally_discussing_access_denied_topic_not_classified():
    """(Test E) An ordinary, substantial article whose actual topic is
    access-control/security -- even mentioning "access denied" -- must
    NOT be classified as a block page merely because it's substantial."""
    html = """<html><head><title>How Companies Handle Access Denied Errors</title></head><body>
    <h1>How Companies Handle Access Denied Errors</h1>
    <p>When a user sees an access denied message, it usually means the system correctly blocked
    an unauthorized request. This article explains how modern security teams design these systems,
    the difference between authentication and authorization failures, and best practices for
    communicating access denied errors to end users without leaking sensitive information about
    why the request was blocked in the first place.</p>
    <p>Security engineers often balance user experience against the risk of over-sharing details
    in an access denied response, since attackers can use overly specific error messages to probe
    a system's internal structure.</p>
    </body></html>"""
    assert orch._is_access_denied_page(html) is False


def test_short_page_with_unrelated_title_not_classified():
    html = "<html><head><title>Contact Us</title></head><body><h1>Contact Us</h1></body></html>"
    assert orch._is_access_denied_page(html) is False


# --- A/B/C: access-denied rendered page -> no TP-001, no EE-001, diagnostic

def test_access_denied_render_produces_no_tp001(monkeypatch):
    pages = {BASE: HOMEPAGE_HTML, f"{BASE}{DEEP_PATH}": REAL_ARTICLE_RAW}
    render_map = {BASE: HOMEPAGE_HTML, f"{BASE}{DEEP_PATH}": ACCESS_DENIED_RENDERED}
    _patch_network(monkeypatch, pages, render_map)

    report = orch.run_audit(BASE, config=AuditConfig(max_pages=5, total_audit_timeout=30))
    assert all(f["id"] != "TP-001" for f in report["findings"])


def test_access_denied_render_produces_no_ee001(monkeypatch):
    pages = {BASE: HOMEPAGE_HTML, f"{BASE}{DEEP_PATH}": REAL_ARTICLE_RAW}
    render_map = {BASE: HOMEPAGE_HTML, f"{BASE}{DEEP_PATH}": ACCESS_DENIED_RENDERED}
    _patch_network(monkeypatch, pages, render_map)

    report = orch.run_audit(BASE, config=AuditConfig(max_pages=5, total_audit_timeout=30))
    assert all(f["id"] not in ("EE-001", "EE-004") for f in report["findings"])


def test_access_denied_produces_diagnostic_not_finding(monkeypatch):
    pages = {BASE: HOMEPAGE_HTML, f"{BASE}{DEEP_PATH}": REAL_ARTICLE_RAW}
    render_map = {BASE: HOMEPAGE_HTML, f"{BASE}{DEEP_PATH}": ACCESS_DENIED_RENDERED}
    _patch_network(monkeypatch, pages, render_map)

    report = orch.run_audit(BASE, config=AuditConfig(max_pages=5, total_audit_timeout=30))
    access_denied_diags = [d for d in report["audit_diagnostics"] if d["type"] == "access_denied"]
    assert len(access_denied_diags) == 1
    assert access_denied_diags[0]["page_url"] == f"{BASE}{DEEP_PATH}"
    assert report["summary"]["critical"] == 0
    assert report["summary"]["total_findings"] == len(report["findings"])


def test_page_falls_back_to_raw_html_content_for_classification(monkeypatch):
    """The real article's content (from raw HTML) should still drive
    page classification/other raw-eligible checks -- not be discarded
    entirely just because rendering was blocked."""
    pages = {BASE: HOMEPAGE_HTML, f"{BASE}{DEEP_PATH}": REAL_ARTICLE_RAW}
    render_map = {BASE: HOMEPAGE_HTML, f"{BASE}{DEEP_PATH}": ACCESS_DENIED_RENDERED}
    _patch_network(monkeypatch, pages, render_map)

    report = orch.run_audit(BASE, config=AuditConfig(max_pages=5, total_audit_timeout=30))
    classification = report["metadata"]["page_classifications"].get(f"{BASE}{DEEP_PATH}")
    assert classification is not None
    assert classification["page_type"] != "other"
    assert report["metadata"]["page_analysis"][f"{BASE}{DEEP_PATH}"]["analysis_mode"] == "raw_html_fallback"


# --- D: genuine JS-heavy page still triggers TP-001 -----------------------

def test_genuine_js_dependent_page_still_triggers_tp001(monkeypatch):
    homepage = f'<html><body><h1>Homepage</h1><a href="/pricing">Pricing</a></body></html>'
    pages = {BASE: homepage, f"{BASE}/pricing": f.RAW_HTML_JS_HEAVY}
    render_map = {BASE: homepage, f"{BASE}/pricing": f.RENDERED_HTML_JS_HEAVY}
    _patch_network(monkeypatch, pages, render_map)

    report = orch.run_audit(BASE, config=AuditConfig(max_pages=5, total_audit_timeout=30))
    assert any(f["id"] == "TP-001" for f in report["findings"])


# --- F: mixed audit -- normal JS-heavy pages + access-denied pages --------

def test_mixed_audit_tp001_only_uses_valid_pages(monkeypatch):
    pages = {
        BASE: f'<html><body><h1>News Site</h1><a href="/pricing">Pricing</a><a href="{DEEP_PATH}">Article</a></body></html>',
        f"{BASE}/pricing": f.RAW_HTML_JS_HEAVY,
        f"{BASE}{DEEP_PATH}": REAL_ARTICLE_RAW,
    }
    render_map = {
        BASE: pages[BASE],
        f"{BASE}/pricing": f.RENDERED_HTML_JS_HEAVY,
        f"{BASE}{DEEP_PATH}": ACCESS_DENIED_RENDERED,
    }
    _patch_network(monkeypatch, pages, render_map)

    report = orch.run_audit(BASE, config=AuditConfig(max_pages=8, total_audit_timeout=30))
    tp001 = [f for f in report["findings"] if f["id"] == "TP-001"]
    assert len(tp001) == 1
    affected = tp001[0]["evidence"].get("affected_pages", [tp001[0]["evidence"].get("url")])
    assert f"{BASE}{DEEP_PATH}" not in affected
    assert any(d["type"] == "access_denied" for d in report["audit_diagnostics"])


# --- G: site with only blocked deep pages ----------------------------------

def test_site_with_only_blocked_deep_pages_produces_no_false_findings(monkeypatch):
    pages = {BASE: HOMEPAGE_HTML, f"{BASE}{DEEP_PATH}": REAL_ARTICLE_RAW}
    render_map = {BASE: ACCESS_DENIED_RENDERED, f"{BASE}{DEEP_PATH}": ACCESS_DENIED_RENDERED}
    _patch_network(monkeypatch, pages, render_map)

    report = orch.run_audit(BASE, config=AuditConfig(max_pages=5, total_audit_timeout=30))
    assert all(f["id"] not in ("TP-001", "EE-001", "EE-004") for f in report["findings"])
    assert report["summary"]["critical"] == 0
