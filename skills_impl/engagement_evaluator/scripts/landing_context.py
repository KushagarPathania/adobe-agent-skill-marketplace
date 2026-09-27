import re
from bs4 import BeautifulSoup

from skills_impl.common.schema import make_finding

GENERIC_TERMS = {
    'overview', 'features', 'details', 'pricing', 'introduction', 'home', 'more',
    'info', 'information', 'about', 'contact', 'services', 'products',
    'documentation', 'docs', 'guide', 'welcome', 'untitled', 'hello', 'index',
    'page', 'default', 'new page', 'menu',
}


def is_generic_text(text):
    """True when `text` is empty or is (once punctuation is stripped) one
    of a small set of placeholder-style words that name nothing specific
    -- 'Home', 'Welcome', 'Overview'. Shared by the entity-clarity check
    so "is this title/H1 actually meaningful, not just present" is
    judged the same way everywhere.
    """
    if not text:
        return True
    return re.sub(r'[^a-zA-Z0-9\s]', '', text).strip().lower() in GENERIC_TERMS


def find_first_substantive_paragraph(soup, min_length=40):
    """The first <p> with more than `min_length` characters of text --
    skips short nav/hatnote-style leading paragraphs that aren't the
    real descriptive content. Shared by the entity-clarity check
    (`semantic_analyzer/ai_discoverability.py`) and the answerability
    check (`semantic_analyzer/answerability.py`) so "is there a real
    intro paragraph" is judged the same way in both places, instead of
    two separate implementations that could quietly drift apart.
    """
    for p in soup.find_all('p'):
        text = p.get_text(separator=' ', strip=True)
        if len(text) > min_length:
            return text
    return ""


# Small set of common abbreviation/full-form pairs where a shallow hub
# page's URL segment and its own natural H1 refer to the exact same
# section but aren't identical strings (e.g. "/docs" -> "Documentation").
# Intentionally minimal -- not a general synonym lookup, just the
# handful of forms this specific ambiguity is likely to take.
_HUB_LABEL_ALIASES = {
    "docs": "documentation", "documentation": "documentation",
    "faq": "faq", "faqs": "faq",
}


def _is_expected_hub_heading(h1_text, url_path):
    """True when a generic-sounding H1 ('Documentation', 'FAQ', 'About')
    is simply naming the section-root page it sits at ('/docs', '/faq',
    '/about') -- i.e. the heading and the URL's own path segment refer to
    the same thing, so the "generic" wording is the correct, expected
    title for a hub/index page rather than a sign of missing context. A
    real red-team finding: an unadorned documentation or FAQ landing page
    (very common in practice) was being flagged purely because its H1
    matches its own section name.

    Deliberately narrow: only applies to a SHALLOW path (at most one
    non-empty segment) whose segment literally equals (or is a known
    abbreviation/full-form pair of) the H1 text -- a deep sub-page
    ("/docs/api/auth") titled just "Overview" still gives a visitor no
    clue which specific topic they're on, and is still flagged.
    """
    segments = [s for s in url_path.strip('/').split('/') if s]
    if len(segments) != 1:
        return False
    segment_norm = re.sub(r'[^a-z0-9]', '', segments[0].lower())
    h1_norm = re.sub(r'[^a-zA-Z0-9\s]', '', h1_text).strip().lower().replace(' ', '')
    if not segment_norm or not h1_norm:
        return False
    if segment_norm == h1_norm:
        return True
    return (
        segment_norm in _HUB_LABEL_ALIASES
        and h1_norm in _HUB_LABEL_ALIASES
        and _HUB_LABEL_ALIASES[segment_norm] == _HUB_LABEL_ALIASES[h1_norm]
    )


def check_landing_context(rendered_html: str, url_path: str = "", url: str = "") -> list:
    path = url_path.strip()
    if not path or path == '/' or path.lower() == '/index.html':
        return []

    soup = BeautifulSoup(rendered_html, 'html.parser')
    has_breadcrumbs = bool(
        soup.find('nav', attrs={'aria-label': re.compile(r'breadcrumb', re.I)})
        or soup.find(class_=re.compile(r'breadcrumb', re.I))
        or soup.find(id=re.compile(r'breadcrumb', re.I))
        or any(s.string and 'BreadcrumbList' in s.string for s in soup.find_all('script', type='application/ld+json'))
    )
    if has_breadcrumbs:
        return []

    h1_tag = soup.find('h1')
    h1_text = h1_tag.get_text(separator=' ', strip=True) if h1_tag else ""
    title_tag = soup.find('title')
    title_text = title_tag.get_text(separator=' ', strip=True) if title_tag else ""

    h1_is_generic = is_generic_text(h1_text)
    has_title_brand_context = bool(re.search(r'\s[\|\-•:—]\s', title_text))

    if not (h1_is_generic and not has_title_brand_context):
        return []

    if h1_tag and _is_expected_hub_heading(h1_text, path):
        # A shallow hub/index page (e.g. "/docs", "/faq") whose H1 simply
        # names that same section is correctly, not poorly, oriented --
        # the "generic" word IS the section's own name here.
        return []

    # A completely missing <h1> is stronger, more direct evidence than a
    # generic-but-present one (e.g. "Overview") -- the page has *some*
    # topical hint in the latter case, just a weak one.
    if not h1_tag:
        parts = ["Missing primary <h1> tag."]
        confidence = 0.7
    else:
        parts = [f"<h1> is highly generic ('{h1_text}')."]
        confidence = 0.6
    parts.append("No breadcrumb navigation detected.")
    parts.append(f"Title tag ('{title_text}') lacks clear brand/topic context separators.")

    return [make_finding(
        check_id="EE-001",
        title="Poor deep-page orientation context",
        severity="medium",
        evidence={
            "summary": "Deep page lacks immediate orientation cues for a visitor arriving directly from an AI citation: " + " ".join(parts),
            "url": url,
        },
        action_summary="Provide immediate orientation via semantic breadcrumbs or an explicit brand/topic mention in the primary <h1>.",
        confidence=confidence,
    )]
