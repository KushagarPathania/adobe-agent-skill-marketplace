"""Site-scope engagement check: does each audited page give a visitor
somewhere useful to go next, or is it a dead end?

This needs the full set of fetched pages (not just one), since "useful
next step" is judged by whether the page links anywhere *meaningful* --
not just whether it links anywhere at all. A footer full of privacy/
terms/cookie/login links is not useful continuation, so those are
excluded from the count rather than counted the same as a link to a
related product, article, or documentation page. Only page types where a
next step is normally expected (product, pricing, service, homepage,
category) are held to this bar at all; a reference article or
documentation page is not a dead end just because it lacks a "Buy Now"
button.
"""
import re
from urllib.parse import urlparse
from bs4 import BeautifulSoup

from skills_impl.common.schema import make_finding

DEAD_END_SENSITIVE_TYPES = {"product", "pricing", "service", "homepage", "category"}

# Anchor text or path patterns that mark a link as generic site
# boilerplate rather than useful continuation -- present on nearly every
# page regardless of content, so they don't demonstrate the page connects
# a visitor to anything actually related to what they're reading.
GENERIC_LINK_TEXT_RE = re.compile(
    r'^(privacy( policy)?|terms( of (service|use))?|cookie(s)?( policy| settings| consent)?|'
    r'legal|login|log in|sign in|sign up|accessibility)$',
    re.I,
)
GENERIC_LINK_PATH_HINTS = ('/privacy', '/terms', '/cookie', '/legal', '/login', '/signin', '/sign-in')


def _is_generic_link(anchor_text, path):
    text = (anchor_text or '').strip()
    if GENERIC_LINK_TEXT_RE.match(text):
        return True
    path_lower = (path or '').lower()
    return any(hint in path_lower for hint in GENERIC_LINK_PATH_HINTS)


def _registrable_domain(netloc):
    """A small heuristic (last two dot-separated labels), not a full
    public-suffix-list lookup -- good enough to recognize that
    "en.example.com" and "www.example.com" are sibling subdomains of the
    same site. Imperfect for two-label ccTLDs (co.uk, com.au), but this
    is used only as one corroborating signal for gateway-page detection
    below, never as a blanket redefinition of "internal"."""
    host = (netloc or '').split(':')[0].lower()
    labels = host.split('.')
    return '.'.join(labels[-2:]) if len(labels) >= 2 else host


# How many links/options are needed before "links to sibling subdomains"
# or "a <select> of choices" reads as a deliberate language/region/
# category gateway mechanism, rather than e.g. one or two incidental
# cross-subdomain links (a "shop.example.com" link in a nav bar).
_GATEWAY_SIBLING_LINK_THRESHOLD = 8
_GATEWAY_SELECT_OPTION_THRESHOLD = 8


def detect_gateway_homepage(html, url):
    """Detect a language/region/category "gateway" homepage: a page that
    intentionally routes visitors onward through a selector mechanism --
    many links to sibling subdomains of the same site (a common pattern
    for multi-language sites, e.g. a language link pointing at
    en.example.com from www.example.com), or a large <select> of
    options -- rather than ordinary same-host content links. This is a
    purely structural, content-agnostic signal (no site is named or
    hard-coded); it exists so a homepage built this way isn't penalized
    for having few or zero ordinary same-host <a href> links, while an
    ordinary page with genuinely no meaningful navigation still is.
    """
    soup = BeautifulSoup(html or '', 'html.parser')
    base_netloc = urlparse(url).netloc
    base_domain = _registrable_domain(base_netloc)

    sibling_subdomain_links = 0
    if base_domain:
        for a in soup.find_all('a', href=True):
            href = a['href'].strip()
            if href.startswith(('mailto:', 'tel:', 'javascript:', '#')):
                continue
            netloc = urlparse(href).netloc
            if netloc and netloc != base_netloc and _registrable_domain(netloc) == base_domain:
                sibling_subdomain_links += 1

    large_selector_options = 0
    for select in soup.find_all('select'):
        option_count = len(select.find_all('option'))
        large_selector_options = max(large_selector_options, option_count)

    is_gateway = (
        sibling_subdomain_links >= _GATEWAY_SIBLING_LINK_THRESHOLD
        or large_selector_options >= _GATEWAY_SELECT_OPTION_THRESHOLD
    )
    return {
        "is_gateway": is_gateway,
        "sibling_subdomain_links": sibling_subdomain_links,
        "large_selector_options": large_selector_options,
    }


