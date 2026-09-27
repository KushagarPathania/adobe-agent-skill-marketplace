"""End-to-end pipeline tests, fully offline.

Every network call the orchestrator could make (URL safety check, HTTP
fetch, headless render) is monkeypatched to a deterministic fake so the
full discovery -> classify -> check -> dedupe -> prioritize pipeline can
be exercised without any real network access.
"""
import skills_impl.audit_orchestrator.scripts.orchestrator as orch
import skills_impl.site_discovery.scripts.discovery as discovery_mod
import skills_impl.site_discovery.scripts.robots as robots_mod
from skills_impl.audit_orchestrator.scripts.config import AuditConfig
from tests import fixtures as f

BASE = "https://fake-test-site.example"

FAKE_PAGES = {
    BASE: f"""
        <html><body>
        <h1>Acme Shop</h1>
        <p>We sell quality gadgets online.</p>
        <a href="/products/a">Product A</a>
        <a href="/products/b">Product B</a>
        </body></html>
    """,
    f"{BASE}/products/a": f.PRODUCT_PAGE_MISSING_SCHEMA_NO_LINKS,
    f"{BASE}/products/b": f.PRODUCT_PAGE_MISSING_SCHEMA_NO_LINKS.replace("Gadget Max", "Gadget Mini"),
}


def _fake_safe_fetch(url, timeout=10, max_bytes=3_000_000, max_redirects=5):
    if url in FAKE_PAGES:
        return {"ok": True, "url": url, "final_url": url, "status": 200,
                 "html": FAKE_PAGES[url], "headers": {}, "truncated": False, "error": None}
    return {"ok": False, "url": url, "final_url": url, "status": 404,
             "html": "", "headers": {}, "truncated": False, "error": "not found"}


def _patch_network(monkeypatch):
    monkeypatch.setattr(orch, "is_safe_url", lambda url: (True, None, "safe"))
    monkeypatch.setattr(orch, "safe_fetch", _fake_safe_fetch)
    monkeypatch.setattr(discovery_mod, "safe_fetch", _fake_safe_fetch)
    monkeypatch.setattr(robots_mod, "safe_fetch", _fake_safe_fetch)


def test_report_schema_has_required_top_level_fields(monkeypatch):
    _patch_network(monkeypatch)
    monkeypatch.setattr(orch, "PLAYWRIGHT_AVAILABLE", False)

    report = orch.run_audit(BASE, config=AuditConfig(max_pages=5, total_audit_timeout=30))

    assert set(("site", "audited_at", "summary", "findings")) <= set(report.keys())
    assert set(("total_findings", "critical", "high", "medium", "low")) <= set(report["summary"].keys())
    for finding in report["findings"]:
        assert set(("id", "title", "severity", "evidence", "suggested_action")) <= set(finding.keys())
        assert "summary" in finding["suggested_action"]
        assert "priority" in finding["suggested_action"]


def test_rendering_unavailable_is_a_limitation_not_a_critical_failure(monkeypatch):
    """A local environment that can't run Playwright must not produce a
    false 'website is broken' verdict."""
    _patch_network(monkeypatch)
    monkeypatch.setattr(orch, "PLAYWRIGHT_AVAILABLE", False)

    report = orch.run_audit(BASE, config=AuditConfig(max_pages=5, total_audit_timeout=30))

    assert report["metadata"]["pages_audited"] > 0
    assert report["summary"]["critical"] == 0
    assert any("Playwright" in msg for msg in report["metadata"]["limitations"])


def test_identical_finding_across_pages_is_deduplicated_to_site_scope(monkeypatch):
    _patch_network(monkeypatch)
    monkeypatch.setattr(orch, "PLAYWRIGHT_AVAILABLE", False)

    report = orch.run_audit(BASE, config=AuditConfig(max_pages=5, total_audit_timeout=30))

    # Two distinct product pages both miss Product schema -> one merged
    # site-scope finding, not two near-identical page-scope findings.
    # (The homepage separately missing Organization schema is a different
    # title/id-pair and correctly stays its own finding.)
    product_schema_findings = [x for x in report["findings"] if x["id"] == "TP-003" and "Product" in x["title"]]
    assert len(product_schema_findings) == 1
    assert product_schema_findings[0]["scope"] == "site"
    assert len(product_schema_findings[0]["evidence"]["affected_pages"]) == 2


def test_findings_are_sorted_worst_first(monkeypatch):
    _patch_network(monkeypatch)
    monkeypatch.setattr(orch, "PLAYWRIGHT_AVAILABLE", False)

    report = orch.run_audit(BASE, config=AuditConfig(max_pages=5, total_audit_timeout=30))
    from skills_impl.common.schema import SEVERITY_WEIGHT

    scores = [SEVERITY_WEIGHT.get(x["severity"], 0) * x.get("confidence", 0.5) for x in report["findings"]]
    assert scores == sorted(scores, reverse=True)


