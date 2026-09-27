from skills_impl.semantic_analyzer.scripts.non_text_accessibility import check_non_text_accessibility
from skills_impl.semantic_analyzer.scripts.content_freshness import check_content_freshness
from skills_impl.semantic_analyzer.scripts.entity_consistency import check_entity_consistency
from skills_impl.semantic_analyzer.scripts.ai_discoverability import check_ai_discoverability, check_proactive_recommendations
from tests import fixtures as f


def test_decorative_empty_alt_image_not_flagged():
    findings = check_non_text_accessibility(f.DECORATIVE_IMAGE_PAGE, "https://acme.example/")
    assert findings == []


def test_important_info_in_image_flagged_high_severity():
    findings = check_non_text_accessibility(f.IMPORTANT_INFO_IN_IMAGE_PAGE, "https://acme.example/pricing")
    assert len(findings) == 1
    assert findings[0]["severity"] == "high"


def test_isolated_decorative_looking_image_flagged_low_not_high():
    findings = check_non_text_accessibility(f.NON_IMPORTANT_ISOLATED_IMAGE_PAGE, "https://acme.example/")
    assert len(findings) == 1
    assert findings[0]["severity"] == "low"


def test_founding_year_alone_never_flagged_stale():
    """Direct false-positive-prevention case from the brief: 'Founded in
    1998' must never be interpreted as a staleness signal."""
    findings = check_content_freshness(f.ARTICLE_HISTORICAL_NO_METADATA, "/history")
    assert findings == []


def test_founding_year_with_metadata_present_still_not_flagged():
    findings = check_content_freshness(f.ARTICLE_HISTORICAL_WITH_METADATA, "/about")
    assert findings == []


def test_explicit_current_year_claim_older_than_modified_date_is_flagged():
    findings = check_content_freshness(f.STALE_CURRENT_CLAIM_PAGE, "/pricing")
    ids = [x["id"] for x in findings]
    assert "SA-003" in ids


def test_conflicting_visible_and_metadata_dates_flagged():
    findings = check_content_freshness(f.FRESHNESS_CONFLICT_PAGE, "/docs")
    ids = [x["id"] for x in findings]
    assert "SA-002" in ids


def test_archival_urls_are_exempt_from_freshness_checks():
    findings = check_content_freshness(f.STALE_CURRENT_CLAIM_PAGE, "/blog/2020/old-post")
    assert findings == []


def test_entity_consistency_ignores_legal_suffix_variation():
    pages = [
        {"url": "https://acme.example/", "html": f.ENTITY_HOMEPAGE_ACME},
        {"url": "https://acme.example/about", "html": f.ENTITY_ABOUT_ACME_SUFFIX_ONLY},
    ]
    assert check_entity_consistency(pages) == []


def test_entity_consistency_flags_genuinely_different_names():
    pages = [
        {"url": "https://acme.example/", "html": f.ENTITY_HOMEPAGE_ACME},
        {"url": "https://acme.example/about", "html": f.ENTITY_ABOUT_DIFFERENT_NAME},
    ]
    findings = check_entity_consistency(pages)
    assert len(findings) == 1
    assert findings[0]["scope"] == "site"


def test_entity_consistency_requires_at_least_two_names():
    pages = [{"url": "https://acme.example/", "html": f.ENTITY_HOMEPAGE_ACME}]
    assert check_entity_consistency(pages) == []


def test_entity_consistency_confidence_scales_with_majority_gap():
    """Priority 2 calibration: a lone disagreeing mention against a large
    consistent majority is stronger evidence than a near-even split."""
    lopsided_pages = [
        {"url": "https://acme.example/", "html": f.ENTITY_HOMEPAGE_ACME},
        {"url": "https://acme.example/about", "html": f.ENTITY_HOMEPAGE_ACME},
        {"url": "https://acme.example/contact", "html": f.ENTITY_HOMEPAGE_ACME},
        {"url": "https://acme.example/careers", "html": f.ENTITY_ABOUT_DIFFERENT_NAME},
    ]
    even_pages = [
        {"url": "https://acme.example/", "html": f.ENTITY_HOMEPAGE_ACME},
        {"url": "https://acme.example/about", "html": f.ENTITY_ABOUT_DIFFERENT_NAME},
    ]
    lopsided_finding = check_entity_consistency(lopsided_pages)[0]
    even_finding = check_entity_consistency(even_pages)[0]
    assert lopsided_finding["confidence"] > even_finding["confidence"]


