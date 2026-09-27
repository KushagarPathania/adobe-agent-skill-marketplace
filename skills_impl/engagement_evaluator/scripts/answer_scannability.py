import re
from bs4 import BeautifulSoup

from skills_impl.common.schema import make_finding

UTILITY_KEYWORDS = re.compile(r'\b(pricing|price|cost|specifications|specs|features|faq|questions|services|locations|compare|documentation|docs)\b', re.I)
UTILITY_PAGE_TYPES = {"pricing", "faq", "documentation", "product", "service"}

# A short, well-written paragraph is perfectly usable without a table or
# list -- only *dense* unstructured prose (long enough that scanning it
# actually gets hard) is worth flagging. This threshold is what keeps the
# check from penalizing every utility section that happens to answer in
# plain sentences instead of bullet points.
_DENSE_PROSE_CHAR_THRESHOLD = 400


def _prose_text(section_elements):
    return " ".join(el.get_text(separator=' ', strip=True) for el in section_elements if el.name == 'p')


def check_answer_scannability(rendered_html: str, url_path: str = "", url: str = "", page_type: str = "other") -> list:
    soup = BeautifulSoup(rendered_html, 'html.parser')
    findings = []

    is_utility_page = page_type in UTILITY_PAGE_TYPES or bool(UTILITY_KEYWORDS.search(url_path))
    title = soup.find('title')
    if title and UTILITY_KEYWORDS.search(title.get_text()):
        is_utility_page = True
    h1 = soup.find('h1')
    if h1 and UTILITY_KEYWORDS.search(h1.get_text()):
        is_utility_page = True

    headings = soup.find_all(['h2', 'h3', 'h4'])
    for heading in headings:
        heading_text = heading.get_text(separator=' ', strip=True)
        if not UTILITY_KEYWORDS.search(heading_text):
            continue

        section_elements = []
        for sibling in heading.find_next_siblings():
            if sibling.name in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
                break
            section_elements.append(sibling)

        prose = _prose_text(section_elements)
        if not prose:
            continue

        has_structure = any(
            el.name in ('table', 'ul', 'ol', 'dl', 'pre', 'code')
            or el.find(['strong', 'b', 'pre', 'code'])
            for el in section_elements
        )
        if has_structure:
            continue

        if len(prose) < _DENSE_PROSE_CHAR_THRESHOLD:
            continue  # a short paragraph answer is fine as plain prose

        findings.append(make_finding(
            check_id="EE-002",
            title="Factual answers buried in unstructured prose",
            severity="medium",
            evidence={
                "summary": (
                    f"The section under '{heading_text}' is {len(prose)} characters of plain paragraph prose "
                    "with no scannable structure (table, list, or bolded labels) -- long enough that scanning "
                    "for a specific fact is difficult."
                ),
                "url": url,
                "prose_length": len(prose),
            },
            action_summary="Convert dense prose under utility headings into scannable tables, lists, or labeled key-value pairs.",
            confidence=0.6,
        ))
        return findings

    if is_utility_page and not headings and not findings and soup.find('p'):
        if not soup.find(['table', 'ul', 'ol', 'dl', 'strong', 'b', 'pre', 'code']):
            prose = " ".join(p.get_text(separator=' ', strip=True) for p in soup.find_all('p'))
            if len(prose) >= _DENSE_PROSE_CHAR_THRESHOLD:
                findings.append(make_finding(
                    check_id="EE-002",
                    title="Utility page lacks scannable information architecture",
                    severity="medium",
                    evidence={
                        "summary": (
                            f"This page was classified as '{page_type}' but relies entirely on {len(prose)} "
                            "characters of unstructured paragraphs with no subheadings, lists, tables, or "
                            "labeled values."
                        ),
                        "url": url,
                        "prose_length": len(prose),
                    },
                    action_summary="Add descriptive subheadings, tables, or lists so key facts can be scanned quickly.",
                    confidence=0.55,
                ))

    return findings
