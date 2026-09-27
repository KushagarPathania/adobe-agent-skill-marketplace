"""Site-scope AI-discoverability signals that don't belong to a single
page: can important pages even be reached by a crawler (REACHABILITY),
and is the entity's identity/purpose explicit enough to be answered
straight from text (ENTITY CLARITY)?

This reads evidence the discovery step already gathered rather than
re-fetching anything, and only ever claims a "machine-extractability
risk" -- never an absolute "AI cannot read this" -- since none of these
signals are direct proof of what a given AI system can or can't do.
"""
import re
from bs4 import BeautifulSoup

from skills_impl.common.schema import make_finding
from skills_impl.engagement_evaluator.scripts.landing_context import is_generic_text, find_first_substantive_paragraph
from skills_impl.engagement_evaluator.scripts.navigation_signals import detect_gateway_homepage
from skills_impl.page_classifier.scripts.classifier import _FAQ_PHRASE_RE, _FAQ_HEADING_RE

_STOPWORDS = {
    'the', 'a', 'an', 'of', 'for', 'and', 'to', 'in', 'on', 'with', 'our',
    'is', 'are', 'at', 'by', 'from', 'your', 'we', 'you', 'this', 'that',
}


def check_ai_discoverability(inventory, homepage_html, homepage_url, language_supported=True) -> list:
    findings = []
    soup = BeautifulSoup(homepage_html or "", "html.parser")

    # REACHABILITY -- "limited discovery paths" is a broad condition
    # requiring multiple corroborating signals, never sitemap-absence
    # alone. A site can be perfectly discoverable through strong internal
    # linking with no sitemap at all. It can also be a deliberate
    # language/region/category "gateway" homepage that routes visitors
    # onward via links to sibling subdomains or a large selector rather
    # than ordinary same-host links -- `weak_internal_linking`'s
    # same-host link count can't see that, so positive structural
    # evidence of a gateway pattern overrides the finding.
    gateway = detect_gateway_homepage(homepage_html, homepage_url)
    if inventory.get("weak_internal_linking") and not gateway["is_gateway"]:
        reasons = []
        if not inventory.get("sitemap_found"):
            reasons.append("no usable sitemap was discovered")
        if inventory.get("homepage_link_count", 0) < 5:
            reasons.append(f"the homepage has only {inventory.get('homepage_link_count', 0)} internal link(s)")
        if inventory.get("depth2_new_urls", 0) < 2:
            reasons.append(
                f"exploring {inventory.get('depth2_pages_explored', 0)} of the site's own internal pages "
                f"surfaced only {inventory.get('depth2_new_urls', 0)} additional page(s)"
            )
        findings.append(make_finding(
            check_id="AI-001",
            title="Limited discovery paths detected",
            severity="low" if len(reasons) < 3 else "medium",
            evidence={
                "summary": (
                    "Multiple discovery signals together suggest this site may be harder than usual for a "
                    "crawler to explore beyond the pages directly linked from the homepage: " + "; ".join(reasons) + "."
                ),
                "url": homepage_url,
            },
            action_summary="Publish a sitemap.xml and/or strengthen internal linking between related pages so important content is reachable without guessing at URLs.",
            confidence=0.55 if len(reasons) < 3 else 0.65,
            scope="site",
        ))

    # NOTE (Adobe submission QA, Priority 5): a robots.txt exclusion used
    # to be reported here as an "AI-002" finding. Respecting robots.txt
    # is correct crawler behavior, not a website defect -- obeying a
    # disallow rule the site itself published is never evidence of a
    # problem with the site. This is now reported as a coverage-
    # limitation `robots_exclusion` diagnostic (see the orchestrator,
    # right after discovery) instead, so it can never inflate
    # `summary.total_findings` or any severity count.

    # ENTITY CLARITY -- two of the seven underlying signals (meaningful
    # title/H1, via is_generic_text's English placeholder list, and the
    # English-stopword-based title/H1-consistency and repeated-naming
    # checks) are English-vocabulary heuristics; the rest (schema
    # presence, meta-description/paragraph length) are language-neutral.
    # Rather than silently misjudging "Accueil"/"Startseite"-style
    # non-English placeholder titles as meaningful, this whole check is
    # skipped (like the other English-dependent checks elsewhere in the
    # pipeline) whenever the homepage's own <html lang> names an
    # unsupported language -- never producing a finding, never a fake
    # "language unsupported" defect either, just conservatively absent.
    entity = _entity_clarity_signals(soup)
    present = [name for name, ok in entity["signals"].items() if ok]
    missing = [name for name, ok in entity["signals"].items() if not ok]

    if len(present) <= 2 and language_supported:
        # Weak evidence (a couple of borderline signals) gets low
        # severity and low-to-moderate confidence; near-total absence of
        # every signal is both stronger evidence AND more impactful, so
        # both scale together deliberately here -- not because confidence
        # is standing in for severity, but because the same underlying
        # fact (how many independent signals are missing) drives both.
        severity = "medium" if len(present) == 0 else "low"
        confidence = round(0.5 + (2 - len(present)) * 0.06, 2)
        findings.append(make_finding(
            check_id="AI-003",
            title="Entity identity is not clearly machine-readable",
            severity=severity,
            evidence={
                "summary": (
                    f"Checked {len(entity['signals'])} independent entity-clarity signals and only "
                    f"{len(present)} were meaningfully present (not just non-empty, but actually descriptive "
                    f"rather than generic placeholders): {', '.join(present) if present else 'none'}. "
                    f"Missing or too generic: {', '.join(missing)}. This may make entity interpretation less "
                    "explicit for AI systems, though the page could still be understood from broader context."
                ),
                "url": homepage_url,
                "signals_present": present,
                "signals_missing": missing,
            },
            action_summary="Use a specific, descriptive title and H1 that name the entity (not 'Home'/'Welcome'), and add a meta description or opening paragraph stating who the entity is and what it offers.",
            confidence=confidence,
            scope="site",
        ))

    return findings