def count_internal_links(html, url):
    """Return {"total": N, "meaningful": M} -- internal links split into
    all of them vs the subset that isn't generic site boilerplate
    (privacy/terms/cookies/login/legal). `meaningful` is what actually
    counts as continuation; `total` is kept for evidence/transparency so
    a page with links that are ALL boilerplate can be described
    accurately rather than just "has links" or "has none".
    """
    soup = BeautifulSoup(html or '', 'html.parser')
    base_netloc = urlparse(url).netloc
    total = 0
    meaningful = 0
    for a in soup.find_all('a', href=True):
        href = a['href'].strip()
        if href.startswith(('mailto:', 'tel:', 'javascript:', '#')):
            continue
        parsed = urlparse(href)
        if parsed.netloc and parsed.netloc != base_netloc:
            continue  # external link
        total += 1
        anchor_text = a.get_text(separator=' ', strip=True)
        if not _is_generic_link(anchor_text, parsed.path):
            meaningful += 1
    return {"total": total, "meaningful": meaningful}


# For a dead-end page of a given type, which OTHER page types make
# sensible link targets -- used only to rank already-discovered pages
# when suggesting a fix, never to invent a URL that wasn't audited.
_RELATED_TYPES_FOR_SUGGESTION = {
    "product": {"product", "category", "pricing", "faq"},
    "category": {"product", "category"},
    "pricing": {"faq", "product", "service"},
    "service": {"faq", "pricing", "contact"},
    "homepage": {"product", "service", "pricing", "about"},
}


def _suggest_related_pages(current_url, current_page_type, pages, page_types, max_suggestions=3):
    """Pick a small number of OTHER pages this audit actually discovered
    and fetched that would make sensible link targets for `current_url`
    -- reused verbatim from the already-audited `pages` list, never
    fabricated. Prefers a page whose type is a natural continuation for
    the current one (e.g. another product/category page for a product
    page's "related items"); falls back to any other audited page if
    nothing more specific is available.
    """
    preferred_types = _RELATED_TYPES_FOR_SUGGESTION.get(current_page_type, set())
    other_urls = [p['url'] for p in pages if p['url'] != current_url]
    preferred = [u for u in other_urls if page_types.get(u) in preferred_types]
    rest = [u for u in other_urls if u not in preferred]
    return (preferred + rest)[:max_suggestions]


def check_navigation(pages, page_types) -> list:
    findings = []
    for page in pages:
        page_type = page_types.get(page['url'], 'other')
        if page_type not in DEAD_END_SENSITIVE_TYPES:
            continue

        counts = count_internal_links(page.get('html', ''), page['url'])

        if counts["meaningful"] > 0:
            continue  # has at least one link that isn't pure boilerplate

        # A homepage with zero ordinary same-host links isn't
        # automatically a dead end -- it may be a deliberate language/
        # region/category gateway that routes visitors onward via links
        # to sibling subdomains or a large selector, which "meaningful"
        # same-host <a href> counting alone can't see. Require that
        # positive structural evidence before excusing the page; an
        # ordinary page with genuinely no navigation is still flagged.
        if page_type == "homepage":
            gateway = detect_gateway_homepage(page.get('html', ''), page['url'])
            if gateway["is_gateway"]:
                continue

        if counts["total"] == 0:
            summary = f"No internal links of any kind were found on this {page_type} page, leaving visitors with no next step."
            confidence = 0.7
        else:
            summary = (
                f"This {page_type} page has {counts['total']} internal link(s), but all of them are generic "
                "site boilerplate (privacy/terms/cookies/login) rather than a contextually relevant next step."
            )
            confidence = 0.5

        # BAD: "Improve navigation." BETTER: name the kind of page to
        # link to. BEST: when the audit itself already discovered a
        # suitable page, name it directly -- never a URL that wasn't
        # actually fetched during this audit.
        suggestions = _suggest_related_pages(page['url'], page_type, pages, page_types)
        if suggestions:
            action_summary = (
                f"This {page_type} page has no meaningful internal continuation links. Add link(s) to relevant "
                f"page(s) already discovered during this audit, for example: {', '.join(suggestions)}. Generic "
                "footer links (privacy/terms/login) don't count as continuation."
            )
        else:
            action_summary = (
                "Add contextually relevant internal links (related items, comparisons, support, or "
                "documentation) so visitors and crawlers have a clear next step -- generic footer links don't count."
            )

        findings.append(make_finding(
            check_id="EE-003",
            title="Page is a navigational dead end",
            severity="medium" if page_type in ("product", "pricing", "service") else "low",
            evidence={
                "summary": summary,
                "url": page['url'],
                "total_internal_links": counts["total"],
                "meaningful_internal_links": counts["meaningful"],
            },
            action_summary=action_summary,
            confidence=confidence,
        ))

    return findings
