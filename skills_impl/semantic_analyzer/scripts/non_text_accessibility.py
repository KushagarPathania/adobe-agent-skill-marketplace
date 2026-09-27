import re
from bs4 import BeautifulSoup

from skills_impl.common.schema import make_finding

GENERIC_ALTS = {'image', 'photo', 'picture', 'graphic', 'logo', 'icon', 'chart', 'graph', 'blank'}
BLOCK_TAGS = {'div', 'p', 'td', 'th', 'dd', 'dt', 'li', 'article', 'section', 'figure', 'main', 'header', 'footer', 'aside'}
IMPORTANT_CONTEXT_RE = re.compile(r'\b(price|pricing|cost|spec|specification|data|chart|results?|comparison|table|schedule|menu)\b', re.I)


def _nearby_heading_text(tag):
    heading = tag.find_previous(['h1', 'h2', 'h3', 'h4'])
    return heading.get_text(separator=' ', strip=True) if heading else ""


def check_non_text_accessibility(rendered_html: str, url: str = "") -> list:
    soup = BeautifulSoup(rendered_html, 'html.parser')

    graphics = soup.find_all(['img', 'svg', 'canvas'])
    if not graphics:
        return []

    suspects = []
    for tag in graphics:
        if tag.get('aria-hidden') == 'true' or tag.get('role') in ('presentation', 'none'):
            continue
        if tag.name == 'img' and tag.has_attr('alt') and tag['alt'].strip() == "":
            continue
        if tag.get('aria-label') or tag.get('aria-labelledby'):
            continue
        # Day 4 red-team finding: the standard, WAI-ARIA-endorsed way to
        # label an icon-only control is an aria-label on the *interactive
        # wrapper* (<button>/<a>/role="button") around the icon, not on
        # the icon itself -- e.g. <button aria-label="Search"><svg>...
        # </svg></button>. Only checking the graphic's own attribute
        # missed this extremely common accessible pattern entirely.
        labelled_control = tag.find_parent(
            lambda t: t.name in ('button', 'a') or t.get('role') in ('button', 'link')
        )
        if labelled_control and (labelled_control.get('aria-label') or labelled_control.get('aria-labelledby')):
            continue
        if tag.name == 'img' and tag.has_attr('alt'):
            alt_text = tag['alt'].strip().lower()
            if alt_text and alt_text not in GENERIC_ALTS:
                continue
        if tag.name == 'svg' and tag.find('title') and tag.find('title').get_text(strip=True):
            continue
        if tag.name == 'canvas' and tag.get_text(strip=True):
            continue
        if tag.find_parent('figure'):
            figcaption = tag.find_parent('figure').find('figcaption')
            if figcaption and figcaption.get_text(strip=True):
                continue

        block = tag.find_parent(BLOCK_TAGS) or tag.parent
        alphanumeric_text = re.sub(r'[^a-zA-Z0-9]', '', block.get_text(separator=' ', strip=True))
        if alphanumeric_text:
            continue

        # Decorative-looking isolated graphics are treated differently from
        # graphics sitting under a heading that suggests real information
        # (pricing, specs, data, a chart) is trapped inside them.
        nearby_heading = _nearby_heading_text(tag)
        likely_important = bool(IMPORTANT_CONTEXT_RE.search(nearby_heading))
        evidence = f"<{tag.name}> is the sole content of its parent <{block.name}>"
        if nearby_heading:
            evidence += f", under heading '{nearby_heading}'"
        evidence += " and has no text equivalent."

        suspects.append({"tag": tag.name, "important": likely_important, "evidence": evidence})

    if not suspects:
        return []

    any_important = any(s['important'] for s in suspects)
    severity = "high" if any_important else "low"
    confidence = 0.75 if any_important else 0.5
    # Evidence-discipline fix: when severity is escalated because SOME
    # suspect on the page is "important" (near a pricing/spec/data
    # heading), the shown examples must actually include one -- otherwise
    # a reviewer sees only decorative-looking examples next to a "high"
    # severity claim that nothing they can see substantiates. Important
    # suspects are surfaced first; this never changes WHICH suspects are
    # found or the severity/confidence decision, only which ones are
    # shown as evidence.
    ordered_suspects = sorted(suspects, key=lambda s: not s['important'])
    examples = [s['evidence'] for s in ordered_suspects[:3]]

    return [make_finding(
        check_id="SA-001",
        title="Potentially factual non-text content lacks accessible text",
        severity=severity,
        evidence={
            "summary": f"{len(suspects)} isolated graphic(s) have no text equivalent and are potentially inaccessible to AI crawlers.",
            "url": url,
            "examples": examples,
        },
        action_summary="Provide machine-readable text equivalents (alt text, aria-labels, or adjacent HTML text) for standalone graphics, especially those near pricing, spec, or data-heavy headings.",
        action_priority=severity,
        confidence=confidence,
    )]