def check_proactive_recommendations(pages, page_types, page_language_supported=None) -> list:
    """A small number of suggestions that go beyond a detected defect --
    proactive improvement opportunities, explicitly labeled as such,
    fired only when the pages this audit actually discovered and
    audited give real evidence to justify them. Deliberately minimal:
    one well-scoped signal rather than a generic checklist applied to
    every site, per the project's "small number of strong findings, not
    a wall of speculative ones" principle.

    `pages` / `page_types` are exactly what `check_navigation` already
    receives -- the audited page set and its classifications -- so this
    reuses data already computed rather than re-fetching or re-inferring
    anything.

    `page_language_supported` (optional, url -> bool) lets this suppress
    the one suggestion below when it can't be trusted: `_page_has_faq_signal`
    only recognizes the English phrase/heading "frequently asked
    questions"/"FAQ(s)", so on an unsupported-language product page its
    "no embedded FAQ" reading is not reliable evidence of absence -- it
    may simply be written in that page's own language. Rather than risk
    a false "no FAQ found" suggestion, the whole opportunity is skipped
    for this run when any audited product page is in such a language.
    """
    findings = []
    type_counts = {}
    for page_type in page_types.values():
        type_counts[page_type] = type_counts.get(page_type, 0) + 1

    product_count = type_counts.get("product", 0)
    # Red-team finding (Day 4, Part D), confirmed live against a real
    # ecommerce site: two distinct false-impression risks, both covered
    # by the same cheap signal. (1) A product page can legitimately
    # answer pre-purchase questions with a Q&A accordion embedded
    # directly on the page, never as a standalone page the classifier
    # would recognize as "faq". (2) A product page can link to a
    # separate FAQ/help page (e.g. in a footer) that this bounded audit
    # simply didn't happen to crawl -- confirmed live on a real site,
    # where a footer link's own label was enough to detect this. In
    # both cases, telling the site owner "no FAQ page found" would be a
    # false impression, so this reuses the same literal-phrase/heading
    # patterns the page classifier itself trusts for FAQ detection --
    # "does this look FAQ-like" is judged the same way in both places --
    # and suppresses the suggestion whenever an audited product page
    # shows ANY such evidence, embedded or merely linked.
    has_embedded_faq_content = any(
        page_types.get(p['url']) == 'product' and _page_has_faq_signal(p.get('html', ''))
        for p in pages
    )
    product_language_unreliable = page_language_supported is not None and any(
        page_types.get(p['url']) == 'product' and not page_language_supported.get(p['url'], True)
        for p in pages
    )
    if (product_count >= 1 and type_counts.get("faq", 0) == 0 and not has_embedded_faq_content
            and not product_language_unreliable):
        product_urls = [p['url'] for p in pages if page_types.get(p['url']) == 'product'][:5]
        findings.append(make_finding(
            check_id="AI-005",
            title="Proactive opportunity: no FAQ/support page found among audited product pages",
            severity="low",
            evidence={
                "summary": (
                    f"{product_count} product page(s) were audited, but none of the {len(pages)} page(s) "
                    "discovered and audited in this run were classified as an FAQ page. This is a proactive "
                    "improvement suggestion, not a confirmed defect -- the site may well have an FAQ page that "
                    "simply wasn't among the bounded set of pages this audit reached."
                ),
                "affected_pages": product_urls,
            },
            action_summary=(
                "Consider adding (or more prominently linking to) an FAQ or comparison page that answers common "
                "pre-purchase questions -- this gives both AI assistants and visitors a concise, quotable place "
                "to find answers that don't naturally belong on an individual product page."
            ),
            action_priority="low",
            confidence=0.4,
            scope="site",
        ))

    return findings


