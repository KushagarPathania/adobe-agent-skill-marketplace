"""Day 4: adversarial-pattern regression tests.

These target realistic unseen-site patterns that commonly fool
deterministic auditors -- documentation hub pages, embedded (not
standalone) FAQ content, listicle/table-based articles, buried-answer
articles, ambiguous/mixed structured data, and icon-only UI controls.
Two real false positives were found and fixed via this exercise
(EE-001 on documentation/FAQ hub pages, AI-005 on product pages with an
embedded FAQ) -- the corresponding tests here are the regression guard
for those fixes. Everything else in this file is a red-team check that
confirms EXISTING behavior already handles the adversarial pattern
correctly, with no code change required.
"""
from bs4 import BeautifulSoup

from skills_impl.engagement_evaluator.scripts.landing_context import check_landing_context
from skills_impl.engagement_evaluator.scripts.answer_scannability import check_answer_scannability
from skills_impl.semantic_analyzer.scripts.answerability import check_answerability
from skills_impl.semantic_analyzer.scripts.ai_discoverability import check_proactive_recommendations
from skills_impl.semantic_analyzer.scripts.non_text_accessibility import check_non_text_accessibility
from skills_impl.technical_parser.scripts.structured_data_validation import check_structured_data
from skills_impl.page_classifier.scripts.classifier import classify_page


# --- EE-001: documentation/FAQ hub false positive (fixed) ---------------

def test_documentation_hub_page_not_flagged_for_orientation():
    html = """<html><head><title>Documentation</title></head><body>
    <aside><nav><a href="/docs/guides">Guides</a><a href="/docs/api">API</a></nav></aside>
    <h1>Documentation</h1>
    <p>Browse the guides in the sidebar to get started.</p>
    </body></html>"""
    assert check_landing_context(html, "/docs", "https://acme.example/docs") == []


def test_faq_hub_page_not_flagged_for_orientation():
    html = "<html><head><title>FAQ</title></head><body><h1>FAQ</h1><p>Answers below.</p></body></html>"
    assert check_landing_context(html, "/faq", "https://acme.example/faq") == []


def test_documentation_full_word_variant_also_exempted():
    html = "<html><head><title>Documentation</title></head><body><h1>Documentation</h1></body></html>"
    assert check_landing_context(html, "/documentation", "https://acme.example/documentation") == []


def test_deep_documentation_subpage_with_generic_heading_still_flagged():
    """The hub exemption must stay narrow: a deep sub-page genuinely
    gives no orientation and must still be caught."""
    html = "<html><head><title>Overview</title></head><body><h1>Overview</h1></body></html>"
    findings = check_landing_context(html, "/docs/api/auth", "https://acme.example/docs/api/auth")
    assert len(findings) == 1
    assert findings[0]["id"] == "EE-001"


def test_shallow_page_with_unrelated_generic_heading_still_flagged():
    """The exemption only applies when the H1 matches its OWN section --
    a shallow but unrelated page ('/careers' titled 'Welcome') is still
    genuinely disorienting and must still be flagged."""
    html = "<html><head><title>Welcome</title></head><body><h1>Welcome</h1></body></html>"
    findings = check_landing_context(html, "/careers", "https://acme.example/careers")
    assert len(findings) == 1
    assert findings[0]["id"] == "EE-001"


# --- AI-005: embedded FAQ content on product pages (fixed) --------------

def test_ai005_suppressed_when_product_page_has_embedded_faq_heading():
    html = """<html><body><h1>Trail Runner</h1><p>$98. Add to cart.</p>
    <h2>Frequently Asked Questions</h2><p>Is this waterproof? Yes.</p>
    </body></html>"""
    pages = [{"url": "https://shop.example/products/trail-runner", "html": html}]
    page_types = {"https://shop.example/products/trail-runner": "product"}
    assert check_proactive_recommendations(pages, page_types) == []


def test_ai005_suppressed_when_product_page_has_faqpage_schema():
    html = """<html><body><h1>Trail Runner</h1><p>$98.</p>
    <script type="application/ld+json">{"@type":"FAQPage","mainEntity":[]}</script>
    </body></html>"""
    pages = [{"url": "https://shop.example/products/trail-runner", "html": html}]
    page_types = {"https://shop.example/products/trail-runner": "product"}
    assert check_proactive_recommendations(pages, page_types) == []