def test_ai_discoverability_flags_missing_sitemap_and_thin_links():
    inventory = {
        "sitemap_found": False, "total_candidates": 1, "skipped_disallowed": [],
        "weak_internal_linking": True, "homepage_link_count": 1,
        "depth2_pages_explored": 1, "depth2_new_urls": 0,
    }
    findings = check_ai_discoverability(inventory, f.HOMEPAGE_THIN, "https://acme.example/")
    ids = [x["id"] for x in findings]
    assert "AI-001" in ids
    assert "AI-003" in ids  # no schema and no clear description


def test_ai_discoverability_language_gateway_homepage_not_flagged():
    """Real false positive found in live testing against
    https://www.wikipedia.org/: a language-gateway homepage whose links
    point at sibling subdomains has a weak SAME-HOST link count (since
    those links aren't same-host), but is not actually a discovery
    problem -- it routes visitors onward through those very links."""
    gateway_html = "<html><body><h1>Choose your language</h1>" + "".join(
        f'<a href="https://{code}.langportal.example/">{code}</a>'
        for code in ["en", "fr", "de", "es", "it", "pt", "ja", "zh", "ru", "ar"]
    ) + "</body></html>"
    inventory = {
        "sitemap_found": False, "total_candidates": 1, "skipped_disallowed": [],
        "weak_internal_linking": True, "homepage_link_count": 0,
        "depth2_pages_explored": 0, "depth2_new_urls": 0,
    }
    findings = check_ai_discoverability(inventory, gateway_html, "https://www.langportal.example/")
    assert all(x["id"] != "AI-001" for x in findings)


def test_ai_discoverability_strong_linking_not_flagged_despite_no_sitemap():
    """False-positive prevention: sitemap absence alone must never be
    enough -- strong internal/depth-2 linking should suppress AI-001."""
    inventory = {
        "sitemap_found": False, "total_candidates": 12, "skipped_disallowed": [],
        "weak_internal_linking": False, "homepage_link_count": 15,
        "depth2_pages_explored": 4, "depth2_new_urls": 6,
    }
    findings = check_ai_discoverability(inventory, f.HOMEPAGE_GOOD, "https://acme-robotics.example/")
    ids = [x["id"] for x in findings]
    assert "AI-001" not in ids


def test_ai_discoverability_clean_homepage_not_flagged_for_entity_clarity():
    inventory = {
        "sitemap_found": True, "total_candidates": 12, "skipped_disallowed": [],
        "weak_internal_linking": False, "homepage_link_count": 15,
        "depth2_pages_explored": 3, "depth2_new_urls": 5,
    }
    findings = check_ai_discoverability(inventory, f.HOMEPAGE_GOOD, "https://acme-robotics.example/")
    ids = [x["id"] for x in findings]
    assert "AI-003" not in ids
    assert "AI-001" not in ids


_CLEAN_INVENTORY = {
    "sitemap_found": True, "total_candidates": 12, "skipped_disallowed": [],
    "weak_internal_linking": False, "homepage_link_count": 15,
    "depth2_pages_explored": 3, "depth2_new_urls": 5,
}


