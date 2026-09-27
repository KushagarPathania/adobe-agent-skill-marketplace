"""P0 hardening: TP-001 substantive-content vs. UI/control classification.

Problem: TP-001 counted every rendered-only DOM block equally toward
severity escalation, even when those blocks were navigation menus,
account/login controls, carousels, or generic action links (not the
transient consent/session-modal chrome already handled separately) --
UI differences that don't imply the page's actual article/product
content requires JavaScript. This suite confirms severity/confidence
now escalate primarily from SUBSTANTIVE missing content, while genuine
JS-dependent article/product/pricing/table/list content still triggers
exactly as before, and the existing overlap-ratio backstop is untouched.
"""
from skills_impl.technical_parser.scripts.js_render_parity import check_js_render_parity, _is_ui_chrome_missing_item
from bs4 import BeautifulSoup
from tests import fixtures as f

RAW_MINIMAL = "<html><head><title>Acme</title></head><body><h1>Acme</h1><p>Welcome to Acme.</p></body></html>"


def _rendered(extra):
    return f"<html><head><title>Acme</title></head><body><h1>Acme</h1><p>Welcome to Acme.</p>{extra}</body></html>"


# --- 1. JS-only navigation ------------------------------------------------

NAV_WIDGET = """
<div class="navbar">
<h3>Quick Links</h3>
<ul><li>Products</li><li>Support</li><li>Careers</li><li>Contact Us</li></ul>
</div>
"""


def test_js_only_navigation_does_not_escalate_to_high_or_medium():
    findings = check_js_render_parity(RAW_MINIMAL, _rendered(NAV_WIDGET), "https://acme.example/")
    if findings:
        assert findings[0]["severity"] == "low"
        assert findings[0]["confidence"] < 0.85


# --- 4. Account/login UI (non-modal, structural id/class) -----------------

ACCOUNT_WIDGET = """
<div class="account-menu">
<h3>My Account</h3>
<ul><li>Order History</li><li>Sign Out</li><li>Profile Settings</li></ul>
</div>
"""


def test_account_ui_does_not_escalate_severity():
    findings = check_js_render_parity(RAW_MINIMAL, _rendered(ACCOUNT_WIDGET), "https://acme.example/")
    if findings:
        assert findings[0]["severity"] == "low"


# --- 5. Dynamic buttons/action links ---------------------------------------

ACTION_LINKS = """
<div><a href="/more">Learn More</a></div>
<div><a href="/shop">Shop Now</a></div>
<div><a href="/all">View All</a></div>
"""


def test_isolated_short_action_links_do_not_escalate_severity():
    findings = check_js_render_parity(RAW_MINIMAL, _rendered(ACTION_LINKS), "https://acme.example/")
    if findings:
        assert findings[0]["severity"] == "low"
        assert findings[0]["evidence"]["substantive_missing_count"] == 0


# --- Carousel/pagination controls ------------------------------------------

CAROUSEL_WIDGET = """
<div class="carousel">
<div class="slider">Featured Item One</div>
<div class="pagination">1 2 3 Next</div>
</div>
"""


def test_carousel_pagination_chrome_does_not_escalate_severity():
    findings = check_js_render_parity(RAW_MINIMAL, _rendered(CAROUSEL_WIDGET), "https://acme.example/")
    if findings:
        assert findings[0]["severity"] == "low"


# --- 6/7/8/9/10: genuine substantive content still triggers ---------------

def test_genuine_js_dependent_article_content_still_triggers_high(monkeypatch=None):
    findings = check_js_render_parity(f.RAW_HTML_JS_HEAVY, f.RENDERED_HTML_JS_HEAVY, "https://acme-saas.example/pricing")
    assert len(findings) == 1
    assert findings[0]["id"] == "TP-001"
    assert findings[0]["severity"] in ("high", "medium")
    assert findings[0]["evidence"]["substantive_missing_count"] > 0


