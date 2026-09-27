"""Consolidated false-positive red-team suite: the ten scenarios called
out for this phase, each mapped to a concrete assertion. Several of
these are already covered by more granular tests elsewhere in the suite
(cross-referenced in each docstring); this file exists so the full list
is verifiable in one place, end to end where practical.
"""
from skills_impl.technical_parser.scripts.structured_data_validation import check_structured_data
from skills_impl.engagement_evaluator.scripts.navigation_signals import check_navigation
from skills_impl.semantic_analyzer.scripts.ai_discoverability import check_ai_discoverability
from tests import fixtures as f

import skills_impl.audit_orchestrator.scripts.orchestrator as orch
import skills_impl.site_discovery.scripts.discovery as discovery_mod
import skills_impl.site_discovery.scripts.robots as robots_mod
from skills_impl.audit_orchestrator.scripts.config import AuditConfig

BASE = "https://redteam-site.example"


def _fake_fetch(pages):
    def fake(url, timeout=10, max_bytes=3_000_000, max_redirects=5):
        if url in pages:
            return {"ok": True, "url": url, "final_url": url, "status": 200,
                     "html": pages[url], "headers": {}, "truncated": False, "error": None}
        return {"ok": False, "url": url, "final_url": url, "status": 404,
                 "html": "", "headers": {}, "truncated": False, "error": "not found",
                 "error_category": "http_error"}
    return fake


def _run(monkeypatch, pages, url=BASE, max_pages=5):
    fake = _fake_fetch(pages)
    monkeypatch.setattr(orch, "is_safe_url", lambda u: (True, None, "safe"))
    monkeypatch.setattr(orch, "safe_fetch", fake)
    monkeypatch.setattr(discovery_mod, "safe_fetch", fake)
    monkeypatch.setattr(robots_mod, "safe_fetch", fake)
    monkeypatch.setattr(orch, "PLAYWRIGHT_AVAILABLE", False)
    return orch.run_audit(url, config=AuditConfig(max_pages=max_pages, total_audit_timeout=30))


# 1. Excellent page -> should not receive many findings.
def test_1_excellent_page_receives_few_findings(monkeypatch):
    excellent_homepage = """
    <html><head>
    <title>Acme Robotics | Industrial Automation</title>
    <meta name="description" content="Acme Robotics designs and manufactures industrial robotic arms for automotive manufacturing plants worldwide.">
    <script type="application/ld+json">{"@type":"Organization","name":"Acme Robotics","url":"https://acme-robotics.example"}</script>
    </head><body>
    <h1>Acme Robotics</h1>
    <p>Acme Robotics designs and manufactures industrial robotic arms for automotive manufacturing plants worldwide.</p>
    <a href="/products">Products</a><a href="/about">About</a><a href="/contact">Contact</a>
    <a href="/support">Support</a><a href="/docs">Documentation</a>
    </body></html>
    """
    report = _run(monkeypatch, {BASE: excellent_homepage})
    assert report["summary"]["total_findings"] <= 2
    assert report["summary"]["critical"] == 0
    assert report["summary"]["high"] == 0


# 2 & 3 are covered in detail by
# tests/test_semantic_analyzer.py::test_clear_visible_identity_without_schema_not_flagged
# and ::test_schema_present_but_poor_visible_identity_is_still_flagged.
def test_2_clear_entity_no_schema_not_strongly_flagged():
    findings = check_ai_discoverability(
        {"sitemap_found": True, "weak_internal_linking": False, "homepage_link_count": 10,
         "depth2_pages_explored": 2, "depth2_new_urls": 3, "skipped_disallowed": []},
        f.HOMEPAGE_GOOD, "https://acme-robotics.example/",
    )
    assert all(x["id"] != "AI-003" for x in findings)


def test_3_schema_present_poor_identity_still_detectable():
    html = """<html><head><title>Home</title>
    <script type="application/ld+json">{"@type":"Organization","name":"Acme"}</script>
    </head><body><h1>Welcome</h1></body></html>"""
    findings = check_ai_discoverability(
        {"sitemap_found": True, "weak_internal_linking": False, "homepage_link_count": 10,
         "depth2_pages_explored": 2, "depth2_new_urls": 3, "skipped_disallowed": []},
        html, "https://acme.example/",
    )
    assert any(x["id"] == "AI-003" for x in findings)


# 4. Article with excellent prose but no table/list -> not automatically flagged.
def test_4_article_with_excellent_prose_not_flagged():
    from skills_impl.engagement_evaluator.scripts.answer_scannability import check_answer_scannability
    html = """<html><head><title>The History of Robotics</title></head><body>
    <h1>The History of Robotics</h1>
    <p>Industrial robotics traces its roots to the early 1960s, when the first programmable arm was
    installed on a General Motors assembly line. Over the following decades, advances in control theory,
    sensing, and computing steadily expanded what these machines could do, from simple repetitive welding
    tasks to today's adaptive, vision-guided assembly systems used across nearly every manufacturing sector.</p>
    </body></html>"""
    # "article" is not a utility page type, so this check never applies
    # scannability pressure to it in the first place.
    findings = check_answer_scannability(html, "/blog/history-of-robotics", "https://acme.example/blog/history-of-robotics", "article")
    assert findings == []


# 5. Government page with no CTA -> should not be flagged for lacking one.
def test_5_government_page_no_cta_not_flagged():
    from skills_impl.page_classifier.scripts.classifier import classify_page
    classification = classify_page("https://springfield.gov/public-works", f.GOVERNMENT_PAGE)
    pages = [{"url": "https://springfield.gov/public-works", "html": f.GOVERNMENT_PAGE}]
    page_types = {"https://springfield.gov/public-works": classification["page_type"]}
    assert check_navigation(pages, page_types) == []


