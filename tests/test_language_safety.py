"""Final hardening pass: conservative language-awareness layer.

`<html lang="...">` is the primary (only) language signal. Only an
explicit, well-formed, unsupported non-English value limits anything;
missing/empty/malformed lang and English all preserve current behavior
exactly. No translation/NLP system, no external libraries -- a small,
explicitly documented supported-language set (English only) and a
conservative skip of the English-vocabulary-dependent checks otherwise.
"""
import skills_impl.audit_orchestrator.scripts.orchestrator as orch
import skills_impl.site_discovery.scripts.discovery as discovery_mod
import skills_impl.site_discovery.scripts.robots as robots_mod
from skills_impl.audit_orchestrator.scripts.config import AuditConfig


# --- Unit tests: _page_language_support -----------------------------------

def test_lang_en_is_supported():
    lang, supported = orch._page_language_support('<html lang="en"><body></body></html>')
    assert lang == "en"
    assert supported is True


def test_lang_en_us_is_supported():
    lang, supported = orch._page_language_support('<html lang="en-US"><body></body></html>')
    assert lang == "en-US"
    assert supported is True


def test_unsupported_non_english_language():
    lang, supported = orch._page_language_support('<html lang="fr"><body></body></html>')
    assert lang == "fr"
    assert supported is False


def test_missing_lang_preserves_current_behavior():
    lang, supported = orch._page_language_support('<html><body>no lang attribute</body></html>')
    assert lang is None
    assert supported is True


def test_malformed_lang_value_preserves_current_behavior():
    lang, supported = orch._page_language_support('<html lang="123"><body></body></html>')
    assert lang == "123"
    assert supported is True  # not penalized -- can't confidently say it's unsupported


def test_empty_lang_value_preserves_current_behavior():
    lang, supported = orch._page_language_support('<html lang=""><body></body></html>')
    assert supported is True


# --- Orchestrator-level integration ----------------------------------------

BASE = "https://lang-safety.example"
DEEP_PATH = "/products/x200/overview"


def _pages_with_lang(lang_attr):
    lang_html = f' lang="{lang_attr}"' if lang_attr else ""
    homepage = f'<html{lang_html}><body><h1>Acme</h1><a href="{DEEP_PATH}">Product</a></body></html>'
    deep_page = f'<html{lang_html}><head><title>Overview</title></head><body><h1>Overview</h1><p>Some text.</p></body></html>'
    return {BASE: homepage, f"{BASE}{DEEP_PATH}": deep_page}


def _fake_fetch_for(pages):
    def fake(url, timeout=10, max_bytes=3_000_000, max_redirects=5):
        if url in pages:
            return {"ok": True, "url": url, "final_url": url, "status": 200,
                     "html": pages[url], "headers": {}, "truncated": False, "error": None}
        return {"ok": False, "url": url, "final_url": url, "status": 404,
                 "html": "", "headers": {}, "truncated": False, "error": "not found"}
    return fake


def _patch_network(monkeypatch, pages):
    fake = _fake_fetch_for(pages)
    monkeypatch.setattr(orch, "is_safe_url", lambda url: (True, None, "safe"))
    monkeypatch.setattr(orch, "safe_fetch", fake)
    monkeypatch.setattr(discovery_mod, "safe_fetch", fake)
    monkeypatch.setattr(robots_mod, "safe_fetch", fake)
    monkeypatch.setattr(orch, "PLAYWRIGHT_AVAILABLE", True)
    monkeypatch.setattr(orch, "_render_page", lambda url, timeout_ms: (pages.get(url, ""), None))


def test_english_dependent_checks_still_fire_for_english_page(monkeypatch):
    pages = _pages_with_lang("en")
    _patch_network(monkeypatch, pages)
    report = orch.run_audit(BASE, config=AuditConfig(max_pages=5, total_audit_timeout=30))
    assert any(f["id"] in ("EE-001", "EE-004") for f in report["findings"])
    assert not any(d["type"] == "language_unsupported" for d in report["audit_diagnostics"])


def test_english_dependent_checks_still_fire_for_unmarked_page(monkeypatch):
    """Missing lang must not become more restrictive -- current behavior
    (assume analyzable) is preserved exactly."""
    pages = _pages_with_lang(None)
    _patch_network(monkeypatch, pages)
    report = orch.run_audit(BASE, config=AuditConfig(max_pages=5, total_audit_timeout=30))
    assert any(f["id"] in ("EE-001", "EE-004") for f in report["findings"])
    assert not any(d["type"] == "language_unsupported" for d in report["audit_diagnostics"])


def test_unsupported_language_suppresses_english_dependent_checks(monkeypatch):
    pages = _pages_with_lang("de")
    _patch_network(monkeypatch, pages)
    report = orch.run_audit(BASE, config=AuditConfig(max_pages=5, total_audit_timeout=30))
    assert all(f["id"] not in ("EE-001", "EE-004") for f in report["findings"])


def test_unsupported_language_produces_diagnostic_not_finding(monkeypatch):
    pages = _pages_with_lang("de")
    _patch_network(monkeypatch, pages)
    report = orch.run_audit(BASE, config=AuditConfig(max_pages=5, total_audit_timeout=30))

    lang_diags = [d for d in report["audit_diagnostics"] if d["type"] == "language_unsupported"]
    assert len(lang_diags) >= 1
    assert all(f["id"] != "language_unsupported" for f in report["findings"])
    # Unsupported language must never itself be a website finding, and
    # must never fabricate a critical/high-severity claim.
    assert report["summary"]["critical"] == 0


