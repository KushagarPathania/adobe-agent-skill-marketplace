"""Day 5 (Adobe submission QA) focused regression tests for:

Priority 5 -- a robots.txt exclusion is a coverage limitation
(`audit_diagnostics`), never a website finding. Respecting robots.txt is
correct crawler behavior, not a defect.

Priority 7 -- findings vs. diagnostics separation, specifically HTTP
401/403: an access-denied response is ambiguous (could be a genuine
crawler-access problem, or an artifact of this audit's own request
signature) and must not be automatically escalated to a high-severity,
high-confidence website defect the way a generic fetch failure is.

All network calls are monkeypatched; fully offline.
"""
import skills_impl.audit_orchestrator.scripts.orchestrator as orch
import skills_impl.site_discovery.scripts.discovery as discovery_mod
import skills_impl.site_discovery.scripts.robots as robots_mod
from skills_impl.audit_orchestrator.scripts.config import AuditConfig

BASE = "https://fake-diag-site.example"

HOMEPAGE_HTML = """
<html><body>
<h1>Acme Shop</h1>
<p>We sell quality gadgets online.</p>
<a href="/products/a">Product A</a>
</body></html>
"""


def _fake_safe_fetch_ok(url, timeout=10, max_bytes=3_000_000, max_redirects=5):
    pages = {BASE: HOMEPAGE_HTML, f"{BASE}/products/a": HOMEPAGE_HTML}
    if url in pages:
        return {"ok": True, "url": url, "final_url": url, "status": 200,
                 "html": pages[url], "headers": {}, "truncated": False, "error": None}
    return {"ok": False, "url": url, "final_url": url, "status": 404,
             "html": "", "headers": {}, "truncated": False, "error": "not found"}


def _patch_network(monkeypatch, fetch_fn=None):
    fetch_fn = fetch_fn or _fake_safe_fetch_ok
    monkeypatch.setattr(orch, "is_safe_url", lambda url: (True, None, "safe"))
    monkeypatch.setattr(orch, "safe_fetch", fetch_fn)
    monkeypatch.setattr(discovery_mod, "safe_fetch", fetch_fn)
    monkeypatch.setattr(robots_mod, "safe_fetch", fetch_fn)
    monkeypatch.setattr(orch, "PLAYWRIGHT_AVAILABLE", False)


# --- Priority 5: robots.txt exclusions are diagnostics, not findings ----

def _fake_inventory_with_robots_exclusion():
    return {
        "base_url": BASE, "robots_found": True, "sitemap_found": False, "sitemap_url_count": 0,
        "probed_common_sitemap": False, "homepage_fetch_ok": True, "homepage_link_count": 5,
        "depth2_pages_explored": 0, "depth2_new_urls": 0, "total_candidates": 2,
        "skipped_disallowed": [f"{BASE}/admin", f"{BASE}/internal-reports"],
        "candidate_urls": [BASE, f"{BASE}/products/a"],
        "weak_internal_linking": False,
    }


def test_robots_exclusion_produces_a_diagnostic(monkeypatch):
    _patch_network(monkeypatch)
    monkeypatch.setattr(orch, "discover_pages", lambda url, max_pages, timeout: _fake_inventory_with_robots_exclusion())

    report = orch.run_audit(BASE, config=AuditConfig(max_pages=5, total_audit_timeout=30))

    robots_diags = [d for d in report["audit_diagnostics"] if d["type"] == "robots_exclusion"]
    assert len(robots_diags) == 2
    urls = {d["page_url"] for d in robots_diags}
    assert urls == {f"{BASE}/admin", f"{BASE}/internal-reports"}
    for d in robots_diags:
        assert "robots.txt disallowed crawling" in d["message"]


def test_robots_exclusion_does_not_produce_a_finding(monkeypatch):
    _patch_network(monkeypatch)
    monkeypatch.setattr(orch, "discover_pages", lambda url, max_pages, timeout: _fake_inventory_with_robots_exclusion())

    report = orch.run_audit(BASE, config=AuditConfig(max_pages=5, total_audit_timeout=30))

    assert all(f["id"] != "AI-002" for f in report["findings"])
    assert not any("/admin" in str(f.get("evidence", {})) for f in report["findings"])
    assert not any("/internal-reports" in str(f.get("evidence", {})) for f in report["findings"])