def test_ai005_suppressed_when_product_page_merely_links_to_faq():
    """Real pattern found live on an unseen ecommerce site: the product
    page doesn't embed Q&A content, it just has a footer link to a
    separate FAQ/help page that this bounded audit didn't happen to
    crawl. Firing 'no FAQ page found' here would be a false impression
    -- the site demonstrably has one, it just wasn't in this run's
    bounded page set."""
    html = """<html><body><h1>Trail Runner</h1><p>$98. Add to cart.</p>
    <footer><a href="/pages/faq" data-analytics-footer-link-name="FAQ/Contact Us">FAQ</a></footer>
    </body></html>"""
    pages = [{"url": "https://shop.example/products/trail-runner", "html": html}]
    page_types = {"https://shop.example/products/trail-runner": "product"}
    assert check_proactive_recommendations(pages, page_types) == []


def test_ai005_still_fires_when_no_faq_evidence_anywhere():
    html = "<html><body><h1>Trail Runner</h1><p>$98. Add to cart.</p></body></html>"
    pages = [{"url": "https://shop.example/products/trail-runner", "html": html}]
    page_types = {"https://shop.example/products/trail-runner": "product"}
    findings = check_proactive_recommendations(pages, page_types)
    assert len(findings) == 1
    assert findings[0]["id"] == "AI-005"


def test_ai005_never_fires_for_documentation_site():
    pages = [
        {"url": "https://docs.example/getting-started", "html": ""},
        {"url": "https://docs.example/api", "html": ""},
    ]
    page_types = {
        "https://docs.example/getting-started": "documentation",
        "https://docs.example/api": "documentation",
    }
    assert check_proactive_recommendations(pages, page_types) == []


def test_ai005_never_fires_for_non_ecommerce_publisher_site():
    pages = [
        {"url": "https://news.example/story-1", "html": ""},
        {"url": "https://news.example/story-2", "html": ""},
    ]
    page_types = {"https://news.example/story-1": "article", "https://news.example/story-2": "article"}
    assert check_proactive_recommendations(pages, page_types) == []


# --- AI-004 red-team (Part C): confirm it's structural, not semantic ----

def test_table_based_answer_counts_as_accessible_intro():
    html = """<html><head><title>Overview</title></head><body><h1>Overview</h1>
    <table><tr><td>Weight</td><td>2.1 lbs, ships in 3-5 business days with free returns within 30 days</td></tr></table>
    </body></html>"""
    assert check_answerability(html, "https://acme.example/specs", "article") == []


def test_list_based_answer_counts_as_accessible_intro():
    html = """<html><head><title>Overview</title></head><body><h1>Overview</h1>
    <ul><li>Ships within 2 business days with tracking provided by email once the order leaves the warehouse</li></ul>
    </body></html>"""
    assert check_answerability(html, "https://acme.example/shipping", "blog") == []


def test_specific_heading_with_buried_answer_is_not_flagged():
    """Documented, intentional trade-off: a SPECIFIC heading is treated
    as strong-enough evidence on its own, even if the actual answer is
    buried past the lookahead window -- avoids requiring every article
    to front-load its content, which would be a false-positive risk on
    legitimate long-form editorial writing."""
    html = "<html><head><title>Return Policy</title></head><body><h1>Return Policy</h1>" + \
        "<p>By.</p><p>5 min read.</p><p>Share.</p><p>Tags.</p><p>Print.</p><p>Save.</p>" + \
        "<p>Items may be returned within 30 days of delivery for a full refund.</p></body></html>"
    assert check_answerability(html, "https://acme.example/returns", "article") == []


def test_generic_heading_with_navigation_clutter_before_content_is_flagged():
    """The inverse: a GENERIC heading combined with several short
    byline/meta fragments before the real content is exactly the
    pattern the check exists to catch -- fires, but stays low
    severity/confidence since it's still a narrow, mechanical signal."""
    html = "<html><head><title>Overview</title></head><body><h1>Overview</h1>" + \
        "<p>By.</p><p>5 min read.</p><p>Share.</p><p>Tags.</p><p>Print.</p><p>Save.</p>" + \
        "<p>Items may be returned within 30 days of delivery for a full refund.</p></body></html>"
    findings = check_answerability(html, "https://acme.example/post", "blog")
    assert len(findings) == 1
    assert findings[0]["severity"] == "low"
    assert findings[0]["confidence"] <= 0.5


# --- Documentation with code examples (Part A) ---------------------------