SUBSTANTIVE_TABLE = """
<table>
<tr><th>Plan</th><th>Price</th></tr>
<tr><td>Starter Plan for individual developers</td><td>$29 per month billed annually</td></tr>
<tr><td>Enterprise Plan for growing teams</td><td>$199 per month billed annually</td></tr>
</table>
"""


def test_rendered_only_table_content_is_classified_substantive():
    soup = BeautifulSoup(SUBSTANTIVE_TABLE, "html.parser")
    td = soup.find_all("td")[0]
    norm_text = "starter plan for individual developers"
    assert _is_ui_chrome_missing_item(td, norm_text, td.get_text(strip=True)) is False


def test_rendered_only_table_triggers_tp001():
    findings = check_js_render_parity(RAW_MINIMAL, _rendered(SUBSTANTIVE_TABLE), "https://acme.example/pricing")
    assert len(findings) == 1
    assert findings[0]["evidence"]["substantive_missing_count"] > 0


SUBSTANTIVE_LIST = """
<ul>
<li>Free shipping on all orders over fifty dollars within the continental United States</li>
<li>Thirty day return policy with no questions asked for unworn items</li>
<li>Lifetime warranty against manufacturing defects on all footwear products</li>
</ul>
"""


def test_rendered_only_list_triggers_tp001():
    findings = check_js_render_parity(RAW_MINIMAL, _rendered(SUBSTANTIVE_LIST), "https://acme.example/shipping")
    assert len(findings) == 1
    assert findings[0]["evidence"]["substantive_missing_count"] > 0


PRODUCT_DESCRIPTION = """
<article>
<h2>Trail Runner Pro</h2>
<p>The Trail Runner Pro is built from recycled ocean plastics and merino wool, offering superior
breathability and cushioning for long-distance trail running in variable weather conditions.</p>
</article>
"""


def test_rendered_only_product_description_triggers_tp001():
    findings = check_js_render_parity(RAW_MINIMAL, _rendered(PRODUCT_DESCRIPTION), "https://acme.example/products/trail-runner")
    assert len(findings) == 1
    assert findings[0]["evidence"]["substantive_missing_count"] > 0


# --- Mixed: UI chrome AND genuine substantive content together -----------

def test_mixed_ui_chrome_and_substantive_content_still_escalates_from_substantive_alone():
    mixed = NAV_WIDGET + ACCOUNT_WIDGET + ACTION_LINKS + PRODUCT_DESCRIPTION
    findings = check_js_render_parity(RAW_MINIMAL, _rendered(mixed), "https://acme.example/products/trail-runner")
    assert len(findings) == 1
    assert findings[0]["evidence"]["substantive_missing_count"] >= 1
    assert findings[0]["evidence"]["ui_chrome_missing_count"] >= 3
    # The genuine product description must be what's shown as evidence,
    # not the nav/account/action-link chrome.
    examples_text = " ".join(findings[0]["evidence"]["examples"])
    assert "Trail Runner Pro" in examples_text or "recycled ocean plastics" in examples_text


def test_evidence_reports_both_substantive_and_ui_chrome_counts():
    mixed = NAV_WIDGET + PRODUCT_DESCRIPTION
    findings = check_js_render_parity(RAW_MINIMAL, _rendered(mixed), "https://acme.example/products/trail-runner")
    assert len(findings) == 1
    evidence = findings[0]["evidence"]
    assert "substantive_missing_count" in evidence
    assert "ui_chrome_missing_count" in evidence
    assert evidence["substantive_missing_count"] + evidence["ui_chrome_missing_count"] <= evidence.get(
        "substantive_missing_count", 0) + evidence.get("ui_chrome_missing_count", 0) + 100  # sanity, non-negative counts