def test_summary_counts_remain_correct_with_robots_exclusions(monkeypatch):
    _patch_network(monkeypatch)
    monkeypatch.setattr(orch, "discover_pages", lambda url, max_pages, timeout: _fake_inventory_with_robots_exclusion())

    report = orch.run_audit(BASE, config=AuditConfig(max_pages=5, total_audit_timeout=30))

    findings = report["findings"]
    summary = report["summary"]
    assert summary["total_findings"] == len(findings)
    actual = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in findings:
        actual[f["severity"]] += 1
    assert summary["critical"] == actual["critical"]
    assert summary["high"] == actual["high"]
    assert summary["medium"] == actual["medium"]
    assert summary["low"] == actual["low"]


def test_audit_continues_on_allowed_pages_despite_robots_exclusions(monkeypatch):
    _patch_network(monkeypatch)
    monkeypatch.setattr(orch, "discover_pages", lambda url, max_pages, timeout: _fake_inventory_with_robots_exclusion())

    report = orch.run_audit(BASE, config=AuditConfig(max_pages=5, total_audit_timeout=30))

    assert report["metadata"]["pages_audited"] > 0


# --- Priority 7: HTTP 401/403 recalibration -------------------------------

def _fake_fetch_status(status, error_text):
    def fake(url, timeout=10, max_bytes=3_000_000, max_redirects=5):
        return {"ok": False, "url": url, "final_url": url, "status": status,
                 "html": "", "headers": {}, "truncated": False, "error": error_text,
                 "error_category": "http_error"}
    return fake


def test_403_response_uses_orch_003_medium_not_high(monkeypatch):
    _patch_network(monkeypatch, _fake_fetch_status(403, "HTTP Error 403: Forbidden"))

    report = orch.run_audit(BASE, config=AuditConfig(max_pages=3, total_audit_timeout=30))

    orch001 = [f for f in report["findings"] if f["id"] == "ORCH-001"]
    orch003 = [f for f in report["findings"] if f["id"] == "ORCH-003"]
    assert orch001 == []
    assert len(orch003) == 1
    assert orch003[0]["severity"] == "medium"
    assert orch003[0]["confidence"] < 0.9
    assert "403" in orch003[0]["evidence"]["summary"]


def test_401_response_also_uses_orch_003(monkeypatch):
    _patch_network(monkeypatch, _fake_fetch_status(401, "HTTP Error 401: Unauthorized"))

    report = orch.run_audit(BASE, config=AuditConfig(max_pages=3, total_audit_timeout=30))

    orch003 = [f for f in report["findings"] if f["id"] == "ORCH-003"]
    assert len(orch003) == 1
    assert orch003[0]["severity"] == "medium"


def test_non_access_denied_http_error_keeps_existing_orch_001_behavior(monkeypatch):
    """Regression guard: only 401/403 are recalibrated -- a genuine
    server error (500) keeps the existing, unmodified ORCH-001 behavior
    (including escalating to 'high' for the target URL itself)."""
    _patch_network(monkeypatch, _fake_fetch_status(500, "HTTP Error 500: Internal Server Error"))

    report = orch.run_audit(BASE, config=AuditConfig(max_pages=3, total_audit_timeout=30))

    orch001 = [f for f in report["findings"] if f["id"] == "ORCH-001"]
    orch003 = [f for f in report["findings"] if f["id"] == "ORCH-003"]
    assert orch003 == []
    assert len(orch001) == 1
    assert orch001[0]["severity"] == "high"  # candidate_url == the requested target
    assert orch001[0]["confidence"] == 0.9


# --- General findings/diagnostics separation ------------------------------

def test_diagnostics_never_appear_inside_findings_list(monkeypatch):
    _patch_network(monkeypatch)
    monkeypatch.setattr(orch, "discover_pages", lambda url, max_pages, timeout: _fake_inventory_with_robots_exclusion())

    report = orch.run_audit(BASE, config=AuditConfig(max_pages=5, total_audit_timeout=30))

    finding_ids = {f["id"] for f in report["findings"]}
    diagnostic_types = {d["type"] for d in report["audit_diagnostics"]}
    # No diagnostic "type" value is ever also used as a finding "id" --
    # the two vocabularies never collide.
    assert finding_ids.isdisjoint(diagnostic_types)
    assert "audit_diagnostics" in report
    assert isinstance(report["audit_diagnostics"], list)
