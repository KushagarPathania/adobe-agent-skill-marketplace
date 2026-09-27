"""Answerability / quotability: can an AI agent (or a human skimming
quickly) reasonably extract a concise, relevant answer from this page
without wading through a large amount of surrounding boilerplate first?

This is the most literal reading of Round 2's "the pages that get picked
as sources tend to be the ones a machine could easily reach, easily
read, and easily quote a clear fact from" -- distinct from
`answer_scannability` (which checks whether a *utility* page's answer,
once you're already in the right section, is structured scannably) and
from `ai_discoverability`'s entity-clarity check (which asks "who/what
is this," not "does this page answer a likely question"). Deliberately
narrow: it applies only to content-type pages (article/blog/about) where
"a page ought to say something and say it clearly near the top" is a
reasonable expectation -- never to product/pricing/faq/documentation/
service pages (already judged on structure, not prose, by
`answer_scannability`), and never to homepages, contact pages, search
pages, profiles, or anything the applicability engine treats as "other" -
which by construction also keeps this off login/cart/checkout/language-
selector/gateway pages, none of which classify into the three applicable
types.

Conservative by design: two independent signals must BOTH fail before
anything is flagged, mirroring the same multi-signal-corroboration
philosophy already used by `citation_landing_experience`.
"""
from bs4 import BeautifulSoup

from skills_impl.common.schema import make_finding
from skills_impl.engagement_evaluator.scripts.landing_context import is_generic_text

# Pages where "does this page clearly answer something" is a reasonable
# expectation. Deliberately excludes every type `answer_scannability`
# already judges (pricing/faq/documentation/product/service -- those are
# legitimately structure-based, card-based, or spec-based rather than
# prose-answerable, and flagging them here would risk exactly the
# false positive this check must avoid), and excludes homepage/contact/
# profile/search/category/event/other, none of which are naturally
# "answers one question" pages.
ANSWERABILITY_APPLICABLE_TYPES = {"article", "blog", "about"}

_MAX_LOOKAHEAD = 6            # how many leading content elements we'll scan
_MIN_SUBSTANTIVE_LENGTH = 40  # matches the threshold used elsewhere for "a real paragraph"


def _has_accessible_intro_content(rendered_html):
    """True when a substantive paragraph, list, or table appears among
    the first few block-level content elements, after removing standard
    nav/header/footer/aside chrome -- i.e. a reader (human or machine)
    doesn't have to scan past many intervening fragments to reach real
    content. Operates on a copy of the page so the caller's own soup is
    never mutated.
    """
    soup = BeautifulSoup(rendered_html or "", "html.parser")
    for tag in soup(['script', 'style', 'noscript', 'nav', 'header', 'footer', 'aside']):
        tag.decompose()

    checked = 0
    for tag in soup.find_all(['p', 'ul', 'ol', 'dl', 'table']):
        text = tag.get_text(separator=' ', strip=True)
        if not text:
            continue
        checked += 1
        if len(text) > _MIN_SUBSTANTIVE_LENGTH:
            return True
        if checked >= _MAX_LOOKAHEAD:
            break
    return False


def check_answerability(rendered_html: str, url: str = "", page_type: str = "other") -> list:
    if page_type not in ANSWERABILITY_APPLICABLE_TYPES:
        return []  # defense in depth -- the orchestrator's applicability engine already gates this

    soup = BeautifulSoup(rendered_html or "", "html.parser")
    h1_tag = soup.find('h1')
    h1_text = h1_tag.get_text(separator=' ', strip=True) if h1_tag else ""
    title_tag = soup.find('title')
    title_text = title_tag.get_text(strip=True) if title_tag else ""

    heading_text = h1_text or title_text
    heading_is_generic = is_generic_text(heading_text)

    has_intro_content = _has_accessible_intro_content(rendered_html)

    # Conservative by design: only flag when BOTH the heading fails to
    # name a specific topic AND no accessible introductory content was
    # found near the top -- a page with either one alone is not flagged
    # (a generic H1 sitting above a genuinely good opening paragraph is
    # fine; a specific, descriptive H1 whose content takes a little
    # longer to reach is fine). This is a low-severity, low-confidence
    # signal even when it does fire -- weak evidence never escalates
    # beyond "low" here.
    if has_intro_content or not heading_is_generic:
        return []

    return [make_finding(
        check_id="AI-004",
        title="Page may not offer a quickly extractable answer",
        severity="low",
        evidence={
            "summary": (
                f"This page's primary heading ('{heading_text or 'none found'}') is generic rather than "
                "topic-specific, and no substantive paragraph, list, or table was found among the first few "
                "content elements after removing navigation/header/footer chrome. An AI assistant or a visitor "
                "skimming this page may have to read past significant surrounding content before reaching a "
                "clear, quotable answer."
            ),
            "url": url,
        },
        action_summary=(
            "Give this page a specific, descriptive heading naming its topic, and move a concise summary or "
            "direct answer into the first paragraph, list, or table -- before any secondary content -- so both "
            "visitors and AI assistants can quickly find and quote the key fact."
        ),
        confidence=0.5,
    )]