# 6 & 7 are covered in detail by
# tests/test_engagement_evaluator.py::test_product_page_with_contextual_links_is_not_a_dead_end
# and ::test_page_with_only_boilerplate_links_is_still_a_dead_end.


# 8. Product page with 2019 / 4090 / 256GB / 12GB -> no fake price findings.
def test_8_spec_numbers_never_produce_fake_price_findings():
    html = """<html><head><title>GraphixCard Pro</title></head><body>
    <h1>GraphixCard Pro</h1>
    <p>Released in 2019, model 4090, with 256GB storage and 12GB of memory. Add to cart. In stock.</p>
    <script type="application/ld+json">{"@type":"Product","name":"GraphixCard Pro","offers":{"@type":"Offer","price":"599.99","priceCurrency":"USD"}}</script>
    </body></html>"""
    findings = check_structured_data(html, "https://acme.example/graphixcard", "product")
    assert all(x["id"] != "TP-005" for x in findings)


# 9. Weak evidence must never produce HIGH/CRITICAL severity.
def test_9_weak_evidence_never_reaches_high_or_critical():
    # A single ambiguous price candidate: weak-ish evidence.
    single_candidate_html = """<html><head><title>Widget</title></head><body><h1>Widget</h1>
    <p>Buy now for $149.99.</p>
    <script type="application/ld+json">{"@type":"Product","offers":{"@type":"Offer","price":"199.99"}}</script>
    </body></html>"""
    findings = check_structured_data(single_candidate_html, "https://acme.example/widget", "product")
    tp005 = [x for x in findings if x["id"] == "TP-005"]
    assert tp005 and tp005[0]["severity"] not in ("high", "critical")

    # A borderline entity-clarity case (a couple of signals present).
    borderline_html = """<html><head><title>Acme Widgets</title></head><body>
    <h1>Welcome</h1></body></html>"""
    findings = check_ai_discoverability(
        {"sitemap_found": True, "weak_internal_linking": False, "homepage_link_count": 10,
         "depth2_pages_explored": 2, "depth2_new_urls": 3, "skipped_disallowed": []},
        borderline_html, "https://acme.example/",
    )
    ai003 = [x for x in findings if x["id"] == "AI-003"]
    assert ai003 and ai003[0]["severity"] not in ("high", "critical")


# 10. One underlying issue detected by multiple checks -> not several
# nearly identical findings, verified end to end through the orchestrator.
def test_10_overlapping_checks_collapse_to_one_finding_end_to_end(monkeypatch):
    poor_identity_homepage = "<html><head><title>Home</title></head><body><h1>Welcome</h1></body></html>"
    report = _run(monkeypatch, {BASE: poor_identity_homepage})

    identity_related = [
        x for x in report["findings"]
        if x["id"] in ("AI-003", "TP-006") and ("Organization" in x["title"] or x["id"] == "AI-003")
    ]
    # Both AI-003 and a same-page Organization/WebSite TP-006 would
    # otherwise independently fire here -- they must have collapsed into
    # at most one finding, not appear as two describing the same gap.
    # (Guard against a vacuous pass: at least one identity-related
    # finding must actually have fired for this assertion to mean
    # anything.)
    assert 1 <= len(identity_related) <= 1


# 11. Regression, end to end: the two real bugs found via live testing
# against an unseen large-catalog ecommerce site (a query-stringed
# sub-sitemap misread as a page, and legal boilerplate misread as
# government identity) must not silently return.
def test_11_realistic_ecommerce_site_discovers_products_and_is_not_misclassified_as_government(monkeypatch):
    ecommerce_site = "https://shopdemo.example"
    pages = {
        f"{ecommerce_site}/robots.txt": f.ECOMMERCE_ROBOTS_TXT,
        f"{ecommerce_site}/sitemap.xml": f.ECOMMERCE_SITEMAP_INDEX_XML,
        f"{ecommerce_site}/sitemap_products_1.xml?from=1&to=500": f.ECOMMERCE_PRODUCTS_SITEMAP_XML,
        f"{ecommerce_site}/sitemap_pages_1.xml": f.ECOMMERCE_PAGES_SITEMAP_XML,
        ecommerce_site: f.ECOMMERCE_HOMEPAGE_WITH_LEGAL_FOOTER,
        f"{ecommerce_site}/products/trail-runner": f.ECOMMERCE_PRODUCT_PAGE,
        f"{ecommerce_site}/products/wool-loafer": f.ECOMMERCE_PRODUCT_PAGE.replace("Trail Runner", "Wool Loafer"),
    }
    report = _run(monkeypatch, pages, url=ecommerce_site, max_pages=6)

    audited_urls = list(report["metadata"]["page_classifications"].keys())
    # The real product pages (from inside the query-stringed sub-sitemap)
    # must have been discovered and audited...
    assert any("/products/trail-runner" in u for u in audited_urls)
    assert any("/products/wool-loafer" in u for u in audited_urls)
    # ...and no raw sitemap XML file was ever treated as a page.
    assert not any(u.endswith(".xml") or ".xml?" in u for u in audited_urls)

    # The legal footer boilerplate must never classify this ecommerce
    # site as government.
    assert report["metadata"]["site_type"] != "government"

    # No new false HIGH/CRITICAL findings from any of this.
    assert report["summary"]["critical"] == 0
    assert report["summary"]["high"] == 0