def test_documentation_page_with_code_block_not_flagged_unscannable():
    """A <pre><code> block is itself scannable structure -- a docs page
    answering via a code sample must not be treated the same as dense
    unstructured prose."""
    html = """<html><head><title>API Reference</title></head><body>
    <h2>API Authentication</h2>
    <pre><code>curl -H "Authorization: Bearer TOKEN" https://api.acme.example/v1/resource</code></pre>
    <p>""" + ("Pass your API token as a bearer token in the Authorization header. " * 15) + """</p>
    </body></html>"""
    findings = check_answer_scannability(html, "/docs/api/auth", "https://acme.example/docs/api/auth", "documentation")
    assert findings == []


# --- Structured data: ambiguous / mixed-type schema (Part A) -------------

def test_mixed_type_schema_does_not_crash_and_satisfies_expected_type():
    """A JSON-LD block declaring an array of @type values (a common,
    valid pattern -- e.g. a page that's both a Product and a slightly
    unusual secondary type) must not crash TP-003's type-matching, and
    should be recognized as satisfying the expected type."""
    html = """<html><body><h1>Trail Runner</h1>
    <script type="application/ld+json">{"@type": ["Product", "Thing"], "name": "Trail Runner", "offers": {"@type": "Offer", "price": "98.00"}}</script>
    <p>$98.00. Add to cart.</p>
    </body></html>"""
    findings = check_structured_data(html, "https://shop.example/products/trail-runner", "product")
    assert all(f["id"] != "TP-003" for f in findings)


def test_ambiguous_schema_with_no_matching_type_still_low_severity_suggestion():
    html = """<html><body><h1>Trail Runner</h1>
    <script type="application/ld+json">{"@type": "Thing", "name": "Trail Runner"}</script>
    <p>$98.00. Add to cart.</p>
    </body></html>"""
    findings = check_structured_data(html, "https://shop.example/products/trail-runner", "product")
    tp003 = [f for f in findings if f["id"] == "TP-003"]
    assert len(tp003) == 1
    assert tp003[0]["severity"] == "low"


# --- Accessibility: isolated icon controls (Part A) -----------------------

def test_icon_button_with_aria_label_not_flagged():
    html = """<html><body><button aria-label="Open search"><svg><path d="M0 0"/></svg></button></body></html>"""
    assert check_non_text_accessibility(html, "https://acme.example/") == []


# --- Page classification: "checkout" as a product name (fixed) ---------

def test_saas_pricing_page_naming_a_checkout_product_not_misclassified_as_product():
    """Real false positive found live on an unseen fintech/SaaS site: a
    pricing page listing "...no-code payments checkout..." among a list
    of product features, plus an unrelated incidental price mention
    elsewhere on the page, was scoring as an ecommerce PRODUCT page --
    the bare word "checkout" is also a common product/feature name, not
    exclusively a cart-flow action."""
    html = """<html><head><title>Pricing</title></head><body>
    <h1>Pricing</h1>
    <p>Explore our payments, billing, and checkout products. Simple, pay-as-you-go pricing with no
    setup fees or monthly commitments.</p>
    <p>Payment processing starts at $0.30 per transaction.</p>
    </body></html>"""
    result = classify_page("https://acme.example/pricing", html)
    assert result["page_type"] != "product"


def test_genuine_checkout_flow_page_still_scores_as_product():
    """The fix must stay narrow: a genuine cart/checkout-flow page still
    reliably triggers via 'add to cart' / 'in stock' -- and explicit
    checkout-action phrasing ('secure checkout', 'proceed to checkout')
    is still recognized too."""
    html = """<html><body><h1>Trail Runner</h1>
    <p>$98.00. Add to cart. In stock. <button>Proceed to Checkout</button></p>
    </body></html>"""
    result = classify_page("https://shop.example/products/trail-runner", html)
    assert result["page_type"] == "product"


def test_isolated_icon_svg_without_important_context_is_low_not_high_severity():
    """A plain icon (hamburger menu, close button) with no text and no
    nearby pricing/spec/data heading is a low-severity concern, not a
    high one -- it's UI chrome, not a likely-factual graphic."""
    html = "<html><body><div><svg><path d='M0 0'/></svg></div></body></html>"
    findings = check_non_text_accessibility(html, "https://acme.example/")
    assert len(findings) == 1
    assert findings[0]["severity"] == "low"
