"""Lightweight, explainable page-type and site-type classification.

Deliberately not ML: every category gets a weighted score built from
transparent signals (URL path, title, headings, visible text patterns,
structured data), and the highest-scoring category wins. This keeps the
reasoning inspectable and avoids the false-positive risk of judging every
page by one rule (e.g. "$" in the text does not, by itself, mean product).
"""
import re
from urllib.parse import urlparse
from bs4 import BeautifulSoup

PAGE_TYPES = [
    "homepage", "product", "category", "pricing", "article", "blog",
    "faq", "documentation", "about", "contact", "service", "event",
    "profile", "search", "other",
]

SITE_TYPES = [
    "ecommerce", "saas", "corporate", "publisher", "education",
    "government", "documentation", "nonprofit", "hospitality",
    "marketplace", "local_business", "portfolio", "other",
]

_PRICE_RE = re.compile(r'[$€£¥]\s?\d[\d,]*(\.\d{2})?|\b\d[\d,]*(\.\d{2})?\s?(USD|EUR|GBP)\b')
# Day 4 red-team finding, confirmed live on a real (non-ecommerce)
# fintech/SaaS site: the bare word "checkout" is far more overloaded
# than the other phrases here -- it's also a common PRODUCT NAME (e.g.
# "Stripe Checkout", "our hosted checkout SDK") that shows up alongside
# an unrelated incidental price mention on ordinary marketing/pricing
# pages, unlike "add to cart"/"buy now"/"in stock", which are reliably
# ecommerce-specific action phrases. Requiring the fuller action-oriented
# phrasing ("proceed to checkout", "secure checkout", ...) keeps genuine
# cart/checkout-flow pages detected while dropping the bare-noun case.
_CART_RE = re.compile(
    r'\b(add to cart|add to bag|buy now|in stock|out of stock|'
    r'proceed to checkout|secure checkout|checkout now|complete (your )?checkout)\b',
    re.I,
)
# Body-wide, this only matches the full phrase -- a single incidental
# mention of the word "FAQ" (e.g. a "See also: Product FAQ" link) should
# not be enough to classify an entire page as a FAQ page; the bare
# "faq(s)" form is only trusted in a heading/title, checked separately.
_FAQ_PHRASE_RE = re.compile(r'\bfrequently asked questions\b', re.I)
_FAQ_HEADING_RE = re.compile(r'\bfrequently asked questions\b|\bfaqs?\b', re.I)
_PRICING_RE = re.compile(r'\b(pricing|plans?|subscription)\b|/mo\b|/yr\b|per month|per year', re.I)
_DOC_RE = re.compile(r'\b(documentation|api reference|getting started|installation guide|changelog)\b', re.I)
_CONTACT_RE = re.compile(r'\b(contact us|get in touch|our address|email us)\b', re.I)
_ABOUT_RE = re.compile(r'\b(about us|our story|our mission|who we are)\b', re.I)
_EVENT_RE = re.compile(r'\b(register now|event date|rsvp|agenda|venue)\b', re.I)
_SAAS_RE = re.compile(r'\b(free trial|subscription|per seat|api key|integrations?)\b', re.I)
_EDU_RE = re.compile(r'\b(admissions|faculty|campus|curriculum|syllabus|enroll)\b', re.I)
# Deliberately more specific than a bare "department of" -- on a long
# page (a full article, a citation-heavy reference page), "department of
# computer science" or "department of biology" in an academic citation
# is common and is not government-agency language. These forms are
# reliable on their own (case-insensitive is fine -- there's no common
# idiomatic English use of "department of public works" that means
# anything else).
_GOV_RE = re.compile(
    r'\b(government of \w+|public notice|'
    r'department of (public works|motor vehicles|health|transportation|parks and recreation))\b',
    re.I,
)
# "City/County/State of X" is a much weaker signal on its own than the
# patterns above: it's also how virtually every US commercial site's
# Terms of Service names its choice-of-law jurisdiction ("governed by
# the laws of the State of California"), and "state of X" alone is
# common idiomatic English with nothing to do with government at all
# ("state of residence", "state of emergency", "state of mind", "state
# of the art"). Two things are required before it counts:
#   1. It must be a properly-capitalized proper noun ("City of
#      Springfield"), which the idiomatic phrases above never are --
#      checked against the ORIGINAL-CASE text, not lowercased.
#   2. It must not sit inside ordinary choice-of-law/jurisdiction legal
#      boilerplate, which routinely capitalizes the state name
#      correctly even though it says nothing about who operates the site.
_GOV_PLACE_RE = re.compile(r'\b(?:City|County|State) of [A-Z][a-zA-Z]+\b')  # case-sensitive by design
_GOV_LEGAL_BOILERPLATE_CONTEXT_RE = re.compile(
    r'\b(governed by|laws? of|jurisdiction|courts? of|in accordance with|pursuant to|'
    r'residents? of|conflict of law|choice of law|applicable law|without regard to|'
    r'shall be governed|shall be construed|shall be interpreted)\b',
    re.I,
)
_GOV_CONTEXT_WINDOW = 40  # chars of preceding text checked for a legal-boilerplate cue
_NONPROFIT_RE = re.compile(r'\b(donate|nonprofit|non-profit|501\(c\)\(3\)|charity|volunteer)\b', re.I)
# Red-team finding, confirmed live on a real (non-hospitality) ecommerce/
# payments SaaS site: the bare, unhyphenated word "checkout" (a near-
# ubiquitous ecommerce/payments term -- "Shopify Checkout", "proceed to
# checkout") was matching the "check-?out" alternative here, since the
# hyphen was only ever optional. Real hospitality usage ("Check-out time
# is 11am", "please check out by 11am") always has a separator (hyphen
# or space) between the two words; the payments/ecommerce sense never
# does. Requiring that separator -- `check[- ]out` instead of
# `check-?out` -- keeps genuine hospitality phrasing matched while
# dropping the bare-word collision. "check-?in" is left as-is: unlike
# "checkout", a bare "checkin" carries no common ecommerce/payments
# meaning, so it isn't a demonstrated collision risk.
_HOSPITALITY_RE = re.compile(r'\b(book now|reservation|check-?in|check[- ]out|nightly rate)\b', re.I)
_MARKETPLACE_RE = re.compile(r'\b(sellers?|vendors?|marketplace|third-party listings)\b', re.I)
_PORTFOLIO_RE = re.compile(r'\b(portfolio|my work|case studies)\b', re.I)
_CORPORATE_RE = re.compile(r'\b(our clients|headquartered|corporation|enterprise)\b', re.I)


