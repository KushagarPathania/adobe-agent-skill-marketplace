"""Regression tests for a targeted calibration fix found via live testing
against https://www.shopify.com:

1. SA-001 could report `severity: "high"` merged across pages while
   `suggested_action.priority` stayed "low" -- an internally
   contradictory report. Root cause: `aggregate.py`'s `_merge_group()`
   escalates severity to the worst instance across pages, but blindly
   copied `suggested_action` from whichever instance happened to be
   first in iteration order, which need not be the instance that
   actually had that severity. Also: SA-001's own "examples" evidence
   (`non_text_accessibility.py`) could show only decorative-looking
   suspects even when severity was escalated by a DIFFERENT, unshown
   suspect elsewhere on the page -- evidence that doesn't substantiate
   the claim.
2. Shopify (a payments/ecommerce SaaS company) was classified
   `site_type: "hospitality"`. Root cause: `_HOSPITALITY_RE`'s
   `check-?out` alternative made the hyphen optional, so it matched the
   bare, unhyphenated word "checkout" -- a near-ubiquitous ecommerce/
   payments term ("Shopify Checkout", "proceed to checkout"), not a
   hospitality signal at all. Fixed by requiring an actual separator
   (hyphen or space) between "check" and "out".
"""
from skills_impl.audit_orchestrator.scripts.aggregate import deduplicate
from skills_impl.common.schema import make_finding
from skills_impl.semantic_analyzer.scripts.non_text_accessibility import check_non_text_accessibility
from skills_impl.page_classifier.scripts.classifier import classify_site, _HOSPITALITY_RE, _seen_at_least_twice


# --- Part 1/2: aggregate.py severity/priority consistency ---------------

def _sa001_instance(url, severity, confidence, priority):
    return make_finding(
        check_id="SA-001",
        title="Potentially factual non-text content lacks accessible text",
        severity=severity,
        evidence={"summary": "1 isolated graphic(s) have no text equivalent...", "url": url},
        action_summary="Provide machine-readable text equivalents...",
        action_priority=priority,
        confidence=confidence,
    )


def test_merged_finding_priority_tracks_the_escalated_severity():
    """The real bug: 3 low-severity page instances (from pages iterated
    first) plus 1 high-severity instance must merge to severity="high"
    WITH suggested_action.priority="high" -- not the low-severity
    priority left over from an earlier instance in the list."""
    instances = [
        _sa001_instance("https://shop.example/1", "low", 0.5, "low"),
        _sa001_instance("https://shop.example/2", "low", 0.5, "low"),
        _sa001_instance("https://shop.example/3", "low", 0.5, "low"),
        _sa001_instance("https://shop.example/4", "high", 0.75, "high"),
    ]
    result = deduplicate(instances)
    assert len(result) == 1
    merged = result[0]
    assert merged["severity"] == "high"
    assert merged["confidence"] == 0.75
    assert merged["suggested_action"]["priority"] == "high"


def test_merged_representative_evidence_includes_the_escalating_instance():
    """Live-confirmed extension of the same fix (Shopify SA-001): when 3
    low-severity pages come first in iteration order and a 4th page is
    what actually escalates severity to "high", the merged finding's
    `representative_evidence` (up to 3 shown samples) must include that
    4th, actually-high instance -- not only the 3 low-severity ones that
    happened to be discovered first."""
    instances = [
        _sa001_instance("https://shop.example/1", "low", 0.5, "low"),
        _sa001_instance("https://shop.example/2", "low", 0.5, "low"),
        _sa001_instance("https://shop.example/3", "low", 0.5, "low"),
        _sa001_instance("https://shop.example/4-the-real-evidence", "high", 0.75, "high"),
    ]
    result = deduplicate(instances)
    merged = result[0]
    shown_urls = [e.get("url") for e in merged["evidence"]["representative_evidence"]]
    assert "https://shop.example/4-the-real-evidence" in shown_urls
    # affected_pages (the full list, unlike the up-to-3 samples) must
    # still include everything, in original discovery order.
    assert merged["evidence"]["affected_pages"] == [
        "https://shop.example/1", "https://shop.example/2",
        "https://shop.example/3", "https://shop.example/4-the-real-evidence",
    ]


