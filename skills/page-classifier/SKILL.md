---
name: page-classifier
description: Lightweight, explainable page-type and site-type classification from URL/title/heading/structured-data signals, so later checks only apply rules relevant to what a page actually is.
license: MIT
compatibility: Python 3.9+; requires beautifulsoup4 (see requirements.txt). Pure in-memory HTML analysis -- no network access, no browser/Playwright dependency, and no external service calls of its own.
---
# Page Classifier

## When to use
Use right after a page is fetched, before running technical/semantic/
engagement checks against it -- so a university page is never judged by
ecommerce rules, a news article isn't judged like a product page, and a
documentation page isn't judged like a marketing landing page.

## Inputs
A page URL and its rendered (or raw, if rendering was unavailable) HTML.
For site-level classification: the list of page-type results collected
so far, plus the primary/homepage HTML.

## Procedure
1. **Page classification.** Score each candidate `page_type` (homepage,
   product, category, pricing, article, blog, faq, documentation, about,
   contact, service, event, profile, search, other) using weighted,
   transparent signals: URL path keywords, title/H1 text, JSON-LD
   `@type` values, and a few structural cues (forms, product-card
   grids, cart/price language together). No single signal alone
   determines the result -- e.g. a "$" in body text does not by itself
   mean "product"; it must co-occur with cart/purchase-action language
   specific enough to avoid an overloaded word (e.g. "checkout" is also
   a common product/feature name, so it only counts as a cart signal in
   an explicit action phrase like "proceed to checkout").
2. Return the highest-scoring type with a **confidence** derived from
   how dominant that score was relative to the others, plus the list of
   signals that contributed (for explainability).
3. **Site classification.** Once every page in the audit is classified,
   aggregate page-type counts and homepage-level language patterns
   (SaaS/education/government/nonprofit/hospitality/marketplace/
   portfolio/corporate/publisher/ecommerce keyword families) into one
   `site_type` + confidence. On a long page, a body-wide keyword must
   appear more than once before it counts as a real thematic signal --
   a single incidental mention is too weak evidence to classify an
   entire site by.
4. **Applicability (`applicability.py`).** Given a page's `page_type`
   and `confidence`, decide which page-type-*sensitive* checks
   (freshness, answer scannability, dead-end detection, citation landing
   experience, answerability) actually apply -- e.g. a contact page gets
   none of them, an article gets freshness but not dead-end detection.
   Below a confidence threshold, the effective type degrades to
   `"other"` (skip every gated check) rather than running type-specific
   rules against an unreliable guess. Generic checks (structured-data
   syntax, non-text accessibility, JS-render parity) are not gated here
   -- they always apply regardless of page type. These thresholds and
   the check-to-type mapping are this project's own calibrated
   heuristics, not a rule the handout specifies.

## Output
`classify_page(url, html) -> {"page_type", "confidence", "signals"}`
`classify_site(base_url, page_classifications, homepage_html) -> {"site_type", "confidence", "signals"}`
`get_applicability(page_type, confidence) -> {"page_type", "effective_page_type", "applicable_checks", "skipped_checks", "reasoning_signals"}`

## Implementation
This is the marketplace-facing skill directory (Agent Skills / agentskills.io
format, hyphenated per convention). Its executable logic lives in the
internal `skills_impl` Python package, at `skills_impl/page_classifier/scripts/`
(underscore-named because Python identifiers cannot contain hyphens),
imported by `audit-orchestrator`. See the root `README.md` ("Agent Skills
vs. Python implementation") for the full rationale.
