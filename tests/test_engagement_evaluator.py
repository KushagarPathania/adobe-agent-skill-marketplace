from skills_impl.engagement_evaluator.scripts.landing_context import check_landing_context
from skills_impl.engagement_evaluator.scripts.answer_scannability import check_answer_scannability
from skills_impl.engagement_evaluator.scripts.navigation_signals import check_navigation
from tests import fixtures as f


def test_homepage_root_path_never_flagged():
    assert check_landing_context(f.HOMEPAGE_GOOD, "/", "https://acme.example/") == []


def test_deep_page_with_generic_h1_and_no_breadcrumbs_flagged():
    html = "<html><head><title>Overview</title></head><body><h1>Overview</h1></body></html>"
    findings = check_landing_context(html, "/products/x200/overview", "https://acme.example/products/x200/overview")
    assert len(findings) == 1
    assert findings[0]["id"] == "EE-001"


def test_deep_page_with_brand_context_in_title_not_flagged():
    html = "<html><head><title>Overview - Acme Robotics</title></head><body><h1>Overview</h1></body></html>"
    findings = check_landing_context(html, "/products/x200/overview", "https://acme.example/products/x200/overview")
    assert findings == []


def test_utility_page_with_dense_unstructured_prose_flagged():
    """Only genuinely dense unstructured prose (long enough that scanning
    for a fact is hard) should be flagged -- a short paragraph is fine,
    tested separately below."""
    html = """<html><head><title>Pricing</title></head><body><h1>Pricing</h1>
    <p>Our pricing depends on many factors including team size, usage, storage needs, support tier,
    contract length, add-ons, regional taxes, currency, billing frequency, and whether you choose
    monthly or annual billing, each of which can shift the final number a customer actually pays
    at checkout by a meaningful amount depending on their specific combination of choices, and we
    recommend contacting sales for a fully itemized quote before committing to any particular plan.</p>
    </body></html>"""
    findings = check_answer_scannability(html, "/pricing", "https://acme.example/pricing", "pricing")
    assert len(findings) == 1
    assert findings[0]["id"] == "EE-002"


def test_utility_page_with_short_prose_not_flagged():
    """False-positive prevention (this phase's Priority 3.B): a short,
    well-written paragraph is perfectly usable without a table or list
    and must not be flagged just because it isn't bulleted."""
    html = """<html><head><title>Pricing</title></head><body><h1>Pricing</h1>
    <p>Our pricing depends on team size, usage, and add-ons that vary by customer.</p>
    </body></html>"""
    findings = check_answer_scannability(html, "/pricing", "https://acme.example/pricing", "pricing")
    assert findings == []


def test_utility_page_with_table_not_flagged():
    html = """<html><head><title>Pricing</title></head><body><h1>Pricing</h1>
    <table><tr><td>Starter</td><td>$10</td></tr></table>
    </body></html>"""
    findings = check_answer_scannability(html, "/pricing", "https://acme.example/pricing", "pricing")
    assert findings == []


def test_reference_article_not_required_to_have_cta():
    """False-positive prevention: an article/reference page is not a
    dead end just because it lacks a purchase-style call to action."""
    pages = [{"url": "https://acme.example/blog/history", "html": "<html><body><h1>History</h1><p>Text.</p></body></html>"}]
    page_types = {"https://acme.example/blog/history": "article"}
    assert check_navigation(pages, page_types) == []


def test_product_page_with_no_internal_links_is_dead_end():
    pages = [{"url": "https://acme.example/products/x", "html": f.PRODUCT_PAGE_MISSING_SCHEMA_NO_LINKS}]
    page_types = {"https://acme.example/products/x": "product"}
    findings = check_navigation(pages, page_types)
    assert len(findings) == 1
    assert findings[0]["id"] == "EE-003"


def test_product_page_with_internal_link_not_dead_end():
    pages = [{"url": "https://acme.example/products/x", "html": f.PRODUCT_PAGE_GOOD_SCHEMA}]
    page_types = {"https://acme.example/products/x": "product"}
    assert check_navigation(pages, page_types) == []


def test_product_page_with_contextual_links_is_not_a_dead_end():
    """Red-team scenario: a product page with genuinely useful
    continuation (related product, pricing, support) must not be flagged."""
    html = """<html><body><h1>Widget Pro</h1><p>Buy now for $49.99.</p>
    <a href="/products/widget-mini">Related: Widget Mini</a>
    <a href="/pricing">Pricing</a>
    <a href="/support">Support</a>
    </body></html>"""
    pages = [{"url": "https://acme.example/products/widget-pro", "html": html}]
    page_types = {"https://acme.example/products/widget-pro": "product"}
    assert check_navigation(pages, page_types) == []


def test_page_with_only_boilerplate_links_is_still_a_dead_end():
    """Red-team scenario: privacy/terms/cookie/login links must not count
    as useful continuation -- a product page with only those is still a
    dead end, just with weaker (lower-confidence) evidence than a page
    with zero links at all."""
    html = """<html><body><h1>Widget Pro</h1><p>Buy now for $49.99.</p>
    <a href="/privacy">Privacy Policy</a>
    <a href="/terms">Terms of Service</a>
    <a href="/login">Log in</a>
    </body></html>"""
    pages = [{"url": "https://acme.example/products/widget-pro", "html": html}]
    page_types = {"https://acme.example/products/widget-pro": "product"}
    findings = check_navigation(pages, page_types)
    assert len(findings) == 1
    assert findings[0]["id"] == "EE-003"
    assert findings[0]["evidence"]["total_internal_links"] == 3
    assert findings[0]["evidence"]["meaningful_internal_links"] == 0
    # Weaker evidence (links exist, just all boilerplate) than "zero
    # links at all" -- confidence must reflect that, not be identical.
    zero_links_html = "<html><body><h1>Widget Pro</h1><p>Buy now.</p></body></html>"
    zero_findings = check_navigation(
        [{"url": "https://acme.example/products/y", "html": zero_links_html}],
        {"https://acme.example/products/y": "product"},
    )
    assert findings[0]["confidence"] < zero_findings[0]["confidence"]