def test_merged_finding_stays_low_when_no_instance_is_worse():
    """Non-regression: when every instance genuinely agrees on "low",
    the merge must not invent an escalation."""
    instances = [
        _sa001_instance("https://shop.example/1", "low", 0.5, "low"),
        _sa001_instance("https://shop.example/2", "low", 0.5, "low"),
    ]
    result = deduplicate(instances)
    assert len(result) == 1
    assert result[0]["severity"] == "low"
    assert result[0]["suggested_action"]["priority"] == "low"


def test_severity_does_not_escalate_solely_from_page_count():
    """Many low-severity pages must still merge to "low" -- escalation
    must come from actual evidence (an instance that IS high), never
    merely from how many pages a check fired on."""
    instances = [_sa001_instance(f"https://shop.example/{i}", "low", 0.5, "low") for i in range(6)]
    result = deduplicate(instances)
    assert len(result) == 1
    assert result[0]["severity"] == "low"
    assert len(result[0]["evidence"]["affected_pages"]) == 6


# --- Part 1/2: non_text_accessibility.py evidence + severity -----------

def test_isolated_decorative_svg_stays_low_not_high():
    """An isolated icon/decorative SVG with no nearby factual heading
    must not become HIGH merely because it exists."""
    html = "<html><body><div><svg><path d='M0 0'/></svg></div></body></html>"
    findings = check_non_text_accessibility(html, "https://acme.example/")
    assert len(findings) == 1
    assert findings[0]["severity"] == "low"
    assert findings[0]["suggested_action"]["priority"] == "low"


def test_factual_graphic_with_no_text_equivalent_is_elevated():
    """A graphic that's the sole content under a genuinely factual
    heading (pricing/spec/data) is appropriately HIGH -- the escalation
    itself is not weakened by this fix."""
    html = """<html><body>
    <h2>Pricing</h2>
    <div><svg><path d="M0 0"/></svg></div>
    </body></html>"""
    findings = check_non_text_accessibility(html, "https://acme.example/pricing")
    assert len(findings) == 1
    assert findings[0]["severity"] == "high"
    assert findings[0]["suggested_action"]["priority"] == "high"


def test_examples_surface_the_important_suspect_when_severity_is_high():
    """Evidence-discipline fix: when severity is escalated because SOME
    suspect is important, the shown examples must include at least one
    important suspect -- not only decorative-looking ones that don't
    substantiate the "high" claim (the exact Shopify symptom: examples
    showed FAQ-style headings that don't match any factual keyword)."""
    html = """<html><body>
    <div><svg><path d="M0 0"/></svg></div>
    <div><svg><path d="M0 0"/></svg></div>
    <h2>Specification</h2>
    <div><svg><path d="M0 0"/></svg></div>
    </body></html>"""
    findings = check_non_text_accessibility(html, "https://acme.example/specs")
    assert len(findings) == 1
    assert findings[0]["severity"] == "high"
    examples = findings[0]["evidence"]["examples"]
    assert any("Specification" in e for e in examples)


def test_existing_false_positive_defenses_remain_intact():
    """Decorative empty-alt images, aria-hidden, and icon buttons
    labelled via their interactive wrapper must all remain unflagged."""
    html = """<html><body>
    <img src="deco.png" alt="">
    <svg aria-hidden="true"><path d="M0 0"/></svg>
    <button aria-label="Search"><svg><path d="M0 0"/></svg></button>
    </body></html>"""
    assert check_non_text_accessibility(html, "https://acme.example/") == []


# --- Part 3: site-type classifier hospitality fix ------------------------

_CHECKOUT_HEAVY_SAAS_HOMEPAGE = """
Our platform makes checkout fast and secure. Millions of merchants trust our
checkout for their online stores. Complete checkout in seconds with our
optimized checkout flow. Try our checkout free for 14 days with a free trial
subscription. Integrate with our API key and start selling online today.
"""

_GENUINE_HOTEL_HOMEPAGE = """
Book now for your next stay. Reservation confirmed instantly. Check-out time
is 11am; please check out by then. Enjoy our nightly rate discounts for
extended stays. Reservation changes are free up to 24 hours before check-in.
"""