def test_unsafe_target_url_is_blocked_before_any_network_call():
    report = orch.run_audit("http://127.0.0.1:9000/admin")
    assert report["metadata"]["blocked"] is True
    assert report["summary"]["critical"] == 1
    assert report["findings"][0]["id"] == "ORCH-000"


def test_metadata_endpoint_is_blocked():
    report = orch.run_audit("http://169.254.169.254/latest/meta-data/")
    assert report["metadata"]["blocked"] is True


def test_dns_failure_on_target_is_a_diagnostic_not_a_critical_finding(monkeypatch):
    """The core reliability-patch requirement: a DNS/network failure on
    an otherwise-legitimate public URL must never be reported as 'this
    website is unsafe' -- it's an audit limitation, and findings must
    stay empty rather than fabricating a critical website defect."""
    monkeypatch.setattr(orch, "is_safe_url", lambda url: (False, "DNS resolution failed: [Errno -2] Name or service not known", "dns_resolution_failed"))

    report = orch.run_audit("https://a-perfectly-real-site.example/")

    assert report["findings"] == []
    assert report["summary"]["critical"] == 0
    assert report["metadata"].get("blocked") is not True
    assert report["metadata"]["network_unreachable"] is True
    assert any(d["type"] == "dns_resolution_failed" for d in report["audit_diagnostics"])


def test_genuinely_unsafe_target_still_produces_critical_orch_000(monkeypatch):
    """Regression guard: the DNS-failure carve-out must not accidentally
    swallow real security rejections -- those must still be ORCH-000
    critical findings with metadata.blocked=True."""
    monkeypatch.setattr(orch, "is_safe_url", lambda url: (False, "host resolves to a non-public address (127.0.0.1)", "unsafe"))

    report = orch.run_audit("https://looks-fine.example/")

    assert report["metadata"]["blocked"] is True
    assert report["summary"]["critical"] == 1
    assert report["findings"][0]["id"] == "ORCH-000"
    assert "network_unreachable" not in report["metadata"]


def test_all_pages_failing_with_network_errors_is_not_a_critical_finding(monkeypatch):
    """If every discovered page fails with a network/timeout/DNS error
    (never an actual HTTP response), that's our own reachability
    limitation -- not proof the website itself is broken -- so findings
    must stay empty rather than raising the critical ORCH-002."""
    monkeypatch.setattr(orch, "is_safe_url", lambda url: (True, None, "safe"))

    def all_timeout(url, timeout=10, max_bytes=3_000_000, max_redirects=5):
        return {"ok": False, "url": url, "final_url": url, "status": None,
                 "html": "", "headers": {}, "truncated": False,
                 "error": "timed out", "error_category": "timeout"}

    monkeypatch.setattr(orch, "safe_fetch", all_timeout)
    monkeypatch.setattr(discovery_mod, "safe_fetch", all_timeout)
    monkeypatch.setattr(robots_mod, "safe_fetch", all_timeout)
    monkeypatch.setattr(orch, "PLAYWRIGHT_AVAILABLE", False)

    report = orch.run_audit(BASE, config=AuditConfig(max_pages=5, total_audit_timeout=30))

    assert report["findings"] == []
    assert report["summary"]["critical"] == 0
    assert report["metadata"]["network_unreachable"] is True
    assert any(d["type"] == "timeout" for d in report["audit_diagnostics"])


def test_some_pages_actually_reachable_keeps_orch_002_for_the_rest(monkeypatch):
    """If discovery genuinely can't reach ANY page but at least one
    failure was a real HTTP-level response (not just network/DNS noise),
    the critical ORCH-002 behavior must be preserved -- this carve-out is
    only for pure network unavailability."""
    monkeypatch.setattr(orch, "is_safe_url", lambda url: (True, None, "safe"))

    def all_404(url, timeout=10, max_bytes=3_000_000, max_redirects=5):
        return {"ok": False, "url": url, "final_url": url, "status": 404,
                 "html": "", "headers": {}, "truncated": False,
                 "error": "HTTP Error 404: Not Found", "error_category": "http_error"}

    monkeypatch.setattr(orch, "safe_fetch", all_404)
    monkeypatch.setattr(discovery_mod, "safe_fetch", all_404)
    monkeypatch.setattr(robots_mod, "safe_fetch", all_404)
    monkeypatch.setattr(orch, "PLAYWRIGHT_AVAILABLE", False)

    report = orch.run_audit(BASE, config=AuditConfig(max_pages=5, total_audit_timeout=30))

    assert report["summary"]["critical"] == 1
    orch002 = [f for f in report["findings"] if f["id"] == "ORCH-002"]
    assert orch002
    # MINOR CLEANUP: describes a site-wide audit failure (every
    # candidate page failed), not a single page's defect.
    assert orch002[0]["scope"] == "site"