def _page_has_faq_signal(html) -> bool:
    """Cheap, deterministic evidence that a page already contains
    Q&A-style content -- an explicit FAQ heading/phrase, or FAQPage
    JSON-LD -- even though the page's overall classification is
    something else (e.g. "product"). A raw substring check for
    "FAQPage" is a deliberate shortcut (not a full JSON-LD parse): this
    only ever SUPPRESSES a low-confidence proactive suggestion, so a
    slightly loose match errs in the safe direction.
    """
    if not html:
        return False
    if _FAQ_HEADING_RE.search(html) or _FAQ_PHRASE_RE.search(html):
        return True
    return 'FAQPage' in html


def _significant_words(text):
    words = re.findall(r"[a-z0-9']+", (text or '').lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def _schema_org_name(soup):
    import json
    for script in soup.find_all('script', type='application/ld+json'):
        if not script.string:
            continue
        try:
            data = json.loads(script.string)
        except (ValueError, TypeError):
            continue
        for obj in (data if isinstance(data, list) else [data]):
            if isinstance(obj, dict) and obj.get('@type') in ('Organization', 'LocalBusiness', 'WebSite'):
                name = obj.get('name')
                if isinstance(name, str) and name.strip():
                    return name.strip()
    return ""


def _entity_clarity_signals(soup):
    """Distinguishes SIGNAL PRESENT from SIGNAL MEANINGFUL: a <title> or
    <h1> that's merely non-empty ("Home", "Welcome") does not count --
    only text that's actually descriptive does. No single signal is
    required, and structured data is only one of several ways a page can
    make its identity clear (a page can have excellent visible identity
    with no schema at all, and conversely, schema alone doesn't save a
    page whose visible content says nothing).
    """
    has_org_schema = bool(_schema_org_name(soup))
    schema_name = _schema_org_name(soup)

    first_paragraph = find_first_substantive_paragraph(soup)

    meta_desc = soup.find('meta', attrs={'name': 'description'})
    meta_desc_text = meta_desc.get('content', '').strip() if meta_desc else ""

    title_tag = soup.find('title')
    title_text = title_tag.get_text(strip=True) if title_tag else ""

    h1_tag = soup.find('h1')
    h1_text = h1_tag.get_text(strip=True) if h1_tag else ""

    og_site = soup.find('meta', property='og:site_name')
    og_site_text = og_site.get('content', '').strip() if og_site else ""

    meaningful_title = len(title_text) > 5 and not is_generic_text(title_text)
    meaningful_h1 = len(h1_text) > 2 and not is_generic_text(h1_text)

    title_words = _significant_words(title_text)
    h1_words = _significant_words(h1_text)
    title_h1_consistent = bool(title_words and h1_words and (title_words & h1_words))

    # "Repeated naming": does the brand/org name (from schema or
    # og:site_name -- whichever is available) also show up in the title
    # or opening paragraph? Naming the entity once is a weak signal;
    # naming it consistently across multiple parts of the page is
    # stronger evidence a reader (or a crawler) can pin down who this is.
    brand_words = _significant_words(schema_name) | _significant_words(og_site_text)
    repeated_naming = bool(brand_words) and bool(brand_words & (title_words | _significant_words(first_paragraph)))

    signals = {
        "structured data (Organization/LocalBusiness/WebSite)": has_org_schema,
        "meaningful title (specific, not a generic placeholder)": meaningful_title,
        "meaningful H1 (specific, not a generic placeholder)": meaningful_h1,
        "title and H1 name the same thing": title_h1_consistent,
        "substantive meta description": len(meta_desc_text) > 40,
        "substantive opening paragraph": len(first_paragraph) > 60,
        "entity name repeated across multiple signals": repeated_naming,
    }
    return {"signals": signals}