def _seen_at_least_twice(pattern, text):
    """A single incidental match of a common word/phrase deep in a long
    page (an article, a citation-heavy reference page) is weak evidence
    for classifying the *entire site*; require it to show up more than
    once before it counts as a real thematic signal."""
    return len(pattern.findall(text)) >= 2


def _count_government_signals(body_text, body_lower):
    """Government-identity evidence count: the reliable patterns
    (government of X / department of public works / public notice) plus
    any "City/County/State of X" match that is both properly capitalized
    (ruling out idiomatic phrases like "state of residence") and not
    sitting inside ordinary choice-of-law/jurisdiction legal boilerplate
    (ruling out "governed by the laws of the State of California" on an
    ordinary commercial site). Operates on `body_text` (original case)
    for the place-name check since capitalization is the signal.
    """
    count = len(_GOV_RE.findall(body_lower))
    for match in _GOV_PLACE_RE.finditer(body_text):
        window_start = max(0, match.start() - _GOV_CONTEXT_WINDOW)
        preceding = body_text[window_start:match.start()]
        if _GOV_LEGAL_BOILERPLATE_CONTEXT_RE.search(preceding):
            continue
        count += 1
    return count


def _text_of(soup, tag):
    el = soup.find(tag)
    return el.get_text(separator=' ', strip=True) if el else ""


def _ld_types(soup):
    types = set()
    for script in soup.find_all('script', type='application/ld+json'):
        if script.string and '"@type"' in script.string:
            types.update(re.findall(r'"@type"\s*:\s*"([A-Za-z]+)"', script.string))
    return types


