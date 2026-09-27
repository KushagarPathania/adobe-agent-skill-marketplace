"""Regression tests for aggregate.py's two dedup mechanisms: the
existing same-check/multi-page merge, and this phase's new
cross-check/same-page overlap merge (Priority 5)."""
import pytest

from skills_impl.audit_orchestrator.scripts.aggregate import (
    deduplicate, merge_overlapping_findings, validate_unique_finding_ids, DuplicateFindingIDError,
)
from skills_impl.common.schema import make_finding


def _finding(check_id, title, url, **kwargs):
    return make_finding(
        check_id=check_id, title=title, severity=kwargs.pop("severity", "medium"),
        evidence={"summary": kwargs.pop("summary", "evidence"), "url": url},
        action_summary="do something", **kwargs,
    )


def test_same_check_across_pages_still_merges_to_site_scope():
    """Existing behavior (same id+title, multiple pages) must be
    unaffected by the new overlap-merge step."""
    findings = [
        _finding("TP-003", "Product structured representation not detected on a product page", "https://a.example/1"),
        _finding("TP-003", "Product structured representation not detected on a product page", "https://a.example/2"),
    ]
    result = deduplicate(findings)
    assert len(result) == 1
    assert result[0]["scope"] == "site"
    assert len(result[0]["evidence"]["affected_pages"]) == 2


def test_entity_clarity_and_schema_gap_on_same_page_are_merged():
    """Priority 5: AI-003 (entity identity unclear) and a same-page
    TP-006 citing Organization/WebSite schema specifically describe the
    same underlying problem and must collapse into one finding."""
    findings = [
        _finding("AI-003", "Entity identity is not clearly machine-readable", "https://acme.example/",
                 summary="Only 1 of 7 entity-clarity signals present."),
        _finding("TP-006", "Organization structured representation not detected on a homepage page", "https://acme.example/",
                 summary="No Organization/WebSite JSON-LD found."),
    ]
    result = merge_overlapping_findings(findings)
    assert len(result) == 1
    assert result[0]["id"] == "AI-003"
    assert "Organization" in result[0]["evidence"]["summary"] or "JSON-LD" in result[0]["evidence"]["summary"]
    assert result[0]["evidence"]["absorbed_findings"] == ["TP-006"]


def test_schema_gap_on_a_different_page_is_not_merged():
    """The merge is page-scoped -- a TP-006 on a DIFFERENT page than the
    AI-003 finding must not be absorbed; it's not evidence for that
    specific page's identity problem."""
    findings = [
        _finding("AI-003", "Entity identity is not clearly machine-readable", "https://acme.example/"),
        _finding("TP-006", "Organization structured representation not detected on a homepage page", "https://acme.example/other-page"),
    ]
    result = merge_overlapping_findings(findings)
    assert len(result) == 2


def test_unrelated_schema_gap_is_not_merged():
    """A TP-003 about Product schema (a different, stable id -- not
    Organization/WebSite's TP-006) on the same page as AI-003 is a
    genuinely distinct issue and must NOT be absorbed -- only the
    name-checked Organization/WebSite pair merges."""
    findings = [
        _finding("AI-003", "Entity identity is not clearly machine-readable", "https://acme.example/"),
        _finding("TP-003", "Product structured representation not detected on a product page", "https://acme.example/"),
    ]
    result = merge_overlapping_findings(findings)
    assert len(result) == 2


def test_citation_landing_capstone_absorbs_its_own_page_singles():
    """Priority 5: EE-004 (weak citation landing experience) already
    restates whichever of EE-001/002/003 contributed to it on that same
    page -- those must be absorbed rather than shown twice."""
    findings = [
        _finding("EE-001", "Poor deep-page orientation context", "https://acme.example/pricing"),
        _finding("EE-002", "Factual answers buried in unstructured prose", "https://acme.example/pricing"),
        _finding("EE-004", "Weak citation landing experience", "https://acme.example/pricing"),
    ]
    result = merge_overlapping_findings(findings)
    assert len(result) == 1
    assert result[0]["id"] == "EE-004"
    assert set(result[0]["evidence"]["absorbed_findings"]) == {"EE-001", "EE-002"}