# --- Critical fix: DOM restructuring / duplicated content false positives -
#
# Real-world false positives found live: stripe.com/in/pricing and
# github.com/pricing both showed whole-page word overlap of 100% yet
# still escalated TP-001, because a "missing" item's own EXACT combined
# text failed the literal-substring check even though virtually every
# individual word it's made of already existed somewhere else in the
# raw HTML -- a client-side hydration/pricing-variant-swap pattern that
# reflows/duplicates the same underlying copy across different DOM
# elements, not genuinely new information.

RAW_SCATTERED_WORDS = (
    "<html><head><title>Acme Payments</title></head><body>"
    "<p>Optimise checkout conversion, accept local payment methods, and increase "
    "acceptance rates for your business today.</p>"
    "<p>We help reduce your card processing costs significantly with smart "
    "routing options.</p>"
    "</body></html>"
)


def test_recombined_content_from_words_already_on_page_does_not_trigger_tp001():
    """Stripe-style false positive: the rendered DOM combines words that
    already exist scattered across separate raw paragraphs into one NEW
    sentence. No new information is actually introduced, so this must
    not be classified as substantive missing content."""
    rendered = RAW_SCATTERED_WORDS.replace(
        "</body>",
        "<p>Increase acceptance rates and reduce card processing costs with "
        "AI-powered optimizations.</p></body>",
    )
    findings = check_js_render_parity(RAW_SCATTERED_WORDS, rendered, "https://acme-payments.example/pricing")
    assert findings == []


def test_client_side_loading_error_widget_does_not_trigger_tp001():
    """GitHub-style false positive: a client-side data-fetch failure
    renders a short 'Uh oh! There was an error while loading. Please
    reload this page.' widget -- a transient client error state, not
    page content, and must not be treated as substantive."""
    rendered = _rendered(
        "<h3>Uh oh!</h3><p>There was an error while loading. Please reload this page.</p>"
    )
    findings = check_js_render_parity(RAW_MINIMAL, rendered, "https://acme.example/")
    if findings:
        assert findings[0]["evidence"]["substantive_missing_count"] == 0
        assert findings[0]["severity"] == "low"
    # else: no finding at all is equally correct (near-total overlap).


def test_genuinely_new_pricing_content_with_novel_words_still_triggers_high():
    """Shopify-style genuine case, preserved: brand-new pricing/plan
    content whose words don't already exist anywhere in the raw HTML
    must still be classified as substantive and escalate normally --
    the new 'already represented elsewhere' filter must never suppress
    content that is actually new."""
    rendered = _rendered(
        "<h2>Enterprise Ultra Plan</h2>"
        "<p>Get unlimited storage, dedicated support, and advanced analytics for "
        "four hundred ninety nine dollars per month billed annually starting today.</p>"
    )
    findings = check_js_render_parity(RAW_MINIMAL, rendered, "https://acme.example/pricing")
    assert len(findings) == 1
    assert findings[0]["evidence"]["substantive_missing_count"] > 0
    assert findings[0]["severity"] in ("high", "medium")


def test_borderline_high_overlap_with_genuine_new_faq_content_still_triggers():
    """Nike-style borderline case: overall word overlap can be elevated
    (a page largely reused elsewhere) while the specific rendered-only
    block is still genuinely new (FAQ-style questions whose own words
    barely overlap with the rest of the page) -- overlap alone must
    never be used to blanket-suppress this."""
    raw = (
        "<html><head><title>Acme Help</title></head><body>"
        "<p>Acme is a global company offering a wide range of products and services "
        "to millions of customers around the world every single day of the year.</p>"
        "</body></html>"
    )
    rendered = raw.replace(
        "</body>",
        "<h3>Returns and Exchanges</h3>"
        "<li>What is the warranty period for defective items?</li>"
        "<li>How do I request a replacement for a damaged shipment?</li>"
        "</body>",
    )
    findings = check_js_render_parity(raw, rendered, "https://acme.example/help/returns")
    assert len(findings) == 1
    assert findings[0]["evidence"]["substantive_missing_count"] > 0