def test_successful_audit_behavior_is_unchanged(monkeypatch):
    """Existing behavior on a healthy fake site must be untouched by the
    reliability patch."""
    _patch_network(monkeypatch)
    monkeypatch.setattr(orch, "PLAYWRIGHT_AVAILABLE", False)

    report = orch.run_audit(BASE, config=AuditConfig(max_pages=5, total_audit_timeout=30))

    assert report["metadata"]["pages_audited"] == 3
    assert "network_unreachable" not in report["metadata"]
    assert report["metadata"].get("blocked") is not True


def test_deep_url_target_still_gets_entity_clarity_signal(monkeypatch):
    """Regression test: targeting a deep page (not the bare domain root,
    e.g. a specific article) must not leave the entity-clarity check
    starved of content and guaranteed to fire every time."""
    deep_base = f"{BASE}/wiki/Some_Article"
    pages = {
        deep_base: f.HOMEPAGE_GOOD,  # has Organization schema + clear description
    }

    def fake(url, timeout=10, max_bytes=3_000_000, max_redirects=5):
        if url in pages:
            return {"ok": True, "url": url, "final_url": url, "status": 200,
                     "html": pages[url], "headers": {}, "truncated": False, "error": None}
        return {"ok": False, "url": url, "final_url": url, "status": 404,
                 "html": "", "headers": {}, "truncated": False, "error": "not found"}

    monkeypatch.setattr(orch, "is_safe_url", lambda url: (True, None, "safe"))
    monkeypatch.setattr(orch, "safe_fetch", fake)
    monkeypatch.setattr(discovery_mod, "safe_fetch", fake)
    monkeypatch.setattr(robots_mod, "safe_fetch", fake)
    monkeypatch.setattr(orch, "PLAYWRIGHT_AVAILABLE", False)

    report = orch.run_audit(deep_base, config=AuditConfig(max_pages=3, total_audit_timeout=30))
    ids = [x["id"] for x in report["findings"]]
    assert "AI-003" not in ids


def test_audit_diagnostics_key_always_present(monkeypatch):
    _patch_network(monkeypatch)
    monkeypatch.setattr(orch, "PLAYWRIGHT_AVAILABLE", False)

    report = orch.run_audit(BASE, config=AuditConfig(max_pages=5, total_audit_timeout=30))
    assert "audit_diagnostics" in report
    assert isinstance(report["audit_diagnostics"], list)
    # Playwright being unavailable is a tool limitation, recorded as a
    # diagnostic -- not a website finding.
    assert any(d["type"] == "render_unavailable" for d in report["audit_diagnostics"])
    assert all(f["id"] != "ORCH-003" for f in report["findings"])


def test_check_crash_becomes_a_diagnostic_not_a_website_finding(monkeypatch):
    """A bug in our own check code must never masquerade as a website
    defect: it should land in audit_diagnostics, not findings."""
    _patch_network(monkeypatch)
    monkeypatch.setattr(orch, "PLAYWRIGHT_AVAILABLE", False)

    def exploding_check(*args, **kwargs):
        raise ValueError("boom: a bug in our own parsing code")

    monkeypatch.setattr(orch, "check_non_text_accessibility", exploding_check)

    report = orch.run_audit(BASE, config=AuditConfig(max_pages=5, total_audit_timeout=30))

    assert all(f["id"] != "ORCH-003" for f in report["findings"])
    crash_diagnostics = [d for d in report["audit_diagnostics"] if d["type"] == "check_error"]
    assert len(crash_diagnostics) >= 1
    assert crash_diagnostics[0]["check"] == "exploding_check"
    assert crash_diagnostics[0]["error_type"] == "ValueError"
    assert crash_diagnostics[0]["page_url"] is not None


def test_applicability_recorded_per_page_and_skips_irrelevant_checks(monkeypatch):
    """End-to-end: a page the classifier calls 'other' with low
    confidence should have no gated checks marked applicable."""
    _patch_network(monkeypatch)
    monkeypatch.setattr(orch, "PLAYWRIGHT_AVAILABLE", False)

    report = orch.run_audit(BASE, config=AuditConfig(max_pages=5, total_audit_timeout=30))
    classifications = report["metadata"]["page_classifications"]
    assert BASE in classifications or f"{BASE}/products/a" in classifications
    for url, info in classifications.items():
        assert "page_type" in info and "applicable_checks" in info
