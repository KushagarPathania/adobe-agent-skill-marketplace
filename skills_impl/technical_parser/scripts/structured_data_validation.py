"""Structured-data (JSON-LD) checks.

Syntax validity and internal fact-consistency are always checked. Which
schema *type* a page is expected to declare depends on the page_type the
classifier already assigned -- a university page is never dinged for
missing Product schema, and a news article is never judged by ecommerce
rules. A missing "expected" type is only ever a low-severity suggestion,
never a hard failure, since plenty of legitimate pages skip schema.org
entirely.
"""
import json
import re
import math
from bs4 import BeautifulSoup

from skills_impl.common.schema import make_finding

EXPECTED_TYPES = {
    "product": ["Product"],
    "pricing": ["Product", "Offer", "Service"],
    "faq": ["FAQPage"],
    "article": ["Article", "NewsArticle", "BlogPosting"],
    "blog": ["Article", "BlogPosting"],
    "event": ["Event"],
    "service": ["Service", "LocalBusiness"],
    "homepage": ["Organization", "WebSite"],
}

# CRITICAL FIX: each distinct "missing expected schema" semantic gets its
# own stable finding id. Previously every page_type above shared the
# single id "TP-003" regardless of which schema family was actually
# missing -- "Product structured representation not detected" and
# "Organization structured representation not detected" are different,
# independently-actionable problems, not one check, and (because they
# have different titles) `deduplicate()`'s (id, title) grouping never
# merged them, so a page missing more than one of these could reach the
# final report with the SAME id on two genuinely different findings.
# IDs are keyed by `expected[0]` (the schema family named in the
# title above) and fixed once here -- never derived from page order or
# a per-run counter. "Product" keeps the original "TP-003" for
# backward compatibility (it's both the most common case and the one
# `aggregate.py`'s AI-003/Organization-gap merge does NOT key off of);
# see `_is_schema_gap_finding` in aggregate.py for the corresponding
# "TP-006" reference this introduces.
_MISSING_SCHEMA_CHECK_ID = {
    "Product": "TP-003",
    "Organization": "TP-006",
    "FAQPage": "TP-007",
    "Article": "TP-008",
    "Event": "TP-009",
    "Service": "TP-010",
}

# A bare number on a real page is often a year, model number, quantity,
# spec, or dimension -- not a price. Only treat a visible number as a
# likely price when it carries actual price-shaped context: a currency
# symbol/code directly on it, or a price-related word nearby. This is
# what keeps TP-005 from firing on "founded in 2019" or "model 4090".
#
# Currency codes are matched both AFTER a number ("69 USD", the
# original form) and BEFORE it ("USD 69", "US$69" is already covered by
# the symbol form since [$...] matches wherever it occurs in the text)
# -- both are standard, legitimate ways prices are written, and only the
# first was previously recognized.
_CURRENCY_NUMBER_RE = re.compile(
    r'(?:[$€£¥]\s?\d[\d,]*(?:\.\d+)?|'
    r'\b\d[\d,]*(?:\.\d+)?\s?(?:USD|EUR|GBP|CAD|AUD)\b|'
    r'\b(?:USD|EUR|GBP|CAD|AUD)\s?\d[\d,]*(?:\.\d+)?)', re.I
)
_PRICE_CONTEXT_WORDS = re.compile(
    r'\b(price|starting at|from|sale|regular price|mrp|per month|per year|/mo|/yr|'
    r'subscription|plan|list price|now only|only)\b',
    re.I,
)
_BARE_NUMBER_RE = re.compile(r'\b\d[\d,]*(?:\.\d+)?\b')
_CONTEXT_WINDOW = 25  # chars of surrounding text checked for a price-context word


def _extract_contextual_prices(visible_text):
    """Return the set of numbers in `visible_text` that carry price-shaped
    context (currency symbol/code directly attached, or a price-related
    word within a short window), rather than every number on the page."""
    prices = set()

    for match in _CURRENCY_NUMBER_RE.finditer(visible_text):
        digits = re.sub(r'[^\d.]', '', match.group())
        try:
            prices.add(float(digits))
        except ValueError:
            pass

    for match in _BARE_NUMBER_RE.finditer(visible_text):
        start, end = match.start(), match.end()
        window = visible_text[max(0, start - _CONTEXT_WINDOW):end + _CONTEXT_WINDOW]
        if _PRICE_CONTEXT_WORDS.search(window):
            try:
                prices.add(float(match.group().replace(',', '')))
            except ValueError:
                pass

    return prices