def _gateway_homepage_html(num_sibling_links=10):
    links = "".join(
        f'<a href="https://{code}.langportal.example/">{code}</a>'
        for code in ["en", "fr", "de", "es", "it", "pt", "ja", "zh", "ru", "ar"][:num_sibling_links]
    )
    return f"<html><body><h1>Choose your language</h1>{links}</body></html>"


def test_language_gateway_homepage_is_not_a_dead_end():
    """Real false positive found in live testing against
    https://www.wikipedia.org/: a language-gateway homepage whose links
    point at sibling subdomains (en.example.com, fr.example.com, ...)
    has zero ordinary same-host <a href> links, but is clearly not a
    dead end -- it routes visitors onward through those very links."""
    html = _gateway_homepage_html()
    pages = [{"url": "https://www.langportal.example/", "html": html}]
    page_types = {"https://www.langportal.example/": "homepage"}
    assert check_navigation(pages, page_types) == []


def test_ordinary_homepage_with_zero_links_is_still_a_dead_end():
    """The gateway carve-out must not become a blanket 'never flag a
    homepage with zero links' rule -- an ordinary homepage with
    genuinely no navigation mechanism of any kind is still flagged."""
    html = "<html><body><h1>Acme Corp</h1><p>Welcome to our website.</p></body></html>"
    pages = [{"url": "https://acme.example/", "html": html}]
    page_types = {"https://acme.example/": "homepage"}
    findings = check_navigation(pages, page_types)
    assert len(findings) == 1
    assert findings[0]["id"] == "EE-003"


def test_few_sibling_subdomain_links_do_not_count_as_a_gateway():
    """A homepage with just one or two incidental cross-subdomain links
    (e.g. a single 'shop.example.com' link in a nav bar) is not a
    deliberate gateway mechanism -- the threshold requires substantially
    more than that before treating it as positive evidence."""
    html = """<html><body><h1>Acme Corp</h1>
    <a href="https://shop.acme.example/">Shop</a>
    </body></html>"""
    pages = [{"url": "https://www.acme.example/", "html": html}]
    page_types = {"https://www.acme.example/": "homepage"}
    findings = check_navigation(pages, page_types)
    assert len(findings) == 1
    assert findings[0]["id"] == "EE-003"


def test_large_select_dropdown_also_counts_as_gateway_evidence():
    """A large <select> of options (a classic country/language/region
    selector) is an alternative form of the same gateway-mechanism
    evidence, not just sibling-subdomain links."""
    options = "".join(f"<option>Country {i}</option>" for i in range(12))
    html = f"<html><body><h1>Choose your region</h1><select>{options}</select></body></html>"
    pages = [{"url": "https://acme.example/", "html": html}]
    page_types = {"https://acme.example/": "homepage"}
    assert check_navigation(pages, page_types) == []


# --- Day 3: recommendation specificity (Part B) ------------------------

def test_dead_end_recommendation_names_actually_discovered_pages():
    """BEST-tier recommendation: when the audit discovered other pages
    that make sensible link targets, the suggested_action must name
    those *actual* URLs from this audit -- not a generic instruction."""
    gizmo_with_link_html = '<html><body><h1>Gizmo</h1><a href="/faq">FAQ</a></body></html>'
    pages = [
        {"url": "https://acme.example/products/widget", "html": f.PRODUCT_PAGE_MISSING_SCHEMA_NO_LINKS},
        {"url": "https://acme.example/products/gizmo", "html": gizmo_with_link_html},
        {"url": "https://acme.example/faq", "html": "<html><body><h1>FAQ</h1><a href=\"/\">Home</a></body></html>"},
    ]
    page_types = {
        "https://acme.example/products/widget": "product",
        "https://acme.example/products/gizmo": "product",
        "https://acme.example/faq": "faq",
    }
    findings = check_navigation(pages, page_types)
    # Only the widget page (which genuinely has no meaningful links) is a
    # dead end -- gizmo has a real continuation link so it's not flagged.
    assert len(findings) == 1
    assert findings[0]["evidence"]["url"] == "https://acme.example/products/widget"
    action = findings[0]["suggested_action"]["summary"]
    # The recommendation must reference real, actually-discovered URLs --
    # never a fabricated or invented path.
    assert "https://acme.example/products/gizmo" in action or "https://acme.example/faq" in action


def test_dead_end_recommendation_falls_back_to_generic_when_no_pages_available():
    """When this is the only page discovered (no related pages exist to
    reference), the recommendation must fall back to generic guidance --
    never invent a URL that wasn't actually audited."""
    pages = [{"url": "https://acme.example/products/widget", "html": f.PRODUCT_PAGE_MISSING_SCHEMA_NO_LINKS}]
    page_types = {"https://acme.example/products/widget": "product"}
    findings = check_navigation(pages, page_types)
    assert len(findings) == 1
    action = findings[0]["suggested_action"]["summary"]
    assert "https://" not in action
    assert "http://" not in action
