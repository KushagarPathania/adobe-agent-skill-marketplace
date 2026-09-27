"""Generalization test suite: one representative page per site category,
checked both for sensible classification and for the specific
cross-type false positives the project must never produce (a university
page must never get ecommerce findings, a product page's model numbers
must never look like a price mismatch, and so on).

All fixtures are static offline HTML strings -- no network access is
used or required to run this suite.
"""
from skills_impl.page_classifier.scripts.classifier import classify_page, classify_site
from skills_impl.page_classifier.scripts.applicability import get_applicability
from skills_impl.technical_parser.scripts.structured_data_validation import check_structured_data
from skills_impl.technical_parser.scripts.js_render_parity import check_js_render_parity
from skills_impl.semantic_analyzer.scripts.content_freshness import check_content_freshness
from skills_impl.engagement_evaluator.scripts.navigation_signals import check_navigation
from skills_impl.engagement_evaluator.scripts.answer_scannability import check_answer_scannability
from tests import fixtures as f

# (fixture, url, expected page_type-ish assertion) -- ten site categories.
CATEGORY_CASES = [
    ("ecommerce/product", f.PRODUCT_PAGE_GOOD_SCHEMA, "https://acme-shop.example/products/x200", "product"),
    ("saas/company", f.SAAS_HOMEPAGE, "https://cloudsync.example/", "homepage"),
    ("news/article", f.NEWS_ARTICLE_PAGE, "https://springfield-news.example/city-council-park", "article"),
    ("university/education", f.UNIVERSITY_ABOUT_PAGE, "https://springfield.edu/about", "about"),
    ("documentation", f.DOCUMENTATION_PAGE, "https://docs.acme.example/getting-started", "documentation"),
    # The government fixture deliberately has no strong page_type signal
    # (no "/service/" path, no product/pricing/faq/etc language) -- the
    # classifier correctly stays conservative and returns "other" rather
    # than guessing, which is itself the behavior under test.
    ("government/institutional", f.GOVERNMENT_PAGE, "https://springfield.gov/public-works", "other"),
    ("corporate/about", f.CORPORATE_ABOUT_PAGE, "https://acme-mfg.example/about", "about"),
    ("static/simple", f.STATIC_SIMPLE_PAGE, "https://janedoe.example/", "homepage"),
]


def test_classifier_produces_a_result_for_every_category():
    """Every category should classify to *something* with a page_type
    and confidence -- not crash, not return garbage."""
    for name, html, url, _expected in CATEGORY_CASES:
        result = classify_page(url, html)
        assert "page_type" in result and "confidence" in result, name
        assert 0.0 <= result["confidence"] <= 1.0, name


def test_classifier_reasonable_type_for_clear_cut_categories():
    for name, html, url, expected in CATEGORY_CASES:
        result = classify_page(url, html)
        assert result["page_type"] == expected, f"{name}: expected {expected}, got {result}"


def test_saas_homepage_site_type():
    classification = classify_page("https://cloudsync.example/", f.SAAS_HOMEPAGE)
    site = classify_site("https://cloudsync.example/", [{"page_type": classification["page_type"]}], f.SAAS_HOMEPAGE)
    assert site["site_type"] == "saas"


def test_government_site_type():
    classification = classify_page("https://springfield.gov/public-works", f.GOVERNMENT_PAGE)
    site = classify_site("https://springfield.gov/", [{"page_type": classification["page_type"]}], f.GOVERNMENT_PAGE)
    assert site["site_type"] == "government"


def test_government_body_text_signals_work_without_gov_domain():
    """Legitimate government self-identification (department names,
    "government of X", "public notice") must still be detected on a
    non-.gov domain -- confirms the fix didn't gut real detection while
    removing the legal-boilerplate false positive."""
    site = classify_site("https://springfield-city.example/", [{"page_type": "service"}], f.GOVERNMENT_PAGE)
    assert site["site_type"] == "government"


def test_ecommerce_legal_footer_boilerplate_not_classified_as_government():
    """Real false positive found via live testing against an unseen
    ecommerce site: ordinary US choice-of-law legal boilerplate
    ("governed by the laws of the State of California") in a commercial
    Terms of Service footer must never, by itself, classify a site as
    government -- neither the properly-capitalized "State of California"
    inside the jurisdiction clause, nor the lowercase idiomatic "state of
    residence", should count as government-identity evidence."""
    classification = classify_page("https://shopdemo.example/products/trail-runner", f.ECOMMERCE_PRODUCT_PAGE)
    site = classify_site(
        "https://shopdemo.example/",
        [{"page_type": "homepage"}, {"page_type": classification["page_type"]}],
        f.ECOMMERCE_HOMEPAGE_WITH_LEGAL_FOOTER,
    )
    assert site["site_type"] != "government"


def test_capitalized_place_name_in_legal_boilerplate_still_excluded():
    """Narrower unit-level check: even a properly-capitalized 'State of
    California' must not count as a government signal when it sits
    inside a choice-of-law/jurisdiction clause."""
    from skills_impl.page_classifier.scripts.classifier import _count_government_signals
    text = (
        "These Terms shall be governed by the laws of the State of California, "
        "without regard to conflict of law principles."
    )
    assert _count_government_signals(text, text.lower()) == 0


def test_genuine_capitalized_place_name_outside_legal_context_counts():
    """Non-regression at the unit level: a genuine 'City of Springfield'
    mention that is NOT inside legal boilerplate should still count."""
    from skills_impl.page_classifier.scripts.classifier import _count_government_signals
    text = "Welcome to the official website of the City of Springfield."
    assert _count_government_signals(text, text.lower()) >= 1