def test_clear_visible_identity_without_schema_not_flagged():
    """Priority 4 red-team case: a page with a specific, consistent title/
    H1/description but NO Organization schema at all must not receive an
    entity-clarity finding -- structured data is supportive, not required."""
    html = """<html><head>
    <title>Acme Cloud Platform</title>
    <meta name="description" content="Acme Cloud Platform helps engineering teams deploy and monitor services at scale.">
    </head><body>
    <h1>Acme Cloud Platform</h1>
    <p>Acme Cloud Platform helps engineering teams deploy and monitor services at scale, with built-in observability.</p>
    </body></html>"""
    findings = check_ai_discoverability(_CLEAN_INVENTORY, html, "https://acmecloud.example/")
    assert all(f["id"] != "AI-003" for f in findings)


def test_schema_present_but_poor_visible_identity_is_still_flagged():
    """The inverse: Organization schema alone must not "save" a page
    whose visible content says nothing about who it is -- schema is
    supportive, not a substitute for visible clarity."""
    html = """<html><head><title>Home</title>
    <script type="application/ld+json">{"@type":"Organization","name":"Acme Cloud Platform"}</script>
    </head><body><h1>Welcome</h1></body></html>"""
    findings = check_ai_discoverability(_CLEAN_INVENTORY, html, "https://acmecloud.example/")
    assert any(f["id"] == "AI-003" for f in findings)


def test_signal_present_but_generic_does_not_count_as_meaningful():
    """Distinguishes SIGNAL PRESENT from SIGNAL MEANINGFUL: <title>Home</title>
    and <h1>Welcome</h1> are both non-empty, but neither says anything
    specific -- this must be treated the same as if they were absent."""
    html = "<html><head><title>Home</title></head><body><h1>Welcome</h1></body></html>"
    findings = check_ai_discoverability(_CLEAN_INVENTORY, html, "https://acme.example/")
    ai003 = [f for f in findings if f["id"] == "AI-003"]
    assert len(ai003) == 1
    missing = ai003[0]["evidence"]["signals_missing"]
    assert any("meaningful title" in m for m in missing)
    assert any("meaningful H1" in m for m in missing)


# --- Day 3: proactive recommendations (Part C) --------------------------

def test_proactive_faq_suggestion_fires_for_product_site_without_faq():
    """Evidence-backed proactive suggestion: product pages were audited,
    no FAQ page was among them -- a safe, low-priority improvement idea,
    not a claimed defect."""
    pages = [
        {"url": "https://shopdemo.example/products/trail-runner", "html": ""},
        {"url": "https://shopdemo.example/products/wool-loafer", "html": ""},
        {"url": "https://shopdemo.example/", "html": ""},
    ]
    page_types = {
        "https://shopdemo.example/products/trail-runner": "product",
        "https://shopdemo.example/products/wool-loafer": "product",
        "https://shopdemo.example/": "homepage",
    }
    findings = check_proactive_recommendations(pages, page_types)
    assert len(findings) == 1
    assert findings[0]["id"] == "AI-005"
    assert findings[0]["severity"] == "low"
    assert findings[0]["suggested_action"]["priority"] == "low"
    # Must reference actually-discovered product URLs, never invent one.
    for u in findings[0]["evidence"]["affected_pages"]:
        assert u in [p["url"] for p in pages]


def test_proactive_faq_suggestion_does_not_fire_when_faq_page_exists():
    """The suggestion must not fire once the evidence no longer supports
    it -- an FAQ page was actually discovered and audited."""
    pages = [
        {"url": "https://shopdemo.example/products/trail-runner", "html": ""},
        {"url": "https://shopdemo.example/faq", "html": ""},
    ]
    page_types = {
        "https://shopdemo.example/products/trail-runner": "product",
        "https://shopdemo.example/faq": "faq",
    }
    assert check_proactive_recommendations(pages, page_types) == []


def test_proactive_faq_suggestion_does_not_fire_without_product_pages():
    """No product pages were audited at all -- there is no evidence base
    for this specific proactive suggestion, so it must not fire."""
    pages = [
        {"url": "https://acme.example/blog/post", "html": ""},
        {"url": "https://acme.example/", "html": ""},
    ]
    page_types = {
        "https://acme.example/blog/post": "blog",
        "https://acme.example/": "homepage",
    }
    assert check_proactive_recommendations(pages, page_types) == []
