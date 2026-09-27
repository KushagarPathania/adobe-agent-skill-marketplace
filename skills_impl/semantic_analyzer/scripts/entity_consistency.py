"""Site-scope check: does the brand/entity identity stay consistent
across pages and structured data, or does it visibly contradict itself?

Deliberately conservative: names are normalized (legal suffixes like
"Inc"/"LLC" stripped, case folded) before comparison, and this only
fires when two confidently-extracted names genuinely disagree -- not
for casing or punctuation variation. No external facts are invented;
only internal consistency across the pages actually fetched is checked.
"""
import json
import re
from bs4 import BeautifulSoup

from skills_impl.common.schema import make_finding

_LEGAL_SUFFIXES = re.compile(r'\b(inc|llc|ltd|corp|co|company|group|plc)\.?\s*$', re.I)
_ORG_TYPES = {"Organization", "Corporation", "LocalBusiness"}


def _normalize_name(name):
    name = _LEGAL_SUFFIXES.sub('', name.strip()).strip()
    return re.sub(r'[^a-z0-9]', '', name.lower())


def _extract_org_names(html):
    soup = BeautifulSoup(html or "", "html.parser")
    candidates = []

    for script in soup.find_all('script', type='application/ld+json'):
        if not script.string:
            continue
        try:
            data = json.loads(script.string)
        except (json.JSONDecodeError, TypeError):
            continue
        for obj in (data if isinstance(data, list) else [data]):
            if isinstance(obj, dict) and obj.get('@type') in _ORG_TYPES:
                name = obj.get('name')
                if isinstance(name, str) and name.strip():
                    candidates.append(('json-ld Organization.name', name.strip()))

    og_site = soup.find('meta', property='og:site_name')
    if og_site and og_site.get('content', '').strip():
        candidates.append(('og:site_name meta tag', og_site['content'].strip()))

    return candidates


def check_entity_consistency(pages) -> list:
    """`pages` is a list of {"url": str, "html": str} for fetched pages."""
    all_candidates = []
    for page in pages:
        for source, name in _extract_org_names(page.get('html', '')):
            all_candidates.append({'url': page['url'], 'source': source, 'name': name, 'norm': _normalize_name(name)})

    if len(all_candidates) < 2:
        return []  # not enough confidently-extracted names to compare

    groups = {}
    for c in all_candidates:
        groups.setdefault(c['norm'], []).append(c)

    if len(groups) <= 1:
        return []

    ordered = sorted(groups.values(), key=len, reverse=True)
    majority, minority = ordered[0], ordered[1]

    # A lone disagreeing mention against a large, consistent majority is
    # stronger evidence of a genuine error than a near-even split (which
    # could just as easily mean two legitimately different names are
    # each used by roughly half the checked signals, a less clear-cut
    # case). Confidence scales with how lopsided the split is.
    gap = len(majority) - len(minority)
    confidence = min(0.85, 0.55 + gap * 0.08)

    return [make_finding(
        check_id="SA-004",
        title="Inconsistent entity name across pages",
        severity="medium",
        evidence={
            "summary": (
                f"'{majority[0]['name']}' ({majority[0]['source']} on {majority[0]['url']}) does not match "
                f"'{minority[0]['name']}' ({minority[0]['source']} on {minority[0]['url']}). "
                f"{len(majority)} signal(s) agree on the former, {len(minority)} on the latter."
            ),
            "affected_pages": sorted({c['url'] for c in majority + minority}),
        },
        action_summary="Use one consistent, official entity name across structured data and visible branding.",
        confidence=confidence,
        scope="site",
    )]