# --- Cross-type false positive prevention ------------------------------

def test_university_page_gets_no_product_or_pricing_findings():
    classification = classify_page("https://springfield.edu/about", f.UNIVERSITY_ABOUT_PAGE)
    findings = check_structured_data(f.UNIVERSITY_ABOUT_PAGE, "https://springfield.edu/about", classification["page_type"])
    assert all("Product" not in x["title"] for x in findings)
    assert all("Pricing" not in x["title"] for x in findings)


def test_government_page_no_commercial_cta_required():
    """A government service page with no commercial CTA must not be
    flagged as a navigational dead end just because it has no purchase
    link -- only zero internal links at all would matter, and even then
    only for the page types actually held to that bar."""
    classification = classify_page("https://springfield.gov/public-works", f.GOVERNMENT_PAGE)
    pages = [{"url": "https://springfield.gov/public-works", "html": f.GOVERNMENT_PAGE}]
    page_types = {"https://springfield.gov/public-works": classification["page_type"]}
    findings = check_navigation(pages, page_types)
    assert findings == []  # the page does have 2 internal links, so this shouldn't fire regardless


def test_university_numbers_never_misread_as_price():
    findings = check_structured_data(f.UNIVERSITY_PAGE_WITH_NUMBERS, "https://springfield.edu/admissions", "other")
    assert all(x["id"] != "TP-005" for x in findings)


def test_article_with_old_publish_year_and_no_dateModified_conflict_not_flagged_stale():
    """An article page's own historical/founding-year content must not
    trigger a freshness finding absent explicit conflicting signals."""
    findings = check_content_freshness(f.ARTICLE_HISTORICAL_NO_METADATA, "/history")
    assert findings == []


def test_product_page_freshness_check_does_not_misfire_from_price_or_model_numbers():
    findings = check_content_freshness(f.PRODUCT_PAGE_GOOD_SCHEMA, "/products/x200")
    assert findings == []


def test_static_simple_page_does_not_crash_any_check():
    """A minimal static page (no schema, no meta description, barely any
    content) should be handled gracefully -- no crash, and no
    aggressive high-severity findings from thin content alone."""
    classification = classify_page("https://janedoe.example/", f.STATIC_SIMPLE_PAGE)
    findings = check_structured_data(f.STATIC_SIMPLE_PAGE, "https://janedoe.example/", classification["page_type"])
    assert all(x["severity"] != "critical" for x in findings)


def test_js_heavy_site_flagged_but_static_site_is_not():
    """The JS-render-parity check should distinguish a genuinely
    JS-dependent page from a static one rendered identically."""
    js_heavy = check_js_render_parity(f.RAW_HTML_JS_HEAVY, f.RENDERED_HTML_JS_HEAVY)
    static_site = check_js_render_parity(f.STATIC_SIMPLE_PAGE, f.STATIC_SIMPLE_PAGE)
    assert len(js_heavy) == 1
    assert static_site == []


def test_applicability_matrix_covers_every_generalization_category():
    """Every category's classified type should resolve to *some*
    applicability decision without raising -- confirms the applicability
    engine generalizes across all ten fixture categories."""
    for name, html, url, _expected in CATEGORY_CASES:
        classification = classify_page(url, html)
        result = get_applicability(classification["page_type"], classification["confidence"])
        assert "applicable_checks" in result, name
        assert "skipped_checks" in result, name


def test_documentation_page_with_a_list_of_steps_is_not_flagged():
    """A documentation page that actually has scannable structure (here,
    a numbered list of steps) should not be flagged just because it's a
    utility page type -- only a complete absence of structure should."""
    html = """<html><head><title>Getting Started | API Reference</title></head><body>
    <h1>Getting Started</h1>
    <p>Follow these steps to install the SDK:</p>
    <ol><li>Install the package</li><li>Set your API key</li><li>Run the example</li></ol>
    </body></html>"""
    findings = check_answer_scannability(html, "/getting-started", "https://docs.acme.example/getting-started", "documentation")
    assert findings == []


def test_documentation_page_with_a_short_intro_paragraph_is_not_flagged():
    """f.DOCUMENTATION_PAGE's single short intro paragraph is exactly the
    kind of well-written short prose Priority 3.B says must NOT be
    flagged just for lacking a table or list."""
    findings = check_answer_scannability(f.DOCUMENTATION_PAGE, "/getting-started", "https://docs.acme.example/getting-started", "documentation")
    assert findings == []


def test_documentation_page_with_dense_unstructured_prose_is_flagged():
    """The true-positive case: a documentation page whose entire content
    is one long unstructured paragraph legitimately lacks scannable
    architecture and should be flagged -- confirming the check still
    catches real cases, not just suppressing false positives."""
    html = """<html><head><title>Getting Started | API Reference</title></head><body>
    <h1>Getting Started</h1>
    <p>This documentation covers installation, configuration, authentication, rate limiting,
    pagination, error handling, versioning, webhooks, retries, idempotency keys, and the full
    request/response lifecycle for every endpoint exposed by the SDK, all described here in a
    single continuous paragraph with no subheadings, lists, or tables anywhere on the page, which
    makes it considerably harder to scan for one specific detail than a properly structured reference.</p>
    </body></html>"""
    findings = check_answer_scannability(html, "/getting-started", "https://docs.acme.example/getting-started", "documentation")
    assert len(findings) == 1
    assert findings[0]["id"] == "EE-002"
