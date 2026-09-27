---
name: engagement-evaluator
description: Evaluates the citation landing experience -- orientation, answer scannability, and meaningful-link continuation (as opposed to generic boilerplate navigation) -- for visitors arriving via a direct AI citation.
license: MIT
compatibility: Python 3.9+; requires beautifulsoup4 (see requirements.txt). Pure in-memory HTML analysis -- no network access or browser dependency of its own. Its landing-context and answer-scannability heuristics rely on English generic-heading/utility-keyword vocabulary; on a page whose `<html lang>` indicates an unsupported non-English language, those specific checks are conservatively skipped rather than guessed at.
---
# Engagement Evaluator

## When to use
Use to determine why a visitor arriving via a direct AI citation link
might bounce -- a lack of immediate contextual orientation, an answer
buried in unstructured prose, or a page that gives them nowhere to go
next.

## Inputs
Rendered DOM HTML string, URL path, page URL, and the page's classified
`page_type`. For navigation checks: the full set of fetched pages and
their classifications.

## Procedure
1. **Landing Context (orientation).** On deep (non-root) pages, check
   for breadcrumbs or an explicit brand/topic mention. Flags only when
   both a generic `<h1>` and no brand context in `<title>` co-occur. A
   shallow hub/index page whose H1 simply names that same section (e.g.
   `/docs` titled "Documentation") is exempt -- the "generic" word IS
   the section's own correct name there, not a sign of missing context;
   a deep sub-page with the same generic heading is still flagged.
2. **Answer Scannability.** For pages/sections whose heading or
   classified type indicates factual/utility content (pricing, specs,
   FAQ, docs), flag prose-only sections that are both unstructured (no
   table, list, or bolded key-value pairs) *and* dense enough (a length
   threshold) that scanning it for one fact is genuinely hard -- a
   short, well-written paragraph is never flagged just for lacking a
   table.
3. **Navigation / Dead Ends (continuation).** For page types where a
   next step is normally expected (product, pricing, service, homepage,
   category), flag a page with no *meaningful* internal links --
   generic site boilerplate (privacy/terms/cookies/login) doesn't count
   as continuation, so a page with several such links is still flagged,
   just with lower confidence than a page with zero links of any kind.
   A homepage is exempt when it shows positive structural evidence of a
   deliberate language/region/category "gateway" (many links to sibling
   subdomains of the same site, or a large `<select>`) rather than
   ordinary same-host content links -- detected generically, never by
   naming a specific site. Reference/article pages are exempt from this
   check entirely -- they are not held to a "needs a next step" bar.
   When a fix is suggested, it names other pages this same audit run
   actually discovered and fetched (never an invented URL); if none fit,
   the suggestion falls back to generic guidance rather than fabricating
   a page.
4. **Citation Landing Experience (`citation_landing_experience.py`).**
   Reuses the three checks above rather than re-implementing them, and
   adds one aggregate judgment: a page where at least two of the three
   dimensions (orientation/answer-visibility/continuation) are weak *at
   the same time* gets its own finding, since that is much stronger,
   less false-positive-prone evidence than any single weak dimension.
5. Format detected issues as standardized finding objects.

## Output
A JSON array of finding objects (`id`, `title`, `severity`, `confidence`,
`evidence`, `suggested_action`).

## Implementation
This is the marketplace-facing skill directory (Agent Skills / agentskills.io
format, hyphenated per convention). Its executable logic lives in the
internal `skills_impl` Python package, at `skills_impl/engagement_evaluator/scripts/`
(underscore-named because Python identifiers cannot contain hyphens),
imported by `audit-orchestrator`. See the root `README.md` ("Agent Skills
vs. Python implementation") for the full rationale.
