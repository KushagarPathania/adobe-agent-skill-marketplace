from skills_impl.semantic_analyzer.scripts.answerability import check_answerability
from tests import fixtures as f


def test_answerable_article_with_specific_heading_not_flagged():
    """A genuinely answerable informational page -- specific heading,
    substantive opening paragraph -- must not be flagged."""
    findings = check_answerability(f.NEWS_ARTICLE_PAGE, "https://acme.example/news/park-funding", "article")
    assert findings == []


def test_generic_heading_with_good_intro_not_flagged():
    """Two-signal AND-gate: a generic heading alone is not enough to flag
    -- a substantive, accessible opening paragraph must save the page."""
    findings = check_answerability(f.GENERIC_HEADING_BUT_GOOD_INTRO_PAGE, "https://acme.example/policies/returns", "about")
    assert findings == []


def test_boilerplate_heavy_page_with_generic_heading_is_flagged():
    """Both signals fail together: generic heading AND no substantive
    content among the first few elements after chrome removal."""
    findings = check_answerability(f.BOILERPLATE_HEAVY_ARTICLE_PAGE, "https://acme.example/blog/post", "blog")
    assert len(findings) == 1
    assert findings[0]["id"] == "AI-004"
    assert findings[0]["severity"] == "low"


def test_ecommerce_product_page_never_flagged():
    """False-positive prevention: ordinary structured product pages must
    never be flagged just because they contain product info instead of
    prose -- the check doesn't even apply to the 'product' page type."""
    findings = check_answerability(f.ECOMMERCE_PRODUCT_PAGE, "https://shopdemo.example/products/trail-runner", "product")
    assert findings == []


def test_gateway_homepage_never_flagged():
    """False-positive prevention: a language/region gateway homepage is
    page_type 'homepage', which is outside the applicable set entirely."""
    gateway_html = "<html><body><h1>Choose your language</h1>" + "".join(
        f'<a href="https://{code}.langportal.example/">{code}</a>'
        for code in ["en", "fr", "de", "es", "it", "pt", "ja", "zh", "ru", "ar"]
    ) + "</body></html>"
    findings = check_answerability(gateway_html, "https://www.langportal.example/", "homepage")
    assert findings == []


def test_utility_pages_never_flagged():
    """False-positive prevention: login/search/cart/checkout/contact and
    other utility page types are outside the applicable set entirely, so
    they can never receive AI-004 regardless of content."""
    thin_html = "<html><head><title>Home</title></head><body><h1>Overview</h1></body></html>"
    for page_type in ("contact", "search", "profile", "faq", "documentation", "pricing", "service", "other"):
        assert check_answerability(thin_html, "https://acme.example/x", page_type) == []


def test_empty_html_never_crashes():
    """No exception on empty input; an entirely empty page legitimately
    has no extractable heading or content, so AI-004 firing here is
    correct rather than a false positive."""
    findings = check_answerability("", "https://acme.example/", "article")
    assert isinstance(findings, list)