def test_language_independent_checks_still_execute_on_unsupported_language(monkeypatch):
    """structured_data and non_text_accessibility (language-independent)
    must keep running even when English-dependent checks are skipped."""
    pages = _pages_with_lang("ja")
    _patch_network(monkeypatch, pages)
    report = orch.run_audit(BASE, config=AuditConfig(max_pages=5, total_audit_timeout=30))

    check_errors = {d.get("check") for d in report["audit_diagnostics"] if d["type"] == "check_error"}
    assert "check_structured_data" not in check_errors
    assert "check_non_text_accessibility" not in check_errors
    # TP-003 (missing expected structured data) is language-independent
    # and should still be able to fire.
    assert any(f["id"] == "TP-003" for f in report["findings"])


# --- P0-B: site-scope AI-003/AI-005 language-gating consistency -----------
#
# AI-003 (entity clarity) and AI-005 (proactive FAQ suggestion) are both
# site-scope semantic-analyzer checks, not part of the four per-page
# checks already covered above -- they were previously ungated, so an
# unsupported-language homepage/product page could still get an
# English-vocabulary-dependent finding/suggestion. Only the specific
# English-dependent signal in each is skipped; AI-001 (reachability,
# purely structural) is confirmed unaffected either way.
from skills_impl.semantic_analyzer.scripts.ai_discoverability import (
    check_ai_discoverability, check_proactive_recommendations,
)
from tests import fixtures as f

_WEAK_IDENTITY_INVENTORY = {
    "sitemap_found": False, "total_candidates": 1, "skipped_disallowed": [],
    "weak_internal_linking": True, "homepage_link_count": 1,
    "depth2_pages_explored": 1, "depth2_new_urls": 0,
}


def test_ai003_entity_clarity_fires_for_english_homepage():
    """1. English page -> AI-003 can run (default/explicit language_supported=True)."""
    findings = check_ai_discoverability(_WEAK_IDENTITY_INVENTORY, f.HOMEPAGE_THIN, "https://acme.example/", True)
    assert "AI-003" in [x["id"] for x in findings]


def test_ai003_entity_clarity_does_not_fire_for_french_homepage():
    """2. French page -> AI-003 must not produce an English-dependent finding."""
    findings = check_ai_discoverability(_WEAK_IDENTITY_INVENTORY, f.HOMEPAGE_THIN, "https://acme.example/", False)
    assert "AI-003" not in [x["id"] for x in findings]


def test_ai003_entity_clarity_does_not_fire_for_german_homepage():
    """3. Same as French, confirming this isn't a single-language special case."""
    findings = check_ai_discoverability(_WEAK_IDENTITY_INVENTORY, f.HOMEPAGE_THIN, "https://acme.example/", False)
    assert "AI-003" not in [x["id"] for x in findings]


def test_ai001_reachability_unaffected_by_unsupported_homepage_language():
    """4. Unsupported page still allows language-independent checks --
    AI-001 is purely structural and must keep firing even when AI-003
    is gated off for the same homepage."""
    findings = check_ai_discoverability(_WEAK_IDENTITY_INVENTORY, f.HOMEPAGE_THIN, "https://acme.example/", False)
    assert "AI-001" in [x["id"] for x in findings]


def test_ai003_default_parameter_preserves_existing_english_behavior():
    """5. Existing English behavior remains unchanged -- callers that
    don't pass the new parameter at all (e.g. any pre-existing direct
    caller) still get the original, unmodified True/on behavior."""
    findings = check_ai_discoverability(_WEAK_IDENTITY_INVENTORY, f.HOMEPAGE_THIN, "https://acme.example/")
    assert "AI-003" in [x["id"] for x in findings]


def test_site_scope_orchestrator_run_does_not_reintroduce_ai003_for_unsupported_language(monkeypatch):
    """6. Full pipeline: a French homepage with weak identity signals
    must not have AI-003 resurface anywhere in the final report --
    confirming merge_overlapping_findings/deduplicate/prioritize don't
    accidentally reintroduce a finding that was never produced."""
    homepage = '<html lang="fr"><body><h1>Bienvenue</h1><a href="/x">x</a></body></html>'
    pages = {BASE: homepage}
    _patch_network(monkeypatch, pages)
    report = orch.run_audit(BASE, config=AuditConfig(max_pages=5, total_audit_timeout=30))
    assert all(x["id"] != "AI-003" for x in report["findings"])


# --- AI-005 (proactive FAQ suggestion) language-gating ---------------------

def test_ai005_fires_normally_for_english_product_page_with_no_faq():
    pages = [{"url": "https://acme.example/p1", "html": "<html lang='en'><body>Product</body></html>"}]
    page_types = {"https://acme.example/p1": "product"}
    findings = check_proactive_recommendations(pages, page_types, {"https://acme.example/p1": True})
    assert any(x["id"] == "AI-005" for x in findings)


def test_ai005_suppressed_when_product_page_language_unsupported():
    """The English-only FAQ-heading/phrase suppression signal can't
    reliably prove a non-English product page has no embedded FAQ, so
    the whole proactive suggestion is skipped for that page rather than
    risking a false 'no FAQ found' claim."""
    pages = [{"url": "https://acme.example/p1", "html": "<html lang='de'><body>Produkt</body></html>"}]
    page_types = {"https://acme.example/p1": "product"}
    findings = check_proactive_recommendations(pages, page_types, {"https://acme.example/p1": False})
    assert findings == []


def test_ai005_unaffected_when_language_map_not_provided():
    """Backward compatibility: existing callers that don't pass
    page_language_supported at all (e.g. any pre-existing direct
    caller/test) keep the original, unmodified behavior."""
    pages = [{"url": "https://acme.example/p1", "html": "<html lang='en'><body>Product</body></html>"}]
    page_types = {"https://acme.example/p1": "product"}
    findings = check_proactive_recommendations(pages, page_types)
    assert any(x["id"] == "AI-005" for x in findings)