def classify_page(url, rendered_html):
    """Return {"page_type": str, "confidence": float, "signals": [str]}."""
    soup = BeautifulSoup(rendered_html or "", "html.parser")
    path = urlparse(url).path.lower().rstrip('/')
    title = _text_of(soup, 'title')
    h1 = _text_of(soup, 'h1')
    body_text = soup.get_text(separator=' ', strip=True)
    body_lower = body_text.lower()
    headline = f"{title} {h1}".lower()
    ld_types = _ld_types(soup)

    scores = {t: 0.0 for t in PAGE_TYPES}
    signals = []

    if path in ("", "/index", "/index.html", "/home"):
        scores["homepage"] += 4
        signals.append("URL path is the site root")

    if _CART_RE.search(body_lower) and _PRICE_RE.search(body_text):
        scores["product"] += 4
        signals.append("Visible cart/purchase language plus a price")
    if {"Product", "Offer"} & ld_types:
        scores["product"] += 3
        signals.append("Product/Offer structured data present")
    if any(k in path for k in ("/product/", "/products/", "/item/", "/shop/")):
        scores["product"] += 2

    if any(k in path for k in ("/category/", "/collections/", "/catalog/")):
        scores["category"] += 3
    if soup.find_all(class_=re.compile(r'product[-_]?(card|grid|list|tile)', re.I)):
        scores["category"] += 2
        signals.append("Repeated product-card style listing found")

    if _PRICING_RE.search(headline) or "/pricing" in path or "/plans" in path:
        scores["pricing"] += 4
        signals.append("Pricing-related heading or URL path")

    if {"Article", "NewsArticle", "BlogPosting"} & ld_types:
        scores["article"] += 4
        signals.append("Article/NewsArticle structured data present")
    if "/blog/" in path:
        scores["blog"] += 3
    if soup.find('time') or soup.find('meta', attrs={'property': 'article:published_time'}):
        scores["article"] += 1

    if _FAQ_HEADING_RE.search(headline) or "FAQPage" in ld_types:
        scores["faq"] += 4
        signals.append("FAQ language in the title/heading or FAQPage structured data present")
    elif _FAQ_PHRASE_RE.search(body_lower):
        scores["faq"] += 2
        signals.append("'Frequently asked questions' phrase found in body text")

    if _DOC_RE.search(body_lower) or any(k in path for k in ("/docs/", "/documentation/", "/api/", "/reference/")):
        scores["documentation"] += 4
        signals.append("Documentation-style language or URL path")

    if _ABOUT_RE.search(body_lower) or "/about" in path:
        scores["about"] += 3
        signals.append("About/company-story language")
    if "Organization" in ld_types:
        scores["about"] += 1

    if _CONTACT_RE.search(body_lower) or "/contact" in path or soup.find('form'):
        scores["contact"] += 1
    if "/contact" in path:
        scores["contact"] += 3
        signals.append("URL path indicates a contact page")

    if any(k in path for k in ("/service/", "/services/", "/solutions/")):
        scores["service"] += 3
        signals.append("Service-oriented URL path")

    if _EVENT_RE.search(body_lower) or "Event" in ld_types or "/event" in path:
        scores["event"] += 3

    if any(k in path for k in ("/profile/", "/team/", "/author/", "/people/")):
        scores["profile"] += 3

    if "/search" in path or soup.find('input', attrs={'type': 'search'}):
        scores["search"] += 2

    best_type = max(scores, key=scores.get)
    best_score = scores[best_type]

    if best_score <= 0:
        return {"page_type": "other", "confidence": 0.3, "signals": ["No strong signals matched a known page type"]}

    total = sum(v for v in scores.values() if v > 0)
    confidence = min(0.97, 0.4 + (best_score / (total + best_score)) * 0.6)
    return {"page_type": best_type, "confidence": round(confidence, 2), "signals": signals[:5]}


def classify_site(base_url, page_classifications, homepage_html):
    """Return {"site_type": str, "confidence": float, "signals": [str]}."""
    soup = BeautifulSoup(homepage_html or "", "html.parser")
    body_text = soup.get_text(separator=' ', strip=True)
    body_lower = body_text.lower()
    host = urlparse(base_url).netloc.lower()

    type_counts = {}
    for pc in page_classifications:
        type_counts[pc["page_type"]] = type_counts.get(pc["page_type"], 0) + 1

    scores = {t: 0.0 for t in SITE_TYPES}
    signals = []

    if type_counts.get("product", 0) or type_counts.get("category", 0):
        scores["ecommerce"] += 3 + type_counts.get("product", 0)
        signals.append("Product/category pages detected")

    # Domain suffix (.edu/.gov) is strong, reliable evidence on its own.
    # Body-language-only signals are much weaker on a long page (a full
    # article, a citation-heavy reference page can contain one incidental
    # match of almost any phrase), so those require the phrase to appear
    # more than once before it counts as a real thematic signal.
    if _seen_at_least_twice(_SAAS_RE, body_lower):
        scores["saas"] += 3
        signals.append("SaaS-style language (free trial/subscription/API) appears repeatedly")

    if host.endswith('.edu') or _seen_at_least_twice(_EDU_RE, body_lower):
        scores["education"] += 4
        signals.append("Education-domain or repeated campus/admissions language")

    if host.endswith('.gov') or _count_government_signals(body_text, body_lower) >= 2:
        scores["government"] += 4
        signals.append("Government-domain or repeated agency language")

    if _seen_at_least_twice(_NONPROFIT_RE, body_lower):
        scores["nonprofit"] += 3
        signals.append("Nonprofit/donation language appears repeatedly")

    if type_counts.get("documentation", 0) >= 2:
        scores["documentation"] += 3
        signals.append("Multiple documentation-style pages detected")

    if _seen_at_least_twice(_HOSPITALITY_RE, body_lower):
        scores["hospitality"] += 3
        signals.append("Booking/reservation language appears repeatedly")

    if _seen_at_least_twice(_MARKETPLACE_RE, body_lower):
        scores["marketplace"] += 3

    if _seen_at_least_twice(_PORTFOLIO_RE, body_lower) and type_counts.get('profile', 0):
        scores["portfolio"] += 3

    if _seen_at_least_twice(_CORPORATE_RE, body_lower):
        scores["corporate"] += 1

    if type_counts.get("article", 0) + type_counts.get("blog", 0) >= 2:
        scores["publisher"] += 2
        signals.append("Multiple article/blog pages detected")

    best_type = max(scores, key=scores.get)
    best_score = scores[best_type]
    if best_score <= 0:
        return {"site_type": "other", "confidence": 0.3, "signals": ["No strong site-type signals detected"]}

    total = sum(v for v in scores.values() if v > 0)
    confidence = min(0.95, 0.35 + (best_score / (total + best_score)) * 0.6)
    return {"site_type": best_type, "confidence": round(confidence, 2), "signals": signals[:5]}