def test_ee004_on_different_page_does_not_absorb_other_pages_singles():
    findings = [
        _finding("EE-001", "Poor deep-page orientation context", "https://acme.example/other"),
        _finding("EE-004", "Weak citation landing experience", "https://acme.example/pricing"),
    ]
    result = merge_overlapping_findings(findings)
    assert len(result) == 2


def test_evidence_is_preserved_not_discarded_on_merge():
    """The merge must fold in evidence, not just drop the absorbed
    finding silently."""
    findings = [
        _finding("AI-003", "Entity identity is not clearly machine-readable", "https://acme.example/",
                 summary="Only 1 of 7 signals present."),
        _finding("TP-006", "Organization structured representation not detected on a homepage page", "https://acme.example/",
                 summary="Specifically: no Organization/WebSite JSON-LD was found on this page."),
    ]
    result = merge_overlapping_findings(findings)
    assert "Only 1 of 7 signals present" in result[0]["evidence"]["summary"]
    assert "no Organization/WebSite JSON-LD" in result[0]["evidence"]["summary"]


def test_distinct_unrelated_findings_are_never_merged():
    """Sanity check: findings that share nothing in particular must
    never be collapsed by either dedup mechanism."""
    findings = [
        _finding("TP-002", "Malformed JSON-LD structured data", "https://acme.example/a"),
        _finding("SA-001", "Potentially factual non-text content lacks accessible text", "https://acme.example/b"),
    ]
    assert merge_overlapping_findings(findings) == findings
    assert deduplicate(findings) == findings


# --- CRITICAL FIX: finding-id uniqueness ---------------------------------
#
# Real bug: every "missing expected schema" semantic in
# structured_data_validation.py shared the single id "TP-003" regardless
# of which schema family was missing (Product/Organization/FAQPage/
# Article/Event/Service), and because the finding's title embeds the
# page_type name ("...on a product page" vs. "...on a pricing page"),
# `deduplicate()`'s old (id, title) grouping key never merged two
# same-schema-family gaps found on differently-typed pages -- both
# survived aggregation under the same id.

def test_deduplicate_groups_by_id_alone_even_when_title_differs_by_page_type():
    """Two 'Product schema missing' findings with DIFFERENT titles
    (because the page_type name is embedded in each) must still merge
    into one site-scope finding -- they're the same check semantic."""
    findings = [
        _finding("TP-003", "Product structured representation not detected on a product page", "https://a.example/1"),
        _finding("TP-003", "Product structured representation not detected on a pricing page", "https://a.example/2"),
    ]
    result = deduplicate(findings)
    assert len(result) == 1
    assert result[0]["scope"] == "site"
    assert len(result[0]["evidence"]["affected_pages"]) == 2


def test_validate_unique_finding_ids_passes_on_a_clean_report():
    findings = [
        _finding("TP-002", "Malformed JSON-LD structured data", "https://acme.example/a"),
        _finding("TP-003", "Product structured representation not detected on a product page", "https://acme.example/b"),
        _finding("TP-006", "Organization structured representation not detected on a homepage page", "https://acme.example/c"),
    ]
    assert validate_unique_finding_ids(findings) == findings


def test_validate_unique_finding_ids_raises_on_a_genuine_duplicate():
    """Fail loudly (never silently rename/drop) when two distinct
    findings somehow reach the final list sharing an id -- this is what
    would have caught the original TP-003 bug before it ever reached a
    report."""
    findings = [
        _finding("TP-003", "Product structured representation not detected on a product page", "https://acme.example/a"),
        _finding("TP-003", "Something else entirely with an accidentally-reused id", "https://acme.example/a", severity="high"),
    ]
    with pytest.raises(DuplicateFindingIDError):
        validate_unique_finding_ids(findings)
