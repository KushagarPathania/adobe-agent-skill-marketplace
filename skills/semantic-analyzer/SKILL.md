---
name: semantic-analyzer
description: Evaluates non-text-content accessibility, temporal-metadata freshness, cross-page entity-name consistency, site-level AI-discoverability (reachability and entity clarity), page-level answerability/quotability for content pages, and proactive (evidence-backed, non-defect) improvement opportunities.
license: MIT
compatibility: Python 3.9+; requires beautifulsoup4 (requirements.txt). Pure in-memory HTML analysis, no network/browser dependency of its own. Some checks (answerability, entity clarity) rely on English vocabulary; on an unsupported non-English `<html lang>`, those are skipped (a `language_unsupported` diagnostic), while language-independent checks still run.
---
# Semantic Analyzer

## When to use
Use to verify whether potentially critical facts are hidden inside
non-text elements without a text equivalent, whether temporal metadata
genuinely contradicts the page's own claims, whether the brand/entity
identity stays consistent across pages, and whether an AI system could
plausibly reach and identify the site at all.

## Inputs
Rendered DOM HTML string, URL path, and (for site-scope checks) the full
set of fetched pages and the discovery inventory produced by
`site-discovery`.

## Procedure
1. **Non-Text Accessibility.** Flag isolated graphics (img/svg/canvas)
   with no text equivalent. Recognizes a label on the graphic's own
   attributes *or* on its interactive wrapper (e.g. `<button
   aria-label="Search"><svg>...`, the standard accessible-icon pattern)
   as sufficient. Severity is raised only when the graphic sits under a
   heading suggesting real information (pricing, specs, data) -- a
   decorative image with empty `alt=""` is never flagged.
2. **Freshness Signals.** Extract explicit temporal signals only:
   JSON-LD `dateModified`, an HTTP `Last-Modified` header, and visible
   "Updated on ..." text. Copyright years and founding/historical
   references ("Founded in 1998") are explicitly excluded from ever
   being read as staleness evidence.
3. **Entity Consistency.** Compare organization names (JSON-LD
   `Organization.name`, `og:site_name`) across pages, normalized to
   ignore legal-suffix/casing noise, and flag only a genuine
   disagreement between two confidently-extracted names.
4. **AI Discoverability.** From the discovery inventory and the primary
   page's content: flag "limited discovery paths" only when *multiple*
   corroborating signals agree (no sitemap, thin homepage linking, and
   thin depth-2 yield together) -- never from sitemap absence alone, and
   never on a homepage that shows positive structural evidence of a
   deliberate language/region "gateway" mechanism (many sibling-
   subdomain links, or a large selector) instead of ordinary links. This
   is a calibrated heuristic (low severity/confidence, cautious "may be
   harder... to explore" wording, framed as a recommendation), not a
   claim that the handout mandates a specific link-count or sitemap
   threshold. A robots.txt exclusion is never folded into this or any
   other finding -- it is reported separately as a coverage-limitation
   diagnostic. Entity clarity is checked across seven independent
   signals -- structured data, a *meaningful* (non-generic) title, a
   *meaningful* H1, title/H1 naming the same thing, a substantive meta
   description, a substantive opening paragraph, and the entity name
   repeating across signals -- distinguishing a signal merely being
   *present* ("Home", "Welcome") from being *meaningful*. No single
   signal is required, and structured data alone does not excuse a page
   with poor visible identity; a finding only fires when most signals
   are absent at once.
5. **Answerability / Quotability.** For content-type pages only
   (article/blog/about -- never product/pricing/faq/documentation/
   service, which are judged on structure instead by
   `engagement-evaluator`'s scannability check, and never homepage/
   utility/gateway pages): flag a page only when its heading is generic
   AND no substantive paragraph, list, or table appears among the first
   few content elements after removing nav/header/footer chrome. Either
   signal alone is not enough -- a generic heading above a genuinely
   good opening paragraph is fine, and a specific heading is treated as
   sufficient evidence on its own even if the fuller answer is further
   down the page. Always low severity/confidence; purely structural, no
   semantic/LLM-style judgment.
6. **Proactive Recommendations.** A small number of evidence-backed
   improvement suggestions that go beyond a detected defect -- e.g. a
   product site with no FAQ page among the audited pages -- explicitly
   labeled as proactive opportunities (never framed as confirmed
   defects), suppressed when the audited pages already show equivalent
   evidence (e.g. an FAQ heading/schema embedded directly on a product
   page, or even a footer link to an FAQ page this bounded audit simply
   didn't crawl).
7. Return standardized finding objects.

## Output
A JSON array of finding objects (`id`, `title`, `severity`, `confidence`,
`scope`, `evidence`, `suggested_action`).

## Implementation
This is the marketplace-facing skill directory (Agent Skills / agentskills.io
format, hyphenated per convention). Its executable logic lives in the
internal `skills_impl` Python package, at `skills_impl/semantic_analyzer/scripts/`
(underscore-named because Python identifiers cannot contain hyphens),
imported by `audit-orchestrator`. See the root `README.md` ("Agent Skills
vs. Python implementation") for the full rationale.
