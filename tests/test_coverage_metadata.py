"""Final hardening pass: coverage metadata.

Confirms the new `metadata.coverage` block is present, accurate, and
reuses existing inventory/diagnostic/page-classification data rather
than performing any redundant crawling -- and that a bounded/small
sample is reported as informational, never as a defect.
"""
import skills_impl.audit_orchestrator.scripts.orchestrator as orch
import skills_impl.site_discovery.scripts.discovery as discovery_mod
import skills_impl.site_discovery.scripts.robots as robots_mod
from skills_impl.audit_orchestrator.scripts.config import AuditConfig

BASE = "https://coverage-meta.example"

PAGES = {
    BASE: '<html lang="en"><body><h1>Acme</h1><a href="/products/a">A</a><a href="/admin">Admin</a></body></html>',
    f"{BASE}/products/a": '<html lang="en"><body><h1>Product A</h1><p>$19.99. Add to cart. In stock.</p></body></html>',
}

ROBOTS_TXT = "User-agent: *\nDisallow: /admin\n"


def _fake_fetch(url, timeout=10, max_bytes=3_000_000, max_redirects=5):
    if url == f"{BASE}/robots.txt":
        return {"ok": True, "url": url, "final_url": url, "status": 200,
                 "html": ROBOTS_TXT, "headers": {}, "truncated": False, "error": None}
    if url in PAGES:
        return {"ok": True, "url": url, "final_url": url, "status": 200,
                 "html": PAGES[url], "headers": {}, "truncated": False, "error": None}
    return {"ok": False, "url": url, "final_url": url, "status": 404,
             "html": "", "headers": {}, "truncated": False, "error": "not found"}


def _patch_network(monkeypatch):
    monkeypatch.setattr(orch, "is_safe_url", lambda url: (True, None, "safe"))
    monkeypatch.setattr(orch, "safe_fetch", _fake_fetch)
    monkeypatch.setattr(discovery_mod, "safe_fetch", _fake_fetch)
    monkeypatch.setattr(robots_mod, "safe_fetch", _fake_fetch)
    monkeypatch.setattr(orch, "PLAYWRIGHT_AVAILABLE", False)


def test_coverage_block_present_with_expected_keys(monkeypatch):
    _patch_network(monkeypatch)
    report = orch.run_audit(BASE, config=AuditConfig(max_pages=5, total_audit_timeout=30))

    coverage = report["metadata"]["coverage"]
    for key in (
        "candidate_pages_discovered", "pages_selected", "pages_successfully_audited",
        "robots_skipped_pages", "timeout_or_network_skipped_pages",
        "runtime_limit_unaudited_pages", "represented_page_types", "coverage_limitations",
    ):
        assert key in coverage, f"missing coverage field: {key}"


def test_coverage_counts_are_accurate(monkeypatch):
    _patch_network(monkeypatch)
    report = orch.run_audit(BASE, config=AuditConfig(max_pages=5, total_audit_timeout=30))

    coverage = report["metadata"]["coverage"]
    assert coverage["pages_successfully_audited"] == report["metadata"]["pages_audited"]
    # MINOR CLEANUP fix: top-level `pages_discovered` must mean the same
    # thing as `coverage.candidate_pages_discovered` (the true discovery
    # count, before ranking/selection) -- it previously aliased
    # `pages_selected` instead, which is a separate, smaller number.
    assert coverage["candidate_pages_discovered"] == report["metadata"]["pages_discovered"]
    assert coverage["pages_selected"] == report["metadata"]["pages_selected"]
    assert coverage["robots_skipped_pages"] == report["metadata"]["pages_blocked_by_robots"]
    assert coverage["robots_skipped_pages"] >= 1  # /admin was disallowed
    assert coverage["candidate_pages_discovered"] >= coverage["pages_selected"]


def test_represented_page_types_reflects_actually_audited_pages(monkeypatch):
    _patch_network(monkeypatch)
    report = orch.run_audit(BASE, config=AuditConfig(max_pages=5, total_audit_timeout=30))

    coverage = report["metadata"]["coverage"]
    classified_types = {v["page_type"] for v in report["metadata"]["page_classifications"].values()}
    assert set(coverage["represented_page_types"]) == classified_types


def test_bounded_small_sample_is_not_treated_as_a_defect(monkeypatch):
    """A small, bounded, sitemap-less sample must never itself become a
    finding -- coverage is informational metadata only."""
    _patch_network(monkeypatch)
    report = orch.run_audit(BASE, config=AuditConfig(max_pages=5, total_audit_timeout=30))

    assert all("coverage" not in f.get("title", "").lower() for f in report["findings"])
    assert all("small sample" not in f.get("evidence", {}).get("summary", "").lower() for f in report["findings"])
