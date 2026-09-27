---
name: technical-parser
description: Analyzes raw and rendered HTML to evaluate machine-readability -- client-side-rendering reliance and structured-data validity/relevance/consistency, gated by the page's classified type.
license: MIT
compatibility: Python 3.9+; requires beautifulsoup4 (see requirements.txt). Pure in-memory HTML/JSON-LD analysis -- no network access or browser dependency of its own; it consumes raw and (when available) rendered HTML already fetched by `audit-orchestrator`/`site-discovery`. Its JS-render-parity check specifically needs rendered-DOM HTML to be meaningful and is conservatively skipped, not guessed at, on a page audited from raw HTML alone.
---
# Technical Parser

## When to use
Use to determine if text-based AI crawlers lose access to substantive
content due to a raw-vs-rendered content gap, or if a page's structured
data is malformed, missing where genuinely expected for that page's
type, or conflicting with visible facts.

## Inputs
Raw HTTP HTML string, rendered DOM HTML string, page URL, and the page's
classified `page_type` (from `page-classifier`).

## Procedure
1. **JS-Render Parity.** Compare substantive text blocks between raw and
   rendered HTML. Ignores UI chrome (cookie banners, "loading", nav
   labels), isolated UI/form-control elements (`label`, `button`,
   `select`/`option`, `input` -- never content regardless of what site
   they're on), pure numeric/timestamp strings, and very short
   non-structural leaf text (a language code, a unit abbreviation) --
   headings/list-items/table-cells are exempt from that length floor
   since those can legitimately be short. As a final backstop, a page
   that is otherwise a near-total word-for-word match (>=98% overlap)
   with no *structural* content among the residual differences is
   treated as insufficient evidence and produces no finding at all.
   These are common sources of false positives, not real content gaps.
   A page that could not be rendered at all (Playwright unavailable, or
   this page's render failed/timed out) never produces a fabricated
   render-gap finding -- that is recorded as a tool diagnostic instead.
2. **Structured Data Extraction.** Extract every `<script
   type="application/ld+json">` block from the rendered DOM.
3. **Syntax Validation.** Flag malformed JSON-LD.
4. **Type Relevance.** Look up which schema type(s), if any, are a
   natural fit for the page's classified type (e.g. `Product` for a
   product page, `FAQPage` for a FAQ page) via a small lookup table --
   never a blanket "every page needs every schema" rule, and a missing
   type is always a low-severity suggestion, never a hard failure.
5. **Fact Consistency.** Compare a schema-declared price only against
   visible numbers that carry actual price-shaped context (a currency
   symbol/code, or a nearby word like "from"/"per month") -- a bare
   number (a model number, a spec, a year) is never treated as a price
   candidate. Severity/confidence scale with how many disagreeing
   price-context candidates are found.
6. Return standardized finding objects.

## Output
A JSON array of finding objects (`id`, `title`, `severity`, `confidence`,
`evidence`, `suggested_action`).

## Implementation
This is the marketplace-facing skill directory (Agent Skills / agentskills.io
format, hyphenated per convention). Its executable logic lives in the
internal `skills_impl` Python package, at `skills_impl/technical_parser/scripts/`
(underscore-named because Python identifiers cannot contain hyphens),
imported by `audit-orchestrator`. See the root `README.md` ("Agent Skills
vs. Python implementation") for the full rationale.
