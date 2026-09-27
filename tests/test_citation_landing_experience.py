from skills_impl.engagement_evaluator.scripts.citation_landing_experience import (
    assess_landing_experience, check_citation_landing_experience, STRONG, WEAK, NOT_APPLICABLE,
)

GOOD_PRODUCT_PAGE = """
<html><head><title>RoboArm X200 - Acme Robotics</title></head><body>
<h1>RoboArm X200</h1>
<p>The RoboArm X200 is our flagship industrial arm, priced at $12,499.00.</p>
<a href="/products">Back to Products</a>
<a href="/support">Support</a>
</body></html>
"""

BAD_DEEP_PAGE = """
<html><head><title>Overview</title></head><body>
<h1>Overview</h1>
<p>Some content with no structure at all describing pricing information in dense prose only.</p>
</body></html>
"""


def test_homepage_orientation_always_strong():
    assessment = assess_landing_experience("<html><body><h1>X</h1></body></html>", "/", "https://acme.example/", "homepage")
    assert assessment["orientation"] == STRONG


def test_good_product_page_scores_strong_overall():
    assessment = assess_landing_experience(GOOD_PRODUCT_PAGE, "/products/x200", "https://acme.example/products/x200", "product")
    assert assessment["overall"] in (STRONG, "adequate")
    assert assessment["continuation"] == STRONG


def test_article_continuation_is_not_applicable_not_weak():
    """Reference articles are not held to a 'needs a next step' bar --
    this must show as insufficient_evidence, not weak."""
    html = "<html><head><title>History - Acme</title></head><body><h1>History</h1><p>Some text.</p></body></html>"
    assessment = assess_landing_experience(html, "/blog/history", "https://acme.example/blog/history", "article")
    assert assessment["continuation"] == NOT_APPLICABLE


def test_weak_orientation_and_weak_scannability_together_produce_finding():
    findings = check_citation_landing_experience(
        BAD_DEEP_PAGE, "/pricing/overview", "https://acme.example/pricing/overview", "pricing"
    )
    # Orientation is weak (generic H1 "Overview", no breadcrumb, no brand
    # in title), answer visibility is weak (utility page, plain prose, no
    # structure), and continuation is weak (no links at all) -- multiple
    # weak dimensions together should produce the compounded EE-004.
    assert len(findings) == 1
    assert findings[0]["id"] == "EE-004"
    assert findings[0]["severity"] == "medium"


def test_single_weak_dimension_alone_does_not_produce_capstone_finding():
    """Only orientation is weak here (generic H1); answer visibility and
    continuation aren't both also weak, so EE-004 should not fire --
    that's covered by EE-001 alone, not a compounded landing-experience
    finding."""
    html = "<html><head><title>Overview</title></head><body><h1>Overview</h1><a href='/next'>Next</a></body></html>"
    findings = check_citation_landing_experience(html, "/products/x/overview", "https://acme.example/products/x/overview", "product")
    assert findings == []


def test_homepage_never_produces_capstone_finding_from_missing_breadcrumbs():
    findings = check_citation_landing_experience("<html><body><h1>Acme</h1></body></html>", "/", "https://acme.example/", "homepage")
    assert findings == []
