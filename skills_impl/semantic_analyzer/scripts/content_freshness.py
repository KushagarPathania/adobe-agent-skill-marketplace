"""Freshness checks.

Grounded in explicit temporal *signals* (JSON-LD dateModified, an HTTP
Last-Modified header, a visible "Updated on ..." label) -- never in
incidental years that show up in copyright lines or founding/historical
references. "Founded in 1998" or a footer "(c) 2019" must never, by
themselves, be read as evidence of stale content.
"""
import json
import re
from bs4 import BeautifulSoup

from skills_impl.common.schema import make_finding

ARCHIVAL_URL_HINTS = ('/blog/', '/news/', '/press/', '/archive/', '/events/')
HISTORICAL_CONTEXT_RE = re.compile(r'\b(founded|established|est\.?|since|copyright|©)\b', re.I)
CURRENCY_CLAIM_RE = re.compile(r'\b(currently|current|as of|updated for|effective)\b.{0,20}?(20\d{2})', re.I)


def _year_from(value):
    match = re.search(r'(20\d{2})', str(value or ''))
    return match.group(1) if match else None


def check_content_freshness(rendered_html: str, url_path: str = "", http_last_modified: str = None) -> list:
    soup = BeautifulSoup(rendered_html, 'html.parser')
    findings = []

    if any(hint in url_path.lower() for hint in ARCHIVAL_URL_HINTS):
        return findings  # archival/dated content is expected to carry old dates

    metadata_years = set()
    for script in soup.find_all('script', type='application/ld+json'):
        if not script.string:
            continue
        try:
            data = json.loads(script.string)
        except (json.JSONDecodeError, TypeError):
            continue

        def walk(obj):
            if isinstance(obj, dict):
                if 'dateModified' in obj:
                    year = _year_from(obj['dateModified'])
                    if year:
                        metadata_years.add(year)
                for val in obj.values():
                    walk(val)
            elif isinstance(obj, list):
                for item in obj:
                    walk(item)
        walk(data)

    for meta in soup.find_all('meta', property=re.compile(r'modified_time', re.I)):
        year = _year_from(meta.get('content'))
        if year:
            metadata_years.add(year)

    if http_last_modified:
        year = _year_from(http_last_modified)
        if year:
            metadata_years.add(year)

    visible_text = soup.get_text(separator=' ', strip=True).lower()
    visible_updated_years = set(re.findall(r'(?:last\s+updated|updated\s+on|updated:?).{0,15}?(20\d{2})', visible_text))

    if metadata_years and visible_updated_years:
        meta_year, vis_year = max(metadata_years), max(visible_updated_years)
        if meta_year != vis_year:
            findings.append(make_finding(
                check_id="SA-002",
                title="Conflicting freshness signals",
                severity="medium",
                evidence={"summary": f"Machine-readable metadata (dateModified/Last-Modified) indicates {meta_year}, but visible text says 'updated {vis_year}'."},
                action_summary="Synchronize the structured dateModified/Last-Modified value with the visible 'updated on' date.",
                confidence=0.7,
            ))

    # Only flag staleness when the page *explicitly* claims to reflect the
    # current year ("2026 pricing", "current as of 2026") -- never from a
    # founding date, copyright line, or other historical reference.
    claim_years = set()
    for heading in soup.find_all(['h1', 'h2', 'title']):
        text = heading.get_text(separator=' ', strip=True)
        if HISTORICAL_CONTEXT_RE.search(text):
            continue
        match = CURRENCY_CLAIM_RE.search(text)
        if match:
            claim_years.add(match.group(2))

    body_match = CURRENCY_CLAIM_RE.search(visible_text)
    if body_match:
        preceding = visible_text[max(0, body_match.start() - 30):body_match.start()]
        if not HISTORICAL_CONTEXT_RE.search(preceding):
            claim_years.add(body_match.group(2))

    if claim_years and metadata_years:
        newest_claim = max(claim_years)
        newest_meta = max(metadata_years)
        if newest_meta < newest_claim:
            findings.append(make_finding(
                check_id="SA-003",
                title="Page claims current relevance but modification date is older",
                severity="medium",
                evidence={"summary": f"Page text explicitly claims currency for {newest_claim}, but the newest modification signal found is {newest_meta}."},
                action_summary="Update the page (and its dateModified/Last-Modified signal) to match the currency it claims, or remove the outdated claim.",
                confidence=0.6,
            ))

    return findings
