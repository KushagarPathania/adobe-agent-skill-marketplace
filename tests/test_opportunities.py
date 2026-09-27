"""Final hardening pass: findings[] vs opportunities[] separation.

The Adobe handout explicitly allows suggested actions that go beyond
detected problems ("proactive improvements ... even where no explicit
defect was found"). AI-005 (no FAQ page found among audited product
pages) is exactly that -- a proactive, non-defect suggestion -- and must
never be counted as a website finding. These are full-pipeline
(orchestrator-level) tests; `check_proactive_recommendations`'s own
conservative logic/false-positive defenses are unit-tested separately in
test_semantic_analyzer.py and test_day4_adversarial.py, and are
unchanged by this split.
"""
import skills_impl.audit_orchestrator.scripts.orchestrator as orch
import skills_impl.site_discovery.scripts.discovery as discovery_mod
import skills_impl.site_discovery.scripts.robots as robots_mod
from skills_impl.audit_orchestrator.scripts.config import AuditConfig
from tests import fixtures as f

BASE = "https://shopdemo-opps.example"

PAGES = {
    BASE: """<html><body><h1>ShopDemo</h1>
        <a href="/products/a">Product A</a>
        <a href="/products/b">Product B</a>
        </body></html>""",
    f"{BASE}/products/a": f.PRODUCT_PAGE_MISSING_SCHEMA_NO_LINKS,
    f"{BASE}/products/b": f.PRODUCT_PAGE_MISSING_SCHEMA_NO_LINKS.replace("Gadget Max", "Gadget Mini"),
}


def _fake_safe_fetch(url, timeout=10, max_bytes=3_000_000, max_redirects=5):
    if url in PAGES:
        return {"ok": True, "url": url, "final_url": url, "status": 200,
                 "html": PAGES[url], "headers": {}, "truncated": False, "error": None}
    return {"ok": False, "url": url, "final_url": url, "status": 404,
             "html": "", "headers": {}, "truncated": False, "error": "not found"}


def _patch_network(monkeypatch):
    monkeypatch.setattr(orch, "is_safe_url", lambda url: (True, None, "safe"))
    monkeypatch.setattr(orch, "safe_fetch", _fake_safe_fetch)
    monkeypatch.setattr(discovery_mod, "safe_fetch", _fake_safe_fetch)
    monkeypatch.setattr(robots_mod, "safe_fetch", _fake_safe_fetch)
    monkeypatch.setattr(orch, "PLAYWRIGHT_AVAILABLE", False)


def test_opportunities_key_always_present(monkeypatch):
    _patch_network(monkeypatch)
    report = orch.run_audit(BASE, config=AuditConfig(max_pages=5, total_audit_timeout=30))
    assert "opportunities" in report
    assert isinstance(report["opportunities"], list)


def test_ai005_appears_in_opportunities_not_findings(monkeypatch):
    _patch_network(monkeypatch)
    report = orch.run_audit(BASE, config=AuditConfig(max_pages=5, total_audit_timeout=30))

    opportunity_ids = [o["id"] for o in report["opportunities"]]
    finding_ids = [f["id"] for f in report["findings"]]
    assert "AI-005" in opportunity_ids
    assert "AI-005" not in finding_ids


def test_opportunities_never_affect_summary_counts(monkeypatch):
    _patch_network(monkeypatch)
    report = orch.run_audit(BASE, config=AuditConfig(max_pages=5, total_audit_timeout=30))

    summary = report["summary"]
    findings = report["findings"]
    assert summary["total_findings"] == len(findings)
    actual = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for fnd in findings:
        actual[fnd["severity"]] += 1
    assert summary["critical"] == actual["critical"]
    assert summary["high"] == actual["high"]
    assert summary["medium"] == actual["medium"]
    assert summary["low"] == actual["low"]
    # The opportunity's own (informational, not summary-affecting) fields
    # must not have been silently folded into any severity bucket.
    assert len(report["opportunities"]) >= 1


def test_opportunity_object_has_required_fields(monkeypatch):
    _patch_network(monkeypatch)
    report = orch.run_audit(BASE, config=AuditConfig(max_pages=5, total_audit_timeout=30))

    ai005 = next(o for o in report["opportunities"] if o["id"] == "AI-005")
    for key in ("id", "title", "evidence", "suggested_action", "confidence"):
        assert key in ai005, f"missing required opportunity field: {key}"
    assert "summary" in ai005["suggested_action"]
    assert "priority" in ai005["suggested_action"]


def test_opportunities_not_deduplicated_against_findings(monkeypatch):
    """An opportunity must never be folded/merged into the findings
    dedup+merge pipeline -- confirm the two lists are independent."""
    _patch_network(monkeypatch)
    report = orch.run_audit(BASE, config=AuditConfig(max_pages=5, total_audit_timeout=30))

    finding_keys = {(f["id"], f.get("scope")) for f in report["findings"]}
    for o in report["opportunities"]:
        # An opportunity's id must never also appear as a finding id --
        # the two vocabularies are disjoint by construction (AI-005 is
        # only ever emitted as an opportunity).
        assert o["id"] not in {k[0] for k in finding_keys}


def test_no_product_pages_yields_no_opportunities(monkeypatch):
    """Evidence-backed conservatism preserved: no product pages audited
    means no basis for the FAQ-opportunity suggestion."""
    pages = {
        BASE: '<html><body><h1>Blog</h1><a href="/post">Post</a></body></html>',
        f"{BASE}/post": '<html><body><h1>A Post</h1><p>Some article content here.</p></body></html>',
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

    report = orch.run_audit(BASE, config=AuditConfig(max_pages=5, total_audit_timeout=30))
    assert report["opportunities"] == []
