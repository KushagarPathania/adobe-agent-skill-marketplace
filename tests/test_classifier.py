from skills_impl.page_classifier.scripts.classifier import classify_page, classify_site
from tests import fixtures as f


def test_homepage_classified_as_homepage():
    result = classify_page("https://acme-robotics.example/", f.HOMEPAGE_GOOD)
    assert result["page_type"] == "homepage"
    assert result["confidence"] > 0.4


def test_product_page_classified_as_product():
    result = classify_page("https://acme.example/products/roboarm", f.PRODUCT_PAGE_GOOD_SCHEMA)
    assert result["page_type"] == "product"


def test_faq_page_classified_as_faq():
    result = classify_page("https://acme.example/support/faq", f.FAQ_PAGE)
    assert result["page_type"] == "faq"


def test_university_about_page_is_not_classified_as_product():
    """False-positive prevention: a university about page must never be
    read as an ecommerce product page just because it has flowing prose."""
    result = classify_page("https://springfield.edu/about", f.UNIVERSITY_ABOUT_PAGE)
    assert result["page_type"] != "product"


def test_documentation_page_classified_as_documentation():
    result = classify_page("https://docs.acme.example/getting-started", f.DOCUMENTATION_PAGE)
    assert result["page_type"] == "documentation"


def test_site_classification_education_from_university_signals():
    page_classes = [{"page_type": "about"}, {"page_type": "other"}]
    result = classify_site("https://springfield.edu", page_classes, f.UNIVERSITY_ABOUT_PAGE)
    assert result["site_type"] == "education"


def test_site_classification_ecommerce_from_product_pages():
    page_classes = [{"page_type": "product"}, {"page_type": "product"}, {"page_type": "homepage"}]
    result = classify_site("https://acme-shop.example", page_classes, f.HOMEPAGE_GOOD)
    assert result["site_type"] == "ecommerce"


def test_no_signals_returns_other_with_low_confidence():
    result = classify_page("https://acme.example/xyz", "<html><body></body></html>")
    assert result["page_type"] == "other"
    assert result["confidence"] <= 0.5


def test_incidental_faq_mention_does_not_classify_as_faq_page():
    """Regression test: a single passing mention of 'FAQ' in a 'see
    also'-style link must not outweigh the page's real subject matter,
    the way a genuine FAQ heading/title should."""
    html = """<html><head><title>About Our Company</title></head><body>
    <h1>About Our Company</h1>
    <p>We build robots. See also our <a href="/faq">FAQ</a> page for support questions.</p>
    </body></html>"""
    result = classify_page("https://acme.example/about", html)
    assert result["page_type"] != "faq"


def test_genuine_faq_heading_still_classifies_as_faq():
    result = classify_page("https://acme.example/support", f.FAQ_PAGE)
    assert result["page_type"] == "faq"