def _extract_product_price_pairs(parsed_schemas):
    """Return [(product_name, price), ...] for every JSON-LD `Product`
    entry that declares a name and at least one resolvable price
    anywhere inside its own `offers` (directly on an `Offer`, or nested
    arbitrarily deep -- e.g. a real-world `AggregateOffer` that itself
    wraps a list of per-seller `Offer` entries, each with its own
    `price`; the nesting shape varies but the `price` key doesn't).
    Unlike the generic recursive `extract()` used for TP-003/the
    page-wide Level-1 price pool, this keeps each price tied to the
    specific product that declared it -- the prerequisite for the
    multi-product association below (Level 2/3). A Product entry with
    no name, or a bare Offer with no wrapping Product, is simply not
    collected here and falls back to the existing page-wide comparison,
    unchanged. A product can yield more than one pair when its own
    offers genuinely disagree (e.g. different sellers listing different
    prices) -- each is checked independently against the same nearby
    visible context.
    """
    pairs = []

    def prices_in(node):
        found = []

        def walk_prices(o):
            if isinstance(o, dict):
                if 'price' in o:
                    try:
                        found.append(float(str(o['price']).replace(',', '')))
                    except ValueError:
                        pass
                for v in o.values():
                    walk_prices(v)
            elif isinstance(o, list):
                for item in o:
                    walk_prices(item)

        walk_prices(node)
        return found

    def walk(obj):
        if isinstance(obj, dict):
            types = obj.get('@type')
            types = types if isinstance(types, list) else [types]
            if 'Product' in types:
                name = obj.get('name')
                if isinstance(name, str) and name.strip():
                    distinct_prices = set(prices_in(obj.get('offers')))
                    if not distinct_prices and 'price' in obj:
                        try:
                            distinct_prices = {float(str(obj['price']).replace(',', ''))}
                        except ValueError:
                            pass
                    for price in distinct_prices:
                        pairs.append((name.strip(), price))
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(parsed_schemas)
    return pairs


_PRODUCT_CONTAINER_TAGS = ('li', 'tr', 'article', 'section', 'p', 'td', 'div')


def _find_product_container_text(soup, product_name):
    """Find the SMALLEST block-level container element (list item, table
    row/cell, article/section, paragraph, or div -- the DOM's own
    'enclosing article/card/product container') whose text contains
    `product_name`, and return that element's own text. Real page
    structure normally wraps each item in a roundup/grid/table in its
    own such container, so this is a much tighter, more reliable
    DOM-proximity signal than an arbitrary character-count window over
    flattened text: it can't accidentally bleed into an adjacent
    product's own paragraph/card/row the way a raw window can.
    """
    name_norm = re.sub(r'\s+', ' ', product_name.strip().lower())
    if not name_norm:
        return None

    best = None
    for tag_name in _PRODUCT_CONTAINER_TAGS:
        for tag in soup.find_all(tag_name):
            text = tag.get_text(separator=' ', strip=True)
            if name_norm in text.lower() and (best is None or len(text) < len(best)):
                best = text
    return best


def _contextual_prices_near_product(soup, product_name):
    """Price-context numbers found in the smallest DOM container that
    mentions `product_name` (see `_find_product_container_text`).
    Returns `None` when the product name can't be located in any such
    container at all (LEVEL 3: insufficient evidence either way), or an
    empty set when it's found but nothing price-shaped is inside that
    same container (also LEVEL 3) -- both are treated as "don't claim a
    mismatch," never as "assume it matches."
    """
    container_text = _find_product_container_text(soup, product_name)
    if container_text is None:
        return None
    return _extract_contextual_prices(container_text.lower())