_UNRELATED_INCIDENTAL_WORDS_HOMEPAGE = """
Our engineering team ships fast. We recently ran a company retreat at a
beautiful hotel near the mountains, and everyone had a great travel
experience. Our product experience team focuses on customer experience above
all else. Book a demo with our sales team today.
"""


def test_checkout_heavy_ecommerce_saas_site_not_classified_hospitality():
    page_classifications = [{"page_type": "pricing"}, {"page_type": "homepage"}]
    result = classify_site("https://shop-like-saas.example/", page_classifications, _CHECKOUT_HEAVY_SAAS_HOMEPAGE)
    assert result["site_type"] != "hospitality"


def test_bare_checkout_word_no_longer_matches_hospitality_regex():
    assert _seen_at_least_twice(_HOSPITALITY_RE, _CHECKOUT_HEAVY_SAAS_HOMEPAGE.lower()) is False


def test_genuine_hotel_site_still_classifies_as_hospitality():
    page_classifications = [{"page_type": "homepage"}]
    result = classify_site("https://genuine-hotel.example/", page_classifications, _GENUINE_HOTEL_HOMEPAGE)
    assert result["site_type"] == "hospitality"


def test_incidental_hospitality_adjacent_words_do_not_trigger_hospitality():
    """"hotel", "travel", "experience" used in unrelated (non-booking)
    context must not cause a false hospitality classification -- none of
    these words are even in the hospitality regex, but this locks in
    that an ordinary corporate/SaaS page mentioning them casually is
    unaffected."""
    page_classifications = [{"page_type": "homepage"}]
    result = classify_site("https://normal-saas.example/", page_classifications, _UNRELATED_INCIDENTAL_WORDS_HOMEPAGE)
    assert result["site_type"] != "hospitality"


def test_existing_ecommerce_classification_remains_stable():
    page_classifications = [{"page_type": "product"}, {"page_type": "product"}, {"page_type": "category"}]
    homepage = "<html><body><h1>Shop</h1><p>Add to cart. In stock. $49.99.</p></body></html>"
    result = classify_site("https://acme-shop.example/", page_classifications, homepage)
    assert result["site_type"] == "ecommerce"


# --- Real-world regression-suite finding: merged (multi-page) findings
# lost check-specific evidence fields (TP-001's substantive_missing_count/
# ui_chrome_missing_count/overlap_ratio, TP-005's schema_price/
# visible_price_candidates, ...) at the top level, even though the exact
# same data was still present one level deeper inside
# representative_evidence[0]. Confirmed live via the Allbirds/GitHub/
# Shopify/docs.python.org 5-site regression run: every merged TP-001
# finding showed substantive_missing_count/ui_chrome_missing_count as
# None at the top level. Fixed generically in `_merge_group()` (not a
# TP-001-specific rule) by carrying forward any check-specific evidence
# key from the representative instance that isn't already set. -------

def _tp001_instance(url, severity, confidence, substantive, ui_chrome, overlap):
    return make_finding(
        check_id="TP-001",
        title="Substantive content requires JavaScript rendering",
        severity=severity,
        evidence={
            "summary": "...", "url": url,
            "substantive_missing_count": substantive,
            "ui_chrome_missing_count": ui_chrome,
            "overlap_ratio": overlap,
        },
        action_summary="...",
        confidence=confidence,
    )


def test_merged_finding_top_level_evidence_carries_forward_check_specific_fields():
    instances = [
        _tp001_instance("https://acme.example/1", "low", 0.4, 0, 6, 0.9),
        _tp001_instance("https://acme.example/2", "high", 0.85, 12, 3, 0.3),
    ]
    result = deduplicate(instances)
    assert len(result) == 1
    merged_evidence = result[0]["evidence"]
    # Must reflect the escalating (worst-severity, "high") instance's
    # own counts -- not be missing/None, and not the low-severity page's.
    assert merged_evidence["substantive_missing_count"] == 12
    assert merged_evidence["ui_chrome_missing_count"] == 3
    assert merged_evidence["overlap_ratio"] == 0.3
    # The generic merge fields must still be present and unaffected.
    assert merged_evidence["affected_pages"] == ["https://acme.example/1", "https://acme.example/2"]
    assert len(merged_evidence["representative_evidence"]) == 2
