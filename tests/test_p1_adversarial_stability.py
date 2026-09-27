"""P1 review: site-type classification and AI-004 (answerability) were
both audited for a clearly-safe calibration improvement. Neither had a
concrete, reproduced false positive in this pass (unlike TP-001/TP-005,
which did) -- both were already hardened in prior sessions (the
"checkout"-as-product-name / hospitality-regex fix, and the two-signal
AND-gate design for AI-004). Per explicit instruction ("if the
improvement is not clearly safe, leave the classifier unchanged"),
production logic for both is UNCHANGED this pass. These are adversarial
regression-lock tests confirming current, already-correct behavior on
the scenarios the hardening pass asked to verify -- not new production
behavior.
"""
from skills_impl.page_classifier.scripts.classifier import classify_site, classify_page
from skills_impl.semantic_analyzer.scripts.answerability import check_answerability
from tests import fixtures as f


# --- Site-type stability (mandatory adversarial items 14-20) -------------

def test_saas_pricing_page_site_classified_saas_not_ambiguous():
    page_classifications = [{"page_type": "pricing"}, {"page_type": "homepage"}]
    result = classify_site("https://saas-example.test/", page_classifications, f.SAAS_HOMEPAGE)
    assert result["site_type"] == "saas"


def test_ecommerce_product_page_site_classified_ecommerce():
    page_classifications = [{"page_type": "product"}, {"page_type": "product"}, {"page_type": "category"}]
    homepage = "<html><body><h1>Shop</h1><p>Add to cart. In stock. $49.99.</p></body></html>"
    result = classify_site("https://shop-example.test/", page_classifications, homepage)
    assert result["site_type"] == "ecommerce"


def test_documentation_site_classified_documentation():
    page_classifications = [{"page_type": "documentation"}, {"page_type": "documentation"}, {"page_type": "homepage"}]
    result = classify_site("https://docs-example.test/", page_classifications, f.DOCUMENTATION_PAGE)
    assert result["site_type"] == "documentation"


def test_publisher_news_site_classified_publisher():
    page_classifications = [{"page_type": "article"}, {"page_type": "blog"}, {"page_type": "homepage"}]
    result = classify_site("https://news-example.test/", page_classifications, f.NEWS_ARTICLE_PAGE)
    assert result["site_type"] == "publisher"


def test_government_site_not_triggered_by_isolated_legal_words():
    """Legal boilerplate mentioning a single incidental government-
    adjacent phrase must not classify an ordinary commercial site as
    government -- already-established, unchanged behavior."""
    page_classifications = [{"page_type": "homepage"}]
    result = classify_site("https://shopdemo.example/", page_classifications, f.ECOMMERCE_HOMEPAGE_WITH_LEGAL_FOOTER)
    assert result["site_type"] != "government"


def test_genuine_government_site_still_classifies_as_government():
    page_classifications = [{"page_type": "homepage"}]
    result = classify_site("https://city-example.test/", page_classifications, f.GOVERNMENT_PAGE)
    assert result["site_type"] == "government"


def test_hospitality_site_not_triggered_by_generic_ecommerce_checkout_language():
    """Regression lock for the prior "checkout"-collision fix -- an
    ordinary ecommerce/SaaS site heavy on "checkout" language must not
    classify as hospitality."""
    homepage = """Our platform makes checkout fast and secure. Millions of merchants trust our
    checkout for their online stores. Complete checkout in seconds with our optimized checkout flow."""
    page_classifications = [{"page_type": "pricing"}, {"page_type": "homepage"}]
    result = classify_site("https://shop-like-saas.test/", page_classifications, homepage)
    assert result["site_type"] != "hospitality"


def test_ambiguous_site_with_no_strong_signals_classifies_as_other():
    page_classifications = [{"page_type": "other"}]
    result = classify_site("https://ambiguous-example.test/", page_classifications, f.STATIC_SIMPLE_PAGE)
    assert result["site_type"] == "other"
    assert result["confidence"] <= 0.5  # a genuinely weak-evidence case must not report high confidence


# --- AI-004 answerability (mandatory adversarial items 21-24) -----------

def test_answerable_article_with_specific_heading_and_good_intro_not_flagged():
    findings = check_answerability(f.NEWS_ARTICLE_PAGE, "https://news-example.test/article", "article")
    assert findings == []


def test_intentionally_sparse_landing_page_with_specific_heading_not_flagged():
    """A sparse but specifically-titled landing page (little content, but
    the heading itself names the exact topic) must not be penalized just
    for being short -- a specific heading is sufficient evidence on its
    own, by design."""
    html = "<html><head><title>Acme Robotics Series X Recall Notice</title></head><body>" \
           "<h1>Acme Robotics Series X Recall Notice</h1></body></html>"
    findings = check_answerability(html, "https://acme.example/recall", "about")
    assert findings == []


def test_faq_page_type_never_evaluated_by_answerability():
    """FAQ pages are judged on structure by answer_scannability instead
    -- answerability must never even apply, by construction."""
    findings = check_answerability(f.FAQ_PAGE, "https://acme.example/faq", "faq")
    assert findings == []


def test_generic_documentation_hub_never_evaluated_by_answerability():
    findings = check_answerability(f.DOCUMENTATION_PAGE, "https://acme.example/docs", "documentation")
    assert findings == []