def check_structured_data(rendered_html: str, url: str = "", page_type: str = "other") -> list:
    soup = BeautifulSoup(rendered_html, 'html.parser')
    findings = []

    schema_scripts = soup.find_all('script', type='application/ld+json')
    parsed_schemas = []

    for script in schema_scripts:
        content = script.string
        if not content:
            continue
        try:
            data = json.loads(content)
            parsed_schemas.extend(data if isinstance(data, list) else [data])
        except json.JSONDecodeError as e:
            findings.append(make_finding(
                check_id="TP-002",
                title="Malformed JSON-LD structured data",
                severity="high",
                evidence={
                    "summary": f"JSON parse error at line {e.lineno}, col {e.colno}. This schema block cannot be read by machines.",
                    "url": url,
                    "element": "script[type=application/ld+json]",
                },
                action_summary="Fix the JSON syntax error so AI crawlers and search engines can parse the structured data.",
                confidence=0.95,
            ))

    declared_types = set()
    schema_prices = set()

    def extract(obj):
        if isinstance(obj, dict):
            if '@type' in obj:
                types = obj['@type'] if isinstance(obj['@type'], list) else [obj['@type']]
                declared_types.update(t for t in types if isinstance(t, str))
            if 'price' in obj:
                try:
                    schema_prices.add(float(str(obj['price']).replace(',', '')))
                except ValueError:
                    pass
            for value in obj.values():
                extract(value)
        elif isinstance(obj, list):
            for item in obj:
                extract(item)

    extract(parsed_schemas)

    visible_text = soup.get_text(separator=' ', strip=True).lower()

    expected = EXPECTED_TYPES.get(page_type)
    if expected and not (declared_types & set(expected)):
        findings.append(make_finding(
            check_id=_MISSING_SCHEMA_CHECK_ID.get(expected[0], "TP-003"),
            title=f"{expected[0]} structured representation not detected on a {page_type} page",
            severity="low",
            evidence={
                "summary": (
                    f"This page was classified as '{page_type}' but declares no {'/'.join(expected)} JSON-LD. "
                    "The page can still be understandable without it; structured data mainly makes extraction "
                    "more reliable."
                ),
                "url": url,
            },
            action_summary=f"Consider adding {expected[0]} structured data so AI assistants can extract this page's key facts more reliably.",
            confidence=0.5,
        ))

    if schema_prices:
        # Only compare against numbers that carry actual price-shaped
        # context -- a bare "199" could be a model number, a year, a
        # quantity, or a spec, not a price. If the page shows no
        # price-context numbers at all, that's insufficient evidence of
        # a *contradiction* (it may just not repeat the price as plain
        # text), so nothing is flagged.
        visible_prices = _extract_contextual_prices(visible_text)
        product_pairs = _extract_product_price_pairs(parsed_schemas)
        distinct_product_names = {name for name, _ in product_pairs}

        if len(distinct_product_names) >= 2:
            # LEVEL 2/3: a genuine multi-product/multi-offer page (e.g. a
            # roundup article with several distinct Product entries).
            # Page-wide pooling is insufficient here -- an unrelated
            # product's visible price must never stand as evidence
            # against a DIFFERENT product's schema price. Each declared
            # product is instead checked only against price-context
            # numbers found near its OWN name in the visible text.
            seen_pairs = set()
            for name, schema_price in product_pairs:
                if (name, schema_price) in seen_pairs:
                    continue
                seen_pairs.add((name, schema_price))

                window_prices = _contextual_prices_near_product(soup, name)
                if not window_prices:
                    # LEVEL 3: the product's name wasn't found at all, or
                    # was found with no price-shaped number nearby --
                    # ambiguous association, same "insufficient evidence"
                    # reasoning as the no-visible-price-context case
                    # below. Never claim a mismatch from this.
                    continue
                if any(math.isclose(schema_price, v, abs_tol=0.01) for v in window_prices):
                    continue

                severity = "high" if len(window_prices) >= 2 else "medium"
                confidence = 0.7 if len(window_prices) >= 2 else 0.55
                findings.append(make_finding(
                    check_id="TP-005",
                    title="Structured data price not found in visible text",
                    severity=severity,
                    evidence={
                        "summary": (
                            f"JSON-LD declares '{name}' at {schema_price}, but the visible price-context "
                            f"number(s) found near this product's own name -- {sorted(window_prices)} -- do not "
                            "match. Only text near the product's own name is used as evidence, so an unrelated "
                            "product's price elsewhere on the page does not count against it."
                        ),
                        "url": url,
                        "product_name": name,
                        "schema_price": schema_price,
                        "visible_price_candidates": sorted(window_prices),
                    },
                    action_summary="Keep structured-data prices synchronized with the visible price so AI assistants don't surface stale or incorrect figures.",
                    confidence=confidence,
                ))
        else:
            # LEVEL 1: a single (or not distinctly-named) product context
            # -- existing, unchanged page-wide comparison.
            for schema_price in schema_prices:
                if visible_prices and not any(math.isclose(schema_price, v, abs_tol=0.01) for v in visible_prices):
                    # More visible price-context candidates, all disagreeing
                    # with the schema value, is stronger evidence of a real
                    # contradiction than a single ambiguous candidate (which
                    # could plausibly be a different SKU/regional price on
                    # the same page rather than a genuine mismatch).
                    severity = "high" if len(visible_prices) >= 2 else "medium"
                    confidence = 0.7 if len(visible_prices) >= 2 else 0.55
                    findings.append(make_finding(
                        check_id="TP-005",
                        title="Structured data price not found in visible text",
                        severity=severity,
                        evidence={
                            "summary": (
                                f"JSON-LD declares a price of {schema_price}, but no visible number with price-like "
                                f"context (currency symbol/code, 'from', 'starting at', 'per month', ...) matches it. "
                                f"Visible price-context number(s) found: {sorted(visible_prices)}."
                            ),
                            "url": url,
                            "schema_price": schema_price,
                            "visible_price_candidates": sorted(visible_prices),
                        },
                        action_summary="Keep structured-data prices synchronized with the visible price so AI assistants don't surface stale or incorrect figures.",
                        confidence=confidence,
                    ))

    return findings
